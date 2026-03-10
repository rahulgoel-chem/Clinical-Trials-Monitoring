import streamlit as st
import requests
import psycopg2
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from textwrap import wrap


# ---------------- CONFIG ---------------- #

AACT_HOST = st.secrets["AACT_HOST"]
AACT_DB = st.secrets["AACT_DB"]
AACT_PORT = st.secrets["AACT_PORT"]
AACT_USER = st.secrets["AACT_USER"]
AACT_PASS = st.secrets["AACT_PASS"]


# ---------------- PDF GENERATOR ---------------- #

def generate_pdf(condition, start, end, new_trials, updates):

    filename = f"trial_report_{condition}.pdf"

    c = canvas.Canvas(filename, pagesize=letter)

    y = 750

    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(300, y, "CLINICAL TRIAL MONITORING REPORT")

    y -= 40
    c.setFont("Helvetica", 11)

    c.drawString(60, y, f"Disease: {condition}")
    y -= 15
    c.drawString(60, y, f"Monitoring Window: {start} → {end}")
    y -= 15
    c.drawString(60, y, f"Generated: {datetime.today().date()}")

    y -= 30
    c.drawString(60, y, f"New Trials: {len(new_trials)}")
    y -= 15
    c.drawString(60, y, f"Updated Trials: {len(updates)}")

    y -= 30

    c.setFont("Helvetica-Bold", 12)
    c.drawString(60, y, "NEW TRIALS")

    y -= 20
    c.setFont("Helvetica", 10)

    for trial in new_trials:

        for line in wrap(trial, 90):

            if y < 60:
                c.showPage()
                y = 750

            c.drawString(70, y, line)
            y -= 14

        y -= 6

    y -= 30

    c.setFont("Helvetica-Bold", 12)
    c.drawString(60, y, "UPDATED TRIALS")

    y -= 20
    c.setFont("Helvetica", 10)

    for trial in updates:

        for line in wrap(trial, 90):

            if y < 60:
                c.showPage()
                y = 750

            c.drawString(70, y, line)
            y -= 14

        y -= 6

    c.save()

    return filename


# ---------------- STREAMLIT UI ---------------- #

st.title("Clinical Trial Intelligence Monitor")

condition = st.text_input("Disease / Condition")

start_date = st.date_input("Start Date")
end_date = st.date_input("End Date")

run = st.button("Run Monitor")


if run:

    start = start_date.strftime("%Y-%m-%d")
    end = end_date.strftime("%Y-%m-%d")

    new_trials = []
    updates = []
    seen_nct = set()


    # ---------------- AACT: GET EXISTING NCT IDS ONLY ---------------- #

    conn = psycopg2.connect(
        host=AACT_HOST,
        database=AACT_DB,
        user=AACT_USER,
        password=AACT_PASS,
        port=AACT_PORT
    )

    cur = conn.cursor()

    cur.execute("SELECT nct_id FROM studies")

    rows = cur.fetchall()

    existing_trials = set(r[0] for r in rows)

    cur.close()
    conn.close()


    # ---------------- CLINICALTRIALS API PAGINATION ---------------- #

    base_url = "https://clinicaltrials.gov/api/v2/studies"

    params = {
        "query.cond": condition,
        "pageSize": 1000
    }

    studies = []
    next_token = None

    while True:

        if next_token:
            params["pageToken"] = next_token

        response = requests.get(base_url, params=params)

        data = response.json()

        studies.extend(data.get("studies", []))

        next_token = data.get("nextPageToken")

        if not next_token:
            break


    # ---------------- PROCESS STUDIES ---------------- #

    for study in studies:

        protocol = study.get("protocolSection", {})

        ident = protocol.get("identificationModule", {})
        status = protocol.get("statusModule", {})
        design = protocol.get("designModule", {})
        sponsor_mod = protocol.get("sponsorCollaboratorsModule", {})
        locations_mod = protocol.get("contactsLocationsModule", {})

        sponsor_class = sponsor_mod.get("leadSponsor", {}).get("class", "")

        if sponsor_class != "INDUSTRY":
            continue


        nct_id = ident.get("nctId")

        if not nct_id:
            continue

        title = ident.get("briefTitle", "")
        sponsor = sponsor_mod.get("leadSponsor", {}).get("name", "")


        # ---------- NEW TRIAL DETECTION ---------- #

        if nct_id not in existing_trials:

            report = f"[{nct_id}] {sponsor} registered new trial: {title}"

            new_trials.append(report)

            seen_nct.add(nct_id)

            continue


        # ---------- UPDATE DETECTION ---------- #

        update_date = status.get("lastUpdatePostDateStruct", {}).get("date")

        if not update_date:
            continue

        update_date = datetime.strptime(update_date, "%Y-%m-%d").date()

        if not (start_date <= update_date <= end_date):
            continue


        trial_status = status.get("overallStatus", "NA")

        start_trial = status.get("startDateStruct", {}).get("date", "NA")

        primary_completion = status.get(
            "primaryCompletionDateStruct", {}
        ).get("date", "NA")

        completion = status.get(
            "completionDateStruct", {}
        ).get("date", "NA")

        enrollment = design.get(
            "enrollmentInfo", {}
        ).get("count", "NA")


        locations = locations_mod.get("locations", [])

        countries = sorted(set(
            loc.get("country")
            for loc in locations
            if loc.get("country")
        ))

        countries_text = ", ".join(countries) if countries else "NA"


        report = (
            f"[{nct_id}] {sponsor} trial updated: {title} | "
            f"Status: {trial_status} | "
            f"Start: {start_trial} | "
            f"Primary Completion: {primary_completion} | "
            f"Study Completion: {completion} | "
            f"Enrollment: {enrollment} | "
            f"Countries: {countries_text}"
        )

        updates.append(report)

        seen_nct.add(nct_id)


    # ---------------- RESULTS ---------------- #

    st.success(f"New Trials: {len(new_trials)}")
    st.success(f"Updated Trials: {len(updates)}")


    pdf_file = generate_pdf(condition, start, end, new_trials, updates)

    with open(pdf_file, "rb") as f:

        st.download_button(
            "Download PDF Report",
            f,
            file_name=pdf_file
        )
