"""CORS: the page and the API are on two hostnames, and the API allows
cross-origin calls only from the page's own origin. Locally the dev server proxies /api, one
origin, so with no origin set there are no CORS headers at all.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ledger_desk.api import create_api
from ledger_desk.settings import api_settings

PAGE = "https://ledger-desk.example"
OTHER = "https://somewhere-else.example"
REPLAYS = Path(__file__).resolve().parents[1] / "replays" / "claude-opus-5-5-low-run2"


@pytest.fixture
def client(erp_db, tmp_path):
    return TestClient(create_api(erp_db, docs_dir=tmp_path, replays_dir=REPLAYS, web_origin=PAGE))


def preflight(client, origin):
    return client.options("/runs", headers={"Origin": origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type,x-session-id"})


def test_the_page_may_call_the_api_with_its_session_header(client):
    r = preflight(client, PAGE)
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == PAGE
    assert "x-session-id" in r.headers["access-control-allow-headers"].lower()
    assert client.get("/samples", headers={"Origin": PAGE}).headers["access-control-allow-origin"] == PAGE


def test_any_other_origin_is_not_allowed(client):
    assert "access-control-allow-origin" not in preflight(client, OTHER).headers
    assert "access-control-allow-origin" not in client.get("/samples", headers={"Origin": OTHER}).headers


def test_no_origin_set_means_no_cors_headers(erp_db, tmp_path):
    local = TestClient(create_api(erp_db, docs_dir=tmp_path, replays_dir=REPLAYS))
    assert "access-control-allow-origin" not in local.get("/samples", headers={"Origin": PAGE}).headers


def test_the_origin_comes_from_the_environment():
    assert api_settings({"LEDGER_DESK_WEB_ORIGIN": PAGE}).web_origin == PAGE
    assert api_settings({}).web_origin is None
