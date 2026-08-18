#!/usr/bin/env bash

# Portable local runner for macOS launchd/cron. It orchestrates the local
# Docker Compose services and never prints the contents of either env file.

set -Eeuo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_DIR="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="$PROJECT_DIR/deploy/local/compose.yaml"
COMPOSE_ENV_FILE="$PROJECT_DIR/deploy/local/.env"
RUNTIME_ENV_FILE="$PROJECT_DIR/deploy/local/runtime.env"
MODE="incremental"
RETRIES=0
RETRY_DELAY=30
RETRIES_SET=0
RETRY_DELAY_SET=0
DRY_RUN=0
SKIP_MIGRATION=0
LOG_RETENTION_DAYS="${ETL_LOG_RETENTION_DAYS:-30}"
RETENTION_DAYS_SET=0
LOCK_DIR="$PROJECT_DIR/.runtime/locks/etl-local.lock"
LOG_DIR="$PROJECT_DIR/.runtime/logs"
STATUS_FILE="$LOG_DIR/last-run.status"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
LOG_FILE="$LOG_DIR/run-${RUN_ID}.log"

usage() {
  cat <<'EOF'
Uso:
  scripts/run_etl_local.sh [opções]

Opções:
  --mode incremental|reconcile  incremental por hora (padrão) ou reconciliação diária completa
  --compose-env-file PATH       arquivo deploy/local/.env
  --runtime-env-file PATH       arquivo deploy/local/runtime.env
  --retries N                   tentativas do comando de projeto (padrão: ETL_RETRIES ou 0)
  --retry-delay N               espera entre tentativas em segundos (padrão: ETL_RETRY_DELAY ou 30)
  --skip-migration              não executa backup/migration (uso excepcional)
  --retention-days N            retenção dos logs (padrão: 30)
  --dry-run                     valida configuração e mostra o plano sem executar Docker
  -h, --help                    mostra esta ajuda

O modo incremental executa: PostgreSQL healthy, backup, migration e
run-projects --resume. O modo reconcile executa também o backfill completo
dos Epics e reconcile-projects.
EOF
}

die() {
  echo "[run_etl_local] ERRO: $*" >&2
  if [ "${DRY_RUN:-0}" -eq 0 ] && [ -n "${STATUS_FILE:-}" ]; then
    mkdir -p "$LOG_DIR" 2>/dev/null || true
    {
      printf 'status=failed\n'
      printf 'exit_code=1\n'
      printf 'mode=%s\n' "${MODE:-unknown}"
      printf 'started_at=%s\n' "${started_at:-unknown}"
      printf 'finished_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
      printf 'message=%s\n' "$*"
    } > "$STATUS_FILE" 2>/dev/null || true
  fi
  exit 1
}

positive_integer() {
  case "$1" in
    ''|*[!0-9]*) return 1 ;;
    *) [ "$1" -ge 0 ] ;;
  esac
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --mode)
      [ "$#" -ge 2 ] || die "--mode exige um valor"
      MODE="$2"
      shift 2
      ;;
    --compose-env-file)
      [ "$#" -ge 2 ] || die "--compose-env-file exige um caminho"
      COMPOSE_ENV_FILE="$2"
      shift 2
      ;;
    --runtime-env-file)
      [ "$#" -ge 2 ] || die "--runtime-env-file exige um caminho"
      RUNTIME_ENV_FILE="$2"
      shift 2
      ;;
    --retries)
      [ "$#" -ge 2 ] || die "--retries exige um valor"
      RETRIES="$2"
      RETRIES_SET=1
      shift 2
      ;;
    --retry-delay)
      [ "$#" -ge 2 ] || die "--retry-delay exige um valor"
      RETRY_DELAY="$2"
      RETRY_DELAY_SET=1
      shift 2
      ;;
    --skip-migration)
      SKIP_MIGRATION=1
      shift
      ;;
    --retention-days)
      [ "$#" -ge 2 ] || die "--retention-days exige um valor"
      LOG_RETENTION_DAYS="$2"
      RETENTION_DAYS_SET=1
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "opção desconhecida: $1"
      ;;
  esac
done

case "$MODE" in
  incremental|reconcile) ;;
  *) die "--mode deve ser incremental ou reconcile" ;;
