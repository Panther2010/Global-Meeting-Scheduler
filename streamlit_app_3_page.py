import streamlit as st
import pandas as pd
import streamlit.components.v1 as components
from datetime import datetime, timedelta
import pytz
import time
import pycountry
import geonamescache

from schedule_v4 import (
    geolocator,
    tf,
    generate_candidate_times,
    calculate_scores,
    best_slot,
    is_client_available
)

from database import (
    get_all_clients,
    save_client,
    delete_client,
    clear_database
)

st.set_page_config(page_title="Meeting Scheduler", layout="centered")

# ── Timezone detection ────────────────────────────────────────────────────────
def detect_timezone(location_text):
    try:
        loc = geolocator.geocode(location_text)
        if not loc:
            return None, "Location not found"
        timezone = tf.timezone_at(lat=loc.latitude, lng=loc.longitude)
        if not timezone:
            return None, "Timezone not found"
        return timezone, None
    except Exception as e:
        return None, str(e)


DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# ── Country list for the searchable dropdown ────────────────────────────────
COUNTRY_NAMES = sorted(c.name for c in pycountry.countries)
_COUNTRY_CODE_BY_NAME = {c.name: c.alpha_2 for c in pycountry.countries}
_GC = geonamescache.GeonamesCache()


@st.cache_data
def get_cities_for_country(country_name):
    """Returns a sorted, deduped list of known city names for a country.
    Backed by geonamescache (offline, no API calls) - covers the major
    cities per country, not every small town."""
    code = _COUNTRY_CODE_BY_NAME.get(country_name)
    if not code:
        return []
    all_cities = _GC.get_cities()
    names = sorted({c["name"] for c in all_cities.values() if c["countrycode"] == code})
    return names


# ── 12hr <-> 24hr conversion (storage/geocoding stays 24hr internally) ──────
def to_24hr(hour_12, am_pm):
    hour_12 = int(hour_12)
    if am_pm == "AM":
        return 0 if hour_12 == 12 else hour_12
    else:
        return 12 if hour_12 == 12 else hour_12 + 12


def to_12hr(hour_24):
    am_pm = "AM" if hour_24 < 12 else "PM"
    hour_12 = hour_24 % 12
    if hour_12 == 0:
        hour_12 = 12
    return hour_12, am_pm


# ── Round a datetime to the nearest 30 minutes, for a friendlier suggestion ──
def round_to_nearest_half_hour(dt):
    discard = timedelta(
        minutes=dt.minute % 30,
        seconds=dt.second,
        microseconds=dt.microsecond,
    )
    rounded = dt - discard
    if discard >= timedelta(minutes=15):
        rounded += timedelta(minutes=30)
    return rounded


# ── Excel bulk-import helpers ──────────────────────────────────────────────────
def parse_hours_cell(cell_value):
    """
    Parses a single day's cell from the uploaded sheet.
    Accepts formats like '9-17', '9 - 17', '09-17'.
    Blank / NaN / not a string -> not working that day (None).
    Returns (start, end) tuple or None. Raises ValueError on a malformed
    (non-blank) cell so the caller can report it instead of silently skipping.
    """
    if cell_value is None:
        return None
    if isinstance(cell_value, float) and pd.isna(cell_value):
        return None
    text = str(cell_value).strip()
    if not text:
        return None

    parts = text.replace(" ", "").split("-")
    if len(parts) != 2:
        raise ValueError(f"expected 'start-end' format, got '{text}'")

    try:
        start, end = int(parts[0]), int(parts[1])
    except ValueError:
        raise ValueError(f"hours must be whole numbers, got '{text}'")

    if not (0 <= start <= 23 and 0 <= end <= 23):
        raise ValueError(f"hours must be between 0-23, got '{text}'")
    if start == end:
        raise ValueError(f"start and end hour cannot be the same ('{text}')")

    return [start, end]


