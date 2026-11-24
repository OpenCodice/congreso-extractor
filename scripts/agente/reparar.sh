#!/usr/bin/env bash
# Lanza al agente (Claude Code) sobre las páginas que los parsers del Senado y
# la Gaceta no pudieron leer (ver `congreso/lecturas.py` y
# brief-reparar.md) y deja su cambio al código como parche, para que las
# compuertas (compuertas_reparar.py) lo prueben en otro job, sobre un checkout
# limpio que el agente no tocó.
#
# Entorno: TRABAJO, FALLOS (carpeta de fallos: {sha256}/pagina.html y
# fallo.json), CLAUDE_CODE_OAUTH_TOKEN; opcionales AGENTE_MAX_TURNOS,
# AGENTE_MODELO. Este paso no debe recibir ningún otro secreto: el agente lee
# páginas de sitios externos.
#
# Deja en $TRABAJO: arreglo.patch (vacío si no cambió nada), reparacion.json
# (lo que el agente dice haber resuelto), agente.log y brief.md.
set -euo pipefail

EXTRACTOR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$EXTRACTOR"
mkdir -p "$TRABAJO"
rm -f "$TRABAJO/arreglo.patch" "$TRABAJO/reparacion.json"
: > "$TRABAJO/arreglo.patch"

if ! ls "$FALLOS"/*/fallo.json > /dev/null 2>&1; then
  echo "Sin fallos: el agente no interviene."
  exit 0
fi

python3 - "$EXTRACTOR" "$FALLOS" "$TRABAJO" <<'PY'
import json, pathlib, sys
extractor, fallos, trabajo = map(pathlib.Path, sys.argv[1:])
lineas = []
for f in sorted(fallos.glob("*/fallo.json")):
    x = json.loads(f.read_text(encoding="utf-8"))
    lectura = pathlib.Path("lecturas", x["fuente"], x["tipo"], f"{x['sha256']}.json")
    lineas += [f"- `{x['sha256']}` — {x['fuente']}/{x['tipo']} {x['clave']}",
               f"  - url: {x['url']}" + (f" (POST {json.dumps(x['datos'], ensure_ascii=False)})" if x.get("datos") else ""),
               f"  - error: {x['error'][:300]}",
               f"  - lectura verificada: `{lectura}`" if (extractor / lectura).exists() else "  - sin lectura verificada"]
brief = (extractor / "scripts/agente/brief-reparar.md").read_text(encoding="utf-8")
for k, v in {"__EXTRACTOR__": str(extractor), "__FALLOS__": str(fallos), "__TRABAJO__": str(trabajo),
             "__SALIDA__": str(trabajo / "reparacion.json"),
             "__INDICE__": f"Fallos ({len(lineas) // 4}):\n\n" + "\n".join(lineas)}.items():
    brief = brief.replace(k, v)
(trabajo / "brief.md").write_text(brief, encoding="utf-8")
PY

base="$(git rev-parse HEAD)"
command -v claude > /dev/null || npm install -g @anthropic-ai/claude-code > /dev/null
claude -p "$(cat "$TRABAJO/brief.md")" \
  --max-turns "${AGENTE_MAX_TURNOS:-150}" \
  --permission-mode acceptEdits \
  --allowedTools Bash Read Write Edit Glob Grep \
  --model "${AGENTE_MODELO:-claude-opus-5-5}" \
  > "$TRABAJO/agente.log" 2>&1 || echo "::warning::El agente terminó con error (ver agente.log)."
tail -n 20 "$TRABAJO/agente.log" || true

# Todo lo que cambió respecto del commit de partida, aunque el agente haya
# hecho commits o creado archivos: las compuertas deciden qué se acepta.
git reset -q --soft "$base"
git add -A
git diff --cached --binary "$base" > "$TRABAJO/arreglo.patch"
git reset -q
if [ -s "$TRABAJO/arreglo.patch" ]; then
  echo "Archivos cambiados por el agente:"
  git apply --numstat "$TRABAJO/arreglo.patch" | cut -f3
else
  echo "El agente no cambió el código."
fi