esac

[ -f "$COMPOSE_FILE" ] || die "Compose não encontrado: $COMPOSE_FILE"
[ -f "$COMPOSE_ENV_FILE" ] || die "Ambiente do Compose não encontrado: $COMPOSE_ENV_FILE"
[ -f "$RUNTIME_ENV_FILE" ] || die "Ambiente do ETL não encontrado: $RUNTIME_ENV_FILE"

# Export the local files explicitly so validation and child commands use the
# same values. Values are never echoed to the log.
set -a
# shellcheck disable=SC1090
. "$COMPOSE_ENV_FILE"
# shellcheck disable=SC1090
. "$RUNTIME_ENV_FILE"
set +a

: "${LOCAL_POSTGRES_DB:=produtividade_local}"
: "${LOCAL_POSTGRES_MIGRATOR_USER:=produtividade_migrator}"
# Compose resolves env_file relative to --project-directory. Use the
# absolute path so the runner behaves identically from cron, launchd or a
# terminal in any working directory.
LOCAL_RUNTIME_ENV_FILE="$RUNTIME_ENV_FILE"
export LOCAL_RUNTIME_ENV_FILE
if [ "$RETRIES_SET" -eq 0 ] && [ -n "${ETL_RETRIES:-}" ]; then
  RETRIES="$ETL_RETRIES"
fi
if [ "$RETRY_DELAY_SET" -eq 0 ] && [ -n "${ETL_RETRY_DELAY:-}" ]; then
  RETRY_DELAY="$ETL_RETRY_DELAY"
fi
if [ "$RETENTION_DAYS_SET" -eq 0 ] && [ -n "${ETL_LOG_RETENTION_DAYS:-}" ]; then
  LOG_RETENTION_DAYS="$ETL_LOG_RETENTION_DAYS"
fi
positive_integer "$RETRIES" || die "--retries/ETL_RETRIES deve ser um inteiro não negativo"
positive_integer "$RETRY_DELAY" || die "--retry-delay/ETL_RETRY_DELAY deve ser um inteiro não negativo"
positive_integer "$LOG_RETENTION_DAYS" || die "--retention-days/ETL_LOG_RETENTION_DAYS deve ser um inteiro não negativo"

mkdir -p "$LOG_DIR" "$PROJECT_DIR/.runtime/locks"

rotate_logs() {
  local old_log
  for old_log in "$LOG_DIR"/run-*.log; do
    [ -f "$old_log" ] || continue
    if [ "$(wc -c < "$old_log" | tr -d ' ')" -gt 5242880 ]; then
      mv "$old_log" "${old_log%.log}.1.log"
    fi
  done
  find "$LOG_DIR" -type f \( -name 'run-*.log' -o -name 'run-*.1.log' \) -mtime "+$LOG_RETENTION_DAYS" -delete
}

if [ "$DRY_RUN" -eq 0 ]; then
  rotate_logs
  # mkdir is atomic and provides a portable lock on macOS without flock.
  if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    if [ -f "$LOCK_DIR/pid" ] && kill -0 "$(cat "$LOCK_DIR/pid")" 2>/dev/null; then
      die "já existe uma execução em andamento (PID $(cat "$LOCK_DIR/pid"))"
    fi
    rm -f "$LOCK_DIR/pid"
    rmdir "$LOCK_DIR" 2>/dev/null || die "lock antigo não pôde ser removido: $LOCK_DIR"
    mkdir "$LOCK_DIR"
  fi
  printf '%s\n' "$$" > "$LOCK_DIR/pid"
  cleanup_lock() {
    rm -f "$LOCK_DIR/pid"
    rmdir "$LOCK_DIR" 2>/dev/null || true
  }
  trap cleanup_lock EXIT
  # Redirect to a durable per-run log. This avoids /dev/fd/process
  # substitution, which is unavailable in some macOS launchd/sandbox modes.
  # The status file is written by finish_run even when a command fails.
  exec >> "$LOG_FILE" 2>&1
fi

