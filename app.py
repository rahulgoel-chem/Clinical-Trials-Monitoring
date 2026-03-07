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


def get_previous_trial_data(conn, nct_id):

    cur = conn.cursor()

    query = """
    SELECT overall_status, phase, enrollment,
           primary_completion_date, completion_date
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
            "enrollment": str(row[2]) if row[2] else "NA",
            "primary_completion": str(row[3]) if row[3] else "NA",
            "completion": str(row[4]) if row[4] else "NA"
        }

    return None


def get_previous_countries(conn, nct_id):

    cur = conn.cursor()

    cur.execute("""
        SELECT DISTINCT country
        FROM facilities
        WHERE nct_id = %s
    """, (nct_id,))

    rows = cur.fetchall()
    cur.close()

    return sorted([r[0] for r in rows if r[0]])


def get_previous_drugs(conn, nct_id):

    cur = conn.cursor()

    cur.execute("""
        SELECT DISTINCT name
        FROM interventions
        WHERE nct_id = %s
        AND intervention_type = 'Drug'
    """, (nct_id,))

    rows = cur.fetchall()
    cur.close()

    return sorted([r[0] for r in rows if r[0]])


# -------- PDF UTILITIES -------- #

LEFT = 60
RIGHT = 550
TOP = 750
BOTTOM = 60


def add_footer(c):
    c.setFont("Helvetica", 9)
    page = c.getPageNumber()
    c.drawCentredString(300, 30, f"Clinical Trial Intelligence Report | Page {page}")


def draw_wrapped_text(c, text, x, y, width=90, line_height=14):

    lines = wrap(text, width)

    for line in lines:

        if y < BOTTOM:
            add_footer(c)
            c.showPage()
            c.setFont("Helvetica", 10)
            y = TOP

        c.drawString(x, y, line)
        y -= line_height

    return y


def draw_section_title(c, title, y, width):

    c.setFont("Helvetica-Bold", 13)
    c.drawString(50, y, title)

    y -= 8
    c.line(50, y, width - 50, y)
    y -= 20

    return y


# -------- PDF GENERATOR -------- #

def generate_pdf(condition, start_date, end_date, new_trials, updates):

    file_name = f"clinical_trial_report_{condition}.pdf"

    c = canvas.Canvas(file_name, pagesize=letter)
    width, height = letter

    y = height - 50

    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(width / 2, y, "CLINICAL TRIAL INTELLIGENCE REPORT")

    y -= 40

    c.setFont("Helvetica", 11)
    c.drawString(50, y, f"Disease: {condition}")
    y -= 15
    c.drawString(50, y, f"Monitoring Window: {start_date} to {end_date}")

    y -= 25
    c.line(40, y, width - 40, y)

    y -= 30

    y = draw_section_title(c, "NEW TRIALS", y, width)

    if not new_trials:
        y = draw_wrapped_text(c, "No new trials detected.", 60, y)

    else:
        for t in new_trials:
            y = draw_wrapped_text(c, f"• {t}", 60, y)
            y -= 5

    y -= 20

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


# -------- STREAMLIT -------- #

st.title("Clinical Trial Intelligence Monitor")

condition = st.text_input("Disease / Condition")
start_date = st.date_input("Start Date")
end_date = st.date_input("End Date")

run_button = st.button("Run Analysis")


if run_button:

    st.write("Fetching trials...")

    base_url = "https://clinicaltrials.gov/api/v2/studies"

    fields = [
        "protocolSection.identificationModule",
        "protocolSection.statusModule",
        "protocolSection.designModule",
        "protocolSection.sponsorCollaboratorsModule",
        "protocolSection.contactsLocationsModule",
        "protocolSection.conditionsModule",
        "protocolSection.armsInterventionsModule"   # IMPORTANT
    ]

    params = {
        "query.cond": condition,
        "fields": ",".join(fields),
        "pageSize": 1000
    }

    studies = []
    next_token = None

    while True:

        if next_token:
            params["pageToken"] = next_token

        r = requests.get(base_url, params=params)
        data = r.json()

        studies.extend(data.get("studies", []))
        next_token = data.get("nextPageToken")

        if not next_token:
            break

    conn = connect_aact()

    new_trials = []
    updates = []

    for study in studies:

        protocol = study.get("protocolSection", {})
        status = protocol.get("statusModule", {})
        sponsor_mod = protocol.get("sponsorCollaboratorsModule", {})
        design = protocol.get("designModule", {})
        ident = protocol.get("identificationModule", {})

        nct_id = ident.get("nctId")
        title = ident.get("briefTitle", "NA")

        sponsor = sponsor_mod.get("leadSponsor", {}).get("name", "NA")
        conditions = ", ".join(
            protocol.get("conditionsModule", {}).get("conditions", [])
        )
        
        # -------- DRUGS -------- #

        interventions = protocol.get(
            "armsInterventionsModule", {}
        ).get("interventions", [])

        drugs = sorted(list(set([
            i.get("name")
            for i in interventions
            if i.get("type") == "DRUG"
        ])))

        drug_text = ", ".join(drugs) if drugs else "NA"

        # -------- CURRENT VALUES -------- #

        current_status = status.get("overallStatus", "NA")
        current_phase = ", ".join(design.get("phases", [])) or "NA"
        current_enrollment = str(design.get("enrollmentInfo", {}).get("count", "NA"))

        primary_completion = status.get("primaryCompletionDateStruct", {}).get("date", "NA")
        completion = status.get("completionDateStruct", {}).get("date", "NA")

        locations = protocol.get("contactsLocationsModule", {}).get("locations", [])

        current_countries = sorted(list(set([
            l.get("country") for l in locations if l.get("country")
        ])))

        # -------- PREVIOUS DATA -------- #

        prev = get_previous_trial_data(conn, nct_id)
        if not prev:
            continue

        prev_countries = get_previous_countries(conn, nct_id)
        prev_drugs = get_previous_drugs(conn, nct_id)

        changes = []

        if current_status != prev["status"]:
            changes.append(f"Status: {prev['status']} → {current_status}")

        if current_phase != prev["phase"]:
            changes.append(f"Phase: {prev['phase']} → {current_phase}")

        if current_enrollment != prev["enrollment"]:
            changes.append(f"Enrollment: {prev['enrollment']} → {current_enrollment}")

        if primary_completion != prev["primary_completion"]:
            changes.append(f"Primary Completion: {prev['primary_completion']} → {primary_completion}")

        if completion != prev["completion"]:
            changes.append(f"Completion Date: {prev['completion']} → {completion}")

        added_countries = list(set(current_countries) - set(prev_countries))
        removed_countries = list(set(prev_countries) - set(current_countries))

        if added_countries:
            changes.append("Countries Added: " + ", ".join(added_countries))

        if removed_countries:
            changes.append("Countries Removed: " + ", ".join(removed_countries))

        added_drugs = list(set(drugs) - set(prev_drugs))

        if added_drugs:
            changes.append("Drugs Added: " + ", ".join(added_drugs))

        if changes:
        
            disease = conditions if conditions else condition
        
            phase_text = current_phase.replace("PHASE_", "Phase ")
        
            drug_sentence = drug_text if drug_text != "NA" else "its investigational therapy"
        
            update_text = (
                f"{sponsor}'s {phase_text} trial evaluating {drug_sentence} "
                f"in patients with {disease} has been updated. "
                f"Changes: {'; '.join(changes)}."
            )

    updates.append(update_text)

    conn.close()

    st.success(f"New Trials: {len(new_trials)}")
    st.success(f"Updates: {len(updates)}")

    file_name = generate_pdf(
        condition,
        start_date,
        end_date,
        new_trials,
        updates
    )

    with open(file_name, "rb") as f:

        st.download_button(
            "Download PDF",
            f,
            file_name=file_name
        )
