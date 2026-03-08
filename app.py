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
    SELECT overall_status, phase, enrollment, 
           start_date, primary_completion_date, completion_date
    FROM studies 
    WHERE nct_id = %s
    """
    cur.execute(query, (nct_id,))
    row = cur.fetchone()
    cur.close()
    
    if row:
        return {
            "status": str(row[0]) if row[0] else "NA",
            "enrollment": str(row[2]) if row[2] else "NA",
            "start_date": str(row[3]) if row[3] else "NA",
            "primary_completion": str(row[4]) if row[4] else "NA",
            "completion_date": str(row[5]) if row[5] else "NA"
        }
    return None

def get_previous_countries(conn, nct_id):
    cur = conn.cursor()
    
   
    query = """
    SELECT DISTINCT country
    FROM countries 
    WHERE nct_id = %s AND removed = false
    ORDER BY country
    """
    cur.execute(query, (nct_id,))
    rows = cur.fetchall()
    cur.close()
    return [r[0] for r in rows if r[0]]

# -------- PDF UTILITIES (UNCHANGED) -------- #
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

# -------- PDF GENERATOR (ENHANCED SUMMARY) -------- #
def generate_pdf(condition, start_date, end_date, new_trials, updates):
    safe_condition = condition.replace(" ", "_").lower()
    file_name = f"clinical_trial_report_{safe_condition}_{start_date}_{end_date}.pdf"
    
    c = canvas.Canvas(file_name, pagesize=letter)
    width, height = letter
    y = height - 50

    # Title & Header
    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(width / 2, y, "CLINICAL TRIAL INTELLIGENCE REPORT")
    y -= 30
    c.setFont("Helvetica", 11)
    c.drawString(50, y, f"Disease: {condition}")
    y -= 15
    c.drawString(50, y, f"Monitoring Window: {start_date} to {end_date}")
    y -= 15
    c.drawString(50, y, f"Generated: {datetime.today().date()}")
    y -= 25
    c.line(40, y, width - 40, y)
    y -= 25

    # Summary
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, "SUMMARY")
    y -= 10
    c.line(50, y, width - 50, y)
    y -= 20
    c.setFont("Helvetica", 11)
    c.drawString(60, y, f"New Trials: {len(new_trials)}")
    y -= 15
    c.drawString(60, y, f"Updates: {len(updates)}")
    y -= 30

    # New Trials Section
    y = draw_section_title(c, "NEW INDUSTRY TRIALS", y, width)
    c.setFont("Helvetica", 10)
    if not new_trials:
        y = draw_wrapped_text(c, "No new industry trials detected.", 60, y)
    else:
        for trial in new_trials:
            y = draw_wrapped_text(c, f"• {trial}", 60, y)
            y -= 5
    y -= 20

    # Updates Section
    y = draw_section_title(c, "TRIAL UPDATES", y, width)
    c.setFont("Helvetica", 10)
    if not updates:
        y = draw_wrapped_text(c, "No trial updates detected.", 60, y)
    else:
        for upd in updates:
            y = draw_wrapped_text(c, f"• {upd}", 60, y)
            y -= 5

    add_footer(c)
    c.save()
    return file_name

# -------- STREAMLIT UI & LOGIC (IMPROVED CHANGE DETECTION) -------- #
st.title("🔬 Clinical Trial Intelligence Monitor")

condition = st.text_input("Disease / Condition", value="lung cancer")
col1, col2 = st.columns(2)
start_date = col1.date_input("Start Date", value=datetime.now().date() - timedelta(days=30))
end_date = col2.date_input("End Date", value=datetime.now().date())

run_button = st.button("🚀 Run Analysis", type="primary")

if run_button:
    with st.spinner("Fetching ClinicalTrials.gov data..."):
        start_date_str = start_date.strftime("%Y-%m-%d")
        end_date_str = end_date.strftime("%Y-%m-%d")

        # Fetch studies (unchanged pagination)
        base_url = "https://clinicaltrials.gov/api/v2/studies"
        fields = [
            "protocolSection.identificationModule",
            "protocolSection.statusModule",
            "protocolSection.designModule",
            "protocolSection.sponsorCollaboratorsModule",
            "protocolSection.contactsLocationsModule",
            "protocolSection.conditionsModule"
        ]
        params = {"query.cond": condition, "fields": ",".join(fields), "pageSize": 1000}
        
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

    st.success(f"📊 Found {len(studies)} total studies. Analyzing changes...")

    # ✅ MAIN IMPROVEMENT: Connect AACT & detect ALL changes
    conn = connect_aact()
    new_trials = []
    updates = []
    seen_nct_ids = set()

    for study in studies:
        protocol = study.get("protocolSection", {})
        status_mod = protocol.get("statusModule", {})
        sponsor_mod = protocol.get("sponsorCollaboratorsModule", {})
        design_mod = protocol.get("designModule", {})
        ident = protocol.get("identificationModule", {})

        nct_id = ident.get("nctId")
        if not nct_id or nct_id in seen_nct_ids:
            continue
        seen_nct_ids.add(nct_id)

        upd_date_str = status_mod.get("lastUpdatePostDateStruct", {}).get("date")
        if not upd_date_str:
            continue
        upd_date = datetime.strptime(upd_date_str, "%Y-%m-%d").date()
        if not (start_date <= upd_date <= end_date):
            continue

        # Industry only
        sponsor_class = sponsor_mod.get("leadSponsor", {}).get("class", "").upper()
        if sponsor_class != "INDUSTRY":
            continue

        sponsor = sponsor_mod.get("leadSponsor", {}).get("name", "Unknown")
        title = ident.get("briefTitle", "")[:100]
        conditions = ", ".join(protocol.get("conditionsModule", {}).get("conditions", [])[:3])

        # NEW TRIAL: First post in window (unchanged, works well)
        first_post_str = status_mod.get("studyFirstPostDateStruct", {}).get("date")
        if first_post_str:
            first_post_date = datetime.strptime(first_post_str, "%Y-%m-%d").date()
            if start_date <= first_post_date <= end_date:
                phase_str = ", ".join(design_mod.get("phases", [])) or "NA"
                start_date_study = status_mod.get("startDateStruct", {}).get("date", "NA")
                prim_comp = status_mod.get("primaryCompletionDateStruct", {}).get("date", "NA")
                comp_date = status_mod.get("completionDateStruct", {}).get("date", "NA")
                enrollment = status_mod.get("enrollmentInfo", {}).get("count", "NA")
                
                locations = protocol.get("contactsLocationsModule", {}).get("locations", [])
                countries = sorted(set(loc.get("country") for loc in locations if loc.get("country")))
                countries_text = ", ".join(countries) or "NA"
                
                new_trials.append(
                    f"{nct_id} | {sponsor} | {title} | Phase: {phase_str} | "
                    f"Start: {start_date_study} | Prim Comp: {prim_comp} | "
                    f"Comp: {comp_date} | Enroll: {enrollment} | Countries: {countries_text}"
                )
                continue  # Skip updates for new trials

        # UPDATE DETECTION: Compare ALL fields with AACT historical data [web:30]
        prev_data = get_previous_trial_data(conn, nct_id)
        if not prev_data:
            continue  # No previous record

        prev_countries = get_previous_countries(conn, nct_id)

        # ✅ CURRENT VALUES (normalized)
        curr_status = status_mod.get("overallStatus", "NA")
        curr_phase = ", ".join(design_mod.get("phases", [])) or "NA"
        curr_enroll = str(status_mod.get("enrollmentInfo", {}).get("count", "NA"))
        curr_start = status_mod.get("startDateStruct", {}).get("date", "NA")
        curr_prim_comp = status_mod.get("primaryCompletionDateStruct", {}).get("date", "NA")
        curr_comp = status_mod.get("completionDateStruct", {}).get("date", "NA")

        curr_locations = protocol.get("contactsLocationsModule", {}).get("locations", [])
        curr_countries_list = sorted(set(loc.get("country") for loc in curr_locations if loc.get("country")))
        curr_countries_str = ", ".join(curr_countries_list)

        changes = []
        if curr_status != prev_data["status"]:
            changes.append(f"Status: {prev_data['status']} → {curr_status}")
        if curr_phase != prev_data["phase"]:
            changes.append(f"Phase: {prev_data['phase']} → {curr_phase}")
        if curr_enroll != prev_data["enrollment"]:
            changes.append(f"Enrollment: {prev_data['enrollment']} → {curr_enroll}")
        if curr_start != prev_data["start_date"]:
            changes.append(f"Start Date: {prev_data['start_date']} → {curr_start}")
        if curr_prim_comp != prev_data["primary_completion"]:
            changes.append(f"Primary Completion: {prev_data['primary_completion']} → {curr_prim_comp}")
        if curr_comp != prev_data["completion_date"]:
            changes.append(f"Completion Date: {prev_data['completion_date']} → {curr_comp}")

        # Countries changes
        added_countries = set(curr_countries_list) - set(prev_countries)
        removed_countries = set(prev_countries) - set(curr_countries_list)
        if added_countries:
            changes.append(f"Added Countries: {', '.join(sorted(added_countries))}")
        if removed_countries:
            changes.append(f"Removed Countries: {', '.join(sorted(removed_countries))}")
        elif curr_countries_str != ", ".join(prev_countries):
            changes.append(f"Countries Updated: {', '.join(prev_countries)} → {curr_countries_str}")

        if changes:
            updates.append(f"{nct_id} | {sponsor} ({conditions}): {' | '.join(changes)}")

    conn.close()

    # Results
    st.success(f"✅ New Trials: {len(new_trials)} | Updates: {len(updates)}")
    
    if new_trials:
        st.subheader("New Trials")
        for trial in new_trials[:10]:  # Preview top 10
            st.write(trial)
    
    if updates:
        st.subheader("Updates")
        for upd in updates[:10]:
            st.write(f"🔄 {upd}")

    # Generate & download PDF
    pdf_file = generate_pdf(condition, start_date_str, end_date_str, new_trials, updates)
    with open(pdf_file, "rb") as f:
        st.download_button(
            label="📥 Download Full PDF Report",
            data=f,
            file_name=pdf_file,
            mime="application/pdf"
        )
