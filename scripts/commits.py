"""Agrupa los cambios del repo de datos en un commit por tipo de dato.

    python scripts/commits.py ../congreso-mexicano

Cada commit lleva el trailer `Tipo` (padron, votaciones, decretos) para que la
bitácora lo lea sin interpretar el título.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

GRUPOS = (
    ("padron", ("organizaciones", "personas", "mandatos"), "Padrón de legisladores al día"),
    ("votaciones", ("expedientes", "votaciones", "fuentes"), "Expedientes y votaciones al día"),
    ("decretos", ("decretos",), "Decretos del DOF al día"),
)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def main(repo: Path) -> None:
    for tipo, carpetas, titulo in GRUPOS:
        existentes = [c for c in carpetas if (repo / c).exists()]
        if not existentes:
            continue
        git(repo, "add", "-A", "--", *existentes)
        if not git(repo, "diff", "--cached", "--name-only"):
            continue
        cambiados = git(repo, "diff", "--cached", "--name-status").splitlines()
        nuevos = sum(1 for l in cambiados if l.startswith("A"))
        mensaje = f"{titulo}: {nuevos} nuevos, {len(cambiados) - nuevos} cambiados\n\nTipo: {tipo}\n"
        git(repo, "commit", "-q", "-m", mensaje)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
