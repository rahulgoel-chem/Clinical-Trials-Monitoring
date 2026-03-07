import streamlit as st
import requests
from datetime import datetime
import psycopg2
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from textwrap import wrap

# -------- CONFIG -------- #
# Ensure these are set in your .streamlit/secrets.toml
AACT_HOST = st.secrets["AACT_HOST"]
AACT_DB = st.secrets["AACT_DB"]
AACT_PORT = st.secrets["AACT_PORT"]
AACT_USER = st.secrets["AACT_USER"]
AACT_PASS = st.secrets["AACT_PASS"]

# -------- DATABASE CONNECTION -------- #
def connect_aact():
    return psycopg2.connect(
        host=AACT_HOST,
        database=AACT_DB,
        user=AACT_USER,
        password=AACT_PASS,
        port=AACT_PORT
    )

# -------- GET PREVIOUS DATA -------- #
def get_previous_trial_data(conn, nct_id):
    cur = conn.cursor()
    query = """
    SELECT overall_status, phase, enrollment
    FROM studies
    WHERE nct_id = %s
    """
    cur.execute(query, (nct_id,))
    row = cur.fetchone()
    cur.close()

    if row:
        return {
            "status": str(row[0]) if row[0] else "NA",
            "phase": str(row[1]) if row[1] else "NA",
            "enrollment": str(row[2]) if row[2] else "NA"
        }
    return None

def get_previous_countries(conn, nct_id):
    cur = conn.cursor()
    query = """
    SELECT DISTINCT country
    FROM facilities
    WHERE nct_id = %s
    """
    cur.execute(query, (nct_id,))
    rows = cur.fetchall()
    cur.close()
    return sorted([r[0] for r in rows if r[0]])

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
    c.line(50, y, width-50, y)
    y -= 20
    return y

# -------- PDF GENERATOR -------- #
def generate_pdf(condition, start_date, end_date, new_trials, updates):
    safe_condition = condition.replace(" ", "_").lower()
    file_name = f"clinical_trial_report_{safe_condition}.pdf"
    c = canvas.Canvas(file_name, pagesize=letter)
    width, height = letter
    y = height - 50

    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(width/2, y, "CLINICAL TRIAL INTELLIGENCE REPORT")
    
    y -= 30
    c.setFont("Helvetica", 11)
    c.drawString(50, y, f"Disease: {condition}")
    y -= 15
    c.drawString(50, y, f"Monitoring Window: {start_date} to {end_date}")
    y -= 15
    c.drawString(50, y, f"Generated on: {datetime.today().date()}")
    
    y -= 25
    c.line(40, y, width-40, y)
    y -= 25

    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, "SUMMARY")
    y -= 10
    c.line(50, y, width-50, y)
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

condition = st.text_input("Disease / Condition", placeholder="e.g. Lung Cancer")
col1, col2 = st.columns(2)
with col1:
    start_date = st.date_input("Start Date")
with col2:
    end_date = st.date_input("End Date")

run_button = st.button("Run Analysis")

if run_button:
    if not condition:
        st.error("Please enter a disease or condition.")
        st.stop()

    st.info("Fetching trials from ClinicalTrials.gov API v2...")

    base_url = "https://clinicaltrials.gov/api/v2/studies"
    
    # Precise fields needed for detection logic
    fields = [
        "protocolSection.identificationModule.nctId",
        "protocolSection.identificationModule.briefTitle",
        "protocolSection.statusModule.overallStatus",
        "protocolSection.statusModule.studyFirstPostDate",
        "protocolSection.statusModule.lastUpdatePostDate",
        "protocolSection.designModule.phases",
        "protocolSection.designModule.enrollmentInfo",
        "protocolSection.sponsorCollaboratorsModule.leadSponsor",
        "protocolSection.contactsLocationsModule.locations",
        "protocolSection.conditionsModule.conditions"
    ]

    params = {
        "query.cond": condition,
        "fields": ",".join(fields),
        "pageSize": 1000
    }

    try:
        response = requests.get(base_url, params=params)
        response.raise_for_status()
        studies = response.json().get("studies", [])
    except Exception as e:
        st.error(f"Failed to fetch data: {e}")
        st.stop()

    try:
        conn = connect_aact()
    except Exception as e:
        st.error(f"Database connection failed: {e}")
        st.stop()

    new_trials = []
    updates = []

    for study in studies:
        protocol = study.get("protocolSection", {})
        status_mod = protocol.get("statusModule", {})
        sponsor_mod = protocol.get("sponsorCollaboratorsModule", {})
        ident_mod = protocol.get("identificationModule", {})

        # Filter for Industry only
        sponsor_class = sponsor_mod.get("leadSponsor", {}).get("class", "")
        if sponsor_class.upper() != "INDUSTRY":
            continue

        nct_id = ident_mod.get("nctId")
        title = ident_mod.get("briefTitle", "No Title")
        sponsor = sponsor_mod.get("leadSponsor", {}).get("name", "NA")
        conditions = ", ".join(protocol.get("conditionsModule", {}).get("conditions", []))

        # -------- NEW TRIAL DETECTION -------- #
        # API v2 uses "studyFirstPostDate" as a direct string "YYYY-MM-DD"
        first_post_date_str = status_mod.get("studyFirstPostDate")
        
        if first_post_date_str:
            # Handle potential variation in date formats
            first_post_date = datetime.strptime(first_post_date_str[:10], "%Y-%m-%d").date()

            if start_date <= first_post_date <= end_date:
                new_trials.append(f"[{nct_id}] {sponsor} started NEW trial: {title}")
                # If it's new, we typically don't count it as an 'update' for this report
                continue

        # -------- UPDATE DETECTION -------- #
        upd_date_str = status_mod.get("lastUpdatePostDate")
        if not upd_date_str:
            continue

        upd_date = datetime.strptime(upd_date_str[:10], "%Y-%m-%d").date()

        if start_date <= upd_date <= end_date:
            prev = get_previous_trial_data(conn, nct_id)
            if not prev:
                continue

            current_status = status_mod.get("overallStatus", "NA")
            current_phase = ", ".join(protocol.get("designModule", {}).get("phases", [])) or "NA"
            current_enrollment = str(protocol.get("designModule", {}).get("enrollmentInfo", {}).get("count", "NA"))
            
            locations = protocol.get("contactsLocationsModule", {}).get("locations", [])
            current_countries = sorted(list(set([loc.get("country") for loc in locations if loc.get("country")])))

            prev_status = prev["status"]
            prev_phase = prev["phase"]
            prev_enrollment = prev["enrollment"]
            prev_countries = get_previous_countries(conn, nct_id)

            changes = []
            if current_status != prev_status:
                changes.append(f"Status: {prev_status} → {current_status}")
            if current_phase != prev_phase:
                changes.append(f"Phase: {prev_phase} → {current_phase}")
            if current_enrollment != prev_enrollment:
                changes.append(f"Enrollment: {prev_enrollment} → {current_enrollment}")
            
            added_countries = list(set(current_countries) - set(prev_countries))
            if added_countries:
                changes.append("New Countries: " + ", ".join(added_countries))

            if changes:
                updates.append(f"[{nct_id}] {sponsor} trial: " + "; ".join(changes))

    conn.close()

    if not new_trials and not updates:
        st.warning("No new trials or updates found for this criteria.")
    else:
        st.success(f"Analysis Complete! Found {len(new_trials)} new trials and {len(updates)} updates.")
        file_name = generate_pdf(condition, start_date, end_date, new_trials, updates)
        with open(file_name, "rb") as f:
            st.download_button("Download PDF Report", f, file_name=file_name)
