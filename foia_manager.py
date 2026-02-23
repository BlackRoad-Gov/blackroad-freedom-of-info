#!/usr/bin/env python3
"""
BlackRoad FOIA Manager — Freedom of Information Act request management system
"""

import sqlite3
import json
import uuid
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import Optional, List
from enum import Enum
from pathlib import Path


DB_PATH = Path("foia_manager.db")
DEFAULT_RESPONSE_DAYS = 20  # Standard FOIA response window


class RequestStatus(str, Enum):
    SUBMITTED = "submitted"
    PROCESSING = "processing"
    FULFILLED = "fulfilled"
    DENIED = "denied"
    APPEALED = "appealed"
    CLOSED = "closed"


@dataclass
class Request:
    requester_name: str
    requester_email: str
    agency: str
    subject: str
    description: str
    fee_waived: bool = False
    status: RequestStatus = RequestStatus.SUBMITTED
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    submitted_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    due_at: str = field(default_factory=lambda: (datetime.utcnow() + timedelta(days=DEFAULT_RESPONSE_DAYS)).isoformat())
    fulfilled_at: Optional[str] = None
    assigned_to: Optional[str] = None
    tracking_number: str = field(default_factory=lambda: f"FOIA-{datetime.utcnow().year}-{uuid.uuid4().hex[:6].upper()}")


@dataclass
class FulfillmentPackage:
    request_id: str
    documents: List[str] = field(default_factory=list)
    redactions: List[str] = field(default_factory=list)
    exemptions_cited: List[str] = field(default_factory=list)
    response_letter: str = ""
    package_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    fulfilled_by: str = "system"


@dataclass
class Appeal:
    request_id: str
    grounds: str
    appellant: str
    appeal_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    submitted_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    status: str = "pending"
    decision: Optional[str] = None
    decided_at: Optional[str] = None


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Initialize the FOIA database."""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS requests (
            request_id      TEXT PRIMARY KEY,
            tracking_number TEXT UNIQUE NOT NULL,
            requester_name  TEXT NOT NULL,
            requester_email TEXT NOT NULL,
            agency          TEXT NOT NULL,
            subject         TEXT NOT NULL,
            description     TEXT NOT NULL,
            fee_waived      INTEGER DEFAULT 0,
            status          TEXT DEFAULT 'submitted',
            submitted_at    TEXT NOT NULL,
            due_at          TEXT NOT NULL,
            fulfilled_at    TEXT,
            assigned_to     TEXT
        );

        CREATE TABLE IF NOT EXISTS fulfillments (
            package_id      TEXT PRIMARY KEY,
            request_id      TEXT NOT NULL,
            documents       TEXT DEFAULT '[]',
            redactions      TEXT DEFAULT '[]',
            exemptions_cited TEXT DEFAULT '[]',
            response_letter TEXT DEFAULT '',
            created_at      TEXT NOT NULL,
            fulfilled_by    TEXT DEFAULT 'system',
            FOREIGN KEY (request_id) REFERENCES requests(request_id)
        );

        CREATE TABLE IF NOT EXISTS denials (
            denial_id       TEXT PRIMARY KEY,
            request_id      TEXT NOT NULL,
            reason          TEXT NOT NULL,
            exemptions      TEXT DEFAULT '[]',
            denied_by       TEXT NOT NULL,
            denied_at       TEXT NOT NULL,
            FOREIGN KEY (request_id) REFERENCES requests(request_id)
        );

        CREATE TABLE IF NOT EXISTS appeals (
            appeal_id       TEXT PRIMARY KEY,
            request_id      TEXT NOT NULL,
            grounds         TEXT NOT NULL,
            appellant       TEXT NOT NULL,
            submitted_at    TEXT NOT NULL,
            status          TEXT DEFAULT 'pending',
            decision        TEXT,
            decided_at      TEXT,
            FOREIGN KEY (request_id) REFERENCES requests(request_id)
        );

        CREATE TABLE IF NOT EXISTS notes (
            note_id         TEXT PRIMARY KEY,
            request_id      TEXT NOT NULL,
            author          TEXT NOT NULL,
            content         TEXT NOT NULL,
            created_at      TEXT NOT NULL,
            FOREIGN KEY (request_id) REFERENCES requests(request_id)
        );
    """)
    conn.commit()
    conn.close()


