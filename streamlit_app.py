import streamlit as st
import pandas as pd
import streamlit.components.v1 as components
from datetime import datetime
import pytz
import time

# Updated import to v3_2
from schedule_v3_3 import (
    geolocator,
    tf,
    generate_candidate_times,
    calculate_scores,
    best_slot,
    load_clients_db,
    save_clients_db,
    is_client_available
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
        db = load_clients_db()
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


# ── Page header ───────────────────────────────────────────────────────────────
st.title("Meeting Scheduler v3.2")


# ── Add / Update Client Form ──────────────────────────────────────────────────
with st.form("add_client", clear_on_submit=True):
    st.subheader("Add or Update Client in Database")
    st.caption("To update an existing client, enter their exact name below with the new details.")
    
    name = st.text_input("Name", key="form_name")
    location = st.text_input("Location (City, Country)", key="form_location")
    
    st.write("---")
    st.markdown("**Weekly Schedule**")
    
    hcol1, hcol2, hcol3 = st.columns([1, 1, 1])
    hcol1.markdown("**Day (Working?)**")
    hcol2.markdown("**Start Hour**")
    hcol3.markdown("**End Hour**")
    
    schedule_inputs = {}

    for day in DAYS:
        col1, col2, col3 = st.columns([1, 1, 1])
        with col1:
            default_working = day not in ["Sat", "Sun"]
            is_working = st.checkbox(f"**{day}**", value=default_working, key=f"work_{day}")
        with col2:
            start_h = st.number_input("Start Hour", min_value=0, max_value=23, value=9, key=f"start_{day}", label_visibility="collapsed")
        with col3:
            end_h = st.number_input("End Hour", min_value=0, max_value=23, value=17, key=f"end_{day}", label_visibility="collapsed")
            
        schedule_inputs[day] = {"working": is_working, "start": start_h, "end": end_h}
        
    submitted = st.form_submit_button("Save Client")

    if submitted:
        valid_hours = True
        for day, vals in schedule_inputs.items():
            if vals["working"] and vals["start"] == vals["end"]:
                st.error(f"On {day}, Start and End hours cannot be the same.")
                valid_hours = False
                break
                
        if not name or not location:
            st.error("Provide both name and location.")
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

                if existing_idx is not None:
                    st.session_state.clients[existing_idx] = client_dict
                    st.success(f"Updated {name} — {tz}")
                else:
                    st.session_state.clients.append(client_dict)
                    st.success(f"Added {name} — {tz}")
                
                db = load_clients_db()
                db[name] = {
                    "location": location,
                    "timezone": tz,
                    "hours": formatted_hours
                }
                save_clients_db(db)

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


# ── Bulk Import from Excel ─────────────────────────────────────────────────────
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
            db = load_clients_db()
            imported, updated, tz_failed = [], [], []

            with st.spinner(f"Detecting timezones for {len(parsed_rows)} client(s)…"):
                for r in parsed_rows:
                    tz, err = detect_timezone(r["location"])
                    if err:
                        tz_failed.append(f"{r['name']} ({r['location']}): {err}")
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

                    db[r["name"]] = {
                        "location": r["location"],
                        "timezone": tz,
                        "hours": r["hours"],
                    }

            save_clients_db(db)

            if imported:
                st.success(f"Added {len(imported)}: {', '.join(imported)}")
            if updated:
                st.info(f"Updated {len(updated)}: {', '.join(updated)}")
            if tz_failed:
                st.warning(
                    f"Could not detect timezone for {len(tz_failed)} client(s), so they were "
                    f"not saved:\n" + "\n".join(f"- {m}" for m in tz_failed)
                )

            time.sleep(1.5)
            st.rerun()


# ── Manage Clients ────────────────────────────────────────────────────────────
with st.expander("View / Manage Saved Clients Database"):
    if not st.session_state.clients:
        st.info("No clients saved in database.")
    else:
        for i, c in enumerate(st.session_state.clients, start=1):
            st.write(f"**{i}. {c['name']}** — {c['location']} — `{c['timezone']}`")
        
        st.write("---")
        client_names = [c["name"] for c in st.session_state.clients]
        client_to_remove = st.selectbox("Select client to remove from database:", [""] + client_names)
        
        if st.button("Delete Client", type="secondary"):
            if client_to_remove:
                st.session_state.clients = [c for c in st.session_state.clients if c["name"] != client_to_remove]
                db = load_clients_db()
                if client_to_remove in db:
                    del db[client_to_remove]
                    save_clients_db(db)
                st.rerun()

st.write("---")


# ── Participant Selection (The new v3.2 Multi-Select Feature) ─────────────────
st.subheader("Select Meeting Participants")
all_client_names = [c["name"] for c in st.session_state.clients]

selected_participant_names = st.multiselect(
    "Choose clients from your database to include in this specific meeting:",
    options=all_client_names,
    default=all_client_names # Defaults to selecting everyone, user can remove as needed
)


# ── Action buttons ────────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
    div[data-testid="column"]:nth-of-type(3) {
        display: flex;
        justify-content: flex-end;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

col_left, col_mid, col_right = st.columns([10, 10, 6])

with col_left:
    if st.button("Clear entire database", key="clear_btn"):
        st.session_state.clients = []
        save_clients_db({}) 
        st.rerun()

with col_right:
    find_clicked = st.button("Find Best Meeting", key="find_btn", type="primary")


# ── Results ───────────────────────────────────────────────────────────────────
if find_clicked:
    # Filter the database to ONLY the selected participants
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