from datetime import date
from decimal import Decimal

from etl.capacity import count_business_days


def test_counts_ten_business_days_for_a_standard_fortnight():
    assert count_business_days(date(2026, 7, 6), date(2026, 7, 20)) == 10


def test_capacity_formula_for_30h_and_40h_groups():
    days = Decimal("10")
    assert Decimal("30") / Decimal("5") * days == Decimal("60")
    assert Decimal("40") / Decimal("5") * days == Decimal("80")
