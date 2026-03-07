import streamlit as st
import requests
import psycopg2
from datetime import date
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
import os


# ----------------------------
# DATABASE CONNECTION
# ----------------------------

def connect_db():

    conn = psycopg2.connect(
        host="aact-db.ctti-clinicaltrials.org",
        database="aact",
        user="reader",
        password=st.secrets["AACT_DB_PASSWORD"],
        port="5432"
    )

    return conn


# ----------------------------
# GET PREVIOUS TRIAL DATA
# ----------------------------

def get_previous_trial_data(conn, nct_id):

    query = """
    SELECT overall_status, phase, enrollment
    FROM studies
    WHERE nct_id = %s
    """

    cur = conn.cursor()
    cur.execute(query, (nct_id,))
    row = cur.fetchone()

    if not row:
        return None

    return {
        "status": row[0],
        "phase": row[1],
        "enrollment": str(row[2])
    }


def get_previous_countries(conn, nct_id):

    query = """
    SELECT DISTINCT country
    FROM facilities
    WHERE nct_id = %s
    """

    cur = conn.cursor()
    cur.execute(query, (nct_id,))
    rows = cur.fetchall()

    return sorted([r[0] for r in rows if r[0]])


# ----------------------------
# CLINICALTRIALS API
# ----------------------------

def fetch_trials(condition, start_date, end_date):

    url = "https://clinicaltrials.gov/api/v2/studies"

    fields = [
        "protocolSection.identificationModule.nctId",
        "protocolSection.identificationModule.briefTitle",
        "protocolSection.statusModule.overallStatus",
        "protocolSection.statusModule.enrollmentStruct",
        "protocolSection.sponsorCollaboratorsModule.leadSponsor.name",
        "protocolSection.conditionsModule.conditions",
        "protocolSection.designModule.phases",
        "protocolSection.contactsLocationsModule.locations"
    ]

    params = {
        "query.cond": condition,
        "query.lastUpdatePostDate": f"RANGE[{start_date},{end_date}]",
        "pageSize": 1000
    }

    response = requests.get(url, params=params)
    data = response.json()

    return data.get("studies", [])


# ----------------------------
# PDF GENERATION
# ----------------------------

def generate_pdf(new_trials, updates):

    filename = "clinical_trial_report.pdf"

    styles = getSampleStyleSheet()

    elements = []

    elements.append(Paragraph("Clinical Trial Intelligence Report", styles["Title"]))
    elements.append(Spacer(1, 20))

    elements.append(Paragraph("New Trials", styles["Heading2"]))
    elements.append(Spacer(1, 10))

    if not new_trials:
        elements.append(Paragraph("None", styles["Normal"]))
    else:
        for trial in new_trials:
            elements.append(Paragraph(trial, styles["Normal"]))
            elements.append(Spacer(1, 5))

    elements.append(Spacer(1, 20))

    elements.append(Paragraph("Updated Trials", styles["Heading2"]))
    elements.append(Spacer(1, 10))

    if not updates:
        elements.append(Paragraph("None", styles["Normal"]))
    else:
        for trial in updates:
            elements.append(Paragraph(trial, styles["Normal"]))
            elements.append(Spacer(1, 5))

    doc = SimpleDocTemplate(filename)
    doc.build(elements)

    return filename


# ----------------------------
# STREAMLIT UI
# ----------------------------

st.title("Clinical Trial Change Tracker")

condition = st.text_input("Disease / Condition", "antibody drug conjugate")

start_date = st.date_input("Start Date", date(2026,3,1))
end_date = st.date_input("End Date", date(2026,3,7))


if st.button("Generate Report"):

    conn = connect_db()

    trials = fetch_trials(condition, start_date, end_date)

    new_trials = []
    updates = []

    for trial in trials:

        protocol = trial.get("protocolSection", {})

        id_module = protocol.get("identificationModule", {})
        status_module = protocol.get("statusModule", {})
        design_module = protocol.get("designModule", {})
        sponsor_module = protocol.get("sponsorCollaboratorsModule", {})
        conditions_module = protocol.get("conditionsModule", {})
        locations_module = protocol.get("contactsLocationsModule", {})

        nct_id = id_module.get("nctId", "NA")
        title = id_module.get("briefTitle", "NA")

        sponsor = sponsor_module.get("leadSponsor", {}).get("name", "NA")

        conditions = ", ".join(conditions_module.get("conditions", []))

        current_status = status_module.get("overallStatus", "NA")

        current_phase = ", ".join(design_module.get("phases", [])) or "NA"

        current_enrollment = str(
            status_module.get("enrollmentStruct", {}).get("count", "NA")
        )

        locations = locations_module.get("locations", [])

        current_countries = sorted(list(set([
            loc.get("country") for loc in locations if loc.get("country")
        ])))

        # --------------------------
        # PREVIOUS DATA
        # --------------------------

        prev = get_previous_trial_data(conn, nct_id)

        if not prev:

            new_trials.append(
                f"[{nct_id}] {sponsor} started NEW trial: {title}"
            )

            continue

        prev_status = prev["status"]
        prev_phase = prev["phase"]
        prev_enrollment = prev["enrollment"]

        prev_countries = get_previous_countries(conn, nct_id)

        # --------------------------
        # CHANGE DETECTION
        # --------------------------

        changes = []

        if current_status != prev_status:
            changes.append(f"Status: {prev_status} → {current_status}")

        if current_phase != prev_phase:
            changes.append(f"Phase: {prev_phase} → {current_phase}")

        if current_enrollment != prev_enrollment:
            changes.append(f"Enrollment: {prev_enrollment} → {current_enrollment}")

        added_countries = list(set(current_countries) - set(prev_countries))

        if added_countries:
            changes.append("New Countries Added: " + ", ".join(added_countries))

        if changes:

            updates.append(
                f"[{nct_id}] {sponsor} trial in {conditions}: "
                + "; ".join(changes)
            )

    # --------------------------
    # CREATE PDF
    # --------------------------

    pdf_file = generate_pdf(new_trials, updates)

    with open(pdf_file, "rb") as f:

        st.download_button(
            "Download Report",
            f,
            file_name=pdf_file
        )
    st.success("Report Generated")
