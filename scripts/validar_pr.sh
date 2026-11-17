#!/usr/bin/env bash
# Valida un PR de congreso-mexicano sobre el sha exacto de su cabeza: los
# invariantes del repo de datos (`python -m congreso validar`) y los commits
# (`scripts/validar_commits.py`: un Tipo por commit, solo sus carpetas, sin
# merges). Lo corre `.github/workflows/revisar-pr.yml` en un job sin secretos;
# solo con su resultado se fusiona.
#
# Uso: validar_pr.sh <número de PR> [sha esperado]
#
# Entorno: GH_TOKEN (basta lectura), TRABAJO (directorio de trabajo),
# GITHUB_OUTPUT (si existe, recibe `sha=<sha validado>`).
set -euo pipefail
trap 'echo "::error::validar_pr.sh se detuvo en la línea $LINENO."' ERR

repo=OpenCodice/congreso-mexicano
pr="${1:?uso: validar_pr.sh <PR> [sha]}"
esperado="${2:-}"
extractor="$(cd "$(dirname "$0")/.." && pwd)"
trabajo="${TRABAJO:-$(mktemp -d)}"
mkdir -p "$trabajo"

read -r estado sha base <<< "$(gh pr view "$pr" -R "$repo" --json state,headRefOid,baseRefName \
  -q '"\(.state) \(.headRefOid) \(.baseRefName)"')"
echo "PR #$pr de $repo: $estado, cabeza $sha, base $base"
case "$estado" in OPEN|MERGED) ;; *) echo "::error::El PR #$pr está cerrado."; exit 1 ;; esac
if [ -n "$esperado" ] && [ "$esperado" != "$sha" ]; then
  echo "::error::La cabeza del PR ($sha) no es la esperada ($esperado)."; exit 1
fi

datos="$trabajo/datos"
rm -rf "$datos"
git clone -q --no-checkout --filter=blob:none "https://github.com/$repo.git" "$datos"
git -C "$datos" fetch -q origin "pull/$pr/head" "$base"
[ "$(git -C "$datos" rev-parse FETCH_HEAD)" = "$sha" ] \
  || { echo "::error::La cabeza del PR cambió mientras se descargaba."; exit 1; }
git -C "$datos" checkout -q --detach "$sha"
desde=$(git -C "$datos" merge-base "origin/$base" "$sha")

python3 "$extractor/scripts/validar_commits.py" "$datos" "$desde" "$sha"
(cd "$extractor" && python3 -m congreso validar --out "$datos")

[ -z "${GITHUB_OUTPUT:-}" ] || echo "sha=$sha" >> "$GITHUB_OUTPUT"
echo "PR #$pr validado en $sha."
