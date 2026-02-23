"""Tests for foia_manager.py"""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import foia_manager as fm
fm.DB_PATH = Path("/tmp/test_foia_manager.db")


@pytest.fixture(autouse=True)
def clean_db():
    if fm.DB_PATH.exists():
        fm.DB_PATH.unlink()
    fm.init_db()
    yield
    if fm.DB_PATH.exists():
        fm.DB_PATH.unlink()


def make_request(**kwargs):
    defaults = dict(
        requester_name="John Doe", requester_email="john@example.com",
        agency="EPA", subject="Air Quality Reports", description="Request for annual air quality data."
    )
    defaults.update(kwargs)
    return fm.submit_request(**defaults)


def test_submit_request():
    req = make_request()
    assert req.requester_name == "John Doe"
    assert req.status == fm.RequestStatus.SUBMITTED
    assert req.tracking_number.startswith("FOIA-")


def test_assign_officer():
    req = make_request()
    result = fm.assign_to_officer(req.request_id, "Officer Davis")
    assert result is True
    details = fm.get_request_details(req.request_id)
    assert details["assigned_to"] == "Officer Davis"
    assert details["status"] == fm.RequestStatus.PROCESSING.value


def test_fulfill_request():
    req = make_request()
    pkg = fm.fulfill_request(
        req.request_id,
        documents=["doc1.pdf", "doc2.pdf"],
        exemptions=["Exemption 6"],
        fulfilled_by="Officer Smith"
    )
    assert pkg.request_id == req.request_id
    assert "doc1.pdf" in pkg.documents
    details = fm.get_request_details(req.request_id)
    assert details["status"] == fm.RequestStatus.FULFILLED.value


def test_deny_request():
    req = make_request()
    result = fm.deny_request(req.request_id, "Classified information", ["Exemption 1"], "Director")
    assert result is True
    details = fm.get_request_details(req.request_id)
    assert details["status"] == fm.RequestStatus.DENIED.value


def test_appeal_denied():
    req = make_request()
    fm.deny_request(req.request_id, "Too broad", denied_by="Officer")
    appeal = fm.appeal_request(req.request_id, req.requester_name, "The request is specific enough.")
    assert appeal.request_id == req.request_id
    assert appeal.status == "pending"
    details = fm.get_request_details(req.request_id)
    assert details["status"] == fm.RequestStatus.APPEALED.value


def test_appeal_only_denied():
    req = make_request()
    with pytest.raises(ValueError, match="denied"):
        fm.appeal_request(req.request_id, "John", "No reason")


def test_overdue_check():
    from datetime import timedelta
    req = make_request()
    conn = fm.get_connection()
    past = (__import__("datetime").datetime.utcnow() - timedelta(days=30)).isoformat()
    conn.execute("UPDATE requests SET due_at=? WHERE request_id=?", (past, req.request_id))
    conn.commit()
    conn.close()
    overdue = fm.overdue_check()
    assert len(overdue) >= 1
    assert any(r["request_id"] == req.request_id for r in overdue)


def test_add_note():
    req = make_request()
    note_id = fm.add_note(req.request_id, "Officer A", "Contacted requester for clarification.")
    assert note_id is not None
    details = fm.get_request_details(req.request_id)
    assert len(details["notes"]) == 1


def test_agency_stats():
    make_request(agency="DOJ")
    make_request(agency="DOJ", requester_email="jane@example.com")
    stats = fm.agency_stats("DOJ")
    assert stats["total_requests"] >= 2


def test_generate_report():
    req = make_request()
    report = fm.generate_request_report(req.request_id)
    assert "FOIA REQUEST REPORT" in report
    assert req.tracking_number in report
    assert "EPA" in report