def submit_request(requester_name: str, requester_email: str, agency: str,
                   subject: str, description: str, fee_waived: bool = False) -> Request:
    """Submit a new FOIA request."""
    init_db()
    req = Request(
        requester_name=requester_name, requester_email=requester_email,
        agency=agency, subject=subject, description=description, fee_waived=fee_waived
    )
    conn = get_connection()
    conn.execute(
        "INSERT INTO requests VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (req.request_id, req.tracking_number, requester_name, requester_email,
         agency, subject, description, int(fee_waived),
         req.status.value, req.submitted_at, req.due_at, None, None)
    )
    conn.commit()
    conn.close()
    return req


def assign_to_officer(request_id: str, officer: str) -> bool:
    """Assign a FOIA request to a processing officer."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM requests WHERE request_id=?", (request_id,)).fetchone()
    if not row:
        conn.close()
        raise ValueError(f"Request {request_id} not found")
    conn.execute(
        "UPDATE requests SET assigned_to=?, status=? WHERE request_id=?",
        (officer, RequestStatus.PROCESSING.value, request_id)
    )
    conn.commit()
    conn.close()
    return True


def add_note(request_id: str, author: str, content: str) -> str:
    """Add an internal note to a request."""
    conn = get_connection()
    note_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO notes VALUES (?,?,?,?,?)",
        (note_id, request_id, author, content, datetime.utcnow().isoformat())
    )
    conn.commit()
    conn.close()
    return note_id


def fulfill_request(request_id: str, documents: List[str], exemptions: Optional[List[str]] = None,
                    redactions: Optional[List[str]] = None, response_letter: str = "",
                    fulfilled_by: str = "system") -> FulfillmentPackage:
    """Fulfill a FOIA request with documents."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM requests WHERE request_id=?", (request_id,)).fetchone()
    if not row:
        conn.close()
        raise ValueError(f"Request {request_id} not found")
    now = datetime.utcnow().isoformat()
    pkg = FulfillmentPackage(
        request_id=request_id,
        documents=documents,
        redactions=redactions or [],
        exemptions_cited=exemptions or [],
        response_letter=response_letter,
        fulfilled_by=fulfilled_by,
        created_at=now
    )
    conn.execute(
        "INSERT INTO fulfillments VALUES (?,?,?,?,?,?,?,?)",
        (pkg.package_id, request_id, json.dumps(documents),
         json.dumps(redactions or []), json.dumps(exemptions or []),
         response_letter, now, fulfilled_by)
    )
    conn.execute(
        "UPDATE requests SET status=?, fulfilled_at=? WHERE request_id=?",
        (RequestStatus.FULFILLED.value, now, request_id)
    )
    conn.commit()
    conn.close()
    return pkg


