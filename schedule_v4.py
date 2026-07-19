from geopy.geocoders import Nominatim
from timezonefinder import TimezoneFinder
from datetime import datetime, timedelta
import pytz

geolocator = Nominatim(user_agent="meeting_scheduler")
tf = TimezoneFinder()

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