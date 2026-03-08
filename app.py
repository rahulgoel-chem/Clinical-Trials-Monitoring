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

# -------- DATABASE -------- #

def connect_aact():
    return psycopg2.connect(
        host=AACT_HOST,
        database=AACT_DB,
        user=AACT_USER,
        password=AACT_PASS,
        port=AACT_PORT
    )


def normalize_date(d):
    if not d or d == "NA":
        return "NA"
    if len(d) == 7:
        return d + "-01"
    return d


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


def get_current_countries(protocol):

    countries = set()

    locations = protocol.get("contactsLocationsModule",{}).get("locations",[])

    for loc in locations:
        c = loc.get("country")
        if c:
            countries.add(c)

    return sorted(list(countries))


# -------- PDF UTILITIES -------- #

LEFT = 60
RIGHT = 550
TOP = 750
BOTTOM = 60


def add_footer(c):

    c.setFont("Helvetica",9)
    page = c.getPageNumber()

    c.drawCentredString(
        300,
        30,
        f"Clinical Trial Intelligence Report | Page {page}"
    )


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

    y -= 30

    y = draw_section_title(c,"NEW INDUSTRY TRIALS",y,width)

    c.setFont("Helvetica",10)

    if not new_trials:
        y = draw_wrapped_text(c,"No new trials detected.",60,y)
    else:
        for t in new_trials:
            y = draw_wrapped_text(c,f"• {t}",60,y)
            y -= 5

    y -= 20

    y = draw_section_title(c,"TRIAL UPDATES",y,width)

    if not updates:
        y = draw_wrapped_text(c,"No trial updates detected.",60,y)
    else:
        for u in updates:
            y = draw_wrapped_text(c,f"• {u}",60,y)
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

    base_url = "https://clinicaltrials.gov/api/v2/studies"

    params = {
        "query.cond": condition,
        "pageSize": 1000,
        "fields": ",".join([
            "protocolSection.identificationModule",
            "protocolSection.statusModule",
            "protocolSection.designModule",
            "protocolSection.sponsorCollaboratorsModule",
            "protocolSection.contactsLocationsModule",
            "protocolSection.conditionsModule",
            "protocolSection.armsInterventionsModule"
        ])
    }

    studies = []
    next_token = None

    while True:

        if next_token:
            params["pageToken"] = next_token

        response = requests.get(base_url,params=params)

        data = response.json()

        studies.extend(data.get("studies",[]))

        next_token = data.get("nextPageToken")

        if not next_token:
            break

    conn = connect_aact()

    new_trials = []
    updates = []

    for study in studies:

        protocol = study.get("protocolSection",{})

        status = protocol.get("statusModule",{})

        sponsor_mod = protocol.get("sponsorCollaboratorsModule",{})

        design = protocol.get("designModule",{})

        ident = protocol.get("identificationModule",{})

        nct_id = ident.get("nctId")

        if not nct_id:
            continue

        sponsor_class = sponsor_mod.get("leadSponsor",{}).get("class","")

        if sponsor_class.upper() != "INDUSTRY":
            continue

        sponsor = sponsor_mod.get("leadSponsor",{}).get("name","NA")

        title = ident.get("briefTitle","")

        phase = design.get("phases",["NA"])[0]

        # -------- DATE FILTER -------- #

        first_post_str = status.get("studyFirstPostDateStruct",{}).get("date")

        update_post_str = status.get("lastUpdatePostDateStruct",{}).get("date")

        first_post_date = None
        update_post_date = None

        if first_post_str:
            first_post_date = datetime.strptime(first_post_str,"%Y-%m-%d").date()

        if update_post_str:
            update_post_date = datetime.strptime(update_post_str,"%Y-%m-%d").date()

        # -------- NEW TRIAL -------- #

        if first_post_date and start_date <= first_post_date <= end_date:

            new_trials.append(
                f"[{nct_id}] {sponsor}'s {phase} trial evaluating {title} has been registered."
            )

        # -------- UPDATE FILTER -------- #

        if not (update_post_date and start_date <= update_post_date <= end_date):
            continue

        prev = get_previous_trial_data(conn,nct_id)

        if not prev:
            continue

        changes = []

        current_status = status.get("overallStatus","NA")

        if current_status != prev["status"]:
            changes.append(
                f"Status updated from {prev['status']} to {current_status}"
            )

        study_start = normalize_date(
            status.get("startDateStruct",{}).get("date","NA")
        )

        if study_start != normalize_date(prev["start"]):
            changes.append(
                f"Study start date updated from {prev['start']} to {study_start}"
            )

        primary_completion = normalize_date(
            status.get("primaryCompletionDateStruct",{}).get("date","NA")
        )

        if primary_completion != normalize_date(prev["primary_completion"]):
            changes.append(
                f"Primary Completion date updated from {prev['primary_completion']} to {primary_completion}"
            )

        study_completion = normalize_date(
            status.get("completionDateStruct",{}).get("date","NA")
        )

        if study_completion != normalize_date(prev["completion"]):
            changes.append(
                f"Study Completion date updated from {prev['completion']} to {study_completion}"
            )

        enrollment = str(
            design.get("enrollmentInfo",{}).get("count","NA")
        )

        if enrollment != prev["enrollment"]:
            changes.append(
                f"Enrollment updated from {prev['enrollment']} to {enrollment}"
            )

        # -------- LOCATION CHANGES -------- #

        prev_countries = get_previous_countries(conn,nct_id)

        curr_countries = get_current_countries(protocol)

        added = list(set(curr_countries) - set(prev_countries))

        if added:
            changes.append(
                "locations added " + ", ".join(sorted(added))
            )

        if changes:

            report = f"[{nct_id}] {sponsor}'s {phase} trial evaluating {title} has been updated.\n"

            for c in changes:
                report += c + " |\n"

            updates.append(report)

    conn.close()

    st.success(f"Total New Trials: {len(new_trials)}")

    st.success(f"Total Updates: {len(updates)}")

    if new_trials:

        st.subheader("New Trials")

        for t in new_trials:
            st.write(t)

    if updates:

        st.subheader("Trial Updates")

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
