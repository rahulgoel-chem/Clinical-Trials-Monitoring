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


# -------- DATABASE CONNECTION -------- #

def connect_aact():

    return psycopg2.connect(
        host=AACT_HOST,
        database=AACT_DB,
        user=AACT_USER,
        password=AACT_PASS,
        port=AACT_PORT
    )


# -------- NORMALIZE DATE -------- #

def normalize_date(d):

    if not d or d == "NA":
        return "NA"

    return str(d)[:7]


# -------- GET PREVIOUS SNAPSHOT -------- #

def get_previous_trial_data(conn, nct_id):

    cur = conn.cursor()

    query = """
    SELECT overall_status,
           start_date,
           primary_completion_date,
           completion_date,
           enrollment
    FROM studies
    WHERE nct_id = %s
    """

    cur.execute(query, (nct_id,))
    row = cur.fetchone()
    cur.close()

    if not row:
        return None

    return {
        "status": str(row[0]) if row[0] else "NA",
        "start": str(row[1]) if row[1] else "NA",
        "primary": str(row[2]) if row[2] else "NA",
        "completion": str(row[3]) if row[3] else "NA",
        "enrollment": str(row[4]) if row[4] else "NA"
    }


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


# -------- NEW TRIAL DETECTION (UNCHANGED LOGIC) -------- #

def get_new_trials(conn, condition, start_date, end_date):

    cur = conn.cursor()

    query = """
    SELECT nct_id, brief_title, phase, lead_sponsor_name
    FROM studies
    WHERE study_first_post_date BETWEEN %s AND %s
    AND lead_sponsor_class = 'INDUSTRY'
    AND condition LIKE %s
    """

    cur.execute(query, (start_date, end_date, f"%{condition}%"))

    rows = cur.fetchall()

    cur.close()

    new_trials = []

    for r in rows:

        nct_id, title, phase, sponsor = r

        new_trials.append(

            f"{sponsor} initiated a {phase} trial: {title} ({nct_id})"

        )

    return new_trials


# -------- FETCH ALL TRIALS (PAGINATION) -------- #

def fetch_all_trials(condition):

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

        "pageSize": 1000

    }

    studies = []

    token = None

    while True:

        if token:

            params["pageToken"] = token

        response = requests.get(base_url, params=params)

        data = response.json()

        studies.extend(data.get("studies", []))

        token = data.get("nextPageToken")

        if not token:

            break

    return studies


# -------- PDF UTILITIES -------- #

BOTTOM = 60
TOP = 750


def add_footer(c):

    c.setFont("Helvetica", 9)

    page = c.getPageNumber()

    c.drawCentredString(
        300,
        30,
        f"Clinical Trial Intelligence Report | Page {page}"
    )


def draw_wrapped_text(c, text, x, y, width=90):

    lines = wrap(text, width)

    for line in lines:

        if y < BOTTOM:

            add_footer(c)

            c.showPage()

            c.setFont("Helvetica", 10)

            y = TOP

        c.drawString(x, y, line)

        y -= 14

    return y


def draw_section_title(c, title, y, width):

    c.setFont("Helvetica-Bold", 13)

    c.drawString(50, y, title)

    y -= 8

    c.line(50, y, width - 50, y)

    y -= 20

    return y


# -------- GENERATE PDF -------- #

def generate_pdf(condition, start, end, new_trials, updates):

    file_name = f"clinical_trial_report_{condition}.pdf"

    c = canvas.Canvas(file_name, pagesize=letter)

    width, height = letter

    y = height - 50

    c.setFont("Helvetica-Bold", 16)

    c.drawCentredString(width/2, y, "CLINICAL TRIAL INTELLIGENCE REPORT")

    y -= 40

    c.setFont("Helvetica", 11)

    c.drawString(50, y, f"Disease: {condition}")

    y -= 15

    c.drawString(50, y, f"Monitoring Window: {start} to {end}")

    y -= 25

    c.line(40, y, width - 40, y)

    y -= 30


    # NEW TRIALS

    y = draw_section_title(c, "NEW INDUSTRY TRIALS", y, width)

    c.setFont("Helvetica", 10)

    if not new_trials:

        y = draw_wrapped_text(c, "No new trials detected.", 60, y)

    else:

        for t in new_trials:

            y = draw_wrapped_text(c, f"• {t}", 60, y)

            y -= 5


    y -= 20


    # UPDATES

    y = draw_section_title(c, "TRIAL UPDATES", y, width)

    if not updates:

        y = draw_wrapped_text(c, "No updates detected.", 60, y)

    else:

        for u in updates:

            y = draw_wrapped_text(c, f"• {u}", 60, y)

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