def parse_clients_excel(uploaded_file):
    """
    Reads the uploaded workbook and returns (parsed_rows, row_errors).
    parsed_rows: list of dicts {name, location, hours}
    row_errors: list of human-readable strings describing skipped rows
    """
    df = pd.read_excel(uploaded_file)
    df.columns = [str(c).strip() for c in df.columns]

    required = {"Name", "Location"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required column(s): {', '.join(sorted(missing))}")

    day_cols = [d for d in DAYS if d in df.columns]

    parsed_rows = []
    row_errors = []

    for i, row in df.iterrows():
        excel_row_num = i + 2  # +2: 1-indexed and header row
        name = str(row.get("Name", "")).strip()
        location = str(row.get("Location", "")).strip()

        if not name or name.lower() == "nan" or not location or location.lower() == "nan":
            row_errors.append(f"Row {excel_row_num}: missing Name or Location — skipped.")
            continue

        hours = {}
        row_ok = True
        for day in DAYS:
            if day not in day_cols:
                hours[day] = None
                continue
            try:
                hours[day] = parse_hours_cell(row.get(day))
            except ValueError as e:
                row_errors.append(f"Row {excel_row_num} ({name}), {day}: {e} — client skipped.")
                row_ok = False
                break

        if row_ok:
            parsed_rows.append({"name": name, "location": location, "hours": hours})

    return parsed_rows, row_errors


# ── Session state & Database Initialization ───────────────────────────────────
def init_state():
    if "clients" not in st.session_state:
        try:
            db = get_all_clients()
        except Exception as e:
            st.error(f"Could not load clients from database: {e}")
            db = {}

        loaded_clients = []
        for name, data in db.items():
            loaded_clients.append({
                "name": name,
                "location": data["location"],
                "timezone": data["timezone"],
                "hours": data.get("hours", {})
            })
        st.session_state.clients = loaded_clients

init_state()


# ── Sidebar navigation ────────────────────────────────────────────────────────
st.sidebar.title("Meeting Scheduler")
page = st.sidebar.radio(
    "Go to",
    ["Manage Clients", "View & Search Clients", "Find Meeting Time"],
    key="nav_page",
)


# ════════════════════════════════════════════════════════════════════════════
# PAGE 1 — MANAGE CLIENTS (add / update / bulk import / delete / clear)
# ════════════════════════════════════════════════════════════════════════════
if page == "Manage Clients":
    st.title("Manage Clients")

    # ── Add / Update Client Form ──────────────────────────────────────────
    st.subheader("Add or Update Client")
    st.caption("To update an existing client, enter their exact name below with the new details.")

    loc_col1, loc_col2 = st.columns([1, 1])
    with loc_col1:
        country = st.selectbox(
            "Country",
            options=COUNTRY_NAMES,
            index=None,
            placeholder="Type to search…",
            key="form_country",
        )

    city_options = get_cities_for_country(country) if country else []
    city_select_options = ["Other (type manually)"] + city_options

    with loc_col2:
        city_choice = st.selectbox(
            "City",
            options=city_select_options if country else [],
            index=None,
            placeholder="Select a country first" if not country else "Type to search…",
            disabled=(country is None),
            key="form_city_select",
        )

    if city_choice == "Other (type manually)":
        city = st.text_input("City not listed — type it here", key="form_city_manual")
    elif city_choice:
        city = city_choice
    else:
        city = ""

    location = f"{city}, {country}" if city and country else ""

    with st.form("add_client", clear_on_submit=True):
        name = st.text_input("Name", key="form_name")

        st.write("---")
        schedule_inputs = {}

        with st.expander("**Weekly Schedule** (click to set working hours)", expanded=False):
            hcol1, hcol2, hcol3 = st.columns([1, 1, 1])
            hcol1.markdown("**Day (Working?)**")
            hcol2.markdown("**Start Time**")
            hcol3.markdown("**End Time**")

            for day in DAYS:
                col1, col2, col3 = st.columns([1, 1, 1])
                with col1:
                    default_working = day not in ["Sat", "Sun"]
                    is_working = st.checkbox(f"**{day}**", value=default_working, key=f"work_{day}")
                with col2:
                    s_h1, s_h2 = st.columns([1, 1])
                    with s_h1:
                        start_hour_12 = st.number_input("Start Hour", min_value=1, max_value=12, value=8, key=f"start_h_{day}", label_visibility="collapsed")
                    with s_h2:
                        start_ampm = st.selectbox("AM/PM", options=["AM", "PM"], index=0, key=f"start_ampm_{day}", label_visibility="collapsed")
                with col3:
                    e_h1, e_h2 = st.columns([1, 1])
                    with e_h1:
                        end_hour_12 = st.number_input("End Hour", min_value=1, max_value=12, value=10, key=f"end_h_{day}", label_visibility="collapsed")
                    with e_h2:
                        end_ampm = st.selectbox("AM/PM", options=["AM", "PM"], index=1, key=f"end_ampm_{day}", label_visibility="collapsed")

                start_h = to_24hr(start_hour_12, start_ampm)
                end_h = to_24hr(end_hour_12, end_ampm)

                schedule_inputs[day] = {"working": is_working, "start": start_h, "end": end_h}

        submitted = st.form_submit_button("Save Client")

        if submitted:
            valid_hours = True
            for day, vals in schedule_inputs.items():
                if vals["working"] and vals["start"] == vals["end"]:
                    st.error(f"On {day}, Start and End hours cannot be the same.")
                    valid_hours = False
                    break

            if not name or not city or not country:
                st.error("Provide name, city, and country.")
            elif valid_hours:
                tz, err = detect_timezone(location)
                if err:
                    st.error(f"{err} — check the location and try again.")
                else:
                    formatted_hours = {}
                    for day, vals in schedule_inputs.items():
                        if vals["working"]:
                            formatted_hours[day] = [vals["start"], vals["end"]]
                        else:
                            formatted_hours[day] = None

                    existing_idx = next((i for i, c in enumerate(st.session_state.clients) if c["name"] == name), None)

                    client_dict = {
                        "name": name,
                        "location": location,
                        "timezone": tz,
                        "hours": formatted_hours
                    }

                    try:
                        save_client(name, location, tz, formatted_hours)
                    except Exception as e:
                        st.error(f"Could not save client to database: {e}")
                    else:
                        if existing_idx is not None:
                            st.session_state.clients[existing_idx] = client_dict
                            st.success(f"Updated {name} — {tz}")
                        else:
                            st.session_state.clients.append(client_dict)
                            st.success(f"Added {name} — {tz}")

                        components.html(
                            f"""
                            <script>
                                setTimeout(function() {{
                                    const inputs = window.parent.document.querySelectorAll('input');
                                    if (inputs.length > 0) {{
                                        inputs[0].focus();
                                    }}
                                }}, 50);
                            </script>
                            """,
                            height=0,
                            width=0,
                        )

    # ── Bulk Import from Excel ────────────────────────────────────────────
    with st.expander("Bulk Import Clients from Excel"):
        st.caption(
            "Columns required: **Name**, **Location**. Optional day columns "
            "**Mon, Tue, Wed, Thu, Fri, Sat, Sun** — each cell in `start-end` 24hr "
            "format (e.g. `9-17`, `8-22`). Leave a day cell blank if the client "
            "doesn't work that day. Existing clients (matched by exact name) will "
            "be updated; new names will be added."
        )

        uploaded_excel = st.file_uploader(
            "Upload Excel file (.xlsx)", type=["xlsx", "xls"], key="bulk_upload"
        )

        if uploaded_excel is not None:
            try:
                parsed_rows, row_errors = parse_clients_excel(uploaded_excel)
            except ValueError as e:
                st.error(f"Could not read file: {e}")
                parsed_rows, row_errors = [], []

            if parsed_rows:
                st.write(f"**{len(parsed_rows)} client(s) ready to import:**")
                st.dataframe(
                    pd.DataFrame([{"Name": r["name"], "Location": r["location"]} for r in parsed_rows]),
                    hide_index=True,
                )

            if row_errors:
                with st.expander(f"⚠️ {len(row_errors)} row(s) with issues (skipped)"):
                    for msg in row_errors:
                        st.write(f"- {msg}")

            if parsed_rows and st.button("Process Import", key="process_bulk_import", type="primary"):
                imported, updated, tz_failed, save_failed = [], [], [], []

                with st.spinner(f"Detecting timezones for {len(parsed_rows)} client(s)…"):
                    for r in parsed_rows:
                        tz, err = detect_timezone(r["location"])
                        if err:
                            tz_failed.append(f"{r['name']} ({r['location']}): {err}")
                            continue

                        try:
                            save_client(r["name"], r["location"], tz, r["hours"])
                        except Exception as e:
                            save_failed.append(f"{r['name']}: {e}")
                            continue

                        client_dict = {
                            "name": r["name"],
                            "location": r["location"],
                            "timezone": tz,
                            "hours": r["hours"],
                        }

                        existing_idx = next(
                            (i for i, c in enumerate(st.session_state.clients) if c["name"] == r["name"]),
                            None,
                        )
                        if existing_idx is not None:
                            st.session_state.clients[existing_idx] = client_dict
                            updated.append(r["name"])
                        else:
                            st.session_state.clients.append(client_dict)
                            imported.append(r["name"])

                if imported:
                    st.success(f"Added {len(imported)}: {', '.join(imported)}")
                if updated:
                    st.info(f"Updated {len(updated)}: {', '.join(updated)}")
                if tz_failed:
                    st.warning(
                        f"Could not detect timezone for {len(tz_failed)} client(s), so they were "
                        f"not saved:\n" + "\n".join(f"- {m}" for m in tz_failed)
                    )
                if save_failed:
                    st.error(
                        f"Database error saving {len(save_failed)} client(s):\n"
                        + "\n".join(f"- {m}" for m in save_failed)
                    )

                time.sleep(1.5)
                st.rerun()

    # ── Delete a client ────────────────────────────────────────────────────
    st.write("---")
    st.subheader("Delete a Client")
    if not st.session_state.clients:
        st.info("No clients saved in database.")
    else:
        client_names = [c["name"] for c in st.session_state.clients]
        client_to_remove = st.selectbox("Select client to remove:", [""] + client_names, key="del_select")

        if st.button("Delete Client", type="secondary"):
            if client_to_remove:
                try:
                    delete_client(client_to_remove)
                except Exception as e:
                    st.error(f"Could not delete client: {e}")
                else:
                    st.session_state.clients = [c for c in st.session_state.clients if c["name"] != client_to_remove]
                    st.rerun()

    # ── Danger zone ─────────────────────────────────────────────────────────
    st.write("---")
    with st.expander("⚠️ Danger Zone"):
        st.caption("This permanently deletes every client from the database.")
        if st.button("Clear entire database", key="clear_btn"):
            try:
                clear_database()
            except Exception as e:
                st.error(f"Could not clear database: {e}")
            else:
                st.session_state.clients = []
                st.rerun()


# ════════════════════════════════════════════════════════════════════════════
# PAGE 2 — VIEW & SEARCH CLIENTS
# ════════════════════════════════════════════════════════════════════════════
elif page == "View & Search Clients":
    st.title("View & Search Clients")

    if not st.session_state.clients:
        st.info("No clients saved in database yet — add some from the Manage Clients page.")
    else:
        keyword = st.text_input(
            "Search by name or location (city/country)",
            placeholder="e.g. 'Alex' or 'India'",
            key="search_keyword",
        )

        if keyword.strip():
            kw = keyword.strip().lower()
            filtered = [
                c for c in st.session_state.clients
                if kw in c["name"].lower() or kw in c["location"].lower()
            ]
        else:
            filtered = st.session_state.clients

        st.caption(f"Showing {len(filtered)} of {len(st.session_state.clients)} client(s).")

        if not filtered:
            st.warning("No clients match that search.")
        else:
            table_rows = []
            for c in sorted(filtered, key=lambda x: x["name"].lower()):
                working_days = [d for d in DAYS if c.get("hours", {}).get(d)]
                table_rows.append({
                    "Name": c["name"],
                    "Location": c["location"],
                    "Timezone": c["timezone"] or "—",
                    "Working Days": ", ".join(working_days) if working_days else "—",
                })
            st.dataframe(pd.DataFrame(table_rows), hide_index=True, use_container_width=True)

            with st.expander("View full weekly schedule for a specific client"):
                names_sorted = sorted([c["name"] for c in filtered])
                chosen_name = st.selectbox("Client", names_sorted, key="detail_select")
                chosen = next(c for c in filtered if c["name"] == chosen_name)

                st.write(f"**{chosen['name']}** — {chosen['location']} — `{chosen['timezone']}`")
                for day in DAYS:
                    hrs = chosen.get("hours", {}).get(day)
                    if hrs:
                        s_h12, s_ampm = to_12hr(hrs[0])
                        e_h12, e_ampm = to_12hr(hrs[1])
                        st.write(f"- **{day}**: {s_h12}:00 {s_ampm} – {e_h12}:00 {e_ampm}")
                    else:
                        st.write(f"- **{day}**: Not working")


# ════════════════════════════════════════════════════════════════════════════
# PAGE 3 — FIND MEETING TIME
# ════════════════════════════════════════════════════════════════════════════
elif page == "Find Meeting Time":
    st.title("Find Meeting Time")

    if not st.session_state.clients:
        st.info("No clients saved in database yet — add some from the Manage Clients page.")
    else:
        st.subheader("Select Meeting Participants")
        all_client_names = [c["name"] for c in st.session_state.clients]

        selected_participant_names = st.multiselect(
            "Choose clients from your database to include in this specific meeting:",
            options=all_client_names,
            default=all_client_names
        )

        find_clicked = st.button("Find Best Meeting", key="find_btn", type="primary")

        if find_clicked:
            selected_clients_data = [c for c in st.session_state.clients if c["name"] in selected_participant_names]

            if len(selected_clients_data) < 2:
                st.error("Please select at least 2 participants to generate a schedule.")
            else:
                valid_clients = [c for c in selected_clients_data if c.get("timezone")]
                bad = [c for c in selected_clients_data if not c.get("timezone")]

                if bad:
                    names = ", ".join(c["name"] for c in bad)
                    st.warning(
                        f"Could not detect timezone for {len(bad)} client(s): {names}. "
                        "They will be excluded from calculations."
                    )

                if not valid_clients or len(valid_clients) < 2:
                    st.error("Not enough clients with valid timezones to generate a meeting.")
                    st.stop()

                with st.spinner("Scanning 168 hours for the best slot…"):
                    candidates = generate_candidate_times()
                    scores = calculate_scores(valid_clients, candidates)
                    best, perfect = best_slot(valid_clients, scores, candidates)

                st.write("---")

                st.markdown(
                    "<h2 style='text-align: center; color: #4CAF50;'>Recommended Meeting Time</h2>",
                    unsafe_allow_html=True,
                )

                if perfect:
                    st.markdown(
                        "<p style='text-align: center;'>Perfect overlap — all selected participants available</p>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        "<p style='text-align: center;'>Best available — no perfect overlap found</p>",
                        unsafe_allow_html=True,
                    )

                st.markdown(
                    f"<h3 style='text-align: center;'>{best.strftime('%d %b %Y %H:%M %Z')}</h3>",
                    unsafe_allow_html=True,
                )

                rounded_best = round_to_nearest_half_hour(best)
                if rounded_best != best:
                    st.markdown(
                        f"<h5 style='text-align: center;'>"
                        f"Rounded-off suggestion: {rounded_best.strftime('%d %b %Y %H:%M %Z')}</h5>",
                        unsafe_allow_html=True,
                    )

                st.write("---")

                st.subheader("Local Times for Participants")
                for client in valid_clients:
                    try:
                        tz = pytz.timezone(client["timezone"])
                        local_time = best.astimezone(tz)

                        status = "🟢 Available" if is_client_available(client, local_time) else "🔴 Outside Working Hours"

                        st.write(
                            f"- **{client['name']}** ({client['location']}): "
                            f"{local_time.strftime('%a %d %b %Y %H:%M %Z')} - {status}"
                        )
                    except Exception as e:
                        st.write(f"- **{client['name']}**: error converting time — {e}")

                st.write("---")

                st.subheader("Top 5 Meeting Slots")
                ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:5]
                table_data = []

                for slot, score in ranked:
                    row = {"UTC Slot": slot.strftime("%Y-%m-%d %H:%M")}

                    for client in valid_clients:
                        try:
                            tz = pytz.timezone(client["timezone"])
                            local = slot.astimezone(tz)
                            row[client["name"]] = local.strftime("%a %d %b %H:%M")
                        except Exception:
                            row[client["name"]] = "error"

                    avail = sum(
                        1 for c in valid_clients
                        if is_client_available(c, slot.astimezone(pytz.timezone(c["timezone"])))
                    )

                    row["Score"] = score
                    row["Available"] = f"{avail}/{len(valid_clients)}"
                    table_data.append(row)

                df = pd.DataFrame(table_data)
                st.table(df)
