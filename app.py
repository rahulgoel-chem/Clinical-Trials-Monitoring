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


# -------- PDF -------- #

def generate_pdf(condition, start_date, end_date, new_trials, updates):

    filename = f"trial_report_{condition}_{start_date}_{end_date}.pdf"
    c = canvas.Canvas(filename, pagesize=letter)

    y = 750

    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(300, y, "CLINICAL TRIAL INTELLIGENCE REPORT")

    y -= 40

    c.setFont("Helvetica", 11)
    c.drawString(60, y, f"Disease: {condition}")

    y -= 15
    c.drawString(60, y, f"Monitoring Window: {start_date} → {end_date}")

    y -= 15
    c.drawString(60, y, f"Generated: {datetime.today().date()}")

    y -= 30

    c.setFont("Helvetica-Bold", 12)
    c.drawString(60, y, "SUMMARY")

    y -= 20

    c.setFont("Helvetica", 11)
    c.drawString(70, y, f"New Trials: {len(new_trials)}")

    y -= 15
    c.drawString(70, y, f"Updated Trials: {len(updates)}")

    y -= 40

    # NEW TRIALS

    c.setFont("Helvetica-Bold", 12)
    c.drawString(60, y, "NEW INDUSTRY TRIALS")

    y -= 20

    c.setFont("Helvetica", 10)

    if not new_trials:
        c.drawString(70, y, "No new trials detected.")
        y -= 15

    else:

        for trial in new_trials:

            for line in wrap(trial, 90):

                if y < 60:
                    c.showPage()
                    y = 750

                c.drawString(70, y, line)
                y -= 14

            y -= 6

    y -= 20

    # UPDATES

    c.setFont("Helvetica-Bold", 12)
    c.drawString(60, y, "TRIAL UPDATES")

    y -= 20

    c.setFont("Helvetica", 10)

    if not updates:
        c.drawString(70, y, "No updates detected.")

    else:

        for upd in updates:

            for line in wrap(upd, 90):

                if y < 60:
                    c.showPage()
                    y = 750

                c.drawString(70, y, line)
                y -= 14

            y -= 6

    c.save()

    return filename


# -------- STREAMLIT UI -------- #

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

    # -------- NEW TRIALS FROM AACT -------- #

    conn = psycopg2.connect(
        host=AACT_HOST,
        database=AACT_DB,
        user=AACT_USER,
        password=AACT_PASS,
        port=AACT_PORT
    )

    cur = conn.cursor()

    query = """
    SELECT DISTINCT
        s.nct_id,
        s.brief_title,
        sp.name,
        s.study_first_post_date
    FROM studies s
    JOIN sponsors sp
        ON s.nct_id = sp.nct_id
    JOIN conditions c
        ON s.nct_id = c.nct_id
    WHERE
        LOWER(c.name) LIKE %s
        AND sp.lead_or_collaborator='lead'
        AND sp.agency_class='INDUSTRY'
        AND s.study_first_post_date BETWEEN %s AND %s
    """

    cur.execute(query, (f"%{condition.lower()}%", start, end))

    rows = cur.fetchall()

    for r in rows:

        nct_id, title, sponsor, post_date = r

        seen_nct.add(nct_id)

        report = f"[{nct_id}] {sponsor} started NEW trial: {title}"

        new_trials.append(report)

    cur.close()
    conn.close()

    # -------- UPDATES FROM CLINICALTRIALS API -------- #

    url = "https://clinicaltrials.gov/api/v2/studies"

    params = {
        "query.cond": condition,
        "pageSize": 1000
    }

    response = requests.get(url, params=params)

    studies = response.json().get("studies", [])

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

        if not nct_id or nct_id in seen_nct:
            continue

        title = ident.get("briefTitle", "")
        sponsor = sponsor_mod.get("leadSponsor", {}).get("name", "")

        update_date = status.get("lastUpdatePostDateStruct", {}).get("date")

        if not update_date:
            continue

        update_date = datetime.strptime(update_date, "%Y-%m-%d").date()

        if not (start_date <= update_date <= end_date):
            continue

        trial_status = status.get("overallStatus", "NA")

        start_trial = status.get("startDateStruct", {}).get("date", "NA")

        primary = status.get("primaryCompletionDateStruct", {}).get("date", "NA")

        completion = status.get("completionDateStruct", {}).get("date", "NA")

        enrollment = design.get("enrollmentInfo", {}).get("count", "NA")

        locations = locations_mod.get("locations", [])

        countries = sorted(set([
            loc.get("country") for loc in locations if loc.get("country")
        ]))

        countries_text = ", ".join(countries) if countries else "NA"

        report = (
            f"[{nct_id}] {sponsor} trial updated: {title} | "
            f"Status: {trial_status} | "
            f"Start: {start_trial} | "
            f"Primary Completion: {primary} | "
            f"Study Completion: {completion} | "
            f"Enrollment: {enrollment} | "
            f"Countries: {countries_text}"
        )

        updates.append(report)

        seen_nct.add(nct_id)

    st.success(f"New Trials: {len(new_trials)}")
    st.success(f"Updated Trials: {len(updates)}")

    pdf_file = generate_pdf(
        condition,
        start,
        end,
        new_trials,
        updates
    )

    with open(pdf_file, "rb") as f:

        st.download_button(
            "Download PDF Report",
            f,
            file_name=pdf_file
        )