started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
finish_run() {
  local code="$1"
  local finished_at
  finished_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  if [ "$DRY_RUN" -eq 0 ]; then
    {
      printf 'status=%s\n' "$([ "$code" -eq 0 ] && printf success || printf failed)"
      printf 'exit_code=%s\n' "$code"
      printf 'mode=%s\n' "$MODE"
      printf 'started_at=%s\n' "$started_at"
      printf 'finished_at=%s\n' "$finished_at"
      printf 'log_file=%s\n' "$LOG_FILE"
    } > "$STATUS_FILE"
  fi
  if [ "$code" -eq 0 ]; then
    echo "[run_etl_local] sucesso mode=$MODE finished_at=$finished_at"
  else
    echo "[run_etl_local] falha exit_code=$code mode=$MODE log=$LOG_FILE" >&2
  fi
  return "$code"
}

on_error() {
  local code=$?
  set +e
  finish_run "$code"
  exit "$code"
}
trap on_error ERR

compose() {
  docker compose \
    --project-directory "$PROJECT_DIR" \
    --env-file "$COMPOSE_ENV_FILE" \
    -f "$COMPOSE_FILE" \
    "$@"
}

run_with_retries() {
  local attempt=1
  local total=$((RETRIES + 1))
  while [ "$attempt" -le "$total" ]; do
    echo "[run_etl_local] projeto attempt=$attempt/$total"
    if "$@"; then
      return 0
    fi
    if [ "$attempt" -lt "$total" ]; then
      echo "[run_etl_local] nova tentativa em ${RETRY_DELAY}s"
      sleep "$RETRY_DELAY"
    fi
    attempt=$((attempt + 1))
  done
  return 1
}

show_plan() {
  echo "[run_etl_local] dry-run project=$PROJECT_DIR mode=$MODE"
  echo "[run_etl_local] compose_env=$COMPOSE_ENV_FILE runtime_env=$RUNTIME_ENV_FILE"
  echo "[run_etl_local] 1. docker compose up -d postgres"
  if [ "$SKIP_MIGRATION" -eq 0 ]; then
    echo "[run_etl_local] 2. backup"
    echo "[run_etl_local] 3. migrate"
  fi
  if [ "$MODE" = "incremental" ]; then
    echo "[run_etl_local] 4. run-projects --resume (retries=$RETRIES)"
  else
    echo "[run_etl_local] 4. backfill-projects --from 2026-01-01 --resume"
    echo "[run_etl_local] 5. reconcile-projects --json"
  fi
}

if [ "$DRY_RUN" -eq 1 ]; then
  show_plan
  finish_run 0
  exit 0
fi

# launchd starts jobs with a minimal PATH; include the standard Docker Desktop
# locations used by Intel and Apple Silicon macOS installations.
export PATH="/opt/homebrew/bin:/usr/local/bin:${PATH:-/usr/bin:/bin:/usr/sbin:/sbin}"
command -v docker >/dev/null 2>&1 || die "Docker CLI não encontrada no PATH"
docker compose version >/dev/null 2>&1 || die "Docker Compose não está disponível"

echo "[run_etl_local] início=$started_at mode=$MODE project=$PROJECT_DIR"
echo "[run_etl_local] log=$LOG_FILE"

compose up -d postgres
healthy=0
for _attempt in $(seq 1 30); do
  if compose exec -T postgres pg_isready -U "$LOCAL_POSTGRES_MIGRATOR_USER" -d "$LOCAL_POSTGRES_DB" >/dev/null 2>&1; then
    healthy=1
    break
  fi
  sleep 2
done
[ "$healthy" -eq 1 ] || die "PostgreSQL não ficou saudável em 60 segundos"
echo "[run_etl_local] PostgreSQL saudável"

if [ "$SKIP_MIGRATION" -eq 0 ]; then
  echo "[run_etl_local] backup antes da migration"
  compose --profile tools run --rm backup
  echo "[run_etl_local] aplicação segura das migrations"
  compose --profile tools run --rm migrate
else
  echo "[run_etl_local] migration ignorada por opção explícita"
fi

if [ "$MODE" = "incremental" ]; then
  run_with_retries compose --profile jobs run --rm etl run-projects --resume
else
  run_with_retries compose --profile jobs run --rm etl backfill-projects --from 2026-01-01 --resume
  run_with_retries compose --profile jobs run --rm etl reconcile-projects --json
fi

finish_run 0
