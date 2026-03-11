import streamlit as st
import requests
from datetime import datetime
import psycopg2
import json
import os

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from textwrap import wrap


# -------- CONFIG -------- #

AACT_HOST = st.secrets["AACT_HOST"]
AACT_DB = st.secrets["AACT_DB"]
AACT_PORT = st.secrets["AACT_PORT"]
AACT_USER = st.secrets["AACT_USER"]
AACT_PASS = st.secrets["AACT_PASS"]

SNAPSHOT_FILE = "trial_snapshots.json"


# -------- HELPER FUNCTIONS -------- #

def connect_aact():
    return psycopg2.connect(
        host=AACT_HOST,
        database=AACT_DB,
        user=AACT_USER,
        password=AACT_PASS,
        port=AACT_PORT
    )


def load_snapshots():

    if not os.path.exists(SNAPSHOT_FILE):
        return {}

    with open(SNAPSHOT_FILE, "r") as f:
        return json.load(f)


def save_snapshots(data):

    with open(SNAPSHOT_FILE, "w") as f:
        json.dump(data, f, indent=2)


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

    safe_condition = condition.replace(" ", "_").lower()

    file_name = f"clinical_trial_report_{safe_condition}_{start_date}_{end_date}.pdf"

    c = canvas.Canvas(file_name, pagesize=letter)

    width, height = letter
    y = height - 50

    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(width / 2, y, "CLINICAL TRIAL INTELLIGENCE REPORT")

    y -= 30

    c.setFont("Helvetica", 11)
    c.drawString(50, y, f"Disease: {condition}")

    y -= 15
    c.drawString(50, y, f"Monitoring Window: {start_date} to {end_date}")

    y -= 15
    c.drawString(50, y, f"Generated on: {datetime.today().date()}")

    y -= 25
    c.line(40, y, width - 40, y)

    y -= 25

    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, "SUMMARY")

    y -= 10
    c.line(50, y, width - 50, y)

    y -= 20

    c.setFont("Helvetica", 11)
    c.drawString(60, y, f"Total New Trials: {len(new_trials)}")

    y -= 15
    c.drawString(60, y, f"Total Updated Trials: {len(updates)}")

    y -= 30

    y = draw_section_title(c, "NEW INDUSTRY TRIALS", y, width)

    c.setFont("Helvetica", 10)

    if not new_trials:
        y = draw_wrapped_text(c, "No new industry trials detected.", 60, y)

    else:
        for trial in new_trials:
            trial_text = f"• {trial}"
            y = draw_wrapped_text(c, trial_text, 60, y)
            y -= 5

    y -= 20

    y = draw_section_title(c, "TRIAL UPDATES", y, width)

    c.setFont("Helvetica", 10)

    if not updates:
        y = draw_wrapped_text(c, "No trial updates detected.", 60, y)

    else:
        for upd in updates:
            upd_text = f"• {upd}"
            y = draw_wrapped_text(c, upd_text, 60, y)
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

    start_date_input = start_date.strftime("%Y-%m-%d")
    end_date_input = end_date.strftime("%Y-%m-%d")

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

    conn = connect_aact()

    snapshots = load_snapshots()

    new_trials = []
    updates = []
    seen_trials = set()

    for study in studies:

        protocol = study.get("protocolSection", {})
        status = protocol.get("statusModule", {})
        sponsor_mod = protocol.get("sponsorCollaboratorsModule", {})
        design = protocol.get("designModule", {})

        upd_date_str = status.get("lastUpdatePostDateStruct", {}).get("date")

        if not upd_date_str:
            continue

        upd_date = datetime.strptime(upd_date_str, "%Y-%m-%d")

        if not (start_date <= upd_date.date() <= end_date):
            continue

        sponsor_class = sponsor_mod.get("leadSponsor", {}).get("class", "")

        if sponsor_class.upper() != "INDUSTRY":
            continue

        ident = protocol.get("identificationModule", {})
        nct_id = ident.get("nctId")
        title = ident.get("briefTitle", "")

        sponsor = sponsor_mod.get("leadSponsor", {}).get("name", "NA")

        conditions = ", ".join(
            protocol.get("conditionsModule", {}).get("conditions", [])
        )

        # -------- NEW TRIAL DETECTION -------- #

        first_post_str = status.get("studyFirstPostDateStruct", {}).get("date")

        if first_post_str:

            first_post_date = datetime.strptime(first_post_str, "%Y-%m-%d").date()

            if start_date <= first_post_date <= end_date:

                phase = ", ".join(design.get("phases", [])) or "NA"

                trial_status = status.get("overallStatus", "NA")

                study_start = status.get("startDateStruct", {}).get("date", "NA")

                primary_completion = status.get(
                    "primaryCompletionDateStruct", {}
                ).get("date", "NA")

                study_completion = status.get(
                    "completionDateStruct", {}
                ).get("date", "NA")

                enrollment = design.get(
                    "enrollmentInfo", {}
                ).get("count", "NA")

                locations = protocol.get(
                    "contactsLocationsModule", {}
                ).get("locations", [])

                countries = sorted(list(set([
                    loc.get("country") for loc in locations if loc.get("country")
                ])))

                countries_text = ", ".join(countries) if countries else "NA"

                trial_report = (
                    f"[{nct_id}] {sponsor} started NEW trial: {title} | "
                    f"Status: {trial_status} | "
                    f"Phase: {phase} | "
                    f"Start: {study_start} | "
                    f"Primary Completion: {primary_completion} | "
                    f"Study Completion: {study_completion} | "
                    f"Enrollment: {enrollment} | "
                    f"Countries: {countries_text}"
                )

                if nct_id not in seen_trials:
                    new_trials.append(trial_report)
                    seen_trials.add(nct_id)

        # -------- UPDATE DETECTION (API SNAPSHOT COMPARISON) -------- #

        current_status = status.get("overallStatus", "NA")
        current_phase = ", ".join(design.get("phases", [])) or "NA"

        current_enrollment = design.get("enrollmentInfo", {}).get("count")
        current_enrollment = str(current_enrollment) if current_enrollment else "NA"

        current_start_date = status.get("startDateStruct", {}).get("date", "NA")

        current_primary_completion = status.get(
            "primaryCompletionDateStruct", {}
        ).get("date", "NA")

        current_completion = status.get(
            "completionDateStruct", {}
        ).get("date", "NA")

        locations = protocol.get("contactsLocationsModule", {}).get("locations", [])

        current_countries = sorted(list(set([
            loc.get("country") for loc in locations if loc.get("country")
        ])))

        current_snapshot = {
            "status": current_status,
            "start_date": current_start_date,
            "primary_completion": current_primary_completion,
            "completion": current_completion,
            "enrollment": current_enrollment,
            "countries": current_countries
        }

        if nct_id in seen_trials:
            snapshots[nct_id] = current_snapshot
            continue

        previous_snapshot = snapshots.get(nct_id)

        if not previous_snapshot:
            snapshots[nct_id] = current_snapshot
            continue

        changes = []

        termination_statuses = ["TERMINATED", "SUSPENDED", "WITHDRAWN"]

        if (
            current_status.upper() in termination_statuses
            and previous_snapshot["status"].upper() not in termination_statuses
        ):
            changes.append(
                f"TRIAL TERMINATED: Status changed {previous_snapshot['status']} → {current_status}"
            )

        elif current_status != previous_snapshot["status"]:
            changes.append(
                f"Status: {previous_snapshot['status']} → {current_status}"
            )

        if str(current_start_date) != str(previous_snapshot["start_date"]):
            changes.append(
                f"Start Date: {previous_snapshot['start_date']} → {current_start_date}"
            )

        if str(current_primary_completion) != str(previous_snapshot["primary_completion"]):
            changes.append(
                f"Primary Completion: {previous_snapshot['primary_completion']} → {current_primary_completion}"
            )

        if str(current_completion) != str(previous_snapshot["completion"]):
            changes.append(
                f"Study Completion: {previous_snapshot['completion']} → {current_completion}"
            )

        if current_enrollment != previous_snapshot["enrollment"]:
            changes.append(
                f"Enrollment: {previous_snapshot['enrollment']} → {current_enrollment}"
            )

        added_countries = list(set(current_countries) - set(previous_snapshot["countries"]))

        if added_countries:
            changes.append("Countries Added: " + ", ".join(sorted(added_countries)))

        removed_countries = list(set(previous_snapshot["countries"]) - set(current_countries))

        if removed_countries:
            changes.append("Countries Removed: " + ", ".join(sorted(removed_countries)))

        if changes and nct_id not in seen_trials:

            updates.append(
                f"[{nct_id}] {sponsor} trial in {conditions} | Phase: {current_phase}: "
                + "; ".join(changes)
            )

            seen_trials.add(nct_id)

        snapshots[nct_id] = current_snapshot

    conn.close()

    save_snapshots(snapshots)

    st.success(f"Total New Trials: {len(new_trials)}")
    st.success(f"Total Updates: {len(updates)}")

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
