from datetime import date, timedelta
from typing import List, Tuple, Dict, Any


# Squad mappings: (squad_jira, squad_padrao)
SQUAD_MAPPINGS: List[Tuple[str, str]] = [
    ("Sem Squad", "Sem Squad"),
    ("ZGT - Evolução", "ZGT - Evolução"),
    ("ZGT - Novas Operadoras", "ZGT - Operadoras"),
    ("ZGT - Rede D'or", "ZGT - RDSL"),
    ("ZGT - Sustentação", "ZGT - Sustentação"),
    ("Operadoras", "Operadoras"),
    ("Núcleo", "Núcleo"),
    ("Rede D'Or - Zero Glosa", "RDSL"),
    ("Analytics", "Descontinuada"),
    ("Monitoramento SRE", "Monitoramento"),
    ("Frente Compartilhada (PrevOps)", "Descontinuada"),
    ("SWAT", "Descontinuada"),
    ("Transversal", "Transversal"),  # Clockify-only squad (no Jira tickets)
]


# Status agrupado mappings
STATUS_CONCLUIDOS: List[str] = [
    "Concluído", "Inválido", "Enviado para evolução", "Showcase"
]

STATUS_NAO_CONCLUIDOS: List[str] = [
    "Backlog", "Em andamento", "Dev", "QA", "Ready 4 Dev", "Ready 4 Devcheck",
    "Ready 4 QA", "Pendência Interna", "Pendencia Interna", "Pendencia Externa",
    "Pendência Externa", "Em Análise", "Ready 4 Correção", "On Hold", "Travado",
    "Aguardando início", "Tarefas pendentes", "Devcheck", "Pronto para Desenvolvimento",
    "Ready 4 Showcase"
]

STATUS_MAPPINGS: List[Tuple[str, str]] = [
    *( (s, "Concluído") for s in STATUS_CONCLUIDOS ),
    *( (s, "Não Concluído") for s in STATUS_NAO_CONCLUIDOS ),
]


# Calendário configuration - Keep only 2026
CALENDARIO_START_DATE = date(2026, 1, 1)
CALENDARIO_END_DATE = date(2026, 12, 31)

MONTH_NAMES: Dict[int, str] = {
    1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril", 5: "Maio", 6: "Junho",
    7: "Julho", 8: "Agosto", 9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro"
}

DAY_NAMES: Dict[int, str] = {
    0: "Segunda-feira", 1: "Terça-feira", 2: "Quarta-feira", 3: "Quinta-feira",
    4: "Sexta-feira", 5: "Sábado", 6: "Domingo"
}


def generate_calendario_records(
    start_date: date = CALENDARIO_START_DATE,
    end_date: date = CALENDARIO_END_DATE,
    reference_date: date | None = None
) -> List[Dict[str, Any]]:
    """Generate calendar records as plain dicts (no ORM dependencies)."""
    if reference_date is None:
        reference_date = date.today()

    records = []
    current = start_date

    while current <= end_date:
        weekday_idx = current.weekday()
        dia_util = weekday_idx < 5

        records.append({
            "data": current,
            "ano": current.year,
            "mes_numero": current.month,
            "mes_nome": MONTH_NAMES[current.month],
            "dia_semana": DAY_NAMES[weekday_idx],
            "dia_util": dia_util,
            "dia_do_mes": current.day
        })
        current += timedelta(days=1)

    return records
