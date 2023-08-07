"""Fetch rows from the failed_emails tale and remove.
"""

import argparse
import os
from pathlib import Path

from psycopg2 import connect
from psycopg2.extensions import cursor

CONNECTIONPARAMS = {"user": "postgres", "password": "password", "host": "localhost"}


def get_entry(row_id: int, this_cursor: cursor) -> dict:
    query = f"SELECT * FROM accounting.failed_emails WHERE id={row_id}"
    this_cursor.execute(query)
    query_result = this_cursor.fetchall()[0]
    failed_email_colnames = [desc[0] for desc in this_cursor.description]
    result = {
        failed_email_colnames[i]: query_result[i] for i in range(len(query_result))
    }
    return result


def truncate_table(this_cursor: cursor) -> None:
    query = "TRUNCATE accounting.failed_emails"
    this_cursor.execute(query)
    assert get_database_row_count(this_cursor) == 0
    print("accounting.failed_emails truncated successfully.")


def delete_row(row_id: int, this_cursor: cursor) -> None:
    prev_row_count = get_database_row_count(this_cursor)
    query = f"DELETE FROM accounting.failed_emails WHERE id={row_id}"
    this_cursor.execute(query)
    assert get_database_row_count(this_cursor) == prev_row_count - 1
    print(f"ID {row_id} deleted successfully.")


def get_database_row_count(this_cursor: cursor) -> int:
    query_check_empty = "SELECT id FROM accounting.failed_emails"
    this_cursor.execute(query_check_empty)
    return len(this_cursor.fetchall())


def reset_auto_increment(this_cursor: cursor) -> None:
    query_check_empty = "SELECT id FROM accounting.failed_emails"
    this_cursor.execute(query_check_empty)
    nrows = len(this_cursor.fetchall())
    if nrows < 1:
        query = "ALTER SEQUENCE accounting.failed_emails_id_seq RESTART"
        this_cursor.execute(query)
        print("Table empty - id has been reset.")


def write_email(email_message: dict, targetdir: Path) -> None:
    email_file_output = (
        "Content-Type: text/html; charset=us-ascii\n"
        f"Subject: {email_message['subject']}\n"
        f"To: {email_message['recipients']}\n"
        "X-unsent: 1\n"
        f"{email_message['message']}"
    )
    filename = Path(
        f"row_{email_message['id']}_time_{email_message['time_created']}.eml".replace(
            " ", "-"
        )
    )
    savepath = targetdir / filename
    with open(savepath, "w", encoding="utf-8") as writer:
        writer.write(email_file_output)
    print(
        f"email saved as {savepath}\n"
        "Open the file in your email app and forward as required."
    )


def process_emails(row_id: int, args: argparse.Namespace, this_cursor: cursor) -> None:
    try:
        email_message = get_entry(row_id, this_cursor)
        if args.display:
            for key in email_message:
                print(f"- {key}")
                print(email_message[key])
                print()
        else:
            if not os.path.exists(args.dirpath):
                raise FileNotFoundError(
                    f"The path provided could not be found: {args.dirpath}"
                )
            write_email(email_message, args.dirpath)
        if args.delete:
            delete_row(row_id, this_cursor)
            reset_auto_increment(this_cursor)
    except IndexError:
        print(f"Row {row_id} not in table.")


def main() -> None:
    """Retrieve failed email"""
    parser = argparse.ArgumentParser(description="Retrieve failed email")
    parser.add_argument("-id", default=1, type=int, help="The row id. [Default = 1]")
    parser.add_argument(
        "-dirpath",
        type=Path,
        default=Path(os.path.expanduser("~/Desktop")),
        help=f"Directory path to save the emails to. [Default = {Path(os.path.expanduser('~/Desktop'))}]",
    )
    parser.add_argument(
        "--all", action="store_true", help="Process all rows. [Default = False]."
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Delete the entry at the end of the operation. [Default = False].",
    )
    parser.add_argument(
        "--display",
        action="store_true",
        help="Display the the email rather than saving to file. [Default = False].",
    )
    parser.add_argument(
        "--just_delete",
        action="store_true",
        help="Don't process emails, just remove all entries from the table. [Default = False].",
    )
    args = parser.parse_args()
    with connect(**CONNECTIONPARAMS) as connection:
        this_cursor = connection.cursor()
        if args.just_delete:
            truncate_table(this_cursor)
        else:
            if args.all:
                nrows = get_database_row_count(this_cursor)
                for i in range(1, nrows + 1):
                    process_emails(i, args, this_cursor)
            else:
                process_emails(args.id, args, this_cursor)


if __name__ == "__main__":
    main()
