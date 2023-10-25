import os

import pandas as pd
import psycopg2
from psycopg2 import sql


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
            (f"Could not find secrets file '{secrets_file}'."),
        )
    with open(secrets_file, encoding="UTF-8") as secrets:
        return {
            line.split("=")[0]: line.split("=")[1].strip()
            for line in secrets.readlines()
        }


def connect_to_db() -> psycopg2.extensions.connection:
    """Connects to the database using the secrets file.

    Returns:
        psycopg2.extensions.connection: Connection to the database.
    """
    secrets_file = os.path.join(os.path.dirname(__file__), ".secrets")
    secrets = get_secrets(secrets_file)
    return psycopg2.connect(
        dbname=secrets["dbname"],
        user=secrets["user"],
        password=secrets["password"],
        host=secrets["host"],
        port=secrets["port"],
    )


def run_query(query: sql) -> pd.DataFrame:
    """Runs a query on the database.

    Args:
        query: Query to run.

    Returns:
        Dataframe of results.
    """
    conn = connect_to_db()
    with conn.cursor() as cursor:
        cursor.execute(query)
        data = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        df = pd.DataFrame(data, columns=columns)
        return df
