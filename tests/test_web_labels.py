"""The web app words every flag the checks can raise (web/src/bills.ts LABELS). A code with no label
would show raw on the bookkeeper's screen, so a new flag in the rules fails here until it has one."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_every_flag_code_the_checks_raise_has_a_plain_label_on_screen():
    raised = set()
    for f in (ROOT / "src" / "ledger_desk").glob("*.py"):
        text = f.read_text(encoding="utf-8")
        # Flag("CODE", ...) in rules.py, and {"code": "CODE", ...} built as a dict (workflow.py SOURCE_NOT_FOUND)
        raised |= set(re.findall(r'Flag\(\s*"([A-Z_]+)"', text)) | set(re.findall(r'"code":\s*"([A-Z_]+)"', text))
    assert len(raised) >= 11  # the 11 codes in the rules on 2026-11-14
    labels = (ROOT / "web" / "src" / "bills.ts").read_text(encoding="utf-8")
    block = labels.split("const LABELS", 1)[1].split("}", 1)[0]
    labelled = set(re.findall(r"^\s*([A-Z_]+):", block, flags=re.M))
    assert raised - labelled == set()


def test_every_bill_the_walkthrough_opens_is_one_of_the_samples():
    from ledger_desk.invoices import load_all

    tour = (ROOT / "web" / "src" / "tour.ts").read_text(encoding="utf-8")
    named = re.findall(r"bill:\s*'([^']+)'", tour)
    assert len(named) >= 4  # the walkthrough's four bills on 2026-11-14
    numbers = {c.invoice.number for c in load_all()}
    assert set(named) - numbers == set()
