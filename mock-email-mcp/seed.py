#!/usr/bin/env python3
"""Seed seed.db from fixtures/seed_emails.json"""
import sqlite3
import json
import os
import pathlib

SCRIPT_DIR = pathlib.Path(__file__).parent.resolve()
DB_PATH = pathlib.Path(os.environ.get("MOCK_DB_PATH", SCRIPT_DIR / "seed.db"))
FIXTURE_PATH = SCRIPT_DIR / "fixtures" / "seed_emails.json"

# IDs for the two emails that have attachments
OFFER_LETTER_MSG_ID = "19e100000000001a"   # the offer letter email
CALENDAR_INVITE_MSG_ID = "19e10000000000f2"  # the calendar invite email

ATTACHMENT_PDF_ID = "ANGjdJ8xKqP3mN7vLwR2sT5uYbZcDhFjGkMnPqRs"
ATTACHMENT_ICS_ID = "ANGjdJ9yLrQ4nO8wMxS3tU6vZcAeDiGkHlNoQrSt"

SYSTEM_LABELS = [
    ("INBOX",                "INBOX",                "system", "labelShow",  "show"),
    ("SENT",                 "SENT",                 "system", "labelShow",  "show"),
    ("DRAFT",                "DRAFT",                "system", "labelShow",  "show"),
    ("TRASH",                "TRASH",                "system", "labelShow",  "show"),
    ("SPAM",                 "SPAM",                 "system", "labelShow",  "show"),
    ("STARRED",              "STARRED",              "system", "labelShow",  "show"),
    ("IMPORTANT",            "IMPORTANT",            "system", "labelShow",  "show"),
    ("UNREAD",               "UNREAD",               "system", "labelHide",  "hide"),
    ("CATEGORY_PERSONAL",    "CATEGORY_PERSONAL",    "system", "labelShow",  "show"),
    ("CATEGORY_SOCIAL",      "CATEGORY_SOCIAL",      "system", "labelShow",  "show"),
    ("CATEGORY_PROMOTIONS",  "CATEGORY_PROMOTIONS",  "system", "labelShow",  "show"),
    ("CATEGORY_UPDATES",     "CATEGORY_UPDATES",     "system", "labelShow",  "show"),
]


def create_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        DROP TABLE IF EXISTS attachments;
        DROP TABLE IF EXISTS drafts;
        DROP TABLE IF EXISTS messages;
        DROP TABLE IF EXISTS labels;

        CREATE TABLE messages (
            id              TEXT PRIMARY KEY,
            thread_id       TEXT NOT NULL,
            label_ids       TEXT NOT NULL,
            sender          TEXT,
            recipient       TEXT,
            subject         TEXT,
            body_plain      TEXT,
            body_html       TEXT,
            internal_date   TEXT,
            snippet         TEXT
        );

        CREATE TABLE attachments (
            id          TEXT PRIMARY KEY,
            message_id  TEXT REFERENCES messages(id),
            filename    TEXT,
            mime_type   TEXT,
            data        BLOB
        );

        CREATE TABLE drafts (
            id          TEXT PRIMARY KEY,
            message_id  TEXT,
            recipient   TEXT,
            cc          TEXT,
            subject     TEXT,
            body        TEXT,
            created_at  TEXT
        );

        CREATE TABLE labels (
            id                      TEXT PRIMARY KEY,
            name                    TEXT,
            type                    TEXT,
            label_list_visibility   TEXT,
            message_list_visibility TEXT
        );
    """)


def seed(conn: sqlite3.Connection) -> None:
    emails = json.loads(FIXTURE_PATH.read_text())

    # Insert messages
    for e in emails:
        conn.execute(
            """
            INSERT INTO messages
                (id, thread_id, label_ids, sender, recipient, subject,
                 body_plain, body_html, internal_date, snippet)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                e["id"],
                e["thread_id"],
                json.dumps(e["label_ids"]),
                e.get("sender"),
                e.get("recipient"),
                e.get("subject"),
                e.get("body_plain"),
                e.get("body_html"),
                e.get("internal_date"),
                e.get("snippet"),
            ),
        )

    # No attachments in the current seed emails

    # Insert system labels
    conn.executemany(
        """
        INSERT INTO labels (id, name, type, label_list_visibility, message_list_visibility)
        VALUES (?, ?, ?, ?, ?)
        """,
        SYSTEM_LABELS,
    )


def main() -> None:
    print(f"Seeding database: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    try:
        create_tables(conn)
        seed(conn)
        conn.commit()

        msg_count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        att_count = conn.execute("SELECT COUNT(*) FROM attachments").fetchone()[0]
        label_count = conn.execute("SELECT COUNT(*) FROM labels").fetchone()[0]

        print(f"  messages   : {msg_count}")
        print(f"  attachments: {att_count}")
        print(f"  labels     : {label_count}")
        print("Seed complete.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
