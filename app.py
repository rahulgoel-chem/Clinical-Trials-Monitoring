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


 (cd "$(git rev-parse --show-toplevel)" && git apply --3way <<'EOF' 
diff --git a/app.py b/app.py
index 9352f045b7258103043cb010feb75b6aac07e2a6..33ce755018e5e2f550f0d3fce18603490cc8ce24 100644
--- a/app.py
+++ b/app.py
@@ -48,50 +48,72 @@ def get_previous_trial_data(conn, nct_id):
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
 
 
+def build_trial_snapshot(nct_id, title, sponsor, conditions, status, phase, enrollment,
+                         study_start, primary_completion, study_completion,
+                         last_update, countries):
+
+    countries_text = ", ".join(countries) if countries else "NA"
+
+    return (
+        f"NCT ID: {nct_id} | "
+        f"Title: {title or 'NA'} | "
+        f"Sponsor: {sponsor or 'NA'} | "
+        f"Conditions: {conditions or 'NA'} | "
+        f"Status: {status or 'NA'} | "
+        f"Phase: {phase or 'NA'} | "
+        f"Enrollment: {enrollment or 'NA'} | "
+        f"Start: {study_start or 'NA'} | "
+        f"Primary Completion: {primary_completion or 'NA'} | "
+        f"Study Completion: {study_completion or 'NA'} | "
+        f"Last Update: {last_update or 'NA'} | "
+        f"Countries: {countries_text}"
+    )
+
+
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
@@ -266,147 +288,182 @@ if run_button:
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
 
+        current_status = status.get("overallStatus", "NA")
+
         # -------- NEW TRIAL DETECTION -------- #
 
         first_post_str = status.get("studyFirstPostDateStruct", {}).get("date")
 
         if first_post_str:
 
             first_post_date = datetime.strptime(first_post_str, "%Y-%m-%d").date()
 
             if start_date <= first_post_date <= end_date:
 
                 phase = ", ".join(design.get("phases", [])) or "NA"
 
                 study_start = status.get("startDateStruct", {}).get("date", "NA")
 
                 primary_completion = status.get(
                     "primaryCompletionDateStruct", {}
                 ).get("date", "NA")
 
                 study_completion = status.get(
                     "completionDateStruct", {}
                 ).get("date", "NA")
 

+                enrollment = str(
+                    design.get("enrollmentInfo", {}).get("count", "NA")
+                )
+
+                last_update = status.get(
+                    "lastUpdatePostDateStruct", {}
+                ).get("date", "NA")
 
                 locations = protocol.get(
                     "contactsLocationsModule", {}
                 ).get("locations", [])
 
                 countries = sorted(list(set([
                     loc.get("country") for loc in locations if loc.get("country")
                 ])))
 
+                trial_report = build_trial_snapshot(
+                    nct_id=nct_id,
+                    title=title,
+                    sponsor=sponsor,
+                    conditions=conditions,
+                    status=current_status,
+                    phase=phase,
+                    enrollment=enrollment,
+                    study_start=study_start,
+                    primary_completion=primary_completion,
+                    study_completion=study_completion,
+                    last_update=last_update,
+                    countries=countries
                 )
 
                 if nct_id not in seen_trials:
                     new_trials.append(trial_report)
                     seen_trials.add(nct_id)
 
         # -------- UPDATE DETECTION -------- #

         current_phase = ", ".join(
             design.get("phases", [])
         ) or "NA"
 
         current_enrollment = str(
             design.get("enrollmentInfo", {}).get("count", "NA")
         )
 
         locations = protocol.get("contactsLocationsModule", {}).get("locations", [])
 
         current_countries = sorted(list(set([
             loc.get("country") for loc in locations if loc.get("country")
         ])))
 
         prev = get_previous_trial_data(conn, nct_id)
 
         if not prev:
             continue
 
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
             changes.append("New Countries Added: " + ", ".join(added_countries))
 
         if changes:
 
+            last_update = status.get(
+                "lastUpdatePostDateStruct", {}
+            ).get("date", "NA")
+
+            study_start = status.get("startDateStruct", {}).get("date", "NA")
+
+            primary_completion = status.get(
+                "primaryCompletionDateStruct", {}
+            ).get("date", "NA")
+
+            study_completion = status.get(
+                "completionDateStruct", {}
+            ).get("date", "NA")
+
             updates.append(

+                build_trial_snapshot(
+                    nct_id=nct_id,
+                    title=title,
+                    sponsor=sponsor,
+                    conditions=conditions,
+                    status=current_status,
+                    phase=current_phase,
+                    enrollment=current_enrollment,
+                    study_start=study_start,
+                    primary_completion=primary_completion,
+                    study_completion=study_completion,
+                    last_update=last_update,
+                    countries=current_countries
+                )
+                + " | Changes: "
                 + "; ".join(changes)
             )
 
     conn.close()
 
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
 
EOF
)
