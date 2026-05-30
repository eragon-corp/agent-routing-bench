#!/usr/bin/env python3
"""
Mock Gmail MCP Server
Exposes 10 Gmail-like tools backed by SQLite.
Start: MOCK_DB_PATH=./inbox.db python server.py
"""
import base64
import json
import os
import re
import secrets
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

# ---------------------------------------------------------------------------
# DB setup
# ---------------------------------------------------------------------------

DB_PATH = Path(os.environ.get("MOCK_DB_PATH", "./inbox.db"))

mcp = FastMCP("mock-gmail")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _random_message_id() -> str:
    """Random 16-char hex string."""
    return secrets.token_hex(8)


def _random_draft_id() -> str:
    """'r' + random 19-digit integer."""
    import random
    n = random.randint(10 ** 18, 10 ** 19 - 1)
    return f"r{n}"


def _is_hex(s: str, min_len: int = 15, max_len: int = 16) -> bool:
    if not (min_len <= len(s) <= max_len):
        return False
    return bool(re.fullmatch(r"[0-9a-fA-F]+", s))


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row_to_message(row: sqlite3.Row, attachments: list[dict], fetch_full: bool = False) -> dict:
    """Convert a DB row to the GMAIL_FETCH_EMAILS message shape."""
    label_ids = json.loads(row["label_ids"]) if row["label_ids"] else []
    body_plain = row["body_plain"] or ""
    msg: dict[str, Any] = {
        "messageId": row["id"],
        "threadId": row["thread_id"],
        "labelIds": label_ids,
        "sender": row["sender"] or "",
        "to": row["recipient"] or "",
        "subject": row["subject"] or "",
        "messageTimestamp": row["internal_date"] or "",
        "messageText": body_plain,
        "preview": {
            "body": body_plain[:200],
            "subject": row["subject"] or "",
        },
        "display_url": f"mock://inbox/{row['id']}",
        "attachmentList": attachments,
    }
    if fetch_full:
        encoded = base64.urlsafe_b64encode(body_plain.encode()).decode()
        msg["payload"] = {
            "partId": "",
            "mimeType": "text/plain",
            "filename": "",
            "headers": [
                {"name": "From", "value": row["sender"] or ""},
                {"name": "To", "value": row["recipient"] or ""},
                {"name": "Subject", "value": row["subject"] or ""},
                {"name": "Date", "value": row["internal_date"] or ""},
            ],
            "body": {"size": len(body_plain), "data": encoded},
            "parts": [],
        }
    return msg


def _get_attachments_for_message(conn: sqlite3.Connection, message_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT id, filename, mime_type FROM attachments WHERE message_id = ?",
        (message_id,),
    ).fetchall()
    return [{"attachmentId": r["id"], "filename": r["filename"], "mimeType": r["mime_type"]} for r in rows]


# ---------------------------------------------------------------------------
# Query parsing
# ---------------------------------------------------------------------------

def _parse_query(query: str) -> tuple[list[str], list[dict]]:
    """
    Parse a Gmail-style query string into (sql_clauses, params).
    Returns (where_clauses, bindings) where bindings is a flat list.
    Special: 'has:attachment' needs a subquery, handled separately.
    Returns (clauses, flat_params).
    """
    clauses: list[str] = []
    params: list[Any] = []
    has_attachment = False

    if not query:
        return clauses, params

    tokens = query.strip().split()
    for token in tokens:
        token_lower = token.lower()

        if token_lower == "in:inbox":
            clauses.append("label_ids LIKE '%\"INBOX\"%'")
        elif token_lower == "in:trash":
            clauses.append("label_ids LIKE '%\"TRASH\"%'")
        elif token_lower == "in:sent":
            clauses.append("label_ids LIKE '%\"SENT\"%'")
        elif token_lower == "in:drafts":
            clauses.append("label_ids LIKE '%\"DRAFT\"%'")
        elif token_lower == "is:unread":
            clauses.append("label_ids LIKE '%\"UNREAD\"%'")
        elif token_lower == "is:read":
            clauses.append("label_ids NOT LIKE '%\"UNREAD\"%'")
        elif token_lower == "has:attachment":
            clauses.append("id IN (SELECT DISTINCT message_id FROM attachments)")
        elif token_lower.startswith("label:"):
            label_val = token[6:]
            clauses.append(f'label_ids LIKE ?')
            params.append(f'%"{label_val}"%')
        elif token_lower.startswith("newer_than:"):
            m = re.match(r"newer_than:(\d+)d", token, re.IGNORECASE)
            if m:
                days = int(m.group(1))
                cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
                clauses.append("internal_date >= ?")
                params.append(cutoff)
        elif token_lower.startswith("from:"):
            addr = token[5:]
            clauses.append("sender LIKE ?")
            params.append(f"%{addr}%")
        # Ignore unknown tokens (matches Gmail behaviour)

    return clauses, params


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def GMAIL_FETCH_EMAILS(
    max_results: int = 50,
    query: str = "",
    fetch_full_message: bool = False,
    next_page_token: str = "",
) -> dict:
    """Fetch emails from the mock Gmail inbox, supporting Gmail query syntax."""
    clauses, params = _parse_query(query)

    where_sql = ""
    if clauses:
        where_sql = "WHERE " + " AND ".join(clauses)

    sql = f"SELECT * FROM messages {where_sql} ORDER BY internal_date DESC LIMIT ?"
    params.append(max_results)

    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        total = conn.execute(f"SELECT COUNT(*) FROM messages {where_sql}", params[:-1]).fetchone()[0]

        messages = []
        for row in rows:
            atts = _get_attachments_for_message(conn, row["id"])
            messages.append(_row_to_message(row, atts, fetch_full=fetch_full_message))

    return {
        "messages": messages,
        "nextPageToken": None,
        "resultSizeEstimate": total,
    }


