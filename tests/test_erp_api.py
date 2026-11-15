"""The mock ERP's API, run in-process with FastAPI's TestClient against the
seeded local database. Every write is checked against what actually landed in the database."""

import pytest
from fastapi.testclient import TestClient

from conftest import entries_for
from ledger_desk.approval import sign

KEY = {"X-API-Key": "test-api-key"}


def lines_for(amount: str):
    return [{"account": "1210", "debit": amount, "credit": "0"}, {"account": "2000", "debit": "0", "credit": amount}]


def entry(keys, ref, amount="2100.00", approver="clerk", signed_amount=None):
    lines = lines_for(amount)
    signature = sign(keys.private, ref, approver, lines_for(signed_amount or amount))
    return {"invoice_ref": ref, "lines": lines, "approval": {"approver": approver, "signature": signature}}


@pytest.fixture
def http(app):
    return TestClient(app)


def post(http, body, key="idem-" + "x", headers=KEY):
    return http.post("/journal-entries", json=body, headers={**headers, "Idempotency-Key": key})


def test_a_wrong_or_missing_api_key_is_401(http):
    assert http.get("/accounts").status_code == 401
    assert http.get("/accounts", headers={"X-API-Key": "nope"}).status_code == 401


def test_vendor_lookup_by_tax_id_includes_the_bank_on_file(http):
    r = http.get("/vendors", params={"tax_id": "00-0000003"}, headers=KEY)
    assert r.status_code == 200
    [vendor] = r.json()
    assert (vendor["name"], vendor["account_last4"]) == ("Packaging Supplier", "3003")


def test_money_comes_back_as_strings_never_floats(http):
    po = http.get("/purchase-orders/PO-1124", headers=KEY).json()
    assert po["lines"][0]["unit_price"] == "0.3800"
    receipts = http.get("/purchase-orders/PO-1124/receipts", headers=KEY).json()
    assert receipts == [{"line": 1, "quantity": "5000.000", "date": "2026-11-06"}]


def test_bills_are_paged(http):
    first = http.get("/bills", params={"vendor_id": "V06", "limit": 4}, headers=KEY).json()
    assert len(first["items"]) == 4 and first["next_offset"] == 4
    second = http.get("/bills", params={"vendor_id": "V06", "limit": 4, "offset": 4}, headers=KEY).json()
    assert len(second["items"]) == 2 and second["next_offset"] is None


def test_posting_without_a_signature_is_403_and_stores_nothing(http, erp_db, keys, ref):
    body = entry(keys, ref)
    del body["approval"]
    assert post(http, body, key=ref).status_code == 403
    assert entries_for(erp_db, ref) == 0


def test_a_signature_for_1900_used_on_a_2100_entry_is_403(http, erp_db, keys, ref):
    r = post(http, entry(keys, ref, amount="2100.00", signed_amount="1900.00"), key=ref)
    assert r.status_code == 403
    assert entries_for(erp_db, ref) == 0


def test_a_different_approver_than_the_one_who_signed_is_403(http, keys, ref):
    body = entry(keys, ref)
    body["approval"]["approver"] = "controller"
    assert post(http, body, key=ref).status_code == 403


def test_a_signed_entry_posts_and_reads_back(http, erp_db, keys, ref):
    r = post(http, entry(keys, ref), key=ref)
    assert r.status_code == 201
    got = http.get(f"/journal-entries/{r.json()['id']}", headers=KEY).json()
    assert got["invoice_ref"] == ref
    assert got["lines"] == [{"account": "1210", "debit": "2100.00", "credit": "0.00"}, {"account": "2000", "debit": "0.00", "credit": "2100.00"}]
    assert entries_for(erp_db, ref) == 1


def test_the_same_idempotency_key_twice_makes_one_entry(http, erp_db, keys, ref):
    body = entry(keys, ref)
    first = post(http, body, key=ref)
    second = post(http, body, key=ref)
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["id"] == second.json()["id"]
    assert entries_for(erp_db, ref) == 1


def test_the_same_idempotency_key_with_a_different_body_is_409(http, keys, ref):
    assert post(http, entry(keys, ref), key=ref).status_code == 201
    assert post(http, entry(keys, ref, amount="900.00"), key=ref).status_code == 409


def test_an_unbalanced_entry_is_422_and_stores_nothing(http, erp_db, keys, ref):
    lines = [{"account": "1210", "debit": "2100.00", "credit": "0"}, {"account": "2000", "debit": "0", "credit": "1900.00"}]
    body = {"invoice_ref": ref, "lines": lines, "approval": {"approver": "clerk", "signature": sign(keys.private, ref, "clerk", lines)}}
    assert post(http, body, key=ref).status_code == 422
    assert entries_for(erp_db, ref) == 0


def test_posting_without_an_idempotency_key_is_400(http, keys, ref):
    assert http.post("/journal-entries", json=entry(keys, ref), headers=KEY).status_code == 400
