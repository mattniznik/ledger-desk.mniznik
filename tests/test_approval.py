"""Approval signatures (docs/decisions/0003). Ed25519: the approval endpoint signs with a
private key only it can read; the ERP verifies with the public key, so not even the ERP can make
an approval. The signature covers the invoice, the approver, the amount and every entry line, so
changing any of them after a person approved makes it invalid."""

from ledger_desk.approval import new_key_pair, sign, verify

LINES = [
    {"account": "1210", "debit": "2100.00", "credit": "0"},
    {"account": "2000", "debit": "0", "credit": "2100.00"},
]


def test_a_signed_approval_verifies():
    keys = new_key_pair()
    signature = sign(keys.private, "PKG-20817", "clerk", LINES)
    assert verify(keys.public, signature, "PKG-20817", "clerk", LINES)


def test_any_change_after_signing_breaks_it():
    keys = new_key_pair()
    signature = sign(keys.private, "PKG-20817", "clerk", LINES)
    other_amount = [{"account": "1210", "debit": "1900.00", "credit": "0"}, {"account": "2000", "debit": "0", "credit": "1900.00"}]
    other_account = [{"account": "6300", "debit": "2100.00", "credit": "0"}, LINES[1]]
    assert not verify(keys.public, signature, "PKG-20817", "clerk", other_amount)
    assert not verify(keys.public, signature, "PKG-20817", "clerk", other_account)
    assert not verify(keys.public, signature, "PKG-20817", "controller", LINES)
    assert not verify(keys.public, signature, "PKG-20822", "clerk", LINES)


def test_another_key_pair_cannot_verify_it():
    signature = sign(new_key_pair().private, "PKG-20817", "clerk", LINES)
    assert not verify(new_key_pair().public, signature, "PKG-20817", "clerk", LINES)


def test_amount_formatting_does_not_change_the_signature():
    keys = new_key_pair()
    signature = sign(keys.private, "PKG-20817", "clerk", LINES)
    same = [{"account": "1210", "debit": "2100", "credit": "0.00"}, {"account": "2000", "debit": "0.0", "credit": "2100.0"}]
    assert verify(keys.public, signature, "PKG-20817", "clerk", same)


def test_garbage_signatures_are_rejected_not_crashing():
    keys = new_key_pair()
    assert not verify(keys.public, "not-base64!!", "PKG-20817", "clerk", LINES)
    assert not verify(keys.public, "", "PKG-20817", "clerk", LINES)
