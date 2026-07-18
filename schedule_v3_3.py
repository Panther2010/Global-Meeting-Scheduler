from geopy.geocoders import Nominatim
from timezonefinder import TimezoneFinder
from datetime import datetime, timedelta
import pytz
import json
import os

CLIENT_DB = "clients.json"

geolocator = Nominatim(user_agent="meeting_scheduler")
tf = TimezoneFinder()

#loading client
def load_clients_db():

    if not os.path.exists(CLIENT_DB):
        return {}

    with open(CLIENT_DB, "r") as f:
        return json.load(f)

#saving client
def save_clients_db(data):

    with open(CLIENT_DB, "w") as f:
        json.dump(data, f, indent=4)

#adding client
def add_client_to_db():

    clients_db = load_clients_db()

    print("\nAdd New Client")

    name = input("Client Name: ")
    
    if name.lower() in [
        client.lower() for client in clients_db.keys()
    ]:
        print("Client already exists.")
        return

    location = input(
        "Location (City, Country): "
    )

    try:

        loc = geolocator.geocode(location)

        if loc is None:

            print("Location not found.")
            return

        timezone = tf.timezone_at(
            lat=loc.latitude,
            lng=loc.longitude
        )

        hours = {}

        days = [
            "Mon",
            "Tue",
            "Wed",
            "Thu",
            "Fri",
            "Sat",
            "Sun"
        ]

        print(
            "\nEnter weekly schedule"
        )

        for day in days:
            while True:
                working = input(
                    f"{day} working? (Yes/No): "
                ).strip().lower()

                if working in ['yes', 'y']:

                    start = int(
                        input(
                            f"{day} start hour: "
                        )
                    )

                    end = int(
                        input(
                            f"{day} end hour: "
                        )
                    )

                    if not (0 <= start <= 23):
                        print(
                            "Start hour must be between 0 and 23."
                        )
                        continue
                    if not (0 <= end <= 23):
                        print(
                            "End hour must be between 0 and 23."
                        )
                        continue
                    if start == end:
                        print(
                            "Start and end hours cannot be the same."
                        )
                        continue

                    hours[day] = [
                        start,
                        end
                    ]
                    break

                elif working in ['no', 'n']:
                    hours[day] = None
                    break
                else:
                    print(
                        "Please enter Yes or No."
                    )

        clients_db[name] = {

            "location": location,

            "timezone": timezone,

            "hours": hours
        }

        save_clients_db(
            clients_db
        )

        print(
            "Client saved successfully!"
        )

    except Exception as e:

        print("Error:", e)

#deleting client
def delete_client_from_db():

    db = load_clients_db()

    if not db:

        print("No saved clients found.")
        return

    names = list(db.keys())

    print("\nSaved Clients")

    for i, name in enumerate(names, start=1):

        print(f"{i}. {name}")

    try:

        idx = int(
            input(
                "\nSelect client to delete: "
            )
        ) - 1

        client_name = names[idx]

        confirm = input(
            f"Delete {client_name}? (y/n): "
        )

        if confirm.lower() == "y":

            del db[client_name]

            save_clients_db(db)

            print(
                f"{client_name} deleted."
            )

    except:

        print("Invalid selection.")

