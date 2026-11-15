"""The example company is generated, not hand-typed, and must come out the same every time:
the duplicate check and the "usual amount" check compare against its history, and every eval
score depends on that history staying put."""

from decimal import Decimal

from ledger_desk.company import COMPANY_NAME, build_company, company_hash


def test_the_seed_is_deterministic():
    assert company_hash(build_company()) == company_hash(build_company())


def test_another_seed_gives_another_history():
    assert company_hash(build_company(seed=8)) != company_hash(build_company())


def test_the_company_and_its_vendors_are_generic_and_fictional():
    company = build_company()
    assert "fictional" in COMPANY_NAME.lower()
    names = [v.name for v in company.vendors]
    assert len(names) == 7, "the POS software vendor is deliberately missing from the vendor master"
    assert "POS Software Vendor" not in names


def test_six_months_of_history_and_a_known_utility_average():
    company = build_company()
    months = {b.date.strftime("%Y-%m") for b in company.bills}
    assert months == {"2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"}
    utility = company.vendor_by_name("Electric Utility")
    last_three = sorted((b for b in company.bills if b.vendor_id == utility.id), key=lambda b: b.date)[-3:]
    assert sum(b.total for b in last_three) / 3 == Decimal("1080.00")


def test_money_is_decimal_everywhere():
    company = build_company()
    for bill in company.bills:
        assert isinstance(bill.total, Decimal)
    for po in company.purchase_orders:
        for line in po.lines:
            assert isinstance(line.unit_price, Decimal)
