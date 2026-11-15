"""The hard tier of the eval: the standard 50 put Claude Opus 5.5 at its ceiling
(504 of 504 fields read, 2026-11-14, n=1 run), so they cannot rank a cheaper model. These cases
make the reading harder in measurable ways; each keeps a hand-written expected answer, and the
standard 50 stay unchanged so results stay comparable.
"""

from pathlib import Path

import pytest
from PIL import Image, ImageFilter, ImageStat
from pypdf import PdfReader

from ledger_desk.company import build_company
from ledger_desk.documents import ink_for, render_case
from ledger_desk.invoices import load_case, load_hard_set, load_variants
from ledger_desk.rules import check

from test_eval_set import _key


@pytest.fixture(scope="module")
def hard():
    return load_hard_set()


def sharpness(path: Path) -> float:
    """Mean edge strength of the image: lower is blurrier."""
    return ImageStat.Stat(Image.open(path).convert("L").filter(ImageFilter.FIND_EDGES)).mean[0]


def test_the_hard_tier_has_ten_cases_each_with_a_hand_written_answer(hard):
    assert [c.id for c in hard] == [f"h{i:02d}" for i in range(1, 11)]
    for c in hard:
        assert c.expected["status"] in ("ready", "exception") and c.what_is_wrong, c.id
        assert c.render or len(c.invoice.lines) > 30, c.id  # every case is harder in some stated way


def test_the_rules_agree_with_every_hard_answer(hard):
    company = build_company()
    for c in hard:
        r = check(c.invoice, company)
        got = (r.status, {_key({"code": f.code, "amount": f.amount, "quantity": f.quantity}) for f in r.flags}, r.approver, r.account)
        want = (c.expected["status"], {_key(f) for f in c.expected["flags"]}, c.expected["approver"], c.expected.get("account"))
        assert got == want, c.id


def test_a_hard_photo_is_measurably_blurrier_and_smaller_than_the_easy_one(hard, tmp_path):
    easy = render_case(next(c for c in load_variants() if c.id == "v10"), tmp_path / "easy")  # 01 as a standard photo
    h01 = render_case(next(c for c in hard if c.id == "h01"), tmp_path / "hard")
    assert sharpness(h01) < 0.8 * sharpness(easy)
    h03 = render_case(next(c for c in hard if c.id == "h03"), tmp_path / "hard")
    assert Image.open(h03).width < 0.5 * Image.open(easy).width  # low resolution


def test_the_long_freight_bill_runs_to_two_pages_and_keeps_every_line(hard, tmp_path):
    h07 = next(c for c in hard if c.id == "h07")
    path = render_case(h07, tmp_path)
    pages = PdfReader(path).pages
    assert len(pages) == 2
    text = " ".join(p.extract_text() for p in pages)
    assert all(f"${l.amount:,.2f}" in text for l in h07.invoice.lines)
    assert f"${h07.invoice.total:,.2f}" in pages[1].extract_text()  # the total is on page 2


def test_a_faint_total_is_drawn_in_light_ink(hard):
    h06 = next(c for c in hard if c.id == "h06")
    assert ink_for(h06, "total") > 150 and ink_for(load_case("10"), "total") < 60  # 0 is black, 255 white
