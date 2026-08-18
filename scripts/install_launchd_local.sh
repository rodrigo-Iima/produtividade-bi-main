#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_DIR="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
USER_HOME="${HOME:?HOME não está definido}"
LAUNCH_AGENTS_DIR="$USER_HOME/Library/LaunchAgents"
USER_ID="$(id -u)"

mkdir -p "$LAUNCH_AGENTS_DIR" "$PROJECT_DIR/.runtime/logs"

escape_sed_replacement() {
  printf '%s' "$1" | sed 's/[&|]/\\&/g'
}

escaped_project_dir="$(escape_sed_replacement "$PROJECT_DIR")"

install_one() {
  local template="$1"
  local output_name="$2"
  local output="$LAUNCH_AGENTS_DIR/$output_name"
  sed "s|__PROJECT_DIR__|$escaped_project_dir|g" "$SCRIPT_DIR/launchd/$template" > "$output"
  chmod 644 "$output"
  launchctl bootout "gui/$USER_ID" "$output" 2>/dev/null || true
  launchctl bootstrap "gui/$USER_ID" "$output"
  echo "Instalado: $output"
}

install_one \
  com.zgsolucoes.produtividade-bi.projects-hourly.plist.in \
  com.zgsolucoes.produtividade-bi.projects-hourly.plist
install_one \
  com.zgsolucoes.produtividade-bi.projects-daily.plist.in \
  com.zgsolucoes.produtividade-bi.projects-daily.plist

echo "Agendamentos ativos no domínio gui/$USER_ID."
