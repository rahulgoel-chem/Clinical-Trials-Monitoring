import streamlit as st
import psycopg2
import pandas as pd
from datetime import datetime

# -----------------------------
# Page configuration
# -----------------------------
st.set_page_config(
    page_title="Clinical Trial Monitoring",
    layout="wide"
)

# Fix text wrapping
st.markdown("""
<style>
.report-box {
    white-space: normal;
    word-wrap: break-word;
    overflow-wrap: break-word;
    font-family: Arial;
    font-size: 16px;
}
</style>
""", unsafe_allow_html=True)

# -----------------------------
# AACT DATABASE CONNECTION
# -----------------------------
AACT_HOST = "aact-db.ctti-clinicaltrials.org"
AACT_DB = "aact"
AACT_USER = "theranode"
AACT_PASS = "R@hul046"
AACT_PORT = 5432


def connect_db():
    conn = psycopg2.connect(
        host=AACT_HOST,
        database=AACT_DB,
        user=AACT_USER,
        password=AACT_PASS,
        port=AACT_PORT
    )
    return conn


# -----------------------------
# GET CURRENT TRIAL DATA
# -----------------------------
def get_trials(conn, condition):

    query = """
    SELECT
        s.nct_id,
        s.brief_title,
        sp.name AS sponsor,
        s.phase,
        s.overall_status,
        s.start_date,
        s.primary_completion_date,
        s.completion_date,
        s.enrollment
    FROM studies s
    LEFT JOIN sponsors sp
    ON s.nct_id = sp.nct_id
    WHERE LOWER(s.conditions) LIKE LOWER(%s)
    LIMIT 50
    """

    df = pd.read_sql(query, conn, params=[f"%{condition}%"])
    return df


# -----------------------------
# GET PREVIOUS VERSION
# -----------------------------
def get_previous_version(conn, nct_id):

    query = """
    SELECT
        overall_status,
        start_date,
        primary_completion_date,
        completion_date,
        enrollment
    FROM study_versions
    WHERE nct_id = %s
    ORDER BY version_number DESC
    LIMIT 1 OFFSET 1
    """

    df = pd.read_sql(query, conn, params=[nct_id])

    if df.empty:
        return None

    return df.iloc[0]


# -----------------------------
# GENERATE CHANGE REPORT
# -----------------------------
def generate_changes(current, previous):

    changes = []

    if previous is None:
        return changes

    if current["overall_status"] != previous["overall_status"]:
        changes.append(
            f"Status updated from {previous['overall_status']} to {current['overall_status']}"
        )

    if current["start_date"] != previous["start_date"]:
        changes.append(
            f"Study start date updated from {previous['start_date']} to {current['start_date']}"
        )

    if current["primary_completion_date"] != previous["primary_completion_date"]:
        changes.append(
            f"Primary Completion date updated from {previous['primary_completion_date']} to {current['primary_completion_date']}"
        )

    if current["completion_date"] != previous["completion_date"]:
        changes.append(
            f"Study Completion date updated from {previous['completion_date']} to {current['completion_date']}"
        )

    if current["enrollment"] != previous["enrollment"]:
        changes.append(
            f"Enrollment updated from {previous['enrollment']} to {current['enrollment']}"
        )

    return changes


# -----------------------------
# STREAMLIT UI
# -----------------------------
st.title("Clinical Trial Monitoring Dashboard")

condition = st.text_input(
    "Enter disease or condition",
    placeholder="Example: Lung Cancer"
)

run = st.button("Run Monitoring")

# -----------------------------
# MAIN LOGIC
# -----------------------------
if run:

    if condition == "":
        st.warning("Please enter a condition")
        st.stop()

    conn = connect_db()

    trials = get_trials(conn, condition)

    if trials.empty:
        st.warning("No trials found")
        st.stop()

    st.subheader("Trial Update Intelligence Report")

    for _, row in trials.iterrows():

        previous = get_previous_version(conn, row["nct_id"])

        current = {
            "overall_status": row["overall_status"],
            "start_date": row["start_date"],
            "primary_completion_date": row["primary_completion_date"],
            "completion_date": row["completion_date"],
            "enrollment": row["enrollment"]
        }

        changes = generate_changes(current, previous)

        if len(changes) == 0:
            continue

        title = f"""
        <div class="report-box">
        <b>[{row['nct_id']}] {row['sponsor']}'s {row['phase']} trial evaluating {row['brief_title']} has been updated.</b>
        <ul>
        """

        for c in changes:
            title += f"<li>{c}</li>"

        title += "</ul></div>"

        st.markdown(title, unsafe_allow_html=True)

    conn.close()
