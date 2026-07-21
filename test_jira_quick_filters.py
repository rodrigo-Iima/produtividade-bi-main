"""Tests for Jira quick-filter parsing and shared Sprint mappings."""

from etl.jira_quick_filters import JiraQuickFilterService


def test_extracts_the_three_zgt_squad_filters():
    jql = (
        'project = ZGT AND "squad[dropdown]" = "ZGT - Evolução"'
    )
    assert JiraQuickFilterService.extract_squad_names(jql) == [
        "ZGT - Evolução"
    ]

    assert JiraQuickFilterService.extract_squad_names(
        '"squad[dropdown]" = "ZGT - Rede D\'or"'
    ) == ["ZGT - Rede D'or"]
    assert JiraQuickFilterService.extract_squad_names(
        '"squad[dropdown]" = "ZGT - Novas Operadoras"'
    ) == ["ZGT - Novas Operadoras"]


def test_ignores_quick_filters_without_squad_condition():
    assert JiraQuickFilterService.extract_squad_names(
        'status != Done AND project = ZGT'
    ) == []


def test_extracts_multiple_squads_from_a_single_or_filter():
    jql = (
        '"squad[dropdown]" = "ZGT - Evolução" OR '
        '"squad[dropdown]" = "ZGT - Rede D\'or"'
    )
    assert JiraQuickFilterService.extract_squad_names(jql) == [
        "ZGT - Evolução",
        "ZGT - Rede D'or",
    ]


def test_extracts_unquoted_single_word_squad_filter():
    assert JiraQuickFilterService.extract_squad_names(
        'project = ZG AND "squad[dropdown]" = Operadoras'
    ) == ["Operadoras"]


def test_maps_single_squad_board_names_to_clockify_squads():
    service = JiraQuickFilterService(client=object())
    aliases = {
        service._normalize("Operadoras"): 10,
        service._normalize("Núcleo"): 20,
        service._normalize("RDSL"): 30,
        service._normalize("Monitoramento"): 40,
        service._normalize("Transversal"): 50,
        service._normalize("ZGT - Sustentação"): 60,
    }

    assert service._board_name_squad_id(
        {"name": "Zero Glosa - Operadoras - Dev"}, aliases
    ) == 10
    assert service._board_name_squad_id(
        {"name": "Núcleo & Analytics - Sprint"}, aliases
    ) == 20
    assert service._board_name_squad_id(
        {"name": "Sprint SRE"}, aliases
    ) == 40
    assert service._board_name_squad_id(
        {"name": "ZG&ZGT - Squad PrevOps"}, aliases
    ) == 50
    assert service._board_name_squad_id(
        {"name": "UX/UI ZGT"}, aliases
    ) == 50
    assert service._board_name_squad_id(
        {"name": "QA Scrum"}, aliases
    ) == 50


def test_includes_sprints_starting_on_the_first_day_of_scope():
    from datetime import datetime, timezone

    from etl.sprint_scope import sprint_is_in_scope

    assert sprint_is_in_scope(
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        "closed",
        now=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
