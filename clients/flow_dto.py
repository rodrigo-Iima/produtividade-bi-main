"""Allowlisted DTOs for the read-only Flow API integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any, Mapping
from zoneinfo import ZoneInfo


FLOW_TIMEZONE = ZoneInfo("America/Sao_Paulo")


class FlowPayloadError(ValueError):
    """Raised when a Flow response does not match the validated contract."""


@dataclass(frozen=True, slots=True)
class FlowPerson:
    """Allowlisted identity fields returned by ``/Pessoas``."""

    CORPORATE_EMAIL_TYPE = 1
    PERSONAL_EMAIL_TYPE = 2

    person_id: str
    name: str
    social_name: str | None
    corporate_email: str | None
    email: str | None
    is_active: bool

    @classmethod
    def from_api(cls, raw: Mapping[str, Any]) -> FlowPerson:
        electronic_addresses = raw.get("enderecosEletronicos") or []
        if not isinstance(electronic_addresses, list):
            raise FlowPayloadError("enderecosEletronicos deve ser uma lista")

        emails: dict[int, str] = {}
        for item in electronic_addresses:
            address = _required_mapping(item, "enderecosEletronicos")
            try:
                address_type = _required_int(
                    address.get("tipoDeEnderecoEletronico"),
                    "tipoDeEnderecoEletronico",
                )
            except FlowPayloadError:
                continue
            email = _normalize_email(address.get("endereco"))
            if address_type in {
                cls.CORPORATE_EMAIL_TYPE,
                cls.PERSONAL_EMAIL_TYPE,
            } and email:
                current = emails.get(address_type)
                if current is not None and current != email:
                    raise FlowPayloadError(
                        "Pessoa possui múltiplos e-mails do mesmo tipo"
                    )
                emails[address_type] = email

        return cls(
            person_id=_required_identifier(raw.get("id"), "id"),
            name=_required_text(raw.get("nome"), "nome"),
            social_name=_optional_text(raw.get("nomeSocial")),
            corporate_email=emails.get(cls.CORPORATE_EMAIL_TYPE),
            email=emails.get(cls.PERSONAL_EMAIL_TYPE),
            is_active=_required_int(raw.get("ativo"), "ativo") == 1,
        )


@dataclass(frozen=True, slots=True)
class FlowEmployeeContract:
    """Minimal employee/contract data needed to map Flow to Clockify."""

    person_id: str
    contract_id: str
    name: str
    social_name: str | None
    corporate_email: str | None
    email: str | None
    status: int
    admitted_at: datetime | None
    terminated_at: datetime | None
    establishment: str | None
    role: str | None
    function: str | None
    work_post: str | None
    hierarchy_circle: str | None
    sector: str | None
    unit: str | None

    @classmethod
    def from_api(cls, raw: Mapping[str, Any]) -> FlowEmployeeContract:
        """Build an allowlisted DTO and discard all unrelated PII fields."""
        return cls(
            person_id=_required_identifier(raw.get("idDaPessoa"), "idDaPessoa"),
            contract_id=_required_identifier(
                raw.get("idDoContrato"),
                "idDoContrato",
            ),
            name=_required_text(raw.get("nomeDaPessoa"), "nomeDaPessoa"),
            social_name=_optional_text(raw.get("nomeSocialDaPessoa")),
            corporate_email=_normalize_email(raw.get("emailCorporativo")),
            email=_normalize_email(raw.get("email")),
            status=_required_int(raw.get("situacao"), "situacao"),
            admitted_at=_optional_datetime(raw.get("dataDeAdmissao")),
            terminated_at=_optional_datetime(
                raw.get("dataDeRescisao") or raw.get("dataDaRescisao")
            ),
            establishment=_optional_text(raw.get("estabelecimento")),
            role=_optional_text(raw.get("cargo")),
            function=_optional_text(raw.get("funcao")),
            work_post=_optional_text(raw.get("postoDeTrabalho")),
            hierarchy_circle=_optional_text(raw.get("circuloHierarquico")),
            sector=_optional_text(raw.get("descricaoDoSetor")),
            unit=_optional_text(raw.get("descricaoDaUnidade")),
        )


@dataclass(frozen=True, slots=True)
class FlowPointDay:
    """Daily attendance data returned inside a Flow calculation period."""

    work_date: date
    day_starts_at: time | None
    kind: str | None
    confirmed: bool
    pending_calculation: bool
    expected_workload: str | None
    moments: tuple[datetime, ...]
    errors: tuple[str, ...]
    warnings: tuple[str, ...]

    @classmethod
    def from_api(cls, raw: Mapping[str, Any]) -> FlowPointDay:
        moments = raw.get("moments") or []
        if not isinstance(moments, list):
            raise FlowPayloadError("moments deve ser uma lista")

        return cls(
            work_date=_required_date(raw.get("master_date"), "master_date"),
            day_starts_at=_optional_time(raw.get("day_starts_at")),
            kind=_optional_text(raw.get("kind")),
            confirmed=_optional_bool(raw.get("confirmed"), "confirmed"),
            pending_calculation=_optional_bool(
                raw.get("pending_calculation"),
                "pending_calculation",
            ),
            expected_workload=_optional_text(raw.get("default_moments")),
            moments=tuple(
                _required_local_datetime(value, "moments")
                for value in moments
            ),
            errors=_string_tuple(raw.get("errors"), "errors"),
            warnings=_string_tuple(raw.get("warnings"), "warnings"),
        )


@dataclass(frozen=True, slots=True)
class FlowPointPeriod:
    """One attendance calculation period and its materialized days."""

    start_date: date
    end_date: date
    max_availability_date: date | None
    days: tuple[FlowPointDay, ...]

    @classmethod
    def from_api(cls, raw: Mapping[str, Any]) -> FlowPointPeriod:
        masters = raw.get("masters") or []
        if not isinstance(masters, list):
            raise FlowPayloadError("masters deve ser uma lista")

        return cls(
            start_date=_required_date(raw.get("start_date"), "start_date"),
            end_date=_required_date(raw.get("end_date"), "end_date"),
            max_availability_date=_optional_date(
                raw.get("max_availability_date")
            ),
            days=tuple(
                FlowPointDay.from_api(_required_mapping(day, "masters"))
                for day in masters
            ),
        )


@dataclass(frozen=True, slots=True)
class FlowPointMark:
    """One normalized clock marking derived from a Flow day."""

    person_id: str
    period_start: date
    period_end: date
    work_date: date
    marked_at: datetime
    order_in_day: int


@dataclass(frozen=True, slots=True)
class FlowPoints:
    """Normalized point response associated with the requested person ID."""

    person_id: str
    periods: tuple[FlowPointPeriod, ...]

    @classmethod
    def from_api(
        cls,
        person_id: str | int,
        raw: Mapping[str, Any],
    ) -> FlowPoints:
        periods = raw.get("periods") or []
        if not isinstance(periods, list):
            raise FlowPayloadError("periods deve ser uma lista")

        return cls(
            person_id=_required_identifier(person_id, "idPessoa"),
            periods=tuple(
                FlowPointPeriod.from_api(_required_mapping(period, "periods"))
                for period in periods
            ),
        )

    @property
    def marks(self) -> tuple[FlowPointMark, ...]:
        """Flatten all daily moments while preserving their order."""
        return tuple(
            FlowPointMark(
                person_id=self.person_id,
                period_start=period.start_date,
                period_end=period.end_date,
                work_date=day.work_date,
                marked_at=marked_at,
                order_in_day=order,
            )
            for period in self.periods
            for day in period.days
            for order, marked_at in enumerate(day.moments, start=1)
        )


def _required_mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FlowPayloadError(f"{field} deve ser um objeto")
    return value


def _required_identifier(value: Any, field: str) -> str:
    if value is None or isinstance(value, bool):
        raise FlowPayloadError(f"{field} obrigatório ausente")
    normalized = str(value).strip()
    if not normalized:
        raise FlowPayloadError(f"{field} obrigatório ausente")
    return normalized


def _required_text(value: Any, field: str) -> str:
    normalized = _optional_text(value)
    if normalized is None:
        raise FlowPayloadError(f"{field} obrigatório ausente")
    return normalized


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _normalize_email(value: Any) -> str | None:
    normalized = _optional_text(value)
    return normalized.casefold() if normalized else None


def _required_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise FlowPayloadError(f"{field} deve ser inteiro")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise FlowPayloadError(f"{field} deve ser inteiro") from exc


def _optional_bool(value: Any, field: str) -> bool:
    if value is None:
        return False
    if not isinstance(value, bool):
        raise FlowPayloadError(f"{field} deve ser booleano")
    return value


def _required_date(value: Any, field: str) -> date:
    parsed = _optional_date(value)
    if parsed is None:
        raise FlowPayloadError(f"{field} obrigatório ausente")
    return parsed


def _optional_date(value: Any) -> date | None:
    normalized = _optional_text(value)
    if normalized is None:
        return None
    try:
        return date.fromisoformat(normalized[:10])
    except ValueError as exc:
        raise FlowPayloadError(f"data inválida: {normalized!r}") from exc


def _optional_time(value: Any) -> time | None:
    normalized = _optional_text(value)
    if normalized is None:
        return None
    try:
        return time.fromisoformat(normalized)
    except ValueError as exc:
        raise FlowPayloadError(f"hora inválida: {normalized!r}") from exc


def _optional_datetime(value: Any) -> datetime | None:
    normalized = _optional_text(value)
    if normalized is None:
        return None
    return _parse_datetime(normalized)


def _required_local_datetime(value: Any, field: str) -> datetime:
    normalized = _optional_text(value)
    if normalized is None:
        raise FlowPayloadError(f"{field} contém data/hora vazia")
    return _parse_datetime(normalized)


def _parse_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise FlowPayloadError(f"data/hora inválida: {value!r}") from exc

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=FLOW_TIMEZONE)
    return parsed.astimezone(FLOW_TIMEZONE)


def _string_tuple(value: Any, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise FlowPayloadError(f"{field} deve ser uma lista")
    return tuple(str(item).strip() for item in value if str(item).strip())
