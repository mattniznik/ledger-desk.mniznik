"""The QuickBooks Online connection and the client that mirrors approved bills (docs/decisions/0006).

Against a fake QuickBooks on httpx.MockTransport that holds the rules from Intuit's docs (read
2026-11-14 in the browser): token requests use Basic auth over client id and secret; every token
response carries a new refresh token and the old one stops working ("Always store the latest
refresh_token value from the most recent API server response"); queries escape an apostrophe with
a backslash; DocNumber is at most 21 characters; VendorRef cannot be filtered on a VendorCredit, so
documents are found by DocNumber and the vendor checked in code. No real QuickBooks is called here.
"""

import base64
import re
import threading
import urllib.parse
from datetime import date

import httpx
import pytest

from ledger_desk.quickbooks import (
    CLIENT_ID,
    CLIENT_SECRET,
    REALM_ID,
    REFRESH_TOKEN,
    SCOPE,
    TOKEN_URL,
    EnvFile,
    QuickBooks,
    QuickBooksError,
    Tokens,
    authorize_url,
    finish_connect,
    mirror_bill,
    wait_for_callback,
)

REALM = "9130000000000001"
SECRET = "csecret-do-not-print"


class FakeQuickBooks:
    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.refresh = "refresh-0"
        self.access: str | None = None
        self.issued = 0
        self.vendors: dict[str, str] = {"56": "Sample Vendor Already There"}
        self.accounts: dict[str, dict] = {}
        self.docs: list[dict] = []
        self.next_id = 100
        self.queries: list[str] = []
        self.fail_create: int | None = None
        self.inactive: set[str] = set()  # ids of vendors and accounts made inactive ("deleted" in the UI)
        self.doc_gate: threading.Barrier | None = None  # lets two threads reach the document lookup together

    def _id(self) -> str:
        self.next_id += 1
        return str(self.next_id)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if str(request.url) == TOKEN_URL:
            return self._token(request)
        if request.headers.get("authorization") != f"Bearer {self.access}":
            return httpx.Response(401, json={"Fault": {"Error": [{"Message": "message=AuthenticationFailed", "code": "3200"}], "type": "AUTHENTICATION"}})
        assert request.url.params.get("minorversion") == "75"
        path = request.url.path
        prefix = f"/v3/company/{REALM}/"
        assert path.startswith(prefix), path
        what = path[len(prefix):]
        if what == "query":
            return self._query(request.url.params["query"])
        if what == f"companyinfo/{REALM}":
            return httpx.Response(200, json={"CompanyInfo": {"CompanyName": "Sandbox Company US 0000", "Id": REALM}})
        body = httpx.Response(200, content=request.content).json()
        if self.fail_create:
            return httpx.Response(self.fail_create, json={"Fault": {"Error": [{"Message": "A business validation error has occurred", "Detail": "made to fail", "code": "6000"}], "type": "ValidationFault"}})
        if what == "vendor":
            if body["DisplayName"] in self.vendors.values():  # unique, inactive ones included (Vendor docs)
                return httpx.Response(400, json={"Fault": {"Error": [{"Message": "Duplicate Name Exists Error", "code": "6240"}], "type": "ValidationFault"}})
            vid = self._id()
            self.vendors[vid] = body["DisplayName"]
            return httpx.Response(200, json={"Vendor": {"Id": vid, "DisplayName": body["DisplayName"]}})
        if what == "account":
            if body.get("AccountType") == "Fixed Asset" and not body.get("AccountSubType"):
                # measured on the real sandbox 2026-11-14 (n=2): a Fixed Asset with no sub-type is refused
                return httpx.Response(400, json={"Fault": {"Error": [{"Message": "A business validation error has occurred while processing your request", "Detail": "Business Validation Error: Invalid input field, unable to parse - please check the input and try again.", "code": "6000"}], "type": "ValidationFault"}})
            if any(a["Name"] == body["Name"] for a in self.accounts.values()):  # "Name must be unique"
                return httpx.Response(400, json={"Fault": {"Error": [{"Message": "Duplicate Name Exists Error", "code": "6240"}], "type": "ValidationFault"}})
            aid = self._id()
            self.accounts[aid] = body
            return httpx.Response(200, json={"Account": {"Id": aid, **body}})
        if what in ("bill", "vendorcredit"):
            entity = "Bill" if what == "bill" else "VendorCredit"
            if len(body.get("DocNumber", "")) > 21:
                return httpx.Response(400, json={"Fault": {"Error": [{"Message": "String length is either shorter or longer than supported", "code": "6200"}], "type": "ValidationFault"}})
            doc = {"entity": entity, "Id": self._id(), "TotalAmt": sum(line["Amount"] for line in body["Line"]), **body}
            self.docs.append(doc)
            return httpx.Response(200, json={entity: doc})
        return httpx.Response(404, json={"Fault": {"Error": [{"Message": f"no {what}"}]}})

    def _token(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["content-type"] == "application/x-www-form-urlencoded"
        if request.headers.get("authorization") != "Basic " + base64.b64encode(f"cid:{SECRET}".encode()).decode():
            return httpx.Response(401, json={"error": "invalid_client"})
        form = dict(urllib.parse.parse_qsl(request.content.decode()))
        if form["grant_type"] == "authorization_code":
            if form.get("code") != "good-code" or form.get("redirect_uri") != "http://localhost:8765/callback":
                return httpx.Response(400, json={"error": "invalid_grant"})
        elif form["grant_type"] == "refresh_token":
            if form.get("refresh_token") != self.refresh:
                return httpx.Response(400, json={"error": "invalid_grant"})
        else:
            return httpx.Response(400, json={"error": "unsupported_grant_type"})
        self.issued += 1
        self.access, self.refresh = f"access-{self.issued}", f"refresh-{self.issued}"
        return httpx.Response(200, json={"token_type": "bearer", "access_token": self.access, "expires_in": 3600, "refresh_token": self.refresh, "x_refresh_token_expires_in": 8640000})

    def _query(self, sql: str) -> httpx.Response:
        self.queries.append(sql)
        m = re.fullmatch(r"select \* from (\w+) where (\w+) = '((?:\\'|[^'])*)'( AND Active IN \(true, false\))?", sql)
        assert m, f"unexpected query: {sql}"
        entity, field, value, both = m.group(1), m.group(2), m.group(3).replace("\\'", "'"), bool(m.group(4))

        def shown(i):  # a plain query returns active list entities only (data-queries docs)
            return both or i not in self.inactive

        if entity == "Vendor":
            found = [{"Id": i, "DisplayName": n, "Active": i not in self.inactive} for i, n in self.vendors.items() if field == "DisplayName" and n == value and shown(i)]
        elif entity == "Account":
            found = [{"Id": i, **a, "Active": i not in self.inactive} for i, a in self.accounts.items() if a.get(field) == value and shown(i)]
        else:
            if self.doc_gate:
                try:
                    self.doc_gate.wait()
                except threading.BrokenBarrierError:
                    pass
            found = [d for d in self.docs if d["entity"] == entity and d.get(field) == value]
        return httpx.Response(200, json={"QueryResponse": {entity: found} if found else {}, "time": "2026-11-14T12:00:00Z"})

    def posts(self, what: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.method == "POST" and r.url.path.endswith(f"/{what}")]


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def fake():
    return FakeQuickBooks()


@pytest.fixture
def env(tmp_path):
    path = tmp_path / ".env.local"
    path.write_text(f"LEDGER_DESK_ANTHROPIC_KEY=keep-me\n{CLIENT_ID}=cid\n{CLIENT_SECRET}={SECRET}\n{REALM_ID}={REALM}\n{REFRESH_TOKEN}=refresh-0\n", encoding="utf-8")
    return EnvFile(path)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def tokens(fake, env, clock):
    return Tokens(httpx.Client(transport=httpx.MockTransport(fake.handler)), env, clock=clock)


@pytest.fixture
def qb(fake, tokens, env):
    return QuickBooks(httpx.Client(transport=httpx.MockTransport(fake.handler)), tokens, env.require(REALM_ID))


def bill(**over):
    request = {
        "kind": "bill",
        "vendor": "Roasting Equipment Supplier",
        "number": "EQP-5502",
        "date": "2026-11-12",
        "due_date": "2026-12-12",
        "lines": [{"account": "1500", "account_name": "Equipment", "amount": "12400.00", "description": "Roaster drum replacement"}],
        "note": "Ledger Desk 13-abcd1234, ERP entry 7",
    }
    return {**request, **over}


# --- connecting -------------------------------------------------------------------------------

def test_the_authorize_url_asks_for_the_accounting_scope_only():
    url = urllib.parse.urlparse(authorize_url("cid", "http://localhost:8765/callback", "state-1"))
    q = dict(urllib.parse.parse_qsl(url.query))
    assert f"{url.scheme}://{url.netloc}{url.path}" == "https://appcenter.intuit.com/connect/oauth2"
    assert q == {"client_id": "cid", "response_type": "code", "scope": "com.intuit.quickbooks.accounting", "redirect_uri": "http://localhost:8765/callback", "state": "state-1"}
    assert SCOPE == "com.intuit.quickbooks.accounting"


def test_a_code_is_exchanged_with_basic_auth_and_the_refresh_token_stored(fake, env, tokens):
    tokens.exchange("good-code", "http://localhost:8765/callback")
    assert env.get(REFRESH_TOKEN) == "refresh-1"
    assert env.get("LEDGER_DESK_ANTHROPIC_KEY") == "keep-me"  # other lines kept
    assert tokens.access_token() == "access-1"  # no second token request while it is fresh
    assert fake.issued == 1


def test_every_refresh_stores_the_new_refresh_token(fake, env, tokens, clock):
    assert tokens.access_token() == "access-1"
    assert env.get(REFRESH_TOKEN) == "refresh-1"
    clock.now += 3600  # the access token has expired
    assert tokens.access_token() == "access-2"
    assert env.get(REFRESH_TOKEN) == "refresh-2"  # the one the fake now accepts; refresh-1 no longer works
    assert fake.issued == 2


def test_a_fresh_access_token_is_reused(fake, tokens, clock):
    tokens.access_token()
    clock.now += 3000
    tokens.access_token()
    assert fake.issued == 1


def test_a_401_from_the_api_refreshes_once_and_retries(fake, qb):
    assert qb.company_name() == "Sandbox Company US 0000"
    fake.access = "revoked-on-intuit-side"
    assert qb.company_name() == "Sandbox Company US 0000"
    assert fake.issued == 2


def test_errors_never_carry_the_secret_a_token_or_the_code(fake, env, tokens, qb):
    with pytest.raises(QuickBooksError) as refused:
        tokens.exchange("bad-code", "http://localhost:8765/callback")
    fake.fail_create = 400
    with pytest.raises(QuickBooksError) as failed:
        mirror_bill(qb, bill())
    for e in (refused.value, failed.value):
        text = str(e)
        for secret in (SECRET, "refresh-0", "refresh-1", "access-1", "bad-code", "cid"):
            assert secret not in text, (secret, text)
    assert "invalid_grant" in str(refused.value)
    assert "6000" in str(failed.value)


def test_a_missing_line_in_the_env_file_names_the_line_not_the_file_contents(tmp_path):
    path = tmp_path / ".env.local"
    path.write_text(f"{CLIENT_ID}=cid\n", encoding="utf-8")
    with pytest.raises(QuickBooksError) as e:
        EnvFile(path).require(CLIENT_SECRET)
    assert CLIENT_SECRET in str(e.value) and "cid" not in str(e.value)


def test_finish_connect_refuses_a_wrong_state_and_exchanges_nothing(fake, env, tokens):
    with pytest.raises(QuickBooksError, match="state"):
        finish_connect({"code": "good-code", "state": "forged", "realmId": REALM}, "state-1", tokens, "http://localhost:8765/callback", env)
    assert fake.issued == 0 and env.get(REFRESH_TOKEN) == "refresh-0"


def test_finish_connect_refuses_a_declined_consent(fake, env, tokens):
    with pytest.raises(QuickBooksError, match="access_denied"):
        finish_connect({"error": "access_denied", "state": "state-1"}, "state-1", tokens, "http://localhost:8765/callback", env)
    assert fake.issued == 0


def test_finish_connect_stores_the_tokens_and_the_company(fake, env, tokens):
    realm = finish_connect({"code": "good-code", "state": "state-1", "realmId": "9130000000000002"}, "state-1", tokens, "http://localhost:8765/callback", env)
    assert realm == "9130000000000002"
    assert env.get(REALM_ID) == "9130000000000002" and env.get(REFRESH_TOKEN) == "refresh-1"


def test_the_callback_server_hands_back_the_query_once():
    got = {}
    t = threading.Thread(target=lambda: got.update(wait_for_callback(8799, timeout=10)))
    t.start()
    for _ in range(50):
        try:
            r = httpx.get("http://127.0.0.1:8799/callback?code=c1&state=s1&realmId=r1", timeout=1)
            break
        except httpx.ConnectError:
            threading.Event().wait(0.1)
    t.join(10)
    assert r.status_code == 200 and "close this tab" in r.text
    assert got == {"code": "c1", "state": "s1", "realmId": "r1"}


# --- mirroring --------------------------------------------------------------------------------

def test_every_call_carries_minorversion_75(fake, qb):
    mirror_bill(qb, bill())
    api_calls = [r for r in fake.requests if r.url.host == "sandbox-quickbooks.api.intuit.com"]
    assert api_calls and all(r.url.params.get("minorversion") == "75" for r in api_calls)


def test_a_bill_carries_vendor_line_docnumber_dates_and_note(fake, qb):
    result = mirror_bill(qb, bill())
    (post,) = fake.posts("bill")
    body = httpx.Response(200, content=post.content).json()
    vendor_id = next(i for i, n in fake.vendors.items() if n == "Roasting Equipment Supplier")
    account_id = next(i for i, a in fake.accounts.items() if a["Name"] == "1500 Equipment")
    assert fake.accounts[account_id]["AccountType"] == "Fixed Asset"
    assert fake.accounts[account_id]["AccountSubType"] == "MachineryAndEquipment"
    assert body == {
        "VendorRef": {"value": vendor_id},
        "Line": [{"DetailType": "AccountBasedExpenseLineDetail", "Amount": 12400.0, "Description": "Roaster drum replacement", "AccountBasedExpenseLineDetail": {"AccountRef": {"value": account_id}}}],
        "DocNumber": "EQP-5502",
        "TxnDate": "2026-11-12",
        "DueDate": "2026-12-12",
        "PrivateNote": "Ledger Desk 13-abcd1234, ERP entry 7",
    }
    assert result == {"entity": "Bill", "id": fake.docs[0]["Id"], "doc_number": "EQP-5502", "created": True, "total": 12400.0}


def test_account_types_follow_the_account_number():
    # Type and sub-type together: with no sub-type QuickBooks picked EmployeeCashAdvances for an
    # Other Current Asset and refused a Fixed Asset outright (real sandbox, 2026-11-14, n=1 and n=2).
    # Pairs measured on the sandbox's own accounts, or (*) from Intuit's .NET SDK AccountSubTypeEnum.
    from ledger_desk.quickbooks import account_type

    assert {n: account_type(n) for n in ("1200", "1210", "1500", "5100", "6200", "6300", "6400", "6500")} == {
        "1200": ("Other Current Asset", "Inventory"),
        "1210": ("Other Current Asset", "Inventory"),
        "1500": ("Fixed Asset", "MachineryAndEquipment"),  # *
        "5100": ("Cost of Goods Sold", "SuppliesMaterialsCogs"),
        "6200": ("Expense", "Utilities"),
        "6300": ("Expense", "RepairMaintenance"),
        "6400": ("Expense", "DuesSubscriptions"),
        "6500": ("Expense", "ShippingFreightDelivery"),  # *
    }
    with pytest.raises(QuickBooksError):
        account_type("2000")  # accounts payable is QuickBooks' own side of a bill, never a line
    with pytest.raises(QuickBooksError):
        account_type("6900")  # an account nobody classified fails loudly instead of getting a default


def test_every_account_a_bill_can_post_to_has_a_quickbooks_class():
    from ledger_desk.company import build_company
    from ledger_desk.quickbooks import account_type

    for account in build_company().accounts:
        if account.number != "2000":
            account_type(account.number)


def test_a_new_account_is_created_with_its_type_and_sub_type(fake, qb):
    mirror_bill(qb, bill(lines=[{"account": "1210", "account_name": "Inventory - packaging", "amount": "200.00", "description": "Bags"}]))
    (created,) = fake.accounts.values()
    assert created == {"Name": "1210 Inventory - packaging", "AccountType": "Other Current Asset", "AccountSubType": "Inventory"}


def test_a_credit_memo_becomes_a_vendor_credit_without_a_due_date(fake, qb):
    result = mirror_bill(qb, bill(kind="credit", number="CM-0042", due_date=None, lines=[{"account": "5100", "account_name": "Dairy (cost of sales)", "amount": "84.00", "description": "Returned spoiled milk"}]))
    assert fake.posts("bill") == []
    (post,) = fake.posts("vendorcredit")
    body = httpx.Response(200, content=post.content).json()
    assert "DueDate" not in body and body["DocNumber"] == "CM-0042" and body["Line"][0]["Amount"] == 84.0
    assert result["entity"] == "VendorCredit"


def test_an_existing_vendor_and_account_are_reused(fake, qb):
    mirror_bill(qb, bill(vendor="Sample Vendor Already There"))
    mirror_bill(qb, bill(vendor="Sample Vendor Already There", number="EQP-5503"))
    assert fake.posts("vendor") == []  # the sandbox's own vendor, found by name
    assert len(fake.posts("account")) == 1  # "1500 Equipment" made once, then found
    assert {d["VendorRef"]["value"] for d in fake.docs} == {"56"}


def test_a_vendor_name_with_an_apostrophe_is_escaped_with_a_backslash(fake, qb):
    mirror_bill(qb, bill(vendor="Roaster's Supply"))
    assert "select * from Vendor where DisplayName = 'Roaster\\'s Supply' AND Active IN (true, false)" in fake.queries
    assert "Roaster's Supply" in fake.vendors.values()


def test_a_name_quickbooks_forbids_fails_loudly(fake, qb):
    with pytest.raises(QuickBooksError, match="colon"):
        mirror_bill(qb, bill(vendor="Supplier: West"))
    assert fake.posts("vendor") == [] and fake.docs == []


def test_mirroring_the_same_bill_twice_creates_it_once(fake, qb):
    first = mirror_bill(qb, bill())
    again = mirror_bill(qb, bill())
    assert len(fake.posts("bill")) == 1
    assert again == {**first, "created": False}


def test_the_same_number_from_another_vendor_is_a_different_bill(fake, qb):
    mirror_bill(qb, bill())
    mirror_bill(qb, bill(vendor="Packaging Supplier"))
    assert len(fake.posts("bill")) == 2


def test_a_number_longer_than_21_characters_fails_before_anything_is_written(fake, qb):
    with pytest.raises(QuickBooksError, match="21"):
        mirror_bill(qb, bill(number="X" * 22))
    assert fake.docs == [] and fake.posts("vendor") == []


def test_due_date_helper_adds_the_vendor_terms():
    from ledger_desk.company import due_date

    assert due_date("2026-11-12", 30) == "2026-12-12"
    assert due_date("not a date", 30) is None
    assert date.fromisoformat(due_date("2026-12-20", 15)) == date(2027, 1, 4)


# --- the commands -----------------------------------------------------------------------------

def test_qbo_check_without_a_connection_names_the_missing_line_only(monkeypatch, tmp_path, capsys):
    from ledger_desk import quickbooks
    from ledger_desk.cli import main

    path = tmp_path / ".env.local"
    path.write_text(f"{CLIENT_ID}=cid\n{CLIENT_SECRET}={SECRET}\n{REALM_ID}={REALM}\n", encoding="utf-8")
    monkeypatch.setattr(quickbooks, "ENV_PATH", path)
    assert main(["qbo-check"]) == 1
    out = capsys.readouterr()
    assert REFRESH_TOKEN in out.err
    assert SECRET not in out.out + out.err and "cid" not in out.out + out.err


def test_api_serve_refuses_the_mirror_without_a_connection_before_touching_the_database(monkeypatch, tmp_path, capsys):
    from ledger_desk import cli, quickbooks

    monkeypatch.setattr(quickbooks, "ENV_PATH", tmp_path / "missing.env")
    touched = []
    monkeypatch.setattr("ledger_desk.db.connect", lambda *a, **k: touched.append(a) or (_ for _ in ()).throw(AssertionError("database touched")))
    assert cli.main(["api-serve", "--dry-run", "--mirror-quickbooks"]) == 1
    assert touched == [] and CLIENT_ID in capsys.readouterr().err


def test_qbo_connect_writes_the_authorize_url_to_a_file_and_never_prints_it(monkeypatch, tmp_path, capsys):
    from ledger_desk import cli, quickbooks

    path = tmp_path / ".env.local"
    path.write_text(f"{CLIENT_ID}=cid-printed-nowhere\n{CLIENT_SECRET}={SECRET}\n", encoding="utf-8")
    monkeypatch.setattr(quickbooks, "ENV_PATH", path)

    def no_callback(port, timeout, **_):
        raise QuickBooksError(f"no callback on port {port} within {timeout:.0f} s")

    monkeypatch.setattr(quickbooks, "wait_for_callback", no_callback)
    url_file = tmp_path / "authorize-url.txt"
    assert cli.main(["qbo-connect", "--url-file", str(url_file), "--timeout", "1"]) == 1
    url = url_file.read_text(encoding="utf-8")
    assert url.startswith("https://appcenter.intuit.com/connect/oauth2?") and "cid-printed-nowhere" in url
    out = capsys.readouterr()
    assert "cid-printed-nowhere" not in out.out + out.err and SECRET not in out.out + out.err
    assert "no callback" in out.err


# --- found by the fresh-context review, 2026-11-14 --------------------------------------------

def test_two_approvals_at_once_create_one_bill(fake, qb):
    fake.doc_gate = threading.Barrier(2, timeout=1)  # without a lock both threads look before either writes
    results, errors = [], []

    def approve():
        try:
            results.append(mirror_bill(qb, bill()))
        except Exception as e:  # noqa: BLE001 - collected and asserted below
            errors.append(e)

    threads = [threading.Thread(target=approve) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert errors == []
    assert len(fake.posts("bill")) == 1
    assert sorted(r["created"] for r in results) == [False, True]


def test_a_failed_env_write_leaves_the_old_file_whole(env, monkeypatch):
    from pathlib import Path

    before = env.path.read_text(encoding="utf-8")
    real_write = Path.write_text

    def crash_half_way(self, data, *args, **kwargs):
        real_write(self, data[: len(data) // 2], *args, **kwargs)
        raise OSError("disk went away mid-write")

    monkeypatch.setattr(Path, "write_text", crash_half_way)
    with pytest.raises(OSError):
        env.set({REFRESH_TOKEN: "refresh-new"})
    monkeypatch.undo()
    assert env.path.read_text(encoding="utf-8") == before
    assert list(env.path.parent.glob(".env.local*")) == [env.path]  # the half-written copy holds secrets: gone


def _get(url):
    for _ in range(50):
        try:
            return httpx.get(url, timeout=2)
        except httpx.ConnectError:
            threading.Event().wait(0.1)
    raise AssertionError("callback server never came up")


def test_a_stray_request_does_not_end_the_wait_for_intuit():
    got = {}
    t = threading.Thread(target=lambda: got.update(wait_for_callback(8798, timeout=10, state="s1")))
    t.start()
    stray = _get("http://127.0.0.1:8798/callback?x=1")
    forged = _get("http://127.0.0.1:8798/callback?code=evil&state=not-ours")
    good = _get("http://127.0.0.1:8798/callback?code=c1&state=s1&realmId=r1")
    t.join(10)
    assert (stray.status_code, forged.status_code, good.status_code) == (400, 400, 200)
    assert got == {"code": "c1", "state": "s1", "realmId": "r1"}


def test_an_idle_connection_does_not_block_the_callback():
    import socket

    got = {}
    t = threading.Thread(target=lambda: got.update(wait_for_callback(8797, timeout=10, state="s1", connection_timeout=0.5)))
    t.start()
    _get("http://127.0.0.1:8797/callback?x=1")  # the server is up
    idle = socket.create_connection(("127.0.0.1", 8797))  # connects and says nothing
    try:
        good = _get("http://127.0.0.1:8797/callback?code=c1&state=s1&realmId=r1")
    finally:
        idle.close()
    t.join(10)
    assert good.status_code == 200 and got.get("code") == "c1"


def test_an_invoice_number_with_a_backslash_fails_before_anything_is_written(fake, qb):
    with pytest.raises(QuickBooksError, match="backslash"):
        mirror_bill(qb, bill(number="INV-7\\"))
    assert fake.docs == [] and fake.posts("vendor") == []


def test_an_inactive_vendor_is_named_instead_of_duplicated(fake, qb):
    fake.vendors["57"] = "Roasting Equipment Supplier"
    fake.inactive.add("57")
    with pytest.raises(QuickBooksError, match="inactive"):
        mirror_bill(qb, bill())
    assert fake.posts("vendor") == [] and fake.docs == []


def test_an_inactive_account_is_named_instead_of_duplicated(fake, qb):
    fake.accounts["58"] = {"Name": "1500 Equipment", "AccountType": "Fixed Asset", "AccountSubType": "MachineryAndEquipment"}
    fake.inactive.add("58")
    with pytest.raises(QuickBooksError, match="inactive"):
        mirror_bill(qb, bill())
    assert fake.posts("account") == [] and fake.docs == []
