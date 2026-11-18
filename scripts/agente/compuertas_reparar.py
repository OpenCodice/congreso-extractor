"""Compuertas deterministas del arreglo del agente a los parsers, y su publicación.

El agente (reparar.sh) deja su cambio como parche. Estas fases corren en jobs
aparte, sobre un checkout limpio del mismo commit, con el caché y los fallos
descargados de nuevo: lo que el agente haya tocado en su máquina no cuenta.

  compuertas  (sin secretos; corre las pruebas, es decir, código del agente)
    a. solo cambia congreso/senado.py, congreso/gaceta.py, congreso/red.py y
       tests/ (cualquier otro archivo, un borrado o un enlace simbólico: se
       descarta todo); ningún fixture existente cambia y cada fixture nuevo
       es, byte por byte, una página descargada (fallo o caché); un cambio a
       un parser trae al menos un fixture nuevo;
    b. `pytest` en verde, y las pruebas de antes del arreglo, tal como
       estaban, en verde contra el código nuevo;
    c. scripts/regresion.py sin regresiones sobre el caché y los fallos;
    d. cada fallo que el agente dice resolver ahora se lee (o, si era un
       bloqueo, `red.bloqueado` lo reconoce), y ninguna página que el cambio
       lee distinto contradice su lectura verificada de `lecturas/`.
    Escribe veredicto.json; `publicable=true|false` en $GITHUB_OUTPUT.

  publicar  (con EXTRACTOR_TOKEN; no ejecuta código del agente)
    Toma el parche del artefacto del agente (no el del job de compuertas, donde
    corrieron sus pruebas), exige que sea el que pasó las compuertas (sha256),
    vuelve a revisar sus rutas, lo aplica, hace commit en main y
    push con rebase y reintentos. `relanzar=true` si es el primer arreglo
    publicado en 12 h (para no encadenar actualizaciones sin fin).

    python scripts/agente/compuertas_reparar.py compuertas --trabajo T --fallos F --cache .cache
    python scripts/agente/compuertas_reparar.py publicar --trabajo T [--parche P]
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
PARSERS = ("congreso/senado.py", "congreso/gaceta.py")
PERMITIDO = re.compile(r"congreso/(?:senado|gaceta|red)\.py|tests/[A-Za-z0-9_.\-/]+")
PREFIJO = "Reparación automática de parsers"
# Los arreglos que escribe el agente llevan su autoría, no la de una persona.
AUTOR = {"GIT_AUTHOR_NAME": "Claude (agente OpenCodice)", "GIT_AUTHOR_EMAIL": "noreply@anthropic.com",
         "GIT_COMMITTER_NAME": "Claude (agente OpenCodice)", "GIT_COMMITTER_EMAIL": "noreply@anthropic.com"}


# Archivos de comandos del runner: el código del agente (pruebas, parsers) corre
# sin ellos, para que no pueda fijar las salidas del paso.
_ARCHIVOS_DEL_RUNNER = {"GITHUB_OUTPUT", "GITHUB_ENV", "GITHUB_PATH", "GITHUB_STATE", "GITHUB_STEP_SUMMARY"}


def entorno_aislado() -> dict:
    return {k: v for k, v in os.environ.items() if k not in _ARCHIVOS_DEL_RUNNER | {"PYTHONPATH"}}


class Descarte(Exception):
    """El arreglo no pasa una compuerta: no se publica nada."""


def git(*args, check=True, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-C", str(RAIZ), *args],
                          check=check, capture_output=True, text=True, **kw)


def salida_gh(**valores) -> None:
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            for k, v in valores.items():
                f.write(f"{k}={v}\n")


def rutas_del_parche(parche: str) -> list[str]:
    """Rutas que toca el parche; Descarte si alguna está fuera de lo permitido."""
    rutas = []
    for linea in parche.splitlines():
        if linea.startswith("diff --git "):
            m = re.fullmatch(r"diff --git a/(\S+) b/(\S+)", linea)
            if not m:
                raise Descarte(f"ruta que no se puede revisar: {linea[11:120]!r}")
            rutas += [m[1], m[2]]
        elif re.match(r"(?:new file |deleted file |old |new )mode 1[26]0000", linea):
            raise Descarte("el parche crea un enlace simbólico o un submódulo")
        elif linea.startswith("deleted file mode"):
            raise Descarte("el parche borra archivos")
    fuera = sorted({r for r in rutas if not PERMITIDO.fullmatch(r) or ".." in r.split("/")})
    if fuera:
        raise Descarte(f"toca archivos fuera de los parsers y tests/: {', '.join(fuera[:5])}")
    return sorted(set(rutas))


def aplicar(parche: Path) -> list[str]:
    rutas = rutas_del_parche(parche.read_text(encoding="utf-8", errors="replace"))
    r = git("apply", "--index", "--binary", str(parche), check=False)
    if r.returncode != 0:
        raise Descarte(f"el parche no aplica: {r.stderr.strip()[:300]}")
    return rutas


def sha(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def paginas_reales(fallos: Path, cache: Path) -> set[str]:
    huellas = {sha(p) for p in fallos.glob("*/pagina.html")} if fallos.is_dir() else set()
    if cache.is_dir():
        huellas |= {sha(p) for p in cache.glob("*/*") if re.fullmatch(r"[0-9a-f]{64}", p.name)}
    return huellas


def revisar_fixtures(fallos: Path, cache: Path) -> None:
    estados = [l.split("\t", 1) for l in git("diff", "--cached", "--name-status", "--no-renames", "HEAD").stdout.splitlines()]
    reales = None
    nuevos = 0
    for estado, ruta in estados:
        if estado == "D":
            raise Descarte(f"borra {ruta}")
        if not ruta.startswith("tests/fixtures/"):
            continue
        if estado != "A":
            raise Descarte(f"modifica un fixture existente: {ruta}")
        reales = paginas_reales(fallos, cache) if reales is None else reales
        if sha(RAIZ / ruta) not in reales:
            raise Descarte(f"el fixture {ruta} no es una página descargada (ni de los fallos ni del caché)")
        nuevos += 1
    if not nuevos and any(ruta in PARSERS for _, ruta in estados):
        raise Descarte("cambia un parser sin agregar un fixture real")


def pytest(carpeta: Path, log: Path, que: str) -> None:
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=carpeta,
                       capture_output=True, text=True, env=entorno_aislado(), timeout=1800)
    log.write_text(r.stdout + r.stderr, encoding="utf-8")
    if r.returncode != 0:
        raise Descarte(f"{que} no pasan: {(r.stdout.strip().splitlines() or ['?'])[-1][:200]}")


def pruebas_anteriores(log: Path) -> None:
    """Las pruebas de HEAD, sin los cambios del agente a tests/, contra los parsers nuevos."""
    with tempfile.TemporaryDirectory(prefix="pruebas-antes-") as tmp:
        tar = subprocess.run(["git", "-C", str(RAIZ), "archive", "--format=tar", "HEAD"],
                             check=True, capture_output=True).stdout
        with tarfile.open(fileobj=io.BytesIO(tar)) as t:
            t.extractall(tmp, filter="data")
        for ruta in (*PARSERS, "congreso/red.py"):
            shutil.copyfile(RAIZ / ruta, Path(tmp) / ruta)
        pytest(Path(tmp), log, "las pruebas anteriores, con el código nuevo,")


def revisar_regresion(trabajo: Path, fallos: Path, cache: Path) -> dict:
    salida = trabajo / "regresion.json"
    r = subprocess.run([sys.executable, str(RAIZ / "scripts" / "regresion.py"), "--cache", str(cache), "--antes", "HEAD",
                        "--fallos", str(fallos), "--salida", str(salida)], cwd=RAIZ, capture_output=True, text=True,
                       env=entorno_aislado())
    (trabajo / "regresion.log").write_text(r.stderr, encoding="utf-8")
    if r.returncode == 2 or not salida.exists():
        raise Descarte(f"no se pudo correr la regresión: {r.stderr.strip()[-300:]}")
    rep = json.loads(salida.read_text(encoding="utf-8"))
    if rep["regresiones"]:
        ej = "; ".join(f"{x['fuente']} {x['tipo']} {x['clave']} ({x['despues'][:80]})" for x in rep["regresiones"][:3])
        raise Descarte(f"{len(rep['regresiones'])} páginas que se leían ahora dan otro resultado: {ej}")
    return rep


def revisar_resueltos(trabajo: Path, fallos: Path, rep: dict) -> list[dict]:
    try:
        dicho = json.loads((trabajo / "reparacion.json").read_text(encoding="utf-8"))
        resueltos = [x for x in dicho.get("resueltos", []) if isinstance(x, dict)]
    except (OSError, ValueError, AttributeError):
        raise Descarte("el agente no entregó reparacion.json legible")
    nuevas = [x for x in rep["contra_lectura"]["difieren"] if x["nuevo"]]
    if nuevas:
        ej = "; ".join(f"{x['fuente']} {x['tipo']} {x['clave']} ({x['diferencia'][:80]})" for x in nuevas[:3])
        raise Descarte(f"el parser nuevo contradice {len(nuevas)} lecturas verificadas: {ej}")
    leidos = {x["sha256"]: x for x in rep["arreglos"] if "fallo" in x["origen"]}
    bloqueos = {x["sha256"]: x for x in rep["ahora_bloqueo"] if "fallo" in x["origen"]}
    salida = []
    for x in resueltos:
        h, causa = str(x.get("sha256", "")), x.get("causa")
        if not (fallos / h / "fallo.json").is_file():
            raise Descarte(f"dice resolver {h[:12]}, que no está entre los fallos")
        cual = bloqueos if causa == "bloqueo" else leidos
        if h not in cual:
            raise Descarte(f"dice resolver {h[:12]} ({causa}), pero el código nuevo no "
                           + ("lo reconoce como bloqueo" if causa == "bloqueo" else "lo lee"))
        p = cual[h]
        salida.append({"sha256": h, "causa": "bloqueo" if causa == "bloqueo" else "formato", "fuente": p["fuente"],
                       "tipo": p["tipo"], "clave": p["clave"], "nota": limpio(x.get("nota", ""), 200)})
    if not salida:
        raise Descarte("no resuelve ningún fallo")
    return salida


def limpio(s, n: int) -> str:
    return " ".join(str(s).split())[:n]


def compuertas(a) -> int:
    trabajo, fallos, cache = a.trabajo, a.fallos, a.cache
    parche = trabajo / "arreglo.patch"
    veredicto = {"publicable": False}
    try:
        if not parche.is_file() or not parche.read_text(encoding="utf-8", errors="replace").strip():
            veredicto["motivo"] = "el agente no cambió el código"
        else:
            if git("status", "--porcelain").stdout.strip():
                raise RuntimeError("el checkout no está limpio antes de aplicar el parche")
            veredicto["parche_sha256"] = sha(parche)
            veredicto["archivos"] = aplicar(parche)
            revisar_fixtures(fallos, cache)
            pytest(RAIZ, trabajo / "pytest.log", "las pruebas")
            pruebas_anteriores(trabajo / "pytest-anteriores.log")
            rep = revisar_regresion(trabajo, fallos, cache)
            resueltos = revisar_resueltos(trabajo, fallos, rep)
            dicho = json.loads((trabajo / "reparacion.json").read_text(encoding="utf-8"))
            veredicto.update(
                publicable=True, motivo="pasa todas las compuertas", resueltos=resueltos,
                titulo=limpio(dicho.get("titulo_commit") or "ajuste a un formato nuevo de la fuente", 72),
                resumen=limpio(dicho.get("resumen", ""), 1200),
                regresion={k: rep[k] if isinstance(rep[k], int) else len(rep[k])
                           for k in ("paginas", "iguales", "arreglos", "siguen_fallando", "ahora_bloqueo")},
                lecturas_coinciden=len(rep["contra_lectura"]["coinciden"]))
    except Descarte as e:
        veredicto["motivo"] = f"descartado: {e}"
        print(f"::warning::Arreglo del agente descartado: {e}")
    (trabajo / "veredicto.json").write_text(json.dumps(veredicto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(veredicto["motivo"])
    salida_gh(publicable=str(veredicto["publicable"]).lower())
    return 0


def mensaje(v: dict) -> str:
    r = v["regresion"]
    lineas = [f"{PREFIJO}: {v['titulo']}", ""]
    if v.get("resumen"):
        lineas += [v["resumen"], ""]
    lineas.append("Páginas que ahora se leen (fallos de la última corrida):")
    for x in v["resueltos"]:
        lineas.append(f"- {x['fuente']} {x['tipo']} {x['clave']} ({x['sha256'][:12]}, {x['causa']})"
                      + (f": {x['nota']}" if x["nota"] else ""))
    lineas += ["", f"Compuertas: pruebas nuevas y anteriores en verde; {r['iguales']} de {r['paginas']} páginas "
                   f"descargadas se leen igual que antes y ninguna cambia; {v.get('lecturas_coinciden', 0)} "
                   f"coinciden con su lectura verificada."]
    return "\n".join(lineas) + "\n"


def publicar(a) -> int:
    v = json.loads((a.trabajo / "veredicto.json").read_text(encoding="utf-8"))
    salida_gh(publicado="false", relanzar="false")
    if not v.get("publicable"):
        print("Nada que publicar.")
        return 0
    parche = a.parche or a.trabajo / "arreglo.patch"
    if sha(parche) != v.get("parche_sha256"):
        print("::error::El parche no es el que pasó las compuertas.")
        return 1
    destino = os.environ.get("EXTRACTOR_PUSH_URL")
    token = os.environ.get("EXTRACTOR_TOKEN", "")
    if not destino:
        if not (token and os.environ.get("EXTRACTOR_SLUG")):
            print("::warning::Sin credenciales para publicar el arreglo.")
            return 0
        destino = f"https://x-access-token:{token}@github.com/{os.environ['EXTRACTOR_SLUG']}.git"
    oculto = lambda s: s.replace(token, "***") if token else s
    try:
        aplicar(parche)
    except Descarte as e:
        print(f"::error::{e}")
        return 1
    entorno = {**os.environ, **AUTOR}
    git("commit", "-q", "-m", mensaje(v), env=entorno)
    for intento in range(1, 4):
        p = git("pull", "-q", "--rebase", destino, "main", check=False, env=entorno)
        if p.returncode == 0 and git("push", "-q", destino, "HEAD:main", check=False).returncode == 0:
            break
        git("rebase", "--abort", check=False)
        print(f"intento {intento} sin éxito: {oculto(p.stderr.strip())[:300]}")
        time.sleep(intento * 5)
    else:
        print("::warning::No se pudo publicar el arreglo en el extractor.")
        return 1
    previos = [l for l in git("log", "--since=12 hours ago", "--format=%s", "HEAD~1").stdout.splitlines()
               if l.startswith(PREFIJO)]
    sha_ = git("rev-parse", "HEAD").stdout.strip()
    print(f"Arreglo publicado: {sha_}")
    salida_gh(publicado="true", relanzar=str(not previos).lower(), sha=sha_)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="fase", required=True)
    c = sub.add_parser("compuertas")
    c.add_argument("--trabajo", type=Path, required=True)
    c.add_argument("--fallos", type=Path, required=True)
    c.add_argument("--cache", type=Path, default=RAIZ / ".cache")
    p = sub.add_parser("publicar")
    p.add_argument("--trabajo", type=Path, required=True, help="con veredicto.json de las compuertas")
    p.add_argument("--parche", type=Path, help="el parche tal como lo dejó el agente (por omisión, el de --trabajo)")
    a = ap.parse_args(argv)
    return compuertas(a) if a.fase == "compuertas" else publicar(a)


if __name__ == "__main__":
    sys.exit(main())
