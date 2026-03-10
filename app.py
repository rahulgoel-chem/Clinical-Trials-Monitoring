import streamlit as st
import requests
from datetime import datetime
import psycopg2
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from textwrap import wrap

# -------- CONFIG (Using Streamlit Secrets) -------- #
AACT_HOST = st.secrets["AACT_HOST"]
AACT_DB = st.secrets["AACT_DB"]
AACT_PORT = st.secrets["AACT_PORT"]
AACT_USER = st.secrets["AACT_USER"]
AACT_PASS = st.secrets["AACT_PASS"]

# -------- HELPER FUNCTIONS -------- #

def connect_aact():
    return psycopg2.connect(
        host=AACT_HOST,
        database=AACT_DB,
        user=AACT_USER,
        password=AACT_PASS,
        port=AACT_PORT
    )

def get_previous_trial_data(conn, nct_id):
    cur = conn.cursor()
    query = """
    SELECT overall_status, phase, enrollment, start_date, 
           primary_completion_date, completion_date
    FROM studies WHERE nct_id = %s
    """
    cur.execute(query, (nct_id,))
    row = cur.fetchone()
    cur.close()

    if row:
        return {
            "status": str(row[0]) if row[0] else "NA",
            "phase": str(row[1]) if row[1] else "NA",
            "enrollment": str(row[2]) if row[2] else "NA",
            "start_date": str(row[3]) if row[3] else "NA",
            "primary_completion": str(row[4]) if row[4] else "NA",
            "completion": str(row[5]) if row[5] else "NA"
        }
    return None

def get_previous_countries(conn, nct_id):
    cur = conn.cursor()
    query = "SELECT DISTINCT country FROM facilities WHERE nct_id = %s"
    cur.execute(query, (nct_id,))
    rows = cur.fetchall()
    cur.close()
    return sorted([r[0] for r in rows if r[0]])

# -------- PDF UTILITIES -------- #
LEFT, RIGHT, TOP, BOTTOM = 60, 550, 750, 60

def add_footer(c):
    c.setFont("Helvetica", 9)
    page = c.getPageNumber()
    c.drawCentredString(300, 30, f"Clinical Trial Intelligence Report | Page {page}")

def draw_wrapped_text(c, text, x, y, width=95, line_height=14):
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

def generate_pdf(condition, start_date, end_date, new_trials, updates):
    safe_condition = condition.replace(" ", "_").lower()
    file_name = f"trial_report_{safe_condition}_{datetime.now().strftime('%Y%m%d')}.pdf"
    c = canvas.Canvas(file_name, pagesize=letter)
    width, height = letter
    y = height - 50

    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(width / 2, y, "CLINICAL TRIAL INTELLIGENCE REPORT")
    y -= 40
    c.setFont("Helvetica", 11)
    c.drawString(50, y, f"Disease: {condition} | Window: {start_date} to {end_date}")
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
    y = draw_section_title(c, "TRIAL UPDATES DETECTED", y, width)
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
st.set_page_config(page_title="Trial Monitor", layout="wide")
st.title("Clinical Trial Intelligence Monitor")

col1, col2, col3 = st.columns(3)
with col1:
    condition = st.text_input("Disease / Condition", value="Oncology")
with col2:
    start_date = st.date_input("Start Date")
with col3:
    end_date = st.date_input("End Date")

