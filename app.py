import streamlit as st
import requests
import psycopg2
import json
import os
from datetime import datetime

# ---------------- CONFIG ---------------- #

AACT_HOST = st.secrets["AACT_HOST"]
AACT_DB = st.secrets["AACT_DB"]
AACT_PORT = st.secrets["AACT_PORT"]
AACT_USER = st.secrets["AACT_USER"]
AACT_PASS = st.secrets["AACT_PASS"]

API_URL = "https://clinicaltrials.gov/api/v2/studies"

# ---------------- DB CONNECTION ---------------- #

def connect_aact():

    return psycopg2.connect(
        host=AACT_HOST,
        dbname=AACT_DB,
        user=AACT_USER,
        password=AACT_PASS,
        port=AACT_PORT
    )

# ---------------- SNAPSHOT FUNCTIONS ---------------- #

def save_snapshot(data, date):

    filename = f"snapshot_{date}.json"

    with open(filename, "w") as f:
        json.dump(data, f, indent=2)


def load_snapshot(date):

    filename = f"snapshot_{date}.json"

    if not os.path.exists(filename):
        return {}

    with open(filename) as f:
        return json.load(f)

# ---------------- FETCH API DATA ---------------- #

def fetch_trials():

    trials = {}

    page_token = None

    while True:

        params = {
            "pageSize": 1000
        }

        if page_token:
            params["pageToken"] = page_token

        r = requests.get(API_URL, params=params)

        data = r.json()

        studies = data.get("studies", [])

        for study in studies:

            protocol = study.get("protocolSection", {})

            identification = protocol.get("identificationModule", {})
            status = protocol.get("statusModule", {})
            design = protocol.get("designModule", {})
            conditions = protocol.get("conditionsModule", {})
            sponsor_module = protocol.get("sponsorCollaboratorsModule", {})
            contacts = protocol.get("contactsLocationsModule", {})

            nct_id = identification.get("nctId")

            if not nct_id:
                continue

            sponsor = sponsor_module.get(
                "leadSponsor", {}
            ).get("name", "Unknown")

            condition = ", ".join(
                conditions.get("conditions", [])
            )

            phase = ", ".join(
                design.get("phases", [])
            )

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
                "condition": condition,
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


# ---------------- COMPARE SNAPSHOTS ---------------- #

def compare_snapshots(prev, curr):

    updates = []

    seen = set()

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

        if changes and nct_id not in seen:

            updates.append(
                f"[{nct_id}] {curr_data['sponsor']} trial in {curr_data['condition']} | Phase {curr_data['phase']}: "
                + "; ".join(changes)
            )

            seen.add(nct_id)

    return updates


# ---------------- STREAMLIT APP ---------------- #

st.title("Clinical Trial Monitoring")

date1 = st.date_input("First Snapshot Date")
date2 = st.date_input("Second Snapshot Date")

if st.button("Run Monitor"):

    st.write("Fetching ClinicalTrials.gov data...")

    trials = fetch_trials()

    date1 = str(date1)
    date2 = str(date2)

    # Save snapshots
    save_snapshot(trials, date2)

    prev_snapshot = load_snapshot(date1)
    curr_snapshot = load_snapshot(date2)

    if not prev_snapshot:
        st.warning(
            f"No snapshot exists for {date1}. Run monitor once on that date first."
        )
        st.stop()

    updates = compare_snapshots(prev_snapshot, curr_snapshot)

    st.subheader("Trial Updates")

    if updates:

        for u in updates:
            st.write(u)

    else:
        st.write("No updates detected.")