#editing client
def edit_client_in_db():

    db = load_clients_db()

    if not db:

        print("No saved clients found.")
        return

    names = list(db.keys())

    print("\nSaved Clients")

    for i, name in enumerate(names, start=1):

        print(f"{i}. {name}")

    try:

        idx = int(
            input(
                "\nSelect client to edit: "
            )
        ) - 1

        client_name = names[idx]

        client = db[client_name]

        print("\nPress Enter to keep current values")

        new_name = input(
            f"Name [{client_name}]: "
        )

        new_location = input(
            f"Location [{client['location']}]: "
        )

        print(
            "\nEdit Weekly Schedule"
        )
        for day in client["hours"]:
            current = client["hours"][day]
            
            if current is None:
                print(
                    f"{day}: OFF"
                )
                while True:
                    working = input(
                        f"{day} working? (Yes/No): "
                    ).strip().lower()
                    if working in ['yes', 'y']:
                        start = int(
                            input(
                                f"{day} start: "
                            )
                        )
                        end = int(
                            input(
                                f"{day} end: "
                            )
                        )
                        if not (0 <= start <= 23):
                            print(
                                "Start hour must be between 0 and 23."
                            )
                            continue
                        if not (0 <= end <= 23):
                            print(
                                "End hour must be between 0 and 23."
                            )
                            continue
                        if start == end:
                            print(
                                "Start and end hours cannot be the same."
                            )
                            continue
                        client["hours"][day] = [
                            start,
                            end
                        ]
                        break
                    elif working in ['no', 'n']:
                        break
                    else:
                        print(
                            "Please enter Yes or No."
                        )
            else:
                print(
                    f"{day}: "
                    f"{current[0]} - {current[1]}"
                )
                action = input(
                    f"{day}: Edit / Off / Keep? "
                    "(E/O/K): "
                ).strip().lower()
                if action in ['e', 'edit']:
                    while True:
                        start = int(
                            input(
                                f"{day} start: "
                            )
                        )
                        end = int(
                            input(
                                f"{day} end: "
                            )
                        )
                        if not (0 <= start <= 23):
                            print(
                                "Start hour must be between 0 and 23."
                            )
                            continue
                        if not (0 <= end <= 23):
                            print(
                                "End hour must be between 0 and 23."
                            )
                            continue
                        if start == end:
                            print(
                                "Start and end hours cannot be the same."
                            )
                            continue
                        client["hours"][day] = [
                            start,
                            end
                        ]
                        break
                elif action in ['o', 'off']:
                    client["hours"][day] = None

        if new_location:

            loc = geolocator.geocode(
                new_location
            )

            if loc:

                timezone = tf.timezone_at(
                    lat=loc.latitude,
                    lng=loc.longitude
                )

                client["location"] = (
                    new_location
                )

                client["timezone"] = (
                    timezone
                )

        if (
            new_name
            and new_name != client_name
        ):
            if new_name.lower() in [
                name.lower() for name in db.keys()
            ]:
                print(
                    "A client with that name already exists."
                )
                return
            db[new_name] = client
            del db[client_name]
        else:
            db[client_name] = client

        save_clients_db(db)
        print("Client updated.")

    except:

        print("Invalid selection.")

#viewing saved clients
def view_saved_clients():

    db = load_clients_db()

    if not db:

        print("No saved clients.")
        return

    print("\nSaved Clients")

    for name, data in db.items():

        print(
            f"\n{name}"
        )
        print(
            f"Location: "
            f"{data['location']}, "
        )
        for day, hours in data["hours"].items():
            if hours is None:
                print(
                    f"   {day}: OFF"
                )
            else:
                print(
                    f"   {day}: "
                    f"{hours[0]} - {hours[1]}"
                )

def collect_clients():

    selected_clients = []

    db = load_clients_db()

    while True:
        if selected_clients:
            print("\nCurrently Selected:"
            )
            for client in selected_clients:
                print(
                    f"- {client['name']}"
                )

        print("\n===== CLIENT MENU =====")
        print("1. Use Saved Client")
        print("2. Add New Client")
        print("3. Edit Client")
        print("4. Delete Client")
        print("5. View Saved Clients")
        print("6. Finish Selection")

        choice = input("Choice: ")

        if choice == "1":

            if not db:
                print("No saved clients.")
                continue

            print("\nSaved Clients")

            names = list(db.keys())

            for i, name in enumerate(names, start=1):
                print(f"{i}. {name}")

            selection = input(
                "\nSelect clients "
                "(example: 1, 3, 5): "
            )                
            try:
                indexes = [
                    int(x.strip()) - 1
                    for x in selection.split(",")
                ]
            except ValueError:
                print(
                    "Invalid input."
                )
                continue
            for idx in indexes:
                if idx < 0 or idx >= len(names):
                    print(
                        f"Invalid selection: {idx + 1}"
                    )
                    continue

                client_name = names[idx]

                already_selected = any(
                    c["name"] == client_name
                    for c in selected_clients
                )

                if already_selected:
                    print(f"{client_name} already selected.")
                    continue

                client_data = db[client_name]

                selected_clients.append({
                    "name": client_name,
                    "location": client_data["location"],
                    "timezone": client_data["timezone"],
                    "hours": client_data["hours"]
                })
                print(
                    f"{client_name} added."
                )

        elif choice == "2":

            add_client_to_db()

            db = load_clients_db()

        elif choice == "3":

            edit_client_in_db()
            db = load_clients_db()
        
        elif choice == "4":

            delete_client_from_db()
            db = load_clients_db()
            
        elif choice == "5":

            view_saved_clients()
        
        elif choice == "6":
            if len(selected_clients) < 2:
                print(
                    "Select at least 2 clients."
                )
                continue
            print(
                "\nParticipants:"
            )
            for client in selected_clients:
                print(
                    f"- {client['name']}"
                )
            confirm = input(
                "\nGenerate schedule? "
                "(Yes/No):"
            ).strip().lower()
            if confirm in ["yes", "y"]:
                break

    return selected_clients

