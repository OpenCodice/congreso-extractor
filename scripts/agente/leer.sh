#!/usr/bin/env bash
# Lanza al agente (Claude Code) sobre las páginas que el parser no pudo leer
# (ver congreso/lecturas.py): escribe una propuesta.json por fallo, que
# `python -m congreso lecturas verificar` acepta o rechaza.
#
# Entorno: CONGRESO_FALLOS (carpeta de fallos), CLAUDE_CODE_OAUTH_TOKEN;
# opcionales AGENTE_MAX_TURNOS, AGENTE_MODELO. Este paso no debe recibir ningún
# otro secreto: el agente lee páginas de fuentes externas.
set -euo pipefail

EXTRACTOR="$(cd "$(dirname "$0")/../.." && pwd)"
mkdir -p "$CONGRESO_FALLOS"
pendientes=$(find "$CONGRESO_FALLOS" -name fallo.json 2>/dev/null | while read -r f; do
  [ -f "$(dirname "$f")/propuesta.json" ] || echo "$f"; done | wc -l | tr -d ' ')
if [ "$pendientes" = 0 ]; then
  echo "Sin páginas por leer."
  exit 0
fi
command -v claude > /dev/null || npm install -g @anthropic-ai/claude-code > /dev/null
texto="$(sed -e "s#__FALLOS__#$CONGRESO_FALLOS#g" -e "s#__EXTRACTOR__#$EXTRACTOR#g" "$EXTRACTOR/scripts/agente/brief-leer.md")"
log="$CONGRESO_FALLOS/agente-leer-$(date -u +%H%M%S).log"
(cd "$CONGRESO_FALLOS" && claude -p "$texto" \
  --max-turns "${AGENTE_MAX_TURNOS:-150}" \
  --permission-mode acceptEdits \
  --allowedTools Bash Read Write Glob Grep \
  --model "${AGENTE_MODELO:-claude-sonnet-5-5}" \
  > "$log" 2>&1) || echo "::warning::El agente lector terminó con error (ver $log)."
tail -n 5 "$log" || true