@mcp.tool()
def GMAIL_CREATE_EMAIL_DRAFT(
    recipient_email: str,
    subject: str = "",
    body: str = "",
    cc: list[str] = [],
    bcc: list[str] = [],
) -> dict:
    """Create a new email draft."""
    if not recipient_email:
        raise ValueError(
            "Invalid request data provided - Following fields are missing: {'recipient_email'}"
        )

    draft_id = _random_draft_id()
    message_id = _random_message_id()
    now = _now_iso()

    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO drafts (id, message_id, recipient, cc, subject, body, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (draft_id, message_id, recipient_email, json.dumps(cc), subject, body, now),
        )

    url = f"mock://drafts/{draft_id}"
    return {
        "id": draft_id,
        "message": {
            "id": message_id,
            "threadId": message_id,
            "labelIds": ["DRAFT"],
            "display_url": url,
        },
        "display_url": url,
    }


@mcp.tool()
def GMAIL_DELETE_DRAFT(draft_id: str) -> dict:
    """Delete a draft by ID."""
    if not draft_id:
        raise ValueError(
            "Invalid request data provided - Following fields are missing: {'draft_id'}"
        )
    with get_conn() as conn:
        row = conn.execute("SELECT id FROM drafts WHERE id = ?", (draft_id,)).fetchone()
        if row is None:
            raise ValueError(f"Draft with ID '{draft_id}' not found.")
        conn.execute("DELETE FROM drafts WHERE id = ?", (draft_id,))
    return {"success": True}


