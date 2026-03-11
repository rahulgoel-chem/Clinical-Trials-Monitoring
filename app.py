import streamlit as st
import requests
from datetime import datetime
import json
import os

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from textwrap import wrap


# -------- PDF SETTINGS -------- #

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
            y = draw_wrapped_text(c, f"• {trial}", 60, y)
            y -= 5

    y -= 20

    y = draw_section_title(c, "TRIAL UPDATES", y, width)

    if not updates:
        y = draw_wrapped_text(c, "No trial updates detected.", 60, y)

    else:
        for upd in updates:
            y = draw_wrapped_text(c, f"• {upd}", 60, y)
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

    start_date_str = start_date.strftime("%Y-%m-%d")
    end_date_str = end_date.strftime("%Y-%m-%d")

    SNAPSHOT_START = f"snapshot_{start_date_str}.json"
    SNAPSHOT_END = f"snapshot_{end_date_str}.json"

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

    snapshot_start = {}
    snapshot_end = {}

    new_trials = []
    updates = []

    for study in studies:

        protocol = study.get("protocolSection", {})
        status = protocol.get("statusModule", {})
        sponsor_mod = protocol.get("sponsorCollaboratorsModule", {})
        design = protocol.get("designModule", {})

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

        upd_date_str = status.get("lastUpdatePostDateStruct", {}).get("date")

        if not upd_date_str:
            continue

        upd_date = datetime.strptime(upd_date_str, "%Y-%m-%d").date()

        first_post_str = status.get("studyFirstPostDateStruct", {}).get("date")

        if first_post_str:

            first_post_date = datetime.strptime(first_post_str, "%Y-%m-%d").date()

            if start_date <= first_post_date <= end_date:

                phase = ", ".join(design.get("phases", [])) or "NA"

                trial_status = status.get("overallStatus", "NA")

                trial_report = (
                    f"[{nct_id}] {sponsor} started NEW trial: {title} | "
                    f"Status: {trial_status} | Phase: {phase}"
                )

                new_trials.append(trial_report)

        current_snapshot = {

            "status": status.get("overallStatus", "NA"),
            "start_date": status.get("startDateStruct", {}).get("date", "NA"),
            "primary_completion": status.get("primaryCompletionDateStruct", {}).get("date", "NA"),
            "completion": status.get("completionDateStruct", {}).get("date", "NA"),
            "enrollment": design.get("enrollmentInfo", {}).get("count", "NA"),
            "countries": sorted(list(set([
                loc.get("country")
                for loc in protocol.get("contactsLocationsModule", {}).get("locations", [])
                if loc.get("country")
            ])))
        }

        if upd_date <= start_date:
            snapshot_start[nct_id] = current_snapshot

        if upd_date <= end_date:
            snapshot_end[nct_id] = current_snapshot

    with open(SNAPSHOT_START, "w") as f:
        json.dump(snapshot_start, f, indent=2)

    with open(SNAPSHOT_END, "w") as f:
        json.dump(snapshot_end, f, indent=2)

    for nct_id in snapshot_start:

        if nct_id not in snapshot_end:
            continue

        prev = snapshot_start[nct_id]
        curr = snapshot_end[nct_id]

        changes = []

        for field in prev:

            if prev[field] != curr[field]:

                changes.append(f"{field}: {prev[field]} → {curr[field]}")

        if changes:
            updates.append(f"{nct_id}: " + "; ".join(changes))

    st.success(f"Total New Trials: {len(new_trials)}")
    st.success(f"Total Updates: {len(updates)}")

    file_name = generate_pdf(
        condition,
        start_date_str,
        end_date_str,
        new_trials,
        updates
    )

    with open(file_name, "rb") as f:

        st.download_button(
            "Download PDF Report",
            f,
            file_name=file_name
        )
