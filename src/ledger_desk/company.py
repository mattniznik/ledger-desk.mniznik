"""The example company: a fictional coffee roastery and what its ERP knows about its suppliers.

Everything here is generated, never hand-typed, from a fixed random seed, so every run builds the
same company. The duplicate check and the "usual amount" check compare against
this history, so the few facts they depend on are pinned instead of drawn: the electric utility's
last three bills average exactly $1,080.00, and the dairy supplier's paid October invoice DAI-5521
exists for invoice #7 to duplicate.

Names are generic on purpose: no real business's name for the company, the vendors, the
banks or the products. Tax ids start with 00, a prefix the IRS does not issue (inferred, not checked
against an IRS list), so none of them can belong to a real business. All of it lives in this one file.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from decimal import Decimal

COMPANY_NAME = "Coffee Roastery (fictional)"

CENT = Decimal("0.01")


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(CENT)


def due_date(invoice_date: str, terms_days: int) -> str | None:
    """The invoice date plus the vendor's terms, or None when the date is not an ISO date."""
    try:
        return (date.fromisoformat(invoice_date) + timedelta(days=terms_days)).isoformat()
    except ValueError:
        return None


@dataclass(frozen=True)
class Bank:
    bank: str
    account_last4: str


@dataclass(frozen=True)
class Vendor:
    id: str
    name: str
    tax_id: str
    category: str
    terms_days: int
    default_account: str
    bank: Bank
    uses_po: bool
    recurring: bool


@dataclass(frozen=True)
class Account:
    number: str
    name: str


@dataclass(frozen=True)
class POLine:
    line: int
    description: str
    quantity: Decimal
    unit_price: Decimal
    account: str


@dataclass(frozen=True)
class PurchaseOrder:
    number: str
    vendor_id: str
    date: date
    lines: tuple[POLine, ...]


@dataclass(frozen=True)
class Receipt:
    po: str
    line: int
    quantity: Decimal
    date: date


@dataclass(frozen=True)
class BilledLine:
    po_line: int
    quantity: Decimal


@dataclass(frozen=True)
class Bill:
    vendor_id: str
    number: str
    date: date
    total: Decimal
    po: str | None = None
    lines: tuple[BilledLine, ...] = ()
    status: str = "paid"


@dataclass
class Company:
    vendors: list[Vendor]
    accounts: list[Account]
    purchase_orders: list[PurchaseOrder]
    receipts: list[Receipt]
    bills: list[Bill]
    _by_id: dict[str, Vendor] = field(default_factory=dict, repr=False, compare=False)

    def vendor(self, vendor_id: str) -> Vendor | None:
        return next((v for v in self.vendors if v.id == vendor_id), None)

    def vendor_by_name(self, name: str) -> Vendor | None:
        return next((v for v in self.vendors if v.name.lower() == name.strip().lower()), None)

    def vendor_by_tax_id(self, tax_id: str | None) -> Vendor | None:
        return next((v for v in self.vendors if tax_id and v.tax_id == tax_id.strip()), None)

    def po(self, number: str | None) -> PurchaseOrder | None:
        return next((p for p in self.purchase_orders if number and p.number == number.strip()), None)

    def received(self, po: str, line: int) -> Decimal:
        return sum((r.quantity for r in self.receipts if r.po == po and r.line == line), Decimal(0))

    def already_billed(self, po: str, line: int) -> Decimal:
        return sum(
            (bl.quantity for b in self.bills if b.po == po for bl in b.lines if bl.po_line == line),
            Decimal(0),
        )

    def bills_for(self, vendor_id: str) -> list[Bill]:
        return sorted((b for b in self.bills if b.vendor_id == vendor_id), key=lambda b: b.date)


ACCOUNTS = [
    Account("1200", "Inventory - green coffee"),
    Account("1210", "Inventory - packaging"),
    Account("1500", "Equipment"),
    Account("2000", "Accounts payable"),
    Account("5100", "Dairy (cost of sales)"),
    Account("6200", "Utilities"),
    Account("6300", "Repairs and maintenance"),
    Account("6400", "Software"),
    Account("6500", "Freight in"),
]

BANK = "Example Bank"

VENDORS = [
    Vendor("V01", "Green Coffee Importer", "00-0000001", "green_coffee", 30, "1200", Bank(BANK, "1001"), True, False),
    Vendor("V02", "Dairy Supplier", "00-0000002", "dairy", 15, "5100", Bank(BANK, "2002"), True, False),
    Vendor("V03", "Packaging Supplier", "00-0000003", "packaging", 30, "1210", Bank(BANK, "3003"), True, False),
    Vendor("V04", "Roasting Equipment Supplier", "00-0000004", "equipment", 30, "6300", Bank(BANK, "4004"), True, False),
    Vendor("V05", "Espresso Repair Service", "00-0000005", "repairs", 0, "6300", Bank(BANK, "4417"), False, False),
    Vendor("V06", "Electric Utility", "00-0000006", "utilities", 20, "6200", Bank(BANK, "6006"), False, True),
    Vendor("V07", "Freight Carrier", "00-0000007", "freight", 30, "6500", Bank(BANK, "7007"), False, False),
    # The POS software vendor is deliberately absent: invoice #11 is a vendor nobody set up yet.
]

