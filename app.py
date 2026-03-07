for study in studies:

    protocol = study.get("protocolSection", {})
    status = protocol.get("statusModule", {})
    sponsor_mod = protocol.get("sponsorCollaboratorsModule", {})

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

    prev = get_previous_trial_data(conn, nct_id)

    # -------- NEW TRIAL -------- #

    if not prev:
        new_trials.append(
            f"[{nct_id}] {sponsor} started NEW trial: {title}"
        )
        continue


    # -------- CURRENT VALUES FROM API -------- #

    current_status = status.get("overallStatus", "NA")

    current_phase = ", ".join(
        protocol.get("designModule", {}).get("phases", [])
    ) or "NA"

    current_enrollment = str(
        status.get("enrollmentStruct", {}).get("count", "NA")
    )

    locations = protocol.get("contactsLocationsModule", {}).get("locations", [])

    current_countries = sorted(list(set([
        loc.get("country") for loc in locations if loc.get("country")
    ])))


    # -------- PREVIOUS VALUES -------- #

    prev_status = prev["status"]
    prev_phase = prev["phase"]
    prev_enrollment = prev["enrollment"]

    prev_countries = get_previous_countries(conn, nct_id)


    # -------- CHANGE DETECTION -------- #

    changes = []

    if current_status != prev_status:
        changes.append(f"Status: {prev_status} → {current_status}")

    if current_phase != prev_phase:
        changes.append(f"Phase: {prev_phase} → {current_phase}")

    if current_enrollment != prev_enrollment:
        changes.append(f"Enrollment: {prev_enrollment} → {current_enrollment}")

    added_countries = list(set(current_countries) - set(prev_countries))

    if added_countries:
        changes.append(
            "New Countries Added: " + ", ".join(added_countries)
        )


    # -------- REPORT UPDATE -------- #

    if changes:
        updates.append(
            f"[{nct_id}] {sponsor} trial in {conditions}: "
            + "; ".join(changes)
        )
