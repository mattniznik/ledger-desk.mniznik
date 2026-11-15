"""The ERP client's retries, against the real app with its "break the ERP" switches.

The case that matters most is a response lost after the entry was committed: the ERP wrote it,
the client never heard back, and it retries. Without idempotency that is a double posting, the
way double payments happen. The retry carries the same Idempotency-Key, so the ERP returns the
entry it already has.
"""

import pytest
from fastapi.testclient import TestClient

from conftest import entries_for
from ledger_desk.approval import sign
from ledger_desk.erp.client import ApprovalRejected, ErpClient, ErpUnavailable


def body(keys, ref, amount="2100.00"):
    lines = [{"account": "1210", "debit": amount, "credit": "0"}, {"account": "2000", "debit": "0", "credit": amount}]
    return {"invoice_ref": ref, "lines": lines, "approval": {"approver": "clerk", "signature": sign(keys.private, ref, "clerk", lines)}}


@pytest.fixture
def waits():
    return []


@pytest.fixture
def client(app, waits):
    return ErpClient(TestClient(app), api_key="test-api-key", sleep=waits.append, max_attempts=4, base_delay=0.5)


def switch(app, **counts):
    TestClient(app).post("/admin/switches", json=counts, headers={"X-API-Key": "test-api-key"}).raise_for_status()


def test_503_before_writing_then_success_makes_one_entry(app, client, erp_db, keys, ref, waits):
    switch(app, fail_before=1)
    result = client.post_journal_entry(body(keys, ref), idempotency_key=ref)
    assert result["attempts"] == 2
    assert waits == [0.5]
    assert entries_for(erp_db, ref) == 1


def test_a_response_lost_after_commit_is_retried_into_the_same_single_entry(app, client, erp_db, keys, ref):
    switch(app, fail_after_commit=1)
    result = client.post_journal_entry(body(keys, ref), idempotency_key=ref)
    assert result["attempts"] == 2 and result["replayed"] is True
    assert entries_for(erp_db, ref) == 1


def test_a_429_waits_for_retry_after(app, client, erp_db, keys, ref, waits):
    switch(app, rate_limit=1, retry_after=2)
    client.post_journal_entry(body(keys, ref), idempotency_key=ref)
    assert waits == [2.0]
    assert entries_for(erp_db, ref) == 1


def test_a_403_is_not_retried(client, erp_db, keys, ref, waits):
    bad = body(keys, ref)
    bad["approval"]["approver"] = "controller"
    with pytest.raises(ApprovalRejected):
        client.post_journal_entry(bad, idempotency_key=ref)
    assert waits == []
    assert entries_for(erp_db, ref) == 0


def test_a_503_that_never_ends_gives_up_without_posting(app, client, erp_db, keys, ref, waits):
    switch(app, fail_before=99)
    with pytest.raises(ErpUnavailable, match="4 attempts"):
        client.post_journal_entry(body(keys, ref), idempotency_key=ref)
    assert waits == [0.5, 1.0, 2.0]
    assert entries_for(erp_db, ref) == 0


def test_reads_go_through_the_client_too(client):
    vendor = client.find_vendors(tax_id="00-0000005")[0]
    assert vendor["account_last4"] == "4417"
    assert [r["quantity"] for r in client.receipts("PO-1130")] == ["100.000"]
