"""QuickBooks Online: the OAuth 2.0 connection and the client that mirrors approved bills (docs/decisions/0006).

The mock ERP stays the system of record. Each bill a person approves is also written to a QuickBooks
Online sandbox company as a Bill (a VendorCredit for a credit memo), so the demo shows the same
posting landing in a real accounting product.

From Intuit's docs, read 2026-11-14 in the browser (the pages render client-side):
- authorize at AUTHORIZE_URL with `scope=com.intuit.quickbooks.accounting`; the scope is asked for
  here, so the app's portal ticking payments too grants nothing extra;
- tokens at TOKEN_URL with `Authorization: "Basic " + base64encode(client_id + ":" + client_secret)`,
  form-encoded; access token 3600 s, refresh token 8,640,000 s; "Always store the latest
  refresh_token value from the most recent API server response", so every token response is
  written to the env file before anything else happens;
- the sandbox base URL `https://sandbox-quickbooks.api.intuit.com`, `minorversion=75` on every call;
- Bill and VendorCredit: VendorRef and Line required; DocNumber "maximum of 21 chars", and a
  duplicate "throws an error"; VendorCredit's VendorRef is not filterable, so a document is found
  by DocNumber and its vendor checked here;
- Vendor DisplayName: unique, no colon, tab or newline. Account Name: unique, no `"` or colon;
  AccountType required when no sub-type is given;
- queries: "Use backslash (\\) to escape special characters like apostrophes (')".

Keys and tokens live in the gitignored `.env.local` and are passed explicitly; never read from the
process environment, never printed, never put in an error message.
"""

from __future__ import annotations

import html
import os
import threading
import time
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qsl, urlencode, urlparse

import httpx

ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = ROOT / ".env.local"

AUTHORIZE_URL = "https://appcenter.intuit.com/connect/oauth2"
TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
SANDBOX_BASE = "https://sandbox-quickbooks.api.intuit.com"
SCOPE = "com.intuit.quickbooks.accounting"
MINOR_VERSION = "75"
DOC_NUMBER_MAX = 21
NOTE_MAX = 4000

CLIENT_ID = "LEDGER_DESK_QBO_CLIENT_ID"
CLIENT_SECRET = "LEDGER_DESK_QBO_CLIENT_SECRET"
REALM_ID = "LEDGER_DESK_QBO_REALM_ID"
REFRESH_TOKEN = "LEDGER_DESK_QBO_REFRESH_TOKEN"


class QuickBooksError(Exception):
    """Every message is written here from status codes and QuickBooks' own fault text, never from a
    request, so no key, token or code can end up in it."""


class EnvFile:
    """`NAME=value` lines, the same format anthropic_api.read_key reads. Updates keep every other line."""

    def __init__(self, path: Path = ENV_PATH):
        self.path = Path(path)
        self._lock = threading.Lock()

    def _lines(self) -> list[str]:
        return self.path.read_text(encoding="utf-8").splitlines() if self.path.exists() else []

    def get(self, name: str) -> str | None:
        for line in self._lines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == name and value.strip():
                return value.strip().strip('"').strip("'")
        return None

    def require(self, name: str) -> str:
        value = self.get(name)
        if value is None:
            raise QuickBooksError(f"{self.path.name} has no {name} line; run `ledger-desk qbo-connect` (keys from the Intuit app's Keys and credentials page)")
        return value

    def set(self, values: dict[str, str]) -> None:
        with self._lock:
            kept = [line for line in self._lines() if line.partition("=")[0].strip() not in values]
            # Written beside the file, then swapped in: a crash or a lock mid-write leaves the old file
            # whole instead of an empty one that has lost every key (fresh-context review, 2026-11-14).
            # The half-written copy holds secrets too, so it is removed on any failure.
            tmp = self.path.with_name(self.path.name + ".tmp")
            try:
                tmp.write_text("\n".join(kept + [f"{k}={v}" for k, v in values.items()]) + "\n", encoding="utf-8")
                os.replace(tmp, self.path)
            except BaseException:
                tmp.unlink(missing_ok=True)
                raise


