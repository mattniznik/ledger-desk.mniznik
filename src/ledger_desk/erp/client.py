"""The client the app uses to talk to the ERP, with the retries a real integration needs.

- 503, 502, 504 and connection errors: retried with exponential backoff (0.5 s, 1 s, 2 s, ...).
- 429: waits exactly as long as Retry-After says.
- 4xx otherwise: never retried. A 403 means the approval does not match; retrying cannot fix it.
- Every retry of a posting carries the same Idempotency-Key, so a response lost after the ERP
  committed comes back as the same entry, never a second one.

`sleep` is injected so tests can check the waits without waiting.
"""

from __future__ import annotations

import time
from typing import Callable

import httpx


class ErpError(Exception):
    pass


class ApprovalRejected(ErpError):
    """403: the signature does not match exactly this entry and approver."""


class EntryConflict(ErpError):
    """409: the Idempotency-Key was already used for a different entry."""


class EntryRejected(ErpError):
    """400 or 422: the request or the entry itself is wrong (e.g. it does not balance)."""


class ErpUnavailable(ErpError):
    """The ERP did not answer successfully within the allowed attempts."""


RETRY_STATUSES = {502, 503, 504}


class ErpClient:
    def __init__(
        self,
        http: httpx.Client,
        api_key: str,
        *,
        max_attempts: int = 5,
        base_delay: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.http = http
        self.api_key = api_key
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.sleep = sleep

    def _request(self, method: str, path: str, **kwargs) -> tuple[httpx.Response, int]:
        headers = {"X-API-Key": self.api_key, **kwargs.pop("headers", {})}
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.http.request(method, path, headers=headers, **kwargs)
            except httpx.TransportError:
                response = None
            if response is not None and response.status_code < 400:
                return response, attempt
            if attempt == self.max_attempts:
                break
            if response is not None and response.status_code == 429:
                self.sleep(float(response.headers.get("Retry-After", self.base_delay)))
            elif response is None or response.status_code in RETRY_STATUSES:
                self.sleep(self.base_delay * 2 ** (attempt - 1))
            else:
                self._raise(response)
        if response is not None and response.status_code not in RETRY_STATUSES | {429}:
            self._raise(response)
        raise ErpUnavailable(f"the ERP did not answer after {self.max_attempts} attempts")

    @staticmethod
    def _raise(response: httpx.Response):
        detail = response.json().get("detail", "") if response.headers.get("content-type", "").startswith("application/json") else response.text
        code = response.status_code
        if code == 403:
            raise ApprovalRejected(detail)
        if code == 409:
            raise EntryConflict(detail)
        if code in (400, 422):
            raise EntryRejected(detail)
        raise ErpError(f"{code}: {detail}")

    def post_journal_entry(self, entry: dict, idempotency_key: str) -> dict:
        response, attempts = self._request("POST", "/journal-entries", json=entry, headers={"Idempotency-Key": idempotency_key})
        return {**response.json(), "attempts": attempts}

    def find_vendors(self, name: str | None = None, tax_id: str | None = None) -> list[dict]:
        params = {k: v for k, v in {"name": name, "tax_id": tax_id}.items() if v}
        return self._request("GET", "/vendors", params=params)[0].json()

    def purchase_order(self, po: str) -> dict:
        return self._request("GET", f"/purchase-orders/{po}")[0].json()

    def receipts(self, po: str) -> list[dict]:
        return self._request("GET", f"/purchase-orders/{po}/receipts")[0].json()

    def bills(self, **params) -> list[dict]:
        """Every page: the client follows next_offset until the ERP says there is no more."""
        out, offset = [], 0
        while offset is not None:
            page = self._request("GET", "/bills", params={**params, "offset": offset})[0].json()
            out += page["items"]
            offset = page["next_offset"]
        return out
