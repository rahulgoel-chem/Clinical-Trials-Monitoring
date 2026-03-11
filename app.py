import streamlit as st
import requests
import psycopg2
import json
import os
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

API_URL = "https://clinicaltrials.gov/api/v2/studies"


# ---------------- SNAPSHOT UTILS ---------------- #

def snapshot_file(date):
    return f"snapshot_{date}.json"


def save_snapshot(data, date):

    with open(snapshot_file(date), "w") as f:
        json.dump(data, f)


def load_snapshot(date):

    file = snapshot_file(date)

    if not os.path.exists(file):
        return {}

    with open(file) as f:
        return json.load(f)


# ---------------- FETCH UPDATED TRIALS ---------------- #

def fetch_trials(condition, date1, date2):

    trials = {}

    page_token = None

    while True:

        params = {
            "query.cond": condition,
            "filter.lastUpdatePostDate": f"{date1}:{date2}",
            "pageSize": 1000
        }

        if page_token:
            params["pageToken"] = page_token

        r = requests.get(API_URL, params=params)

        data = r.json()

        studies = data.get("studies", [])

        for study in studies:

            protocol = study.get("protocolSection", {})

            ident = protocol.get("identificationModule", {})
            status = protocol.get("statusModule", {})
            design = protocol.get("designModule", {})
            sponsor_mod = protocol.get("sponsorCollaboratorsModule", {})
            contacts = protocol.get("contactsLocationsModule", {})
            cond_mod = protocol.get("conditionsModule", {})

            nct_id = ident.get("nctId")

            if not nct_id:
                continue

            sponsor = sponsor_mod.get(
                "leadSponsor", {}
            ).get("name", "Unknown")

            phase = ", ".join(design.get("phases", []))

            status_val = status.get("overallStatus", "NA")

            start_date = status.get(
                "startDateStruct", {}
            ).get("date", "NA")

            primary_completion = status.get(
                "primaryCompletionDateStruct", {}
            ).get("date", "NA")

            completion = status.get(
                "completionDateStruct", {}
            ).get("date", "NA")

            enrollment = design.get(
                "enrollmentInfo", {}
            ).get("count")

            enrollment = str(enrollment) if enrollment else "NA"

            condition_val = ", ".join(
                cond_mod.get("conditions", [])
            )

            locations = contacts.get("locations", [])

            countries = sorted(
                list(
                    set(
                        loc.get("country")
                        for loc in locations
                        if loc.get("country")
                    )
                )
            )

            trials[nct_id] = {
                "sponsor": sponsor,
                "condition": condition_val,
                "phase": phase,
                "status": status_val,
                "start_date": start_date,
                "primary_completion": primary_completion,
                "completion": completion,
                "enrollment": enrollment,
                "countries": countries
            }

        page_token = data.get("nextPageToken")

        if not page_token:
            break

    return trials


# ---------------- NEW INDUSTRY TRIALS (AACT) ---------------- #

def fetch_new_trials(condition, date1, date2):

    conn = psycopg2.connect(
        host=AACT_HOST,
        dbname=AACT_DB,
        user=AACT_USER,
        password=AACT_PASS,
        port=AACT_PORT
    )

    cur = conn.cursor()

    query = """
    SELECT DISTINCT
    s.nct_id,
    s.brief_title,
    s.phase,
    s.overall_status,
    s.start_date,
    s.primary_completion_date,
    s.completion_date,
    s.enrollment
    FROM studies s
    JOIN sponsors sp
    ON s.nct_id = sp.nct_id
    JOIN conditions c
    ON s.nct_id = c.nct_id
    WHERE
    s.study_first_post_date BETWEEN %s AND %s
    AND sp.agency_class = 'INDUSTRY'
    AND LOWER(c.name) LIKE %s
    """

    cur.execute(
        query,
        (date1, date2, f"%{condition.lower()}%")
    )

    rows = cur.fetchall()

    conn.close()

    trials = []

    seen = set()

    for r in rows:

        if r[0] in seen:
            continue

        seen.add(r[0])

        trials.append(
            f"[{r[0]}] NEW trial: {r[1]} | "
            f"Phase {r[2]} | Status {r[3]} | "
            f"Start {r[4]} | "
            f"Primary Completion {r[5]} | "
            f"Completion {r[6]} | "
            f"Enrollment {r[7]}"
        )

    return trials


# ---------------- SNAPSHOT COMPARISON ---------------- #

