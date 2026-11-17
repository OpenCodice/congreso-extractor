#!/usr/bin/env bash
# Lanza al agente (Claude Code) sobre los decretos que `decretos` no pudo
# ligar a su expediente (ver `congreso/residuos.py`):
#
#   residuos.sh proponer   un agente elige el expediente y cita su evidencia
#   residuos.sh juzgar     otro agente, en otra sesión, confirma o rechaza lo que
#                          pasó la verificación determinista (`residuos para-juicio`)
#
# Entorno: TRABAJO (con pendientes.json), CLAUDE_CODE_OAUTH_TOKEN; opcionales
# AGENTE_MAX_TURNOS, AGENTE_MODELO. Este paso no debe recibir ningún otro
# secreto: el agente lee texto de fuentes externas.
set -euo pipefail

EXTRACTOR="$(cd "$(dirname "$0")/../.." && pwd)"
etapa="$1"
if ! python3 -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1]))["decretos"] else 1)' "$TRABAJO/pendientes.json"; then
  echo "Sin decretos por resolver."
  exit 0
fi
case "$etapa" in
  proponer) brief=brief-proponer.md; salida="$TRABAJO/propuestas.json" ;;
  juzgar)   brief=brief-juzgar.md;   salida="$TRABAJO/juicio.json"
            python3 -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1]))["decretos"] else 1)' \
              "$TRABAJO/propuestas-juicio.json" 2>/dev/null || { echo "Sin propuestas que juzgar."; exit 0; } ;;
  *) echo "etapa desconocida: $etapa" >&2; exit 2 ;;
esac
command -v claude > /dev/null || npm install -g @anthropic-ai/claude-code > /dev/null

texto="$(sed -e "s#__PENDIENTES__#$TRABAJO/pendientes.json#g" -e "s#__PROPUESTAS__#$TRABAJO/propuestas-juicio.json#g" \
             -e "s#__TRABAJO__#$TRABAJO#g" -e "s#__SALIDA__#$salida#g" "$EXTRACTOR/scripts/agente/$brief")"
# Desde el directorio de trabajo: este agente no edita código ni datos.
(cd "$TRABAJO" && claude -p "$texto" \
  --max-turns "${AGENTE_MAX_TURNOS:-80}" \
  --permission-mode acceptEdits \
  --allowedTools Bash Read Write Glob Grep \
  ${AGENTE_MODELO:+--model "$AGENTE_MODELO"} \
  > "$TRABAJO/agente-$etapa.log" 2>&1) || echo "::warning::El agente ($etapa) terminó con error (ver $TRABAJO/agente-$etapa.log)."
tail -n 5 "$TRABAJO/agente-$etapa.log" || true
