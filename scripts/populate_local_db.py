"""Insert data from database json files into local database.
"""

import argparse
import json
import os
from datetime import datetime, timedelta

import psycopg2


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


def get_user_admin_code() -> str:
    """Get admin code for user running the script. Reads oid field from the
    users local database.

    Returns:
        str: User's admin UUID code.
    """
    query = "SELECT oid FROM user_rbac"
    connection = psycopg2.connect(
        user="postgres", password="password", host="localhost"
    )
    cursor = connection.cursor()
    cursor.execute(query)
    result = cursor.fetchall()[0][0]
    connection.close()
    return result


def update_admincode(data: list, admin: str) -> None:
    """Replaces admin code in loaded json data with the provided admin code.
    Changes data in place.

    Args:
        data (list): List of data rows dictionary.
        admin (str): Admin UUID code.
    """
    for entry in data:
        entry["admin"] = admin


def update_end_date(data: list) -> None:
    """Update the project end date to be 180 days (~6 months) in the future
    from the current date.

    Args:
        data (list): List of data rows dictionary
    """
    for entry in data:
        if "end_datetime" in entry:
            entry["end_datetime"] = str(datetime.today() + timedelta(days=180))


def truncate_local_table(table: str) -> None:
    """Remove contents of given table name.

    Args:
        table (str): Name of table to truncate.
    """
    connection = psycopg2.connect(
        user="postgres", password="password", host="localhost"
    )
    cursor = connection.cursor()
    cursor.execute(f"truncate table {table} CASCADE")
    connection.commit()
    connection.close()


def insert_into_local_db(data: list, tablename: str) -> None:
    """Insert provided json data into named table.

    Args:
        data (list): Data to insert into the table. Json format.
        tablename (str): Name of the table to insert data in to.
    """
    chunk_size = 100000
    packets = [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]
    for i in range(len(packets)):
        print(f"\tUploading packet {i+1} of {len(packets)}")
        connection = psycopg2.connect(
            user="postgres", password="password", host="localhost"
        )
        cursor = connection.cursor()
        query = f""" INSERT INTO {tablename}
                SELECT * FROM json_populate_recordset(NULL::{tablename}, %s)
                """
        cursor.execute(
            query,
            (json.dumps(packets[i]),),
        )
        connection.commit()
        connection.close()


def read_json_data(tablename: str, dirpath: str) -> list:
    """Load the json data from the given table name.

    Args:
        tablename (str): The name of the table to load data from.
        dirpath   (str): The path to the directory the json files are stored in.
    Returns:
        data (list): The data from tablename's json file
    """
    filename = tablename.replace(".", "-") + ".json"
    path = os.path.join(dirpath, filename)
    with open(path, encoding="UTF-8") as jsonfile:
        data = json.load(jsonfile)
    return data


def main() -> None:
    """Insert data from database json files into local database."""
    parser = argparse.ArgumentParser(
        description="Inserts data from json files into local database"
    )
    parser.add_argument(
        "path", type=str, help="Path to directory containing json data files"
    )
    args = parser.parse_args()
    dirpath = args.path
    check_dirpath(dirpath)
    admincode = get_user_admin_code()
    table_list = [
        "accounting.subscription",
        "accounting.subscription_details",
        "accounting.allocations",
        "accounting.approvals",
        "accounting.finance",
        "accounting.cost_recovery",
        "accounting.cost_recovery_log",
        "accounting.costmanagement",
        "accounting.emails",
        "accounting.persistence",
        "accounting.status",
        "accounting.usage",
    ]
    for tbl in table_list:
        filename = tbl.replace(".", "-") + ".json"
        path = os.path.join(dirpath, filename)
        if os.path.exists(path):
            # if tbl == 'accounting.cost_recovery':
            #     continue
            print(f"Extracting data from '{tbl}'")
            truncate_local_table(tbl)
            data = read_json_data(tbl, dirpath)
            update_admincode(data, admincode)
            update_end_date(data)
            insert_into_local_db(data, tbl)
        else:
            print(f"'{tbl}' not found in {dirpath}")


if __name__ == "__main__":
    main()