def compare_snapshots(prev, curr):

    updates = []

    for nct_id, curr_data in curr.items():

        if nct_id not in prev:
            continue

        prev_data = prev[nct_id]

        changes = []

        if curr_data["status"] != prev_data["status"]:
            changes.append(
                f"Status: {prev_data['status']} → {curr_data['status']}"
            )

        if curr_data["start_date"] != prev_data["start_date"]:
            changes.append(
                f"Start Date: {prev_data['start_date']} → {curr_data['start_date']}"
            )

        if curr_data["primary_completion"] != prev_data["primary_completion"]:
            changes.append(
                f"Primary Completion: {prev_data['primary_completion']} → {curr_data['primary_completion']}"
            )

        if curr_data["completion"] != prev_data["completion"]:
            changes.append(
                f"Completion Date: {prev_data['completion']} → {curr_data['completion']}"
            )

        if curr_data["enrollment"] != prev_data["enrollment"]:
            changes.append(
                f"Enrollment: {prev_data['enrollment']} → {curr_data['enrollment']}"
            )

        added = set(curr_data["countries"]) - set(prev_data["countries"])
        removed = set(prev_data["countries"]) - set(curr_data["countries"])

        if added:
            changes.append(
                "Countries Added: " + ", ".join(sorted(added))
            )

        if removed:
            changes.append(
                "Countries Removed: " + ", ".join(sorted(removed))
            )

        if changes:

            updates.append(
                f"[{nct_id}] {curr_data['sponsor']} trial in "
                f"{curr_data['condition']} | Phase {curr_data['phase']} : "
                + "; ".join(changes)
            )

    return updates


# ---------------- PDF GENERATION ---------------- #

def generate_pdf(condition, date1, date2, new_trials, updates):

    filename = f"trial_report_{condition}_{date2}.pdf"

    c = canvas.Canvas(filename, pagesize=letter)

    width, height = letter
    y = height - 40

    c.setFont("Helvetica-Bold", 16)

    c.drawCentredString(
        width/2,
        y,
        "Clinical Trial Intelligence Report"
    )

    y -= 40

    c.setFont("Helvetica", 11)

    c.drawString(50, y, f"Disease: {condition}")
    y -= 20

    c.drawString(50, y, f"Monitoring Window: {date1} → {date2}")
    y -= 30

    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, "NEW INDUSTRY TRIALS")

    y -= 20

    c.setFont("Helvetica", 10)

    for t in new_trials:

        for line in wrap(t, 90):

            if y < 50:
                c.showPage()
                y = height - 40

            c.drawString(50, y, line)
            y -= 15

    y -= 20

    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, "TRIAL UPDATES")

    y -= 20

    c.setFont("Helvetica", 10)

    for u in updates:

        for line in wrap(u, 90):

            if y < 50:
                c.showPage()
                y = height - 40

            c.drawString(50, y, line)
            y -= 15

    c.save()

    return filename


# ---------------- STREAMLIT UI ---------------- #

st.title("Clinical Trial Monitoring System")

condition = st.text_input("Disease / Condition")

date1 = st.date_input("First Snapshot Date")
date2 = st.date_input("Second Snapshot Date")


if st.button("Run Monitor"):

    if not condition:
        st.warning("Please enter a disease.")
        st.stop()

    date1 = str(date1)
    date2 = str(date2)

    if not os.path.exists(snapshot_file(date1)):

        st.write("Creating first snapshot...")

        trials = fetch_trials(condition, date1, date2)

        save_snapshot(trials, date1)

        st.warning(
            "First snapshot created. Run again to compare."
        )

        st.stop()

    if not os.path.exists(snapshot_file(date2)):

        st.write("Creating second snapshot...")

        trials = fetch_trials(condition, date1, date2)

        save_snapshot(trials, date2)

    prev_snapshot = load_snapshot(date1)
    curr_snapshot = load_snapshot(date2)

    updates = compare_snapshots(prev_snapshot, curr_snapshot)

    new_trials = fetch_new_trials(condition, date1, date2)

    st.subheader("New Industry Trials")

    if new_trials:
        for t in new_trials:
            st.write(t)
    else:
        st.write("No new trials detected.")

    st.subheader("Trial Updates")

    if updates:
        for u in updates:
            st.write(u)
    else:
        st.write("No updates detected.")

    pdf = generate_pdf(condition, date1, date2, new_trials, updates)

    with open(pdf, "rb") as f:

        st.download_button(
            "Download PDF Report",
            f,
            file_name=pdf
        )
