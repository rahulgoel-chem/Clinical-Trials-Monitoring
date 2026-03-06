import requests
from datetime import datetime
import psycopg2

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from textwrap import wrap


# -------- CONFIG -------- #

AACT_HOST = "aact-db.ctti-clinicaltrials.org"
AACT_DB = "aact"
AACT_PORT = 5432
AACT_USER = "theranode"
AACT_PASS = "R@hul046"


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
    SELECT overall_status, phase, enrollment
    FROM studies
    WHERE nct_id = %s
    """

    cur.execute(query, (nct_id,))
    row = cur.fetchone()
    cur.close()

    if row:
        return {
            "status": str(row[0]) if row[0] else "NA",
            "phase": str(row[1]) if row[1] else "NA",
            "enrollment": str(row[2]) if row[2] else "NA"
        }

    return None


def get_previous_countries(conn, nct_id):

    cur = conn.cursor()

    query = """
    SELECT DISTINCT country
    FROM facilities
    WHERE nct_id = %s
    """

    cur.execute(query, (nct_id,))
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


    # ---- HEADER ---- #

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


    # ---- SUMMARY ---- #

    c.setFont("Helvetica-Bold",12)
    c.drawString(50,y,"SUMMARY")

    y -= 10
    c.line(50,y,width-50,y)

    y -= 20

    c.setFont("Helvetica",11)
    c.drawString(60,y,f"Total New Trials: {len(new_trials)}")

    y -= 15
    c.drawString(60,y,f"Total Updated Trials: {len(updates)}")

    y -= 30


    # ---- NEW TRIALS ---- #

    y = draw_section_title(c,"NEW INDUSTRY TRIALS",y,width)

    c.setFont("Helvetica",10)

    if not new_trials:

        y = draw_wrapped_text(c,"No new industry trials detected.",60,y)

    else:

        for trial in new_trials:

            trial_text = f"• {trial}"
            y = draw_wrapped_text(c,trial_text,60,y)

            y -= 5


    y -= 20


    # ---- UPDATES ---- #

    y = draw_section_title(c,"TRIAL UPDATES",y,width)

    c.setFont("Helvetica",10)

    if not updates:

        y = draw_wrapped_text(c,"No trial updates detected.",60,y)

    else:

        for upd in updates:

            upd_text = f"• {upd}"
            y = draw_wrapped_text(c,upd_text,60,y)

            y -= 5


    add_footer(c)

    c.save()

    print("\nPDF REPORT GENERATED:",file_name)


# -------- MAIN PIPELINE -------- #

def fetch_and_report_updates():

    print("\n===== CLINICAL TRIAL INTELLIGENCE MONITOR =====\n")

    condition = input("Disease / condition search: ")
    start_date_input = input("Start date (YYYY-MM-DD): ")
    end_date_input = input("End date (YYYY-MM-DD): ")

    start_date = datetime.strptime(start_date_input,"%Y-%m-%d")
    end_date = datetime.strptime(end_date_input,"%Y-%m-%d")

    base_url = "https://clinicaltrials.gov/api/v2/studies"

    fields = [
        "protocolSection.identificationModule",
        "protocolSection.statusModule",
        "protocolSection.designModule",
        "protocolSection.sponsorCollaboratorsModule",
        "protocolSection.contactsLocationsModule",
        "protocolSection.conditionsModule"
    ]

    params = {
        "query.cond": condition,
        "fields": ",".join(fields),
        "pageSize":1000
    }

    print("\nFetching trials...\n")

    response = requests.get(base_url,params=params)
    studies = response.json().get("studies",[])

    conn = connect_aact()

    new_trials = []
    updates = []


    for study in studies:

        protocol = study.get("protocolSection",{})
        status = protocol.get("statusModule",{})
        sponsor_mod = protocol.get("sponsorCollaboratorsModule",{})

        upd_date_str = status.get("lastUpdatePostDateStruct",{}).get("date")

        if not upd_date_str:
            continue

        upd_date = datetime.strptime(upd_date_str,"%Y-%m-%d")

        if not(start_date <= upd_date <= end_date):
            continue

        sponsor_class = sponsor_mod.get("leadSponsor",{}).get("class","")

        if sponsor_class.upper() != "INDUSTRY":
            continue

        ident = protocol.get("identificationModule",{})

        nct_id = ident.get("nctId")
        title = ident.get("briefTitle","")

        sponsor = sponsor_mod.get("leadSponsor",{}).get("name","NA")

        conditions = ", ".join(protocol.get("conditionsModule",{}).get("conditions",[]))

        current_status = status.get("overallStatus","NA")

        current_phase = ", ".join(
            protocol.get("designModule",{}).get("phases",[])
        ) or "NA"

        current_enrollment = str(
            status.get("enrollmentStruct",{}).get("count","NA")
        )

        current_locs = protocol.get("contactsLocationsModule",{}).get("locations",[])

        current_countries = sorted(list(set([
            loc.get("country") for loc in current_locs if loc.get("country")
        ])))

        prev = get_previous_trial_data(conn,nct_id)

        if not prev:

            new_trials.append(
                f"[{nct_id}] {sponsor} started NEW trial: {title}"
            )

            continue

        prev_status = prev["status"]
        prev_phase = prev["phase"]
        prev_enrollment = prev["enrollment"]

        prev_countries = get_previous_countries(conn,nct_id)

        changes = []

        if current_status != prev_status:
            changes.append(f"Status: {prev_status} -> {current_status}")

        if current_phase != prev_phase:
            changes.append(f"Phase: {prev_phase} -> {current_phase}")

        if current_enrollment != prev_enrollment:
            changes.append(f"Enrollment: {prev_enrollment} -> {current_enrollment}")

        added_sites = list(set(current_countries) - set(prev_countries))

        if added_sites:
            changes.append(f"New Countries Added: {', '.join(added_sites)}")

        if changes:

            updates.append(
                f"[{nct_id}] {sponsor} trial in {conditions}: "
                + "; ".join(changes)
            )

    conn.close()

    print("\nTotal new trials:",len(new_trials))
    print("Total updates:",len(updates))

    generate_pdf(condition,start_date_input,end_date_input,new_trials,updates)

    print("\nAnalysis complete.\n")


# -------- RUN -------- #

fetch_and_report_updates()