if st.button("Run Analysis"):
    st.info("Fetching data from ClinicalTrials.gov and AACT...")
    
    # 1. FETCH FROM API
    base_url = "https://clinicaltrials.gov/api/v2/studies"
    fields = ["protocolSection.identificationModule", "protocolSection.statusModule", 
              "protocolSection.designModule", "protocolSection.sponsorCollaboratorsModule", 
              "protocolSection.contactsLocationsModule", "protocolSection.conditionsModule"]
    
    params = {"query.cond": condition, "fields": ",".join(fields), "pageSize": 1000}
    studies, next_token = [], None

    while True:
        if next_token: params["pageToken"] = next_token
        response = requests.get(base_url, params=params)
        data = response.json()
        studies.extend(data.get("studies", []))
        next_token = data.get("nextPageToken")
        if not next_token: break

    conn = connect_aact()
    new_trials, updates, seen_trials = [], [], set()

    for study in studies:
        # --- DATA EXTRACTION ---
        proto = study.get("protocolSection", {})
        ident = proto.get("identificationModule", {})
        stat = proto.get("statusModule", {})
        dsgn = proto.get("designModule", {})
        spon = proto.get("sponsorCollaboratorsModule", {})
        
        nct_id = ident.get("nctId")
        lead_sponsor = spon.get("leadSponsor", {})
        if lead_sponsor.get("class", "").upper() != "INDUSTRY": continue

        title = ident.get("briefTitle", "No Title")
        sponsor_name = lead_sponsor.get("name", "NA")
        conds = ", ".join(proto.get("conditionsModule", {}).get("conditions", []))
        
        # Current API Values
        curr_status = stat.get("overallStatus", "NA")
        curr_phase = ", ".join(dsgn.get("phases", [])) or "NA"
        curr_enroll = str(dsgn.get("enrollmentInfo", {}).get("count", "NA"))
        curr_start = stat.get("startDateStruct", {}).get("date", "NA")
        curr_prim = stat.get("primaryCompletionDateStruct", {}).get("date", "NA")
        curr_comp = stat.get("completionDateStruct", {}).get("date", "NA")
        
        locs = proto.get("contactsLocationsModule", {}).get("locations", [])
        curr_countries = sorted(list(set([l.get("country") for l in locs if l.get("country")])))

        # --- NEW TRIAL DETECTION ---
        first_post = stat.get("studyFirstPostDateStruct", {}).get("date")
        if first_post:
            fp_date = datetime.strptime(first_post, "%Y-%m-%d").date()
            if start_date <= fp_date <= end_date:
                report = f"[{nct_id}] {sponsor_name}: {title} | Status: {curr_status} | Phase: {curr_phase} | Countries: {', '.join(curr_countries)}"
                if nct_id not in seen_trials:
                    new_trials.append(report)
                    seen_trials.add(nct_id)

        # --- UPDATE DETECTION ---
        prev = get_previous_trial_data(conn, nct_id)
        if prev:
            changes = []
            
            # Helper to normalize comparison (strips time/spaces)
            def clean(val): return str(val).split(' ')[0].strip().upper()

            if clean(curr_status) != clean(prev["status"]):
                changes.append(f"Status: {prev['status']} → {curr_status}")
            
            if clean(curr_enroll) != clean(prev["enrollment"]):
                changes.append(f"Enrollment: {prev['enrollment']} → {curr_enroll}")

            if clean(curr_start) != clean(prev["start_date"]):
                changes.append(f"Start: {prev['start_date']} → {curr_start}")

            if clean(curr_prim) != clean(prev["primary_completion"]):
                changes.append(f"Primary Comp: {prev['primary_completion']} → {curr_prim}")

            # Country Changes
            prev_countries = get_previous_countries(conn, nct_id)
            added = sorted(list(set(curr_countries) - set(prev_countries)))
            removed = sorted(list(set(prev_countries) - set(curr_countries)))
            
            if added: changes.append(f"Added Countries: {', '.join(added)}")
            if removed: changes.append(f"Removed Countries: {', '.join(removed)}")

            if changes:
                updates.append(f"[{nct_id}] {sponsor_name} ({conds}): " + " | ".join(changes))

    conn.close()

    # --- UI RESULTS ---
    st.success(f"Analysis Complete! Found {len(new_trials)} new trials and {len(updates)} updates.")
    
    pdf_path = generate_pdf(condition, start_date, end_date, new_trials, updates)
    with open(pdf_path, "rb") as f:
        st.download_button("Download Full Intelligence Report (PDF)", f, file_name=pdf_path)
