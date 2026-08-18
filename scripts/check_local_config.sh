#!/usr/bin/env bash

# Safe preflight for the local Jira/Clockify/Flow runtime. It reports names,
# modes and missing placeholders, never values of credentials or tokens.

set -Eeuo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_DIR="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
COMPOSE_ENV_FILE="$PROJECT_DIR/deploy/local/.env"
RUNTIME_ENV_FILE="$PROJECT_DIR/deploy/local/runtime.env"
CHECK_JIRA=0

usage() {
  cat <<'EOF'
Uso:
  scripts/check_local_config.sh [--probe-jira]

Opções:
  --probe-jira  faz uma chamada Jira autenticada e informa apenas o status HTTP
  -h, --help    mostra esta ajuda

Sem --probe-jira, o comando é offline e só valida arquivos, placeholders e
regras de operação. Nenhum segredo é exibido.
EOF
}

failures=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --probe-jira) CHECK_JIRA=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERRO: opção desconhecida: $1" >&2; exit 2 ;;
  esac
done

require_file() {
  if [ ! -f "$1" ]; then
    echo "[FALHA] arquivo ausente: $1"
    failures=$((failures + 1))
  fi
}

require_file "$COMPOSE_ENV_FILE"
require_file "$RUNTIME_ENV_FILE"
[ "$failures" -eq 0 ] || exit 1

set -a
# shellcheck disable=SC1090
. "$COMPOSE_ENV_FILE"
# shellcheck disable=SC1090
. "$RUNTIME_ENV_FILE"
set +a

placeholder_pattern='(replace-with|your-domain|your-email|change-me|replace-with-workspace-id|<segredo>)'
for file in "$COMPOSE_ENV_FILE" "$RUNTIME_ENV_FILE"; do
  if grep -Eiq "$placeholder_pattern" "$file"; then
    echo "[FALHA] ainda há placeholders em $(basename "$file")"
    failures=$((failures + 1))
  fi
done

required_value() {
  local name="$1"
  local value="${!name:-}"
  if [ -z "$value" ]; then
    echo "[FALHA] variável ausente: $name"
    failures=$((failures + 1))
  fi
}

required_value JIRA_URL
required_value JIRA_EMAIL
required_value JIRA_TOKEN

if [ "${FLOW_ENABLED:-false}" = "true" ]; then
  required_value FLOW_LOGIN_URL
  if [ -z "${FLOW_API_TOKEN:-}" ]; then
    required_value FLOW_LOGIN_USERNAME
    required_value FLOW_LOGIN_PASSWORD
  fi
fi

echo "[OK] configuração local carregada sem exibir credenciais"
echo "[INFO] Jira: ${JIRA_URL}"
echo "[INFO] Epic Link legado: ${JIRA_EPIC_LINK_FIELD:-não configurado (parent nativo)}"
echo "[INFO] Campo início planejado: ${JIRA_PLANNED_START_FIELD:-não configurado}"
echo "[INFO] Flow habilitado: ${FLOW_ENABLED:-false}"
echo "[INFO] Identidades Flow: ${FLOW_IDENTITY_SYNC_ENABLED:-true}"
echo "[INFO] Fechamento de competência: dia ${HOURS_COMPETENCE_CLOSING_DAY:-25}"
echo "[INFO] Tolerância ponto × Clockify: ${HOURS_RECONCILIATION_TOLERANCE_MINUTES:-15} minutos"

if [ "$CHECK_JIRA" -eq 1 ]; then
  command -v curl >/dev/null 2>&1 || {
    echo "[FALHA] curl não encontrado para --probe-jira"
    failures=$((failures + 1))
  }
  if [ "$failures" -eq 0 ]; then
    jira_url="${JIRA_URL%/}"
    http_status="$(curl -sS -o /dev/null -w '%{http_code}' \
      --connect-timeout 10 --max-time 30 \
      --config <(printf 'user = "%s:%s"\n' "$JIRA_EMAIL" "$JIRA_TOKEN") \
      "$jira_url/rest/api/2/myself" || true)"
    case "$http_status" in
      2??) echo "[OK] probe Jira autenticado: HTTP $http_status" ;;
      *) echo "[FALHA] probe Jira retornou HTTP ${http_status:-sem resposta}"; failures=$((failures + 1)) ;;
    esac
  fi
fi

if [ "$failures" -gt 0 ]; then
  echo "Configuração pendente: $failures verificação(ões) falharam." >&2
  exit 1
fi

echo "Configuração pronta para a execução solicitada."
