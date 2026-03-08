import streamlit as st
import requests
from datetime import datetime
import psycopg2

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from textwrap import wrap

# -------- CONFIG -------- #

AACT_HOST = st.secrets["AACT_HOST"]
AACT_DB = st.secrets["AACT_DB"]
AACT_PORT = st.secrets["AACT_PORT"]
AACT_USER = st.secrets["AACT_USER"]
AACT_PASS = st.secrets["AACT_PASS"]

# -------- HELPER FUNCTIONS -------- #

def connect_aact():
    return psycopg2.connect(
        host=AACT_HOST,
        database=AACT_DB,
        user=AACT_USER,
        password=AACT_PASS,
        port=AACT_PORT
    )


def get_previous_trial_data(conn, nct_id):

    cur = conn.cursor()

    query = """
    SELECT overall_status,start_date,primary_completion_date,
           completion_date,enrollment
    FROM studies
    WHERE nct_id = %s
    """

    cur.execute(query,(nct_id,))
    row = cur.fetchone()
    cur.close()

    if row:
        return {
            "status": str(row[0]) if row[0] else "NA",
            "start": str(row[1]) if row[1] else "NA",
            "primary_completion": str(row[2]) if row[2] else "NA",
            "completion": str(row[3]) if row[3] else "NA",
            "enrollment": str(row[4]) if row[4] else "NA"
        }

    return None


def get_previous_countries(conn,nct_id):

    cur = conn.cursor()

    query = """
    SELECT DISTINCT country
    FROM facilities
    WHERE nct_id = %s
    """

    cur.execute(query,(nct_id,))
    rows = cur.fetchall()
    cur.close()

    return sorted([r[0] for r in rows if r[0]])


# -------- PDF UTILITIES -------- #

LEFT = 60
RIGHT = 550
TOP = 750
BOTTOM = 60


def add_footer(c):
    c.setFont("Helvetica",9)
    page = c.getPageNumber()
    c.drawCentredString(300,30,f"Clinical Trial Intelligence Report | Page {page}")


def draw_wrapped_text(c,text,x,y,width=90,line_height=14):

    lines = wrap(text,width)

    for line in lines:

        if y < BOTTOM:
            add_footer(c)
            c.showPage()
            c.setFont("Helvetica",10)
            y = TOP

        c.drawString(x,y,line)
        y -= line_height

    return y


def draw_section_title(c,title,y,width):

    c.setFont("Helvetica-Bold",13)
    c.drawString(50,y,title)

    y -= 8
    c.line(50,y,width-50,y)

    y -= 20

    return y


# -------- PDF GENERATOR -------- #

def generate_pdf(condition,start_date,end_date,new_trials,updates):

    safe_condition = condition.replace(" ","_").lower()

    file_name = f"clinical_trial_report_{safe_condition}_{start_date}_{end_date}.pdf"

    c = canvas.Canvas(file_name,pagesize=letter)

    width,height = letter
    y = height - 50

    c.setFont("Helvetica-Bold",16)
    c.drawCentredString(width/2,y,"CLINICAL TRIAL INTELLIGENCE REPORT")

    y -= 30

    c.setFont("Helvetica",11)
    c.drawString(50,y,f"Disease: {condition}")

    y -= 15
    c.drawString(50,y,f"Monitoring Window: {start_date} to {end_date}")

    y -= 15
    c.drawString(50,y,f"Generated on: {datetime.today().date()}")

    y -= 25
    c.line(40,y,width-40,y)

    y -= 25

    c.setFont("Helvetica-Bold",12)
    c.drawString(50,y,"SUMMARY")

    y -= 20
    c.setFont("Helvetica",11)

    c.drawString(60,y,f"Total New Trials: {len(new_trials)}")
    y -= 15
    c.drawString(60,y,f"Total Updated Trials: {len(updates)}")

    y -= 30

    y = draw_section_title(c,"NEW INDUSTRY TRIALS",y,width)
    c.setFont("Helvetica",10)

    if not new_trials:
        y = draw_wrapped_text(c,"No new industry trials detected.",60,y)
    else:
        for trial in new_trials:
            y = draw_wrapped_text(c,f"• {trial}",60,y)
            y -= 5

    y -= 20

    y = draw_section_title(c,"TRIAL UPDATES",y,width)

    if not updates:
        y = draw_wrapped_text(c,"No trial updates detected.",60,y)
    else:
        for upd in updates:
            y = draw_wrapped_text(c,f"• {upd}",60,y)
            y -= 5

    add_footer(c)
    c.save()

    return file_name


