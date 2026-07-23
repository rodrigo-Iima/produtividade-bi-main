from decimal import Decimal

import pytest

from etl.clockify import ClockifyService


def test_classifies_capacity_squad_and_role_groups():
    service = ClockifyService()

    assert service._classify_clockify_group("30h") == (
        "capacity",
        Decimal("30"),
    )
    assert service._classify_clockify_group(" 40h ") == (
        "capacity",
        Decimal("40"),
    )
    assert service._classify_clockify_group("Squad Núcleo") == ("squad", None)
    assert service._classify_clockify_group("Papel - Desenvolvedor") == (
        "papel",
        None,
    )


def test_resolves_users_from_all_group_types():
    groups = [
        {"id": "capacity-30", "name": "30h", "userIds": ["u1"]},
        {"id": "capacity-40", "name": "40h", "userIds": ["u2"]},
        {"id": "squad", "name": "Squad Núcleo", "userIds": ["u1", "u2"]},
        {"id": "role", "name": "Papel - Desenvolvedor", "userIds": ["u1"]},
    ]

    roles, squads, capacity = ClockifyService()._resolve_user_groups(groups)

    assert roles == {"u1": "Desenvolvedor"}
    assert squads == {"u1": "Núcleo", "u2": "Núcleo"}
    assert capacity == {"u1": Decimal("30"), "u2": Decimal("40")}


def test_rejects_conflicting_capacity_membership():
    groups = [
        {"id": "capacity-30", "name": "30h", "userIds": ["u1"]},
        {"id": "capacity-40", "name": "40h", "userIds": ["u1"]},
    ]

    with pytest.raises(ValueError, match="mais de um grupo de capacidade"):
        ClockifyService()._resolve_user_groups(groups)