# -------- MAIN PIPELINE -------- #

if run_button:

    start_date_input = start_date.strftime("%Y-%m-%d")

    end_date_input = end_date.strftime("%Y-%m-%d")

    conn = connect_aact()

    # -------- NEW TRIALS (UNCHANGED) -------- #

    new_trials = get_new_trials(
        conn,
        condition,
        start_date_input,
        end_date_input
    )


    # -------- FETCH ALL TRIALS -------- #

    studies = fetch_all_trials(condition)

    updates = []


    for study in studies:

        protocol = study.get("protocolSection", {})

        ident = protocol.get("identificationModule", {})

        status = protocol.get("statusModule", {})

        design = protocol.get("designModule", {})

        sponsor_mod = protocol.get("sponsorCollaboratorsModule", {})

        nct_id = ident.get("nctId")

        sponsor = sponsor_mod.get("leadSponsor", {}).get("name", "NA")

        upd_date_str = status.get("lastUpdatePostDateStruct", {}).get("date")

        if not upd_date_str:

            continue

        upd_date = datetime.strptime(upd_date_str, "%Y-%m-%d")

        if not (start_date <= upd_date.date() <= end_date):

            continue


        current_status = status.get("overallStatus", "NA")

        current_start = status.get("startDateStruct", {}).get("date", "NA")

        current_primary = status.get(
            "primaryCompletionDateStruct", {}
        ).get("date", "NA")

        current_completion = status.get(
            "completionDateStruct", {}
        ).get("date", "NA")

        enrollment = design.get("enrollmentInfo", {}).get("count")

        current_enrollment = str(enrollment) if enrollment else "NA"


        locations = protocol.get("contactsLocationsModule", {}).get("locations", [])

        current_countries = sorted(list(set([

            loc.get("country") for loc in locations if loc.get("country")

        ])))


        prev = get_previous_trial_data(conn, nct_id)

        if not prev:

            continue

        prev_countries = get_previous_countries(conn, nct_id)

        changes = []


        if current_status != prev["status"]:

            changes.append(f"Status: {prev['status']} → {current_status}")


        if normalize_date(current_start) != normalize_date(prev["start"]):

            changes.append(f"Start Date: {prev['start']} → {current_start}")


        if normalize_date(current_primary) != normalize_date(prev["primary"]):

            changes.append(
                f"Primary Completion: {prev['primary']} → {current_primary}"
            )


        if normalize_date(current_completion) != normalize_date(prev["completion"]):

            changes.append(
                f"Completion Date: {prev['completion']} → {current_completion}"
            )


        if current_enrollment != prev["enrollment"]:

            changes.append(
                f"Enrollment: {prev['enrollment']} → {current_enrollment}"
            )


        added = list(set(current_countries) - set(prev_countries))

        removed = list(set(prev_countries) - set(current_countries))


        if added:

            changes.append("Countries Added: " + ", ".join(added))


        if removed:

            changes.append("Countries Removed: " + ", ".join(removed))


        if changes:

            updates.append(

                f"{sponsor}'s trial ({nct_id}) updated: "

                + "; ".join(changes)

            )


    conn.close()


    st.success(f"New Trials: {len(new_trials)} | Updates: {len(updates)}")


    file_name = generate_pdf(

        condition,

        start_date_input,

        end_date_input,

        new_trials,

        updates

    )


    with open(file_name, "rb") as f:

        st.download_button(

            "Download PDF Report",

            f,

            file_name=file_name

        )
