"""Signed approvals (docs/decisions/0003).

A person's approval becomes an Ed25519 signature over exactly what they approved: the invoice
reference, who approved, the amount and every entry line. The approval endpoint (api.py)
signs with the private key, which only it can read; the ERP verifies with the public key. With a
shared secret (HMAC) the ERP would need the same key and could then make approvals itself; with
a key pair it cannot.

Amounts are normalised to two decimals before signing, so "2100" and "2100.00" sign the same,
while any real change (an account, a cent, the approver) breaks the signature.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from decimal import Decimal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


@dataclass(frozen=True)
class KeyPair:
    private: Ed25519PrivateKey
    public: Ed25519PublicKey


def new_key_pair() -> KeyPair:
    private = Ed25519PrivateKey.generate()
    return KeyPair(private, private.public_key())


# Keys as text, so a deployment can keep them in a secret store: the API reads the private half,
# the ERP only the public half. Raw 32-byte Ed25519 keys, base64.
def private_to_b64(key: Ed25519PrivateKey) -> str:
    raw = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    return base64.b64encode(raw).decode()


def private_from_b64(text: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(base64.b64decode(text))


def public_to_b64(key: Ed25519PublicKey) -> str:
    return base64.b64encode(key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()


def public_from_b64(text: str) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(base64.b64decode(text))


def _cents(value) -> str:
    return f"{Decimal(str(value)):.2f}"


def payload(invoice_ref: str, approver: str, lines: list[dict]) -> bytes:
    """The exact bytes that get signed: canonical JSON, keys sorted, amounts as 2-decimal strings."""
    norm = [[str(l["account"]), _cents(l["debit"]), _cents(l["credit"])] for l in lines]
    amount = sum((Decimal(d) for _, d, _ in norm), Decimal(0))
    doc = {"invoice_ref": invoice_ref, "approver": approver, "amount": f"{amount:.2f}", "lines": norm}
    return json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()


def sign(private: Ed25519PrivateKey, invoice_ref: str, approver: str, lines: list[dict]) -> str:
    return base64.b64encode(private.sign(payload(invoice_ref, approver, lines))).decode()


def verify(public: Ed25519PublicKey, signature: str, invoice_ref: str, approver: str, lines: list[dict]) -> bool:
    try:
        public.verify(base64.b64decode(signature, validate=True), payload(invoice_ref, approver, lines))
        return True
    except (InvalidSignature, binascii.Error, ValueError):
        return False
