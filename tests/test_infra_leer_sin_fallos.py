"""leer.sh no debe fallar si la carpeta de fallos no existe (no hubo fallos)."""
import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def test_leer_sin_carpeta_de_fallos(tmp_path):
    fallos = tmp_path / "fallos"
    r = subprocess.run(
        ["bash", str(RAIZ / "scripts" / "agente" / "leer.sh")],
        env={"PATH": "/usr/bin:/bin", "CONGRESO_FALLOS": str(fallos)},
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    assert "Sin páginas por leer." in r.stdout
