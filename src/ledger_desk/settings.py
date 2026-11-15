"""Deploy settings: what the API and the mock ERP read from the environment when they run as
separate containers (docs/DEPLOY.md). The platform fills these from its secret store; nothing
here is baked into an image, and nothing is printed.

    API   LEDGER_DESK_ERP_URL               the ERP container's address; unset means in-process
          LEDGER_DESK_ERP_KEY               the ERP's API key (required with the URL)
          LEDGER_DESK_APPROVAL_PRIVATE_KEY  the approval signing key, base64 (required with the URL)
    ERP   LEDGER_DESK_ERP_KEY               its own API key
          LEDGER_DESK_APPROVAL_PUBLIC_KEY   the public half, base64: it verifies, it cannot sign

Locally, in one process, none of this is set: the API makes the ERP in-process with a throwaway
key pair. A half-set deployment is refused at start-up, not on the first approval.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .approval import KeyPair, new_key_pair, private_from_b64, public_from_b64

LOCAL_ERP_KEY = "local-dev-key"  # local only; a deployment sets LEDGER_DESK_ERP_KEY


class SettingsError(RuntimeError):
    pass


@dataclass(frozen=True)
class ApiSettings:
    erp_url: str | None
    erp_key: str | None
    keys: KeyPair | None
    web_origin: str | None = None  # LEDGER_DESK_WEB_ORIGIN: the only origin CORS allows; unset locally


def api_settings(env: Mapping[str, str] | None = None) -> ApiSettings:
    env = os.environ if env is None else env
    url, key, private = env.get("LEDGER_DESK_ERP_URL"), env.get("LEDGER_DESK_ERP_KEY"), env.get("LEDGER_DESK_APPROVAL_PRIVATE_KEY")
    if url and not key:
        raise SettingsError("LEDGER_DESK_ERP_URL is set without LEDGER_DESK_ERP_KEY: the ERP would refuse every call")
    if url and not private:
        raise SettingsError("LEDGER_DESK_ERP_URL is set without LEDGER_DESK_APPROVAL_PRIVATE_KEY: the ERP could not verify any approval")
    keys = None
    if private:
        p = private_from_b64(private)
        keys = KeyPair(p, p.public_key())
    return ApiSettings(url or None, key or None, keys, env.get("LEDGER_DESK_WEB_ORIGIN") or None)


def erp_settings(env: Mapping[str, str] | None = None) -> tuple[str, Ed25519PublicKey]:
    env = os.environ if env is None else env
    public = env.get("LEDGER_DESK_APPROVAL_PUBLIC_KEY")
    return env.get("LEDGER_DESK_ERP_KEY") or LOCAL_ERP_KEY, public_from_b64(public) if public else new_key_pair().public
