import streamlit as st
import requests
import pandas as pd
import os
from datetime import datetime

st.title("Clinical Trials Tracker")

API_URL = "https://clinicaltrials.gov/api/v2/studies"

# File to store previous run data
DATA_FILE = "stored_trials.csv"


def fetch_trials():
    params = {
        "pageSize": 100,
        "format": "json"
    }

    response = requests.get(API_URL, params=params)

    if response.status_code != 200:
        st.error("Error fetching data from ClinicalTrials.gov")
        return pd.DataFrame()

    data = response.json()

    trials = []

    for study in data.get("studies", []):

        protocol = study.get("protocolSection", {})
        status = protocol.get("statusModule", {})
        design = protocol.get("designModule", {})
        identification = protocol.get("identificationModule", {})

        nct_id = identification.get("nctId", "NA")
        title = identification.get("briefTitle", "NA")
        phase = design.get("phases", ["NA"])
        phase = ", ".join(phase)

        overall_status = status.get("overallStatus", "NA")

        last_update = status.get("lastUpdatePostDateStruct", {}).get("date", "NA")

        trials.append({
            "NCT_ID": nct_id,
            "Title": title,
            "Phase": phase,
            "Status": overall_status,
            "Last_Update": last_update
        })

    df = pd.DataFrame(trials)
    return df


def load_previous_data():
    if os.path.exists(DATA_FILE):
        return pd.read_csv(DATA_FILE)
    return pd.DataFrame()


def save_current_data(df):
    df.to_csv(DATA_FILE, index=False)


def detect_changes(current_df, previous_df):

    if previous_df.empty:
        return current_df, pd.DataFrame()

    merged = current_df.merge(
        previous_df,
        on="NCT_ID",
        how="left",
        suffixes=("", "_old")
    )

    # New trials
    new_trials = merged[merged["Title_old"].isna()].copy()

    # Updated trials
    updated_trials = merged[
        (~merged["Title_old"].isna()) &
        (
            (merged["Status"] != merged["Status_old"]) |
            (merged["Phase"] != merged["Phase_old"])
        )
    ].copy()

    # Detect status change
    updated_trials["Status_Change"] = updated_trials["Status_old"] + " → " + updated_trials["Status"]

    return new_trials, updated_trials


if st.button("Run Trial Check"):

    st.write("Fetching latest trials...")

    current_df = fetch_trials()
    previous_df = load_previous_data()

    new_trials, updated_trials = detect_changes(current_df, previous_df)

    st.subheader("New Trials")

    if new_trials.empty:
        st.write("No new trials found")
    else:
        st.dataframe(new_trials[[
            "NCT_ID",
            "Title",
            "Phase",
            "Status",
            "Last_Update"
        ]])

    st.subheader("Updated Trials")

    if updated_trials.empty:
        st.write("No updated trials found")
    else:
        st.dataframe(updated_trials[[
            "NCT_ID",
            "Title",
            "Phase",
            "Status_old",
            "Status",
            "Status_Change",
            "Last_Update"
        ]])

    save_current_data(current_df)

    st.success("Check completed at " + str(datetime.now()))