#Ulility_function

def generate_candidate_times():

    now = datetime.now(pytz.utc)

    candidates = []

    for hour_offset in range(168):

        candidates.append(
            now + timedelta(hours=hour_offset)
        )

    return candidates

#Working_Module

def comfort_score(hour):

    if 10 <= hour <= 16:
        return 3

    elif 9 <= hour < 18:
        return 1

    return 0

def is_client_available(
    client,
    local_time
):

    day = local_time.strftime("%a")

    schedule = client["hours"]

    if schedule[day] is None:

        return False

    start_hour, end_hour = schedule[day]
    if start_hour < end_hour:
        return (
            start_hour
            <= local_time.hour
            < end_hour
        )
    else:
        #overnight shift
        return (
            local_time.hour >= start_hour
            or local_time.hour < end_hour
        )

def find_perfect_overlap(clients, candidates):

    perfect_slots = []

    for candidate_time in candidates:

        all_available = True

        for client in clients:

            timezone = pytz.timezone(
                client["timezone"]
            )

            local_time = candidate_time.astimezone(
                timezone
            )

            if not is_client_available(
                client,
                local_time
            ):
                all_available = False
                break

        if all_available:
            perfect_slots.append(candidate_time)

    return perfect_slots

def availability_count(clients, candidate_time):

    count = 0

    for client in clients:

        timezone = pytz.timezone(
            client["timezone"]
        )

        local_time = candidate_time.astimezone(
            timezone
        )

        if is_client_available(
            client,
            local_time
        ):
            count += 1

    return count

def calculate_scores(clients, candidates):

    scores = {}

    # Weight must exceed the maximum possible comfort bonus a slot could
    # accumulate (len(clients) * 3), otherwise a slot with fewer available
    # clients but great comfort timing can outscore a slot where more
    # clients (or all of them) are actually available. This keeps
    # "more people available" strictly more important than "more
    # comfortable time" no matter how many clients are being scheduled.
    AVAILABILITY_WEIGHT = max(1000, len(clients) * 3 + 1)

    for candidate_time in candidates:

        total_score = 0

        for client in clients:

            timezone = pytz.timezone(
                client["timezone"]
            )

            local_time = candidate_time.astimezone(
                timezone
            )

            if is_client_available(
                client,
                local_time
            ):
                total_score += AVAILABILITY_WEIGHT

                total_score += comfort_score(local_time.hour)

        scores[candidate_time] = total_score

    return scores

def best_slot(clients, scores, candidates):

    perfect_slots = find_perfect_overlap(
        clients,
        candidates
    )

    # Perfect overlap exists

    if perfect_slots:

        best_hour = max(
            perfect_slots,
            key=lambda h: scores[h]
        )

        return best_hour, True

    # No perfect overlap

    best_hour = max(
        scores,
        key=scores.get
    )

    return best_hour, False


def show_results(
    clients,
    best_time,
    perfect_overlap
):

    print("\nRecommended Meeting Time")

    print(
        best_time.strftime(
            "%Y-%m-%d %H:%M UTC"
        )
    )

    print(
        f"\nAvailable Clients: "
        f"{availability_count(clients, best_time)}/{len(clients)}"
    )

    print(
        f"Perfect Overlap: "
        f"{'YES' if perfect_overlap else 'NO'}"
    )

    print("\nLocal Times")

    for client in clients:

        timezone = pytz.timezone(
            client["timezone"]
        )

        local_time = best_time.astimezone(
            timezone
        )

        status = "Available"
        if not is_client_available(
            client,
            local_time
        ):
            status = "Outside Working Hours"
        
        print(
            f"{client['name']} "
            f"({client['location']}) : "
            f"{local_time.strftime('%Y-%m-%d %H:%M')} "
            f"[{status}]"
        )


def show_top_slots(scores):

    ranked = sorted(
        scores.items(),
        key=lambda x: x[1],
        reverse=True
    )

    print("\nTop 5 Meeting Slots")

    for candidate_time, score in ranked[:5]:

        print(
            candidate_time.strftime(
                "%Y-%m-%d %H:%M UTC"
            ),
            f"Score = {score}"
        )