# -------- STREAMLIT UI -------- #

st.title("Clinical Trial Intelligence Monitor")

condition = st.text_input("Disease / Condition")
start_date = st.date_input("Start Date")
end_date = st.date_input("End Date")

run_button = st.button("Run Analysis")


if run_button:

    st.write("Fetching trials...")

    base_url = "https://clinicaltrials.gov/api/v2/studies"

    params = {
        "query.cond": condition,
        "pageSize":1000
    }

    response = requests.get(base_url,params=params)
    studies = response.json().get("studies",[])

    conn = connect_aact()

    new_trials = []
    updates = []

    for study in studies:

        protocol = study.get("protocolSection",{})
        status = protocol.get("statusModule",{})
        sponsor_mod = protocol.get("sponsorCollaboratorsModule",{})
        design = protocol.get("designModule",{})
        interventions_mod = protocol.get("armsInterventionsModule",{})

        upd_date_str = status.get("lastUpdatePostDateStruct",{}).get("date")

        if not upd_date_str:
            continue

        upd_date = datetime.strptime(upd_date_str,"%Y-%m-%d").date()

        if not(start_date <= upd_date <= end_date):
            continue

        sponsor_class = sponsor_mod.get("leadSponsor",{}).get("class","")

        if sponsor_class.upper() != "INDUSTRY":
            continue

        ident = protocol.get("identificationModule",{})
        nct_id = ident.get("nctId")
        title = ident.get("briefTitle","")

        sponsor = sponsor_mod.get("leadSponsor",{}).get("name","NA")

        phase = design.get("phases",["NA"])[0]

        interventions = interventions_mod.get("interventions",[])

        drug_names = ", ".join([i.get("name") for i in interventions if i.get("name")]) or "NA"

        study_start = status.get("startDateStruct",{}).get("date","NA")
        primary_completion = status.get("primaryCompletionDateStruct",{}).get("date","NA")
        study_completion = status.get("completionDateStruct",{}).get("date","NA")
        enrollment = str(design.get("enrollmentInfo",{}).get("count","NA"))

        locations = protocol.get("contactsLocationsModule",{}).get("locations",[])

        countries = sorted(list(set([loc.get("country") for loc in locations if loc.get("country")])))

        prev = get_previous_trial_data(conn,nct_id)

        if not prev:
            continue

        prev_countries = get_previous_countries(conn,nct_id)

        changes = []

        if status.get("overallStatus","NA") != prev["status"]:
            changes.append(f"Status updated from {prev['status']} to {status.get('overallStatus')}")

        if study_start != prev["start"]:
            changes.append(f"Study start date updated from {prev['start']} to {study_start}")

        if primary_completion != prev["primary_completion"]:
            changes.append(f"Primary Completion date updated from {prev['primary_completion']} to {primary_completion}")

        if study_completion != prev["completion"]:
            changes.append(f"Study Completion date updated from {prev['completion']} to {study_completion}")

        if enrollment != prev["enrollment"]:
            changes.append(f"Enrollment updated from {prev['enrollment']} to {enrollment}")

        added = list(set(countries)-set(prev_countries))

        if added:
            changes.append("Locations added " + ", ".join(added))

        if changes:

            update_report = f"[{nct_id}] {sponsor}'s {phase} trial evaluating {drug_names} in {condition} has been updated.\n"

            for c in changes:
                update_report += c + " |\n"

            updates.append(update_report)

    conn.close()

    st.success(f"Total Updates Detected: {len(updates)}")

    for u in updates:
        st.write(u)

    file_name = generate_pdf(
        condition,
        start_date,
        end_date,
        new_trials,
        updates
    )

    with open(file_name,"rb") as f:

        st.download_button(
            "Download PDF Report",
            f,
            file_name=file_name
        )
