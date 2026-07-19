from config import supabase


# -------------------------------
# Get all clients
# -------------------------------

def get_all_clients():
    response = (
        supabase
        .table("clients")
        .select("*")
        .order("name")
        .execute()
    )

    clients = {}

    for row in response.data:

        clients[row["name"]] = {
            "location": row["location"],
            "timezone": row["timezone"],
            "hours": row["hours"]
        }

    return clients


# -------------------------------
# Get one client
# -------------------------------

def get_client(name):

    response = (
        supabase
        .table("clients")
        .select("*")
        .eq("name", name)
        .execute()
    )

    if len(response.data) == 0:
        return None

    row = response.data[0]

    return {
        "location": row["location"],
        "timezone": row["timezone"],
        "hours": row["hours"]
    }


# -------------------------------
# Check duplicate
# -------------------------------

def client_exists(name):

    response = (
        supabase
        .table("clients")
        .select("id")
        .eq("name", name)
        .execute()
    )

    return len(response.data) > 0


# -------------------------------
# Add client
# -------------------------------

def add_client(name,
               location,
               timezone,
               hours):

    if client_exists(name):
        raise ValueError("Client already exists.")

    (
        supabase
        .table("clients")
        .insert({
            "name": name,
            "location": location,
            "timezone": timezone,
            "hours": hours
        })
        .execute()
    )


# -------------------------------
# Update client
# -------------------------------

def update_client(name,
                  location,
                  timezone,
                  hours):

    (
        supabase
        .table("clients")
        .update({
            "location": location,
            "timezone": timezone,
            "hours": hours
        })
        .eq("name", name)
        .execute()
    )


# -------------------------------
# Add or Update
# -------------------------------

def save_client(name,
                location,
                timezone,
                hours):

    if client_exists(name):

        update_client(
            name,
            location,
            timezone,
            hours
        )

    else:

        add_client(
            name,
            location,
            timezone,
            hours
        )


# -------------------------------
# Rename client
# -------------------------------

def rename_client(old_name,
                  new_name):

    if old_name == new_name:
        return

    if client_exists(new_name):
        raise ValueError(
            "A client with this name already exists."
        )

    (
        supabase
        .table("clients")
        .update({
            "name": new_name
        })
        .eq("name", old_name)
        .execute()
    )


# -------------------------------
# Delete client
# -------------------------------

def delete_client(name):

    (
        supabase
        .table("clients")
        .delete()
        .eq("name", name)
        .execute()
    )


# -------------------------------
# Clear database
# -------------------------------

def clear_database():

    (
        supabase
        .table("clients")
        .delete()
        .neq("id", "00000000-0000-0000-0000-000000000000")
        .execute()
    )


# -------------------------------
# Bulk Import
# -------------------------------

def bulk_import_clients(client_list):
    """
    client_list format

    [
        {
            "name":"John",
            "location":"London",
            "timezone":"Europe/London",
            "hours":{}
        },
        ...
    ]
    """

    for client in client_list:

        save_client(
            client["name"],
            client["location"],
            client["timezone"],
            client["hours"]
        )


# -------------------------------
# Search client
# -------------------------------

def search_clients(keyword):

    response = (
        supabase
        .table("clients")
        .select("*")
        .ilike("name", f"%{keyword}%")
        .order("name")
        .execute()
    )

    return response.data