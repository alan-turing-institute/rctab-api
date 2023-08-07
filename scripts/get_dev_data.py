"""Get data from production database and save as json files for testing
"""
import argparse
import json
import os
import uuid

import psycopg2
from psycopg2 import sql

# Set up Global anonymous dictionary
ANONYMOUSDICT = {}
USERCOUNTER = {"counter": 0}


def check_dirpath(path: str) -> None:
    """Check path is to a directory.

    Args:
        path (str): Path to check.

    Raises:
        NotADirectoryError: Error to say the path does not go to an existing
        directory.
    """
    if not os.path.isdir(path):
        raise NotADirectoryError(path, f"The directory '{path}' was not found")


def get_secrets(secrets_file: str) -> dict:
    """Reads a secrets file of the form 'key=value' and returns a dictionary
    of key:value.

    Args:
        secrets_file (str): Name of secrets file.

    Returns:
        dict: Dictionary of secret name and secret.
    """
    if os.path.isfile(secrets_file) is False:
        raise FileNotFoundError(
            secrets_file,
            (
                f"Could not find secrets file '{secrets_file}'."
                " See scripts/README.md for details."
            ),
        )
    with open(secrets_file, encoding="UTF-8") as secrets:
        return {
            line.split("=")[0]: line.split("=")[1].strip()
            for line in secrets.readlines()
        }


def update_anonymous_dict(entry: str) -> None:
    """Adds an entry to a dictionary of users. The dictionary of users
    'ANONYMOUSDICT' has the real entry as a key and an anonymised email and
    username as values. When an entry is added, the username before the '@' in
    the email is replaced with user_{USERCOUNTER}, where USERCOUNTER is the
    nth user. This ensures that the same username has the same anonymised
    username in different tables.

    For example: {"jdoe@myorg.ac.uk" : {
            "email" : "user_1@myorg.ac.uk",
            "username" : "user_1"
        }

    Args:
        entry (str): A users email to anonymise.
    """
    ANONYMOUSDICT[entry] = {
        "email": f"user_{USERCOUNTER['counter']}@email.ac.uk",
        "username": f"user_{USERCOUNTER['counter']}",
    }
    USERCOUNTER["counter"] += 1


def anonymise_admin(row: dict) -> None:
    """Replace admin values with a UUID of zeros if admin is a column.
    Updates in place.

    Args:
        row (dict): Row in a table. key:value = column name: row value.
    """
    if "admin" in row:
        row["admin"] = uuid.UUID(int=0)


def anonymise_recipients(row: dict) -> None:
    """Replace recipients emails with anonymised emails if recipients is a
    column. Updates in place.

    Args:
        row (dict): Row in a table. key:value = column name: row value.
    """
    if "recipients" in row:
        anonymous_row = []
        for email in row["recipients"].split(";"):
            if email not in ANONYMOUSDICT:
                update_anonymous_dict(email)
            anonymous_row.append(ANONYMOUSDICT[email]["email"])
        row["recipients"] = ";".join(anonymous_row)
    if "account_owner_id" in row:
        account_username = row["account_owner_id"]
        if account_username not in ANONYMOUSDICT:
            update_anonymous_dict(account_username)
        row["account_owner_id"] = ANONYMOUSDICT[account_username]["email"]


def anonymise_role_assignments(row: dict) -> None:
    """Replace role assignment emails and usernames with anonymised versions
    if role_assignments is a column with values in. Updates in place.

    Args:
        row (dict): Row in a table. key:value = column name: row value
    """
    if "role_assignments" in row and len(row["role_assignments"]) > 0:
        for i in range(len(row["role_assignments"])):
            data_username = row["role_assignments"][i]["mail"]
            if data_username is not None:
                if data_username not in ANONYMOUSDICT:
                    update_anonymous_dict(data_username)
                row["role_assignments"][i]["mail"] = ANONYMOUSDICT[data_username][
                    "email"
                ]
                row["role_assignments"][i]["display_name"] = ANONYMOUSDICT[
                    data_username
                ]["username"]


def remove_identifiers(row: dict) -> None:
    """Replace identifying data with anonymised versions. Updates in place.

    Args:
        row (dict): Row in a table. key:value = column name: row value
    """
    anonymise_admin(row)
    anonymise_recipients(row)
    anonymise_role_assignments(row)


def convert_to_json(data: list, colnames: list) -> list:
    """Convert data to json format dictionary of columns names and data values.

    Args:
        data (list): List of rows extracted from a table.
        colnames (list): List of column names of the table the data came from.

    Returns:
        list: List of json formatted table rows.
    """
    results_json = [dict(zip(colnames, row)) for row in data]
    return results_json


def query_table(table_name: str) -> list:
    """Get data from given table where the subscription ID is associated with
    Research computing platforms. If the table does not have a subscription_id
    field then all the data is returned.

    Args:
        table_name (str): The table name to extract data from.

    Returns:
        list: A list of dictionaries of the column name and value for each row
    """
    secrets_path = os.path.join(os.path.dirname(__file__), ".get_dev_secrets")
    secrets = get_secrets(secrets_path)
    query = sql.SQL("SELECT * FROM {tbl} WHERE subscription_id = {subid}").format(
        tbl=sql.SQL(table_name), subid=sql.Literal(secrets["subscription_id"])
    )
    connection = psycopg2.connect(
        dbname=secrets["dbname"],
        user=secrets["user"],
        host=secrets["host"],
        password=secrets["password"],
        port=secrets["port"],
    )
    cursor = connection.cursor()
    try:
        cursor.execute(query)
        data = cursor.fetchall()
        connection.close()
        data_json = convert_to_json(data, [desc[0] for desc in cursor.description])
    except psycopg2.errors.UndefinedColumn:  # pylint: disable=no-member
        print("\t- No data found in table")
        connection.rollback()
        cursor = connection.close()
        data_json = []
    return data_json


def write_table_json(dirpath: str, tablename: str, data: list) -> None:
    """Write json data to json file.

    Args:
        dirname (str): Path to directory to save the files to.
        tablename (str): Name of the table in the database.
        data (list): Json data to write to file.
    """
    filename = f"{tablename.replace('.', '-')}.json"
    path = os.path.join(dirpath, filename)
    with open(path, "w", encoding="UTF-8") as jsonfile:
        json.dump(data, jsonfile, default=str, indent=1)


def main() -> None:
    """Extract database data from the Research Computing Platforms subscription
    and save as a json file.
    """
    parser = argparse.ArgumentParser(
        description="""Get data from production database and save as json
        files for testing.
        """
    )
    parser.add_argument(
        "--path",
        default="database_data",
        type=str,
        help="""Location to save files to. Default saves to 'database_data'
        created in the current working directory.""",
    )
    args = parser.parse_args()
    dirpath = args.path
    if dirpath == "database_data" and not os.path.isdir(dirpath):
        os.makedirs(dirpath)
    check_dirpath(dirpath)
    print(f"Saving output to {dirpath}")
    table_list = [
        "accounting.allocations",
        "accounting.approvals",
        "accounting.cost_recovery",
        "accounting.cost_recovery_log",
        "accounting.costmanagement",
        "accounting.emails",
        "accounting.finance",
        "accounting.persistence",
        "accounting.status",
        "accounting.subscription",
        "accounting.subscription_details",
        "accounting.usage",
    ]
    for tbl in table_list:
        print(f"- Writing snapshot of {tbl} to json")
        data_json = query_table(tbl)
        for row in data_json:
            remove_identifiers(row)
        write_table_json(dirpath, tbl, data_json)


if __name__ == "__main__":
    main()