def deny_request(request_id: str, reason: str, exemptions: Optional[List[str]] = None,
                 denied_by: str = "system") -> bool:
    """Deny a FOIA request with reason."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM requests WHERE request_id=?", (request_id,)).fetchone()
    if not row:
        conn.close()
        raise ValueError(f"Request {request_id} not found")
    now = datetime.utcnow().isoformat()
    conn.execute(
        "INSERT INTO denials VALUES (?,?,?,?,?,?)",
        (str(uuid.uuid4()), request_id, reason, json.dumps(exemptions or []), denied_by, now)
    )
    conn.execute(
        "UPDATE requests SET status=? WHERE request_id=?",
        (RequestStatus.DENIED.value, request_id)
    )
    conn.commit()
    conn.close()
    return True


def appeal_request(request_id: str, appellant: str, grounds: str) -> Appeal:
    """File an appeal for a denied FOIA request."""
    conn = get_connection()
    row = conn.execute("SELECT status FROM requests WHERE request_id=?", (request_id,)).fetchone()
    if not row:
        conn.close()
        raise ValueError(f"Request {request_id} not found")
    if row["status"] != RequestStatus.DENIED.value:
        conn.close()
        raise ValueError(f"Only denied requests can be appealed")
    appeal = Appeal(request_id=request_id, grounds=grounds, appellant=appellant)
    conn.execute(
        "INSERT INTO appeals VALUES (?,?,?,?,?,?,?,?)",
        (appeal.appeal_id, request_id, grounds, appellant,
         appeal.submitted_at, appeal.status, None, None)
    )
    conn.execute(
        "UPDATE requests SET status=? WHERE request_id=?",
        (RequestStatus.APPEALED.value, request_id)
    )
    conn.commit()
    conn.close()
    return appeal


def decide_appeal(appeal_id: str, decision: str, decided_by: str) -> bool:
    """Make a decision on an appeal."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM appeals WHERE appeal_id=?", (appeal_id,)).fetchone()
    if not row:
        conn.close()
        raise ValueError(f"Appeal {appeal_id} not found")
    now = datetime.utcnow().isoformat()
    conn.execute(
        "UPDATE appeals SET status=?, decision=?, decided_at=? WHERE appeal_id=?",
        (decision, decision, now, appeal_id)
    )
    if decision == "granted":
        conn.execute(
            "UPDATE requests SET status=? WHERE request_id=?",
            (RequestStatus.PROCESSING.value, row["request_id"])
        )
    conn.commit()
    conn.close()
    return True


