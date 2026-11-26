"""Revisa los commits de un PR de congreso-mexicano: cada uno lleva un trailer
`Tipo` conocido y solo toca las carpetas de su tipo (como los arma
`scripts/commits.py`), así el historial se puede leer por tipo de dato.

    python scripts/validar_commits.py <repo de datos> <desde> <hasta>

Sale con 1 si algún commit no cumple.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# Tipo → carpetas que puede tocar. `indice` es la documentación del repo: los
# archivos de la raíz (README, AGENTS, LICENSE…) y, para retirarlo, `.github/`.
CARPETAS = {
    "padron": ("organizaciones/", "personas/", "mandatos/"),
    "votaciones": ("expedientes/", "votaciones/"),
    "asuntos": ("iniciativas/", "proposiciones/", "dictamenes-negativos/"),
    "decretos": ("decretos/",),
    "cronologia": ("cronologia/",),
    "fuentes": ("fuentes/",),
}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def permitido(tipo: str, ruta: str) -> bool:
    if tipo == "indice":
        return "/" not in ruta or ruta.startswith(".github/")
    return ruta.startswith(CARPETAS.get(tipo, ("\0",)))


def revisar(repo: Path, desde: str, hasta: str) -> list[str]:
    errores = []
    for sha in git(repo, "rev-list", "--reverse", f"{desde}..{hasta}").split():
        mensaje = git(repo, "log", "-1", "--format=%B", sha)
        titulo = mensaje.splitlines()[0] if mensaje else ""
        tipos = re.findall(r"^Tipo: (\S+)\s*$", mensaje, re.M)
        if len(git(repo, "rev-list", "--parents", "-1", sha).split()) > 2:
            errores.append(f"{sha[:7]} «{titulo}»: es un merge; el historial va lineal")
            continue
        if len(tipos) != 1 or tipos[0] not in {*CARPETAS, "indice"}:
            errores.append(f"{sha[:7]} «{titulo}»: trailer Tipo ausente o desconocido ({tipos})")
            continue
        fuera = [r for r in git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", sha).split("\n")
                 if r and not permitido(tipos[0], r)]
        if fuera:
            errores.append(f"{sha[:7]} «{titulo}»: Tipo {tipos[0]} pero toca {fuera[:5]}")
    return errores


if __name__ == "__main__":
    errores = revisar(Path(sys.argv[1]), sys.argv[2], sys.argv[3])
    for e in errores:
        print(e)
    print(f"{len(errores)} commits con problemas")
    sys.exit(1 if errores else 0)
