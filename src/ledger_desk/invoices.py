"""The sample invoices: one YAML file each in invoices/, holding the invoice as printed and the
result the checks must produce. The YAML is the ground truth: the PDF and
the phone photo are rendered from it, and the evals grade against it.

Amounts are read through str() into Decimal, so a YAML float can never sneak in as binary money.
"""

from __future__ import annotations

import copy
import dataclasses
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

import yaml

from .company import Bank, money

INVOICES = Path(__file__).resolve().parents[2] / "invoices"
VARIANTS = Path(__file__).resolve().parents[2] / "evals" / "variants.yaml"
HARD = Path(__file__).resolve().parents[2] / "evals" / "hard.yaml"


@dataclass
class Line:
    description: str
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal
    po_line: int | None = None


@dataclass
class Invoice:
    kind: str  # "invoice" or "credit_memo"
    vendor_name: str
    vendor_tax_id: str | None
    number: str
    date: date
    po: str | None
    remit_to: Bank
    lines: list[Line]
    subtotal: Decimal
    tax: Decimal
    total: Decimal
    notes: list[str] = field(default_factory=list)
    refers_to: str | None = None


@dataclass
class Case:
    id: str
    slug: str
    document: str  # "pdf" or "photo"
    what_is_wrong: str
    invoice: Invoice
    expected: dict
    layout: str | None = None  # an eval variant may print in another vendor's layout
    printed_total: Decimal | None = None  # set when a wrong printed total is the point
    known_limit: bool = False  # the expected answer is right, and the rules are known to miss it
    base: str | None = None  # the sample a variant was made from
    render: dict | None = None  # renderer options for the hard tier: skew, blur, low resolution...


def _dec(value) -> Decimal:
    return Decimal(str(value))


def parse_invoice(raw: dict) -> Invoice:
    return Invoice(
        kind=raw.get("kind", "invoice"),
        vendor_name=raw["vendor_name"],
        vendor_tax_id=raw.get("vendor_tax_id"),
        number=str(raw["number"]),
        date=raw["date"] if isinstance(raw["date"], date) else date.fromisoformat(str(raw["date"])),
        po=raw.get("po"),
        remit_to=Bank(raw["remit_to"]["bank"], str(raw["remit_to"]["account_last4"])),
        lines=[
            Line(
                description=l["description"],
                quantity=_dec(l["quantity"]),
                unit_price=_dec(l["unit_price"]),
                amount=money(l["amount"]),
                po_line=l.get("po_line"),
            )
            for l in raw["lines"]
        ],
        subtotal=money(raw["subtotal"]),
        tax=money(raw.get("tax", "0")),
        total=money(raw["total"]),
        notes=list(raw.get("notes", [])),
        refers_to=raw.get("refers_to"),
    )


def load_file(path: Path) -> Case:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Case(
        id=str(raw["id"]),
        slug=path.stem,
        document=raw.get("document", "pdf"),
        what_is_wrong=raw.get("what_is_wrong", ""),
        invoice=parse_invoice(raw["invoice"]),
        expected=raw["expected"],
    )


def load_all(folder: Path = INVOICES) -> list[Case]:
    return [load_file(p) for p in sorted(folder.glob("*.yaml"))]


def load_case(case_id: str, folder: Path = INVOICES) -> Case:
    matches = sorted(folder.glob(f"{case_id}-*.yaml"))
    if len(matches) != 1:
        raise FileNotFoundError(f"expected one invoice file for {case_id}, found {len(matches)}")
    return load_file(matches[0])


def _variant(spec: dict, bases: dict[str, Case]) -> Case:
    """One eval variant: its base sample with only the listed changes. Line amounts, subtotal and
    total are recomputed so the document adds up, unless a wrong printed total is the point."""
    base = bases[str(spec["base"])]
    inv = copy.deepcopy(base.invoice)
    generated = spec.get("replace_lines")
    if generated:  # a long statement: count lines at a stepped price, quantity 1 each
        start, step = _dec(generated["unit_price_start"]), _dec(generated["unit_price_step"])
        inv.lines = [
            Line(generated["description"].format(n=n), Decimal(1), start + step * (n - 1), money(start + step * (n - 1)))
            for n in range(1, int(generated["count"]) + 1)
        ]
    for i, change in enumerate(spec.get("lines", [])):
        line = inv.lines[i]
        quantity = _dec(change.get("quantity", line.quantity))
        unit_price = _dec(change.get("unit_price", line.unit_price))
        inv.lines[i] = dataclasses.replace(line, quantity=quantity, unit_price=unit_price, amount=money(quantity * unit_price))
    if spec.get("lines") or generated:  # only then: a base's own wrong total (sample 04) must survive a layout change
        inv.subtotal = money(sum((l.amount for l in inv.lines), Decimal(0)))
        inv.total = inv.subtotal + inv.tax
    if "notes" in spec:
        inv.notes = list(spec["notes"])
    if "remit_account_last4" in spec:
        inv.remit_to = Bank(inv.remit_to.bank, str(spec["remit_account_last4"]))
    printed = spec.get("printed_total")
    if printed is not None:
        inv.total = money(printed)
    expected = base.expected if spec.get("expected", "same") == "same" else spec["expected"]
    return Case(
        id=spec["id"],
        slug=f"{spec['id']}-{base.slug}",
        document=spec.get("document", base.document),
        what_is_wrong=spec["what"],
        invoice=inv,
        expected=expected,
        layout=spec.get("layout"),
        printed_total=None if printed is None else money(printed),
        known_limit=bool(spec.get("known_limit", False)),
        base=base.id,
        render=spec.get("render"),
    )


def load_variants(path: Path = VARIANTS) -> list[Case]:
    bases = {c.id: c for c in load_all()}
    return [_variant(spec, bases) for spec in yaml.safe_load(path.read_text(encoding="utf-8"))]


def load_eval_set() -> list[Case]:
    """The 50 cases the eval grades: the 13 samples, then the 37 variants."""
    return load_all() + load_variants()


def load_hard_set() -> list[Case]:
    """The hard tier: harder documents, graded the same way, reported apart from the standard 50."""
    return load_variants(HARD)
