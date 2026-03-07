import streamlit as st
import requests
from datetime import datetime
import psycopg2
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from textwrap import wrap


# ---------- CONFIG ----------

AACT_HOST = st.secrets["AACT_HOST"]
AACT_DB = st.secrets["AACT_DB"]
AACT_PORT = st.secrets["AACT_PORT"]
AACT_USER = st.secrets["AACT_USER"]
AACT_PASS = st.secrets["AACT_PASS"]


# ---------- DATABASE ----------

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

    cur.execute("""
        SELECT overall_status,
               phase,
               enrollment,
               primary_completion_date,
               completion_date
        FROM studies
        WHERE nct_id = %s
    """, (nct_id,))

    row = cur.fetchone()
    cur.close()

    if row:
        return {
            "status": str(row[0]),
            "phase": str(row[1]),
            "enrollment": str(row[2]),
            "primary_completion": str(row[3]),
            "completion": str(row[4])
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


def get_previous_interventions(conn, nct_id):

    cur = conn.cursor()

    cur.execute("""
        SELECT name
        FROM interventions
        WHERE nct_id = %s
    """, (nct_id,))

    rows = cur.fetchall()
    cur.close()

    return sorted([r[0] for r in rows])


# ---------- PDF ----------

def generate_pdf(condition, start_date, end_date, new_trials, updates):

    file_name = f"trial_report_{condition}_{start_date}_{end_date}.pdf"

    c = canvas.Canvas(file_name, pagesize=letter)
    width, height = letter
    y = height - 50

    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(width/2, y, "Clinical Trial Intelligence Report")

    y -= 30
    c.setFont("Helvetica", 11)

    c.drawString(60, y, f"Disease: {condition}")
    y -= 15
    c.drawString(60, y, f"Monitoring Window: {start_date} to {end_date}")

    y -= 30

    c.setFont("Helvetica-Bold", 12)
    c.drawString(60, y, "New Trials")

    y -= 20

    for t in new_trials:
        for line in wrap(t, 90):
            c.drawString(60, y, line)
            y -= 14

    y -= 20

    c.setFont("Helvetica-Bold", 12)
    c.drawString(60, y, "Trial Updates")

    y -= 20

    for u in updates:
        for line in wrap(u, 90):
            c.drawString(60, y, line)
            y -= 14

    c.save()

    return file_name


# ---------- STREAMLIT UI ----------

st.title("Clinical Trial Intelligence Monitor")

condition = st.text_input("Disease / Condition")

start_date = st.date_input("Start Date")
end_date = st.date_input("End Date")

run = st.button("Run Analysis")


if run:

    base_url = "https://clinicaltrials.gov/api/v2/studies"

    fields = [
        "protocolSection.identificationModule",
        "protocolSection.statusModule",
        "protocolSection.designModule",
        "protocolSection.conditionsModule",
        "protocolSection.contactsLocationsModule",
        "protocolSection.sponsorCollaboratorsModule",
        "protocolSection.interventionsModule"
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
        ident = protocol.get("identificationModule", {})
        status = protocol.get("statusModule", {})
        design = protocol.get("designModule", {})
        sponsor_mod = protocol.get("sponsorCollaboratorsModule", {})
        loc_mod = protocol.get("contactsLocationsModule", {})
        int_mod = protocol.get("interventionsModule", {})

        sponsor_class = sponsor_mod.get("leadSponsor", {}).get("class", "")

        if sponsor_class.upper() != "INDUSTRY":
            continue

        nct_id = ident.get("nctId")
        title = ident.get("briefTitle")

        sponsor = sponsor_mod.get("leadSponsor", {}).get("name")

        conditions = ", ".join(protocol.get("conditionsModule", {}).get("conditions", []))

        last_update = status.get("lastUpdatePostDateStruct", {}).get("date")

        if not last_update:
            continue

        upd_date = datetime.strptime(last_update, "%Y-%m-%d").date()

        if not(start_date <= upd_date <= end_date):
            continue


        # ----- CURRENT VALUES -----

        current_status = status.get("overallStatus")

        current_phase = ", ".join(design.get("phases", []))

        current_enrollment = str(
            design.get("enrollmentInfo", {}).get("count", "NA")
        )

        primary_completion = status.get("primaryCompletionDateStruct", {}).get("date")

        completion = status.get("completionDateStruct", {}).get("date")

        interventions = sorted([
            i.get("name") for i in int_mod.get("interventions", [])
        ])

        locations = loc_mod.get("locations", [])

        countries = sorted(list(set([
            l.get("country") for l in locations if l.get("country")
        ])))


        # ----- PREVIOUS VALUES -----

        prev = get_previous_trial_data(conn, nct_id)

        if not prev:
            continue

        prev_countries = get_previous_countries(conn, nct_id)
        prev_drugs = get_previous_interventions(conn, nct_id)


        changes = []

        if current_status != prev["status"]:
            changes.append(f"Status: {prev['status']} → {current_status}")

        if current_phase != prev["phase"]:
            changes.append(f"Phase: {prev['phase']} → {current_phase}")

        if current_enrollment != prev["enrollment"]:
            changes.append(f"Enrollment: {prev['enrollment']} → {current_enrollment}")

        if str(primary_completion) != prev["primary_completion"]:
            changes.append(
                f"Primary Completion: {prev['primary_completion']} → {primary_completion}"
            )

        if str(completion) != prev["completion"]:
            changes.append(
                f"Study Completion: {prev['completion']} → {completion}"
            )

        added = list(set(countries) - set(prev_countries))
        removed = list(set(prev_countries) - set(countries))

        if added:
            changes.append("Countries Added: " + ", ".join(added))

        if removed:
            changes.append("Countries Removed: " + ", ".join(removed))

        drug_added = list(set(interventions) - set(prev_drugs))
        drug_removed = list(set(prev_drugs) - set(interventions))

        if drug_added:
            changes.append("Drugs Added: " + ", ".join(drug_added))

        if drug_removed:
            changes.append("Drugs Removed: " + ", ".join(drug_removed))

        if changes:

            updates.append(
                f"[{nct_id}] {sponsor} trial in {conditions}: "
                + "; ".join(changes)
            )


    conn.close()

    st.success(f"Updates detected: {len(updates)}")

    file = generate_pdf(condition, start_date, end_date, [], updates)

    with open(file, "rb") as f:
        st.download_button("Download PDF", f, file_name=file)
