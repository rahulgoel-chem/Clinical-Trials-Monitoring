import requests
import json
import os
import time
from datetime import datetime, timedelta

# ===============================
# CONFIG
# ===============================

SEARCH_TERMS = [
    "cancer",
    "diabetes",
    "alzheimer",
    "covid-19",
    "cardiovascular"
]

DAYS_BACK = 3
MAX_RESULTS = 50

SEEN_FILE = "seen_trials.json"

# ===============================
# HELPERS
# ===============================

def load_seen_trials():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_seen_trials(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)


def get_query_string():
    return " OR ".join(SEARCH_TERMS)


# ===============================
# CLINICALTRIALS.GOV API
# ===============================

def fetch_trials():
    url = "https://clinicaltrials.gov/api/v2/studies"

    params = {
        "query.term": get_query_string(),
        "pageSize": MAX_RESULTS,
        "filter.overallStatus": "RECRUITING,NOT_YET_RECRUITING",
        "sort": "LastUpdatePostDate:desc"
    }

    try:
        response = requests.get(url, params=params, timeout=30)

        if response.status_code != 200:
            print("API ERROR:", response.status_code)
            return []

        data = response.json()
        return data.get("studies", [])

    except Exception as e:
        print("Fetch error:", e)
        return []


# ===============================
# PARSE TRIAL DATA
# ===============================

def parse_trial(study):

    protocol = study.get("protocolSection", {})

    id_module = protocol.get("identificationModule", {})
    status_module = protocol.get("statusModule", {})
    design_module = protocol.get("designModule", {})
    contacts_module = protocol.get("contactsLocationsModule", {})

    nct_id = id_module.get("nctId")
    title = id_module.get("briefTitle")

    condition_list = protocol.get("conditionsModule", {}).get("conditions", [])

    status = status_module.get("overallStatus")

    last_update = status_module.get("lastUpdatePostDateStruct", {}).get("date")

    # Countries
    locations = contacts_module.get("locations", [])
    countries = list(set(
        loc.get("country") for loc in locations if loc.get("country")
    ))

    # Trial design
    design_info = design_module.get("studyType", "Unknown")

    phases = design_module.get("phases", [])

    return {
        "nct_id": nct_id,
        "title": title,
        "conditions": condition_list,
        "status": status,
        "last_update": last_update,
        "countries": countries,
        "design": design_info,
        "phases": phases,
        "url": f"https://clinicaltrials.gov/study/{nct_id}"
    }


# ===============================
# FILTER NEW TRIALS
# ===============================

def filter_new_trials(trials, seen_ids):

    new_trials = []

    for study in trials:

        trial = parse_trial(study)

        if not trial["nct_id"]:
            continue

        if trial["nct_id"] in seen_ids:
            continue

        new_trials.append(trial)

    return new_trials


# ===============================
# DISPLAY
# ===============================

def print_trials(trials):

    if not trials:
        print("No new trials found")
        return

    print("\n===== NEW CLINICAL TRIALS =====\n")

    for t in trials:

        print("TITLE:", t["title"])
        print("NCT ID:", t["nct_id"])
        print("STATUS:", t["status"])

        print("CONDITIONS:", ", ".join(t["conditions"]))

        print("COUNTRIES:", ", ".join(t["countries"]))

        print("DESIGN:", t["design"])

        if t["phases"]:
            print("PHASE:", ", ".join(t["phases"]))

        print("UPDATED:", t["last_update"])

        print("LINK:", t["url"])

        print("\n------------------------------\n")


# ===============================
# MAIN
# ===============================

def main():

    print("\nChecking ClinicalTrials.gov...")
    print("Time:", datetime.utcnow())

    seen = load_seen_trials()

    studies = fetch_trials()

    if not studies:
        print("No studies returned from API")
        return

    new_trials = filter_new_trials(studies, seen)

    print_trials(new_trials)

    for trial in new_trials:
        seen.add(trial["nct_id"])

    save_seen_trials(seen)

    print("Finished")


# ===============================
# RUN
# ===============================

if __name__ == "__main__":
    main()