HISTORY_MONTHS = [(2026, m) for m in range(5, 11)]  # May to October 2026

# Pinned facts the checks depend on (see the module docstring).
UTILITY_PINNED = {(2026, 8): "1050.00", (2026, 9): "1080.00", (2026, 10): "1110.00"}
DAIRY_PAID_OCTOBER = ("DAI-5521", "462.00", Decimal("110"))  # number, total, gallons at $4.20


def build_company(seed: int = 7) -> Company:
    rng = random.Random(seed)
    pos: list[PurchaseOrder] = []
    receipts: list[Receipt] = []
    bills: list[Bill] = []
    po_counter = 1001
    number_counter = {v.id: 100 for v in VENDORS}

    def next_number(prefix: str, vendor_id: str) -> str:
        number_counter[vendor_id] += 1
        return f"{prefix}-{number_counter[vendor_id] + 1000}"

    def po_bill(vendor: Vendor, d: date, description: str, qty: Decimal, price: Decimal, account: str, number: str | None = None):
        nonlocal po_counter
        po_number = f"PO-{po_counter}"
        po_counter += 1
        pos.append(PurchaseOrder(po_number, vendor.id, d, (POLine(1, description, qty, price, account),)))
        receipts.append(Receipt(po_number, 1, qty, d))
        total = money(qty * price)
        bills.append(Bill(vendor.id, number or next_number(PREFIX[vendor.id], vendor.id), d, total, po_number, (BilledLine(1, qty),)))

    green, dairy, packaging, equipment, repairs, utility, freight = VENDORS
    for year, month in HISTORY_MONTHS:
        day = date(year, month, 10)
        po_bill(green, day, "Green coffee, 60 kg bag", Decimal(rng.randint(10, 30)), Decimal("310.00"), "1200")
        if (year, month) == (2026, 10):
            number, _total, gallons = DAIRY_PAID_OCTOBER
            po_bill(dairy, date(year, month, 14), "Whole milk, gallon", gallons, Decimal("4.20"), "5100", number=number)
        else:
            po_bill(dairy, date(year, month, 14), "Whole milk, gallon", Decimal(rng.randint(80, 140)), Decimal("4.20"), "5100")
        po_bill(packaging, date(year, month, 18), "Hot cup, 12 oz", Decimal(rng.choice([2000, 3000, 4000, 5000])), Decimal("0.38"), "1210")
        utility_total = UTILITY_PINNED.get((year, month)) or str(rng.randint(980, 1180)) + ".00"
        bills.append(Bill(utility.id, next_number(PREFIX[utility.id], utility.id), date(year, month, 5), money(utility_total)))
        bills.append(Bill(freight.id, next_number(PREFIX[freight.id], freight.id), date(year, month, 22), money(rng.randint(150, 400))))
        if month in (6, 9):
            bills.append(Bill(repairs.id, next_number(PREFIX[repairs.id], repairs.id), date(year, month, 3), money(rng.randint(180, 900))))
        if month == 7:
            po_bill(equipment, date(year, month, 25), "Chaff collector filter", Decimal(2), Decimal("145.00"), "6300")

    # Open purchase orders for this month's inbox. Not random: each one is
    # set up for a specific sample invoice.
    open_pos = [
        ("PO-1093", green, "Green coffee, 60 kg bag", "20", "310.00", "1200", "20"),  # 01: all received
        ("PO-1107", green, "Green coffee, 60 kg bag", "20", "310.00", "1200", "10"),  # 02: half received
        ("PO-1124", packaging, "Hot cup, 12 oz", "5000", "0.38", "1210", "5000"),  # 03: price variance
        ("PO-1130", dairy, "Whole milk, gallon", "120", "4.20", "5100", "100"),  # 06: 20 short
        ("PO-1101", equipment, "Roaster drum replacement", "1", "12400.00", "1500", "1"),  # 13: capital
    ]
    for number, vendor, description, qty, price, account, received in open_pos:
        pos.append(PurchaseOrder(number, vendor.id, date(2026, 11, 2), (POLine(1, description, Decimal(qty), Decimal(price), account),)))
        receipts.append(Receipt(number, 1, Decimal(received), date(2026, 11, 6)))
    # 04: two lines, both received in full; the invoice's printed total is $90.00 too high.
    pos.append(
        PurchaseOrder(
            "PO-1126",
            packaging.id,
            date(2026, 11, 2),
            (
                POLine(1, "Hot cup lid, 12 oz", Decimal(2000), Decimal("0.12"), "1210"),
                POLine(2, "Retail coffee bag, 340 g", Decimal(500), Decimal("0.85"), "1210"),
            ),
        )
    )
    receipts += [Receipt("PO-1126", 1, Decimal(2000), date(2026, 11, 6)), Receipt("PO-1126", 2, Decimal(500), date(2026, 11, 6))]

    return Company(list(VENDORS), list(ACCOUNTS), pos, receipts, bills)


PREFIX = {"V01": "GCI", "V02": "DAI", "V03": "PKG", "V04": "EQP", "V05": "REP", "V06": "UTL", "V07": "FRT"}


def _plain(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def company_hash(company: Company) -> str:
    """sha256 of the whole company as canonical JSON: equal hashes mean identical rows."""
    data = _plain(asdict(company))
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