def overdue_check() -> List[dict]:
    """Find all overdue FOIA requests."""
    now = datetime.utcnow().isoformat()
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM requests
           WHERE due_at < ? AND status NOT IN ('fulfilled','denied','closed')
           ORDER BY due_at ASC""",
        (now,)
    ).fetchall()
    conn.close()
    overdue = []
    for r in rows:
        d = dict(r)
        due = datetime.fromisoformat(r["due_at"])
        now_dt = datetime.utcnow()
        d["days_overdue"] = (now_dt - due).days
        overdue.append(d)
    return overdue


def get_request_details(request_id: str) -> dict:
    """Get full details of a FOIA request."""
    conn = get_connection()
    req = conn.execute("SELECT * FROM requests WHERE request_id=?", (request_id,)).fetchone()
    if not req:
        conn.close()
        raise ValueError(f"Request {request_id} not found")
    fulfillment = conn.execute(
        "SELECT * FROM fulfillments WHERE request_id=?", (request_id,)
    ).fetchone()
    denial = conn.execute(
        "SELECT * FROM denials WHERE request_id=?", (request_id,)
    ).fetchone()
    appeals = conn.execute(
        "SELECT * FROM appeals WHERE request_id=? ORDER BY submitted_at", (request_id,)
    ).fetchall()
    notes = conn.execute(
        "SELECT * FROM notes WHERE request_id=? ORDER BY created_at", (request_id,)
    ).fetchall()
    conn.close()

    result = dict(req)
    if fulfillment:
        f = dict(fulfillment)
        f["documents"] = json.loads(f["documents"])
        f["redactions"] = json.loads(f["redactions"])
        f["exemptions_cited"] = json.loads(f["exemptions_cited"])
        result["fulfillment"] = f
    if denial:
        d = dict(denial)
        d["exemptions"] = json.loads(d["exemptions"])
        result["denial"] = d
    result["appeals"] = [dict(a) for a in appeals]
    result["notes"] = [dict(n) for n in notes]
    return result


def list_requests(status: Optional[str] = None, agency: Optional[str] = None) -> List[dict]:
    """List FOIA requests with optional filters."""
    conn = get_connection()
    query = "SELECT * FROM requests WHERE 1=1"
    params = []
    if status:
        query += " AND status=?"
        params.append(status)
    if agency:
        query += " AND agency=?"
        params.append(agency)
    rows = conn.execute(query + " ORDER BY submitted_at DESC", params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def agency_stats(agency: Optional[str] = None) -> dict:
    """Statistics for FOIA requests by agency."""
    conn = get_connection()
    query_filter = "WHERE agency=?" if agency else ""
    params = [agency] if agency else []
    total = conn.execute(f"SELECT COUNT(*) FROM requests {query_filter}", params).fetchone()[0]
    by_status = {}
    for s in RequestStatus:
        cnt = conn.execute(
            f"SELECT COUNT(*) FROM requests {query_filter}{' AND' if agency else ' WHERE'} status=?",
            params + [s.value]
        ).fetchone()[0]
        by_status[s.value] = cnt
    overdue = len(overdue_check()) if not agency else len([r for r in overdue_check() if r.get("agency") == agency])
    conn.close()
    return {
        "agency": agency or "all",
        "total_requests": total,
        "by_status": by_status,
        "overdue": overdue,
        "fulfillment_rate": round(by_status.get("fulfilled", 0) / total * 100, 2) if total else 0.0,
        "denial_rate": round(by_status.get("denied", 0) / total * 100, 2) if total else 0.0,
    }


def generate_request_report(request_id: str) -> str:
    """Generate a printable FOIA request report."""
    details = get_request_details(request_id)
    due = datetime.fromisoformat(details["due_at"])
    now = datetime.utcnow()
    overdue_str = f" (OVERDUE by {(now-due).days} days)" if now > due and details["status"] not in ("fulfilled","denied","closed") else ""

    lines = [
        "=" * 65,
        "FOIA REQUEST REPORT",
        "=" * 65,
        f"Tracking #    : {details['tracking_number']}",
        f"Request ID    : {details['request_id']}",
        f"Requester     : {details['requester_name']} <{details['requester_email']}>",
        f"Agency        : {details['agency']}",
        f"Subject       : {details['subject']}",
        f"Status        : {details['status'].upper()}",
        f"Submitted     : {details['submitted_at'][:10]}",
        f"Due Date      : {details['due_at'][:10]}{overdue_str}",
        f"Assigned To   : {details.get('assigned_to') or 'Unassigned'}",
        f"Fee Waived    : {'Yes' if details['fee_waived'] else 'No'}",
        "",
        "DESCRIPTION",
        "-" * 40,
        details["description"],
        "",
    ]
    if "fulfillment" in details:
        f = details["fulfillment"]
        lines += [
            "FULFILLMENT",
            "-" * 40,
            f"  Documents : {', '.join(f['documents']) or 'None'}",
            f"  Redactions: {len(f['redactions'])} items",
            f"  Exemptions: {', '.join(f['exemptions_cited']) or 'None'}",
        ]
    if "denial" in details:
        d = details["denial"]
        lines += [
            "DENIAL",
            "-" * 40,
            f"  Reason    : {d['reason']}",
            f"  Exemptions: {', '.join(d['exemptions']) or 'None'}",
        ]
    if details["appeals"]:
        lines += ["", f"APPEALS ({len(details['appeals'])}):", "-" * 40]
        for a in details["appeals"]:
            lines.append(f"  [{a['status'].upper()}] {a['grounds'][:80]}")
    if details["notes"]:
        lines += ["", f"INTERNAL NOTES ({len(details['notes'])})", "-" * 40]
        for n in details["notes"][-3:]:
            lines.append(f"  {n['created_at'][:10]} [{n['author']}]: {n['content'][:100]}")
    lines.append("=" * 65)
    return "\n".join(lines)


def cli():
    import sys
    if len(sys.argv) < 2:
        print("Usage: python foia_manager.py <command>")
        print("Commands: submit, list, stats, overdue, report, details")
        return
    init_db()
    cmd = sys.argv[1]
    if cmd == "stats":
        print(json.dumps(agency_stats(), indent=2))
    elif cmd == "list":
        for r in list_requests():
            print(f"[{r['status'].upper()}] {r['tracking_number']} — {r['agency']} — {r['subject'][:50]}")
    elif cmd == "overdue":
        overdue = overdue_check()
        if not overdue:
            print("No overdue requests.")
        for r in overdue:
            print(f"  OVERDUE {r['days_overdue']}d: {r['tracking_number']} — {r['agency']}")
    elif cmd == "report" and len(sys.argv) >= 3:
        print(generate_request_report(sys.argv[2]))
    else:
        print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    cli()
