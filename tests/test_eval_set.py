"""The eval set: the 13 samples plus 37 variants, 50 cases, each with its
expected result written by hand in `evals/variants.yaml`, never computed by the rules it grades.

The rules run on each variant's ground truth must agree with the hand-written answer, except where
a variant is marked as a known limit: the instruction-in-the-invoice check is a keyword list, and
one variant says it without any of the keywords. That case is in the set on purpose, so the eval
reports the limit instead of hiding it.
"""

from decimal import Decimal

import pytest

from ledger_desk.company import build_company
from ledger_desk.documents import layout_for, render_case
from ledger_desk.invoices import load_all, load_eval_set, load_variants
from ledger_desk.reading import document_text
from ledger_desk.rules import check


@pytest.fixture(scope="module")
def variants():
    return load_variants()


def test_the_set_is_the_13_samples_plus_37_variants(variants):
    cases = load_eval_set()
    assert len(variants) == 37 and len(cases) == 50
    assert len({c.id for c in cases}) == 50
    assert [c.id for c in cases[:13]] == [c.id for c in load_all()]
    for v in variants:
        assert v.expected["status"] in ("ready", "exception") and v.expected["approver"] in ("clerk", "controller"), v.id
        assert v.what_is_wrong, v.id


def test_it_covers_what_section_9_asks_for(variants):
    base_layout = {v.id: layout_for(v.invoice.vendor_name) for v in variants}
    other_layouts = [v for v in variants if v.layout and v.layout != base_layout[v.id]]
    photos = [v for v in variants if v.document == "photo"]
    assert len(other_layouts) >= 9 and len(photos) >= 7
    whats = " ".join(v.what_is_wrong for v in variants)
    for phrase in ("just inside", "just outside", "exactly 2%", "exactly 25%", "$5,000"):
        assert phrase in whats, phrase
    assert sum(1 for v in variants if "SUSPICIOUS_TEXT" in {f["code"] for f in v.expected["flags"]}) >= 5


def test_every_variant_adds_up_unless_the_wrong_total_is_the_point(variants):
    for v in variants:
        inv = v.invoice
        for l in inv.lines:
            assert (l.quantity * l.unit_price).quantize(Decimal("0.01")) == l.amount, (v.id, l)
        wrong_total_is_the_point = v.printed_total is not None or "TOTALS_MISMATCH" in {f["code"] for f in v.expected["flags"]}
        adds_up = sum(l.amount for l in inv.lines) == inv.subtotal and inv.subtotal + inv.tax == inv.total
        assert adds_up != wrong_total_is_the_point, v.id  # sample 04's wrong total survives its layout variant


def _key(f):
    d = lambda x: None if x is None else Decimal(str(x))  # noqa: E731
    return (f["code"], d(f.get("amount")), d(f.get("quantity")))


def test_the_rules_agree_with_the_hand_written_answers_except_the_known_limit(variants):
    company = build_company()
    disagree = []
    for v in variants:
        r = check(v.invoice, company)
        got = (r.status, {_key({"code": f.code, "amount": f.amount, "quantity": f.quantity}) for f in r.flags}, r.approver, r.account)
        want = (v.expected["status"], {_key(f) for f in v.expected["flags"]}, v.expected["approver"], v.expected.get("account"))
        if got != want:
            disagree.append(v.id)
    known = [v.id for v in variants if v.known_limit]
    assert known and disagree == known


def test_every_variant_renders_in_its_own_layout_or_as_a_photo(variants, tmp_path):
    for v in variants:
        path = render_case(v, tmp_path)
        assert path.suffix == (".jpg" if v.document == "photo" else ".pdf"), v.id
        if v.document == "pdf":
            text = document_text(path)
            assert v.invoice.number in text and f"{v.invoice.total:,.2f}" in text, v.id
    assert len(list(tmp_path.glob("*.jpg"))) == sum(1 for v in variants if v.document == "photo")


def test_variants_use_only_the_fictional_vendors(variants):
    names = {v.name for v in build_company().vendors} | {"POS Software Vendor"}
    assert {v.invoice.vendor_name for v in variants} <= names
