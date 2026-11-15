# 0003. An approval is an Ed25519 signature that the ERP verifies

**Status:** accepted, 2026-11-14

## Decision

When a person approves, the approval endpoint signs exactly what they approved - the invoice reference, who
approved, the amount and every entry line - with an Ed25519 private key that only it holds
(`src/ledger_desk/approval.py`). The mock ERP holds the public half and refuses any posting whose signature does
not verify. The agent's database role cannot insert an approval at all.

## Sources

- cryptography, Ed25519 signing (read 2026-11-14): "Ed25519 is an elliptic curve signing algorithm using EdDSA and
  Curve25519"; `verify()` raises `InvalidSignature`, "Raised when the signature cannot be verified."

## Evidence (this repository)

- `tests/test_approval.py`: `test_a_signed_approval_verifies`, `test_any_change_after_signing_breaks_it` (an
  account, a cent or the approver), `test_another_key_pair_cannot_verify_it`,
  `test_garbage_signatures_are_rejected_not_crashing`.
- `tests/test_db.py`: `test_the_agent_role_cannot_insert_an_approval`.
- `tests/test_deploy_settings.py`: when the ERP refuses the signature, nothing posts and the audit says so.

## Rejected

- **A shared secret (HMAC).** The ERP would need the same key to check it, and could then make approvals itself;
  with a key pair it can only verify.
- **Trusting the API's word.** Anything that reached the ERP's endpoint could post.

## Trade-off

A key to keep: the private half lives only in the API's secret store, and losing it means re-keying both sides.

## What would change it

A real ERP with its own approval workflow would take the signature's place; the rule that the poster cannot also
approve would stay.