def authorize_url(client_id: str, redirect_uri: str, state: str) -> str:
    return AUTHORIZE_URL + "?" + urlencode({"client_id": client_id, "response_type": "code", "scope": SCOPE, "redirect_uri": redirect_uri, "state": state})


class Tokens:
    """The access token in memory; the refresh token in the env file, replaced on every response."""

    def __init__(self, http: httpx.Client, env: EnvFile, clock: Callable[[], float] = time.monotonic):
        self.http = http
        self.env = env
        self.clock = clock
        self._access: str | None = None
        self._expires = 0.0
        self._lock = threading.Lock()

    def _request(self, form: dict) -> str:
        response = self.http.post(
            TOKEN_URL,
            data=form,
            auth=(self.env.require(CLIENT_ID), self.env.require(CLIENT_SECRET)),
            headers={"Accept": "application/json"},
        )
        if response.status_code != 200:
            try:
                error = str(response.json().get("error", ""))[:60]
            except ValueError:
                error = ""
            raise QuickBooksError(f"Intuit refused the token request: {response.status_code} {error}".strip())
        body = response.json()
        self.env.set({REFRESH_TOKEN: body["refresh_token"]})  # first, so a crash after this loses nothing
        self._access = body["access_token"]
        self._expires = self.clock() + float(body.get("expires_in", 3600)) - 60
        return self._access

    def exchange(self, code: str, redirect_uri: str) -> None:
        with self._lock:
            self._request({"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri})

    def access_token(self) -> str:
        with self._lock:
            if self._access and self.clock() < self._expires:
                return self._access
            return self._request({"grant_type": "refresh_token", "refresh_token": self.env.require(REFRESH_TOKEN)})

    def invalidate(self) -> None:
        with self._lock:
            self._access = None


def finish_connect(params: dict, expected_state: str, tokens: Tokens, redirect_uri: str, env: EnvFile) -> str:
    """The callback's query string: check it is ours, exchange the code, keep the company id."""
    if params.get("state") != expected_state:
        raise QuickBooksError("the callback's state does not match this connection attempt; nothing was exchanged")
    if "error" in params:
        raise QuickBooksError(f"Intuit returned {params['error'][:60]} instead of a code; nothing was exchanged")
    if not params.get("code") or not params.get("realmId"):
        raise QuickBooksError("the callback carries no code or no company id; nothing was exchanged")
    tokens.exchange(params["code"], redirect_uri)
    env.set({REALM_ID: params["realmId"]})
    return params["realmId"]


def wait_for_callback(port: int, timeout: float = 300, state: str | None = None, connection_timeout: float = 5) -> dict:
    """Serve GET /callback on 127.0.0.1:<port> until Intuit's answer arrives and return its query
    (Intuit's redirect URIs may not be an IP address, so the URI says localhost).

    With `state`, a request carrying any other state (a stray page, a forged code) gets a 400 and the
    wait goes on; a connection that sends nothing is dropped after `connection_timeout` seconds, so it
    cannot hold the single-threaded server past the deadline."""
    got: dict = {}

    class Handler(BaseHTTPRequestHandler):
        timeout = connection_timeout

        def do_GET(self):  # noqa: N802 - the stdlib's name
            url = urlparse(self.path)
            if url.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            params = dict(parse_qsl(url.query))
            if state is not None and params.get("state") != state:
                self.send_response(400)
                self.end_headers()
                return
            got.update(params)
            text = "Ledger Desk received Intuit's answer. You can close this tab."
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"<!doctype html><title>Ledger Desk</title><p>{html.escape(text)}</p>".encode())

        def log_message(self, *args):  # the query carries the code: never logged
            pass

    server = HTTPServer(("127.0.0.1", port), Handler)
    server.timeout = 1
    deadline = time.monotonic() + timeout
    try:
        while not got and time.monotonic() < deadline:
            server.handle_request()
    finally:
        server.server_close()
    if not got:
        raise QuickBooksError(f"no callback on port {port} within {timeout:.0f} s")
    return got


# Type and sub-type for each account a bill line can post to. Both are sent: with the type alone the
# real sandbox gave an Other Current Asset the sub-type EmployeeCashAdvances and refused a Fixed Asset
# ("Invalid input field, unable to parse"), 2026-11-14. Every pair below is one the sandbox's own
# accounts use, except MachineryAndEquipment and ShippingFreightDelivery, which are members of
# Intuit's .NET SDK AccountSubTypeEnum (read 2026-11-14). Accounts payable (2000) is QuickBooks' own
# side of a bill, so it has none.
ACCOUNT_CLASSES = {
    "1200": ("Other Current Asset", "Inventory"),
    "1210": ("Other Current Asset", "Inventory"),
    "1500": ("Fixed Asset", "MachineryAndEquipment"),
    "5100": ("Cost of Goods Sold", "SuppliesMaterialsCogs"),
    "6200": ("Expense", "Utilities"),
    "6300": ("Expense", "RepairMaintenance"),
    "6400": ("Expense", "DuesSubscriptions"),
    "6500": ("Expense", "ShippingFreightDelivery"),
}


def account_type(number: str) -> tuple[str, str]:
    """(AccountType, AccountSubType) for one of the roastery's accounts; never a guessed default."""
    try:
        return ACCOUNT_CLASSES[number]
    except KeyError:
        raise QuickBooksError(f"account {number} has no QuickBooks type: a bill line goes to an asset, cost or expense account listed in ACCOUNT_CLASSES") from None


def _quoted(value: str) -> str:
    return "'" + value.replace("'", "\\'") + "'"


def _check_name(kind: str, name: str, forbidden: dict[str, str]) -> str:
    name = name.strip()
    for char, label in forbidden.items():
        if char in name:
            raise QuickBooksError(f"QuickBooks does not allow a {label} in a {kind} name")
    if "\\" in name:
        raise QuickBooksError(f"a {kind} name with a backslash cannot be queried safely")
    return name


class QuickBooks:
    def __init__(self, http: httpx.Client, tokens: Tokens, realm_id: str, base: str = SANDBOX_BASE):
        self.http = http
        self.tokens = tokens
        self.realm = realm_id
        self.base = base
        # One mirror at a time per client: find-then-create is not atomic in QuickBooks, so two
        # approvals at once would both find nothing and both write (fresh-context review, 2026-11-14).
        # It covers one API process; the mirror runs locally only today (docs/DEPLOY.md).
        self.mirror_lock = threading.Lock()

    def _call(self, method: str, path: str, **kwargs) -> dict:
        url = f"{self.base}/v3/company/{self.realm}/{path}"
        params = {**kwargs.pop("params", {}), "minorversion": MINOR_VERSION}
        for attempt in (1, 2):
            response = self.http.request(method, url, params=params, headers={"Authorization": f"Bearer {self.tokens.access_token()}", "Accept": "application/json"}, **kwargs)
            if response.status_code == 401 and attempt == 1:
                self.tokens.invalidate()  # revoked or expired early: one refresh, one retry
                continue
            break
        if response.status_code >= 400:
            raise QuickBooksError(f"QuickBooks {method} {path.split('?')[0].split('/')[0]}: {response.status_code} {self._fault(response)}")
        return response.json()

    @staticmethod
    def _fault(response: httpx.Response) -> str:
        try:
            errors = response.json().get("Fault", {}).get("Error", [])
        except ValueError:
            return ""
        return "; ".join(f"{e.get('code', '')} {e.get('Message', '')} {e.get('Detail', '')}".strip() for e in errors)[:300]

    def query(self, entity: str, field: str, value: str, include_inactive: bool = False) -> list[dict]:
        # A plain query returns active list entities only; "Active IN (true, false)" returns both
        # (data-queries docs, read 2026-11-14).
        sql = f"select * from {entity} where {field} = {_quoted(value)}" + (" AND Active IN (true, false)" if include_inactive else "")
        return self._call("GET", "query", params={"query": sql}).get("QueryResponse", {}).get(entity, [])

    def company_name(self) -> str:
        return self._call("GET", f"companyinfo/{self.realm}")["CompanyInfo"]["CompanyName"]

    def _found_active(self, kind: str, name: str, found: list[dict]) -> str | None:
        """The id of the one already there; an inactive one ("deleted" in QuickBooks) is named, because
        the name is still taken and creating it again would only fail as a duplicate."""
        if not found:
            return None
        if found[0].get("Active") is False:
            raise QuickBooksError(f"the {kind} '{name}' is inactive in QuickBooks; make it active again there, then approve again")
        return found[0]["Id"]

    def vendor_id(self, name: str) -> str:
        name = _check_name("vendor", name, {":": "colon", "\t": "tab", "\n": "newline"})
        found = self._found_active("vendor", name, self.query("Vendor", "DisplayName", name, include_inactive=True))
        return found or self._call("POST", "vendor", json={"DisplayName": name})["Vendor"]["Id"]

    def account_id(self, number: str, name: str) -> str:
        full = _check_name("account", f"{number} {name}", {":": "colon", '"': "double quote"})
        kind, sub = account_type(number)
        found = self._found_active("account", full, self.query("Account", "Name", full, include_inactive=True))
        return found or self._call("POST", "account", json={"Name": full, "AccountType": kind, "AccountSubType": sub})["Account"]["Id"]

    def find_document(self, entity: str, doc_number: str, vendor_id: str) -> dict | None:
        return next((d for d in self.query(entity, "DocNumber", doc_number) if d.get("VendorRef", {}).get("value") == vendor_id), None)

    def create(self, entity: str, body: dict) -> dict:
        return self._call("POST", entity.lower(), json=body)[entity]


def mirror_bill(qb: QuickBooks, request: dict) -> dict:
    """One approved bill (workflow.mirror_request's shape) into QuickBooks, once.

    The same bill mirrored again (a re-run step, a second approval of the same sample) finds the
    first by DocNumber and vendor and writes nothing, the way the mock ERP's idempotency key works.
    """
    entity = "VendorCredit" if request["kind"] == "credit" else "Bill"
    number = request["number"].strip()
    if not number or len(number) > DOC_NUMBER_MAX:
        raise QuickBooksError(f"invoice number must be 1 to {DOC_NUMBER_MAX} characters for QuickBooks' DocNumber")
    if "\\" in number:  # read off an untrusted document; a trailing backslash would unbalance the query's quotes
        raise QuickBooksError("an invoice number with a backslash cannot be looked up safely in QuickBooks")
    with qb.mirror_lock:
        return _mirror_locked(qb, request, entity, number)


def _mirror_locked(qb: QuickBooks, request: dict, entity: str, number: str) -> dict:
    vendor = qb.vendor_id(request["vendor"])
    existing = qb.find_document(entity, number, vendor)
    if existing:
        return {"entity": entity, "id": existing["Id"], "doc_number": number, "created": False, "total": existing.get("TotalAmt")}
    lines = [
        {
            "DetailType": "AccountBasedExpenseLineDetail",
            "Amount": float(Decimal(line["amount"])),
            "Description": line["description"][:NOTE_MAX],
            "AccountBasedExpenseLineDetail": {"AccountRef": {"value": qb.account_id(line["account"], line["account_name"])}},
        }
        for line in request["lines"]
    ]
    body = {"VendorRef": {"value": vendor}, "Line": lines, "DocNumber": number, "TxnDate": request["date"]}
    if entity == "Bill" and request.get("due_date"):
        body["DueDate"] = request["due_date"]
    body["PrivateNote"] = request["note"][:NOTE_MAX]
    created = qb.create(entity, body)
    return {"entity": entity, "id": created["Id"], "doc_number": number, "created": True, "total": created.get("TotalAmt")}


def connect_from_env(env: EnvFile | None = None, http: httpx.Client | None = None) -> QuickBooks:
    """The sandbox client from `.env.local`: keys, company id and refresh token must all be there."""
    env = env or EnvFile()
    for name in (CLIENT_ID, CLIENT_SECRET, REALM_ID, REFRESH_TOKEN):
        env.require(name)
    http = http or httpx.Client(timeout=20)
    return QuickBooks(http, Tokens(http, env), env.require(REALM_ID))