@mcp.tool()
def GMAIL_LIST_DRAFTS(
    max_results: int = 50,
    verbose: bool = False,
    page_token: str = "",
) -> dict:
    """List email drafts."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM drafts ORDER BY created_at DESC LIMIT ?", (max_results,)
        ).fetchall()

        drafts = []
        for row in rows:
            if not verbose:
                drafts.append({
                    "id": row["id"],
                    "message": {
                        "id": row["message_id"],
                        "threadId": row["message_id"],
                    },
                })
            else:
                # Verbose: construct a full message-like shape from draft fields
                body = row["body"] or ""
                cc_list = json.loads(row["cc"]) if row["cc"] else []
                msg: dict[str, Any] = {
                    "messageId": row["message_id"],
                    "threadId": row["message_id"],
                    "labelIds": ["DRAFT"],
                    "sender": "me",
                    "to": row["recipient"] or "",
                    "subject": row["subject"] or "",
                    "messageTimestamp": row["created_at"] or "",
                    "messageText": body,
                    "preview": {"body": body[:200], "subject": row["subject"] or ""},
                    "display_url": f"mock://drafts/{row['id']}",
                    "attachmentList": [],
                }
                drafts.append({"id": row["id"], "message": msg})

    return {
        "drafts": drafts,
        "next_page_token": None,
        "display_url": "mock://drafts",
    }


@mcp.tool()
def GMAIL_SEND_EMAIL(
    recipient_email: str = "",
    subject: str = "",
    body: str = "",
    cc: list[str] = [],
    bcc: list[str] = [],
) -> dict:
    """Send an email (inserts a SENT message into the DB)."""
    if not recipient_email and not cc and not bcc:
        raise ValueError(
            "Invalid request data provided - Following fields are missing: {'recipient_email'}"
        )

    message_id = _random_message_id()
    now = _now_iso()
    label_ids = json.dumps(["SENT"])
    to_addr = recipient_email or (cc[0] if cc else bcc[0])

    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO messages
                (id, thread_id, label_ids, sender, recipient, subject,
                 body_plain, body_html, internal_date, snippet)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message_id,
                message_id,
                label_ids,
                "me",
                to_addr,
                subject,
                body,
                None,
                now,
                body[:100],
            ),
        )

    return {
        "id": message_id,
        "threadId": message_id,
        "labelIds": ["SENT"],
        "display_url": f"mock://sent/{message_id}",
    }


@mcp.tool()
def GMAIL_REPLY_TO_THREAD(
    thread_id: str,
    message_body: str = "",
    recipient_email: str = "",
    subject: str = "",
) -> dict:
    """Reply to an existing email thread."""
    if not thread_id:
        raise ValueError(
            "Invalid request data provided - Following fields are missing: {'thread_id'}"
        )
    if not _is_hex(thread_id, min_len=15, max_len=16):
        raise ValueError("Invalid id value")

    message_id = _random_message_id()
    now = _now_iso()
    label_ids = json.dumps(["UNREAD", "SENT", "INBOX"])

    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO messages
                (id, thread_id, label_ids, sender, recipient, subject,
                 body_plain, body_html, internal_date, snippet)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message_id,
                thread_id,
                label_ids,
                "me",
                recipient_email,
                subject,
                message_body,
                None,
                now,
                message_body[:100],
            ),
        )

    return {
        "id": message_id,
        "threadId": thread_id,
        "labelIds": ["UNREAD", "SENT", "INBOX"],
        "display_url": f"mock://all/{message_id}",
    }


@mcp.tool()
def GMAIL_ADD_LABEL_TO_EMAIL(
    message_id: str,
    add_label_ids: list[str] = [],
    remove_label_ids: list[str] = [],
) -> dict:
    """Add or remove labels on an email."""
    if not message_id:
        raise ValueError(
            "Invalid request data provided - Following fields are missing: {'message_id'}"
        )
    if not _is_hex(message_id, min_len=15, max_len=16):
        raise ValueError(f"Invalid message_id '{message_id}': must be 15-16 hex characters")
    if not add_label_ids and not remove_label_ids:
        raise ValueError(
            "Invalid request data provided - Following fields are missing: {'add_label_ids or remove_label_ids'}"
        )

    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, thread_id, label_ids FROM messages WHERE id = ?", (message_id,)
        ).fetchone()
        if row is None:
            # Return empty-ish response; message not found is not a hard error per spec
            raise ValueError(f"Message '{message_id}' not found.")

        current = json.loads(row["label_ids"]) if row["label_ids"] else []
        label_set = set(current)
        for lbl in remove_label_ids:
            label_set.discard(lbl)
        for lbl in add_label_ids:
            label_set.add(lbl)
        updated = list(label_set)

        conn.execute(
            "UPDATE messages SET label_ids = ? WHERE id = ?",
            (json.dumps(updated), message_id),
        )

    return {
        "id": message_id,
        "threadId": row["thread_id"],
        "labelIds": updated,
        "display_url": f"mock://inbox/{message_id}",
    }


@mcp.tool()
def GMAIL_MOVE_THREAD_TO_TRASH(thread_id: str) -> dict:
    """Move all messages in a thread to Trash."""
    if not thread_id:
        raise ValueError(
            "Invalid request data provided - Following fields are missing: {'thread_id'}"
        )
    if not re.fullmatch(r"[0-9a-fA-F]+", thread_id):
        raise ValueError(f"Invalid thread_id '{thread_id}': must be hex characters")

    remove_labels = {"INBOX", "UNREAD", "IMPORTANT"}

    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, label_ids FROM messages WHERE thread_id = ?", (thread_id,)
        ).fetchall()

        updated_messages = []
        for row in rows:
            current = json.loads(row["label_ids"]) if row["label_ids"] else []
            label_set = set(current) - remove_labels
            label_set.add("TRASH")
            updated = list(label_set)
            conn.execute(
                "UPDATE messages SET label_ids = ? WHERE id = ?",
                (json.dumps(updated), row["id"]),
            )
            updated_messages.append({
                "id": row["id"],
                "labelIds": updated,
                "threadId": thread_id,
            })

    return {
        "id": thread_id,
        "messages": updated_messages,
        "display_url": f"mock://trash/{thread_id}",
    }


@mcp.tool()
def GMAIL_LIST_LABELS() -> dict:
    """List all Gmail labels."""
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM labels").fetchall()

    labels = [
        {
            "id": r["id"],
            "name": r["name"],
            "type": r["type"],
            "labelListVisibility": r["label_list_visibility"],
            "messageListVisibility": r["message_list_visibility"],
        }
        for r in rows
    ]
    return {"labels": labels, "display_url": "mock://labels"}


@mcp.tool()
def GMAIL_GET_ATTACHMENT(
    message_id: str,
    attachment_id: str,
    file_name: str,
) -> dict:
    """Retrieve an attachment by ID and return base64-encoded data."""
    if not message_id:
        raise ValueError(
            "Invalid request data provided - Following fields are missing: {'message_id'}"
        )
    if not attachment_id:
        raise ValueError(
            "Invalid request data provided - Following fields are missing: {'attachment_id'}"
        )
    if not file_name:
        raise ValueError(
            "Invalid request data provided - Following fields are missing: {'file_name'}"
        )

    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM attachments WHERE id = ? AND message_id = ?",
            (attachment_id, message_id),
        ).fetchone()

    if row is None:
        raise ValueError(
            f"Attachment '{attachment_id}' not found for message '{message_id}'."
        )

    data_b64 = base64.b64encode(row["data"]).decode() if row["data"] else ""

    return {
        "file": {
            "name": row["filename"],
            "mimetype": row["mime_type"],
            "s3url": f"mock://attachments/{attachment_id}",
        },
        "data": data_b64,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"Starting mock Gmail MCP server (DB: {DB_PATH})")
    mcp.run()
