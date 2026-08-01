from datetime import date
from decimal import Decimal

from database.migrations.phase22 import TIMEBOX_CARD_VIEW_SQL
from etl.capacity import count_business_days, is_non_working_flow_kind


def test_counts_ten_business_days_for_a_standard_fortnight():
    assert count_business_days(date(2026, 7, 6), date(2026, 7, 20)) == 10


def test_capacity_formula_for_30h_and_40h_groups():
    days = Decimal("10")
    assert Decimal("30") / Decimal("5") * days == Decimal("60")
    assert Decimal("40") / Decimal("5") * days == Decimal("80")


def test_flow_non_working_kinds_reduce_timebox_capacity():
    assert is_non_working_flow_kind("Compensado")
    assert is_non_working_flow_kind("FÉRIAS")
    assert is_non_working_flow_kind("Repouso Remunerado")
    assert is_non_working_flow_kind(" ocorrência ")
    assert not is_non_working_flow_kind("Trabalhado")
    assert not is_non_working_flow_kind(None)


def test_timebox_card_view_keeps_capacity_point_and_clockify_separate():
    assert "timebox_hours" in TIMEBOX_CARD_VIEW_SQL
    assert "hours_worked" in TIMEBOX_CARD_VIEW_SQL
    assert "hours_logged" in TIMEBOX_CARD_VIEW_SQL
    assert "clockify_to_point_pct" in TIMEBOX_CARD_VIEW_SQL
    assert "America/Sao_Paulo" in TIMEBOX_CARD_VIEW_SQL
