from datetime import date

from sqlalchemy.orm import Session

from models.dim_calendario import DimCalendario
from models.dim_papel_tag import DimPapelTag
from models.dim_squad import DimSquad
from models.dim_squad_alias import DimSquadAlias
from models.dim_status import DimStatus
from models.dim_tag import DimTag
from providers.tags_provider import TagsProvider, normalize_tag

from .data import SQUAD_MAPPINGS, STATUS_MAPPINGS, generate_calendario_records


def load_dim_squad(session: Session) -> int:
    """Upsert standard squads and Jira/Clockify aliases."""
    standard_names = sorted({standard for _, standard in SQUAD_MAPPINGS})
    squad_ids: dict[str, int] = {}

    for name in standard_names:
        squad = session.query(DimSquad).filter(DimSquad.nome == name).first()
        if squad is None:
            squad = DimSquad(nome=name)
            session.add(squad)
            session.flush()
        squad_ids[name] = squad.squad_id

    for raw_name, standard_name in SQUAD_MAPPINGS:
        session.merge(DimSquadAlias(
            origem="jira",
            nome_bruto=raw_name,
            squad_id=squad_ids[standard_name],
        ))
        session.merge(DimSquadAlias(
            origem="clockify",
            nome_bruto=raw_name,
            squad_id=squad_ids[standard_name],
        ))

    for standard_name, squad_id in squad_ids.items():
        session.merge(DimSquadAlias(
            origem="clockify",
            nome_bruto=standard_name,
            squad_id=squad_id,
        ))

    print(f"[Seeding] Synced {len(squad_ids)} standard squads")
    return len(squad_ids)


def load_dim_status(session: Session) -> int:
    """Upsert Jira status groupings."""
    for original, grouped in STATUS_MAPPINGS:
        session.merge(DimStatus(
            status_original=original,
            status_agrupado=grouped,
        ))
    print(f"[Seeding] Synced {len(STATUS_MAPPINGS)} Jira statuses")
    return len(STATUS_MAPPINGS)


def load_dim_calendario(session: Session, reference_date: date | None = None) -> int:
    """Seed the calendar once for the configured date range."""
    if session.query(DimCalendario).first():
        return 0

    records = generate_calendario_records(reference_date=reference_date)
    session.bulk_insert_mappings(DimCalendario, records)
    print(f"[Seeding] Seeded {len(records)} calendar days")
    return len(records)


def load_dim_tags(session: Session) -> int:
    """Upsert tags and the role/tag focus matrix from the local CSV."""
    provider = TagsProvider()
    loaded = 0

    for row in provider.load():
        tag_name = row["tag_clockify"]
        normalized = normalize_tag(tag_name)
        tag = session.query(DimTag).filter(
            DimTag.nome_normalizado == normalized
        ).first()
        if tag is None:
            tag = DimTag(nome=tag_name, nome_normalizado=normalized)
            session.add(tag)
            session.flush()

        session.merge(DimPapelTag(
            papel=row["papel"],
            tag_id=tag.tag_id,
            foco=row["foco"],
        ))
        loaded += 1

    print(f"[Seeding] Synced {loaded} role/tag mappings")
    return loaded
