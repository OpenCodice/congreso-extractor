"""Regresión de los parsers del Senado y la Gaceta sobre páginas reales.

Lee con el código de una revisión anterior ("antes", vía `git archive`) y con
el árbol de trabajo ("después") cada página descargada que esté en el caché de
`congreso/red.py` y sea de un tipo de `lecturas.PARSERS`, más las páginas de
una carpeta de fallos (`CONGRESO_FALLOS`). Cada versión corre en su propio
subproceso, que importa `congreso` solo de su carpeta.

Reporta, en JSON:
- regresiones: antes se leía y ahora da otro resultado (o ya no se lee, o se
  toma por bloqueo);
- arreglos: antes fallaba y ahora se lee;
- siguen_fallando, ahora_bloqueo (antes fallaba y ahora `red.bloqueado` la
  reconoce) e iguales;
- contra_lectura: las páginas que tienen lectura verificada en `lecturas/` y
  que el código de después lee: si da exactamente esos `datos` o no (`nuevo`
  dice si la diferencia la trae el cambio).

Sale con 1 si hay regresiones y con 2 si no pudo correr.

    python scripts/regresion.py --cache .cache --antes HEAD [--fallos DIR] [--lecturas lecturas]
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

RAIZ = Path(__file__).resolve().parent.parent
LIMITE_SEGUNDOS = 900

# Lo corre cada versión del código en su subproceso (`python -I -c`): importa
# `congreso` de la carpeta que recibe y no de otra. Recibe por stdin
# [{id, ruta, fuente, tipo}] y devuelve {id: {bloqueado, datos | error}}.
_LECTOR = r"""
import importlib, json, sys
sys.path.insert(0, sys.argv[1])
red = importlib.import_module("congreso.red")
bloqueado = getattr(red, "bloqueado", lambda contenido: False)
salida = {}
for p in json.load(sys.stdin):
    contenido = open(p["ruta"], "rb").read()
    r = {"bloqueado": bool(bloqueado(contenido))}
    try:
        m = importlib.import_module(f"congreso.{p['fuente']}")
        r["datos"] = json.loads(json.dumps(getattr(m, p["tipo"])(m.decodificar(contenido)), default=repr))
    except Exception as e:
        r["error"] = f"{type(e).__name__}: {e}"[:500]
    salida[p["id"]] = r
json.dump(salida, sys.stdout, ensure_ascii=False)
"""


def tipos_conocidos() -> set[tuple[str, str]]:
    sys.path.insert(0, str(RAIZ))
    from congreso.lecturas import PARSERS
    return set(PARSERS)


def clasificar(url: str, datos: dict | None) -> tuple[str, str, str] | None:
    """(fuente, tipo, clave) de una página por su URL, o None si no es de un parser con lecturas."""
    u = urlsplit(url)
    host, ruta = (u.hostname or "").lower(), u.path
    if host.endswith("senado.gob.mx"):
        if datos is None and (m := re.fullmatch(r"/\d+/votacion/(\d+)/?", ruta)):
            return "senado", "votacion", m[1]
        if datos is None and ruta.endswith("/viewTableVot.php") and (m := re.search(r"(?:^|&)votacion=(\d+)", u.query)):
            return "senado", "tabla", m[1]
    elif host == "gaceta.diputados.gob.mx":
        if datos is None and (m := re.fullmatch(r"/Gaceta/Votaciones/\d+/(tabla[^/]*)\.php3", ruta, re.I)):
            return "gaceta", "tabla", m[1]
        if datos and "evento" in datos and re.match(r"/voto\d+/", ruta):
            return "gaceta", "lista", f"{ruta}#evento={datos['evento']}"
    return None


def paginas_del_cache(cache: Path, tipos: set) -> list[dict]:
    salida = []
    if not cache.is_dir():
        return salida
    for meta in sorted(cache.glob("*/*.json")):
        contenido = meta.with_suffix("")
        if not re.fullmatch(r"[0-9a-f]{64}", meta.stem) or not contenido.is_file():
            continue
        try:
            m = json.loads(meta.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        c = clasificar(m.get("url", ""), m.get("datos"))
        if c is None or c[:2] not in tipos:
            continue
        salida.append({"fuente": c[0], "tipo": c[1], "clave": c[2], "url": m["url"], "datos_formulario": m.get("datos"),
                       "ruta": str(contenido), "origen": "cache"})
    return salida


def paginas_de_fallos(fallos: Path | None, tipos: set) -> list[dict]:
    salida = []
    if fallos is None or not fallos.is_dir():
        return salida
    for f in sorted(fallos.glob("*/fallo.json")):
        pagina = f.parent / "pagina.html"
        try:
            m = json.loads(f.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if not pagina.is_file() or (m.get("fuente"), m.get("tipo")) not in tipos:
            continue
        salida.append({"fuente": m["fuente"], "tipo": m["tipo"], "clave": str(m.get("clave", "")), "url": m.get("url"),
                       "datos_formulario": m.get("datos"), "ruta": str(pagina), "origen": "fallo"})
    return salida


def unir(paginas: list[dict]) -> list[dict]:
    """Una entrada por (fuente, tipo, sha256): la misma página en el caché y en los fallos se lee una vez."""
    por_clave: dict[tuple, dict] = {}
    for p in paginas:
        p["sha256"] = hashlib.sha256(Path(p["ruta"]).read_bytes()).hexdigest()
        k = (p["fuente"], p["tipo"], p["sha256"])
        if k in por_clave:
            por_clave[k]["origen"] = sorted(set(por_clave[k]["origen"]) | {p["origen"]})
        else:
            por_clave[k] = dict(p, origen=[p["origen"]], id=str(len(por_clave)))
    return list(por_clave.values())


def extraer(repo: Path, revision: str, destino: Path) -> str:
    """Copia `congreso/` de la revisión en `destino`; devuelve el sha de la revisión."""
    sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", f"{revision}^{{commit}}"],
                         check=True, capture_output=True, text=True).stdout.strip()
    tar = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", sha, "congreso"],
                         check=True, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(tar)) as t:
        t.extractall(destino, filter="data")
    return sha


def leer_con(raiz: Path, paginas: list[dict]) -> dict:
    # El lector corre con cwd en `raiz`: una ruta relativa (`--cache .cache`) no se encontraría desde ahí.
    entrada = [dict({k: p[k] for k in ("id", "fuente", "tipo")}, ruta=str(Path(p["ruta"]).resolve())) for p in paginas]
    r = subprocess.run([sys.executable, "-I", "-c", _LECTOR, str(raiz)], input=json.dumps(entrada),
                       capture_output=True, text=True, timeout=LIMITE_SEGUNDOS, cwd=raiz)
    if r.returncode != 0:
        raise RuntimeError(f"el código de {raiz} no pudo leer las páginas: {r.stderr.strip()[-2000:]}")
    return json.loads(r.stdout)


def _diferencia(a, b, nombres=("antes", "después")) -> str:
    if isinstance(a, dict) and isinstance(b, dict):
        claves = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
        return "cambian: " + ", ".join(claves[:10])
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return f"{len(a)} elementos {nombres[0]}, {len(b)} {nombres[1]}"
        i = next(i for i, (x, y) in enumerate(zip(a, b)) if x != y)
        return f"elemento {i}: {json.dumps(a[i], ensure_ascii=False)[:200]} → {json.dumps(b[i], ensure_ascii=False)[:200]}"
    return "otro resultado"


def _estado(r: dict) -> str:
    return "bloqueo" if r["bloqueado"] else ("error: " + r["error"]) if "error" in r else "lee"


def comparar(paginas: list[dict], antes: dict, despues: dict, lecturas: Path | None) -> dict:
    rep = {"paginas": len(paginas), "iguales": 0, "ignoradas_bloqueo": 0, "regresiones": [], "arreglos": [],
           "siguen_fallando": [], "ahora_bloqueo": [], "contra_lectura": {"coinciden": [], "difieren": []}}
    for p in paginas:
        a, d = antes[p["id"]], despues[p["id"]]
        base = {k: p[k] for k in ("fuente", "tipo", "clave", "url", "datos_formulario", "sha256", "origen")}
        if a["bloqueado"]:
            rep["ignoradas_bloqueo"] += 1
            continue
        if "datos" in a:
            if "datos" in d and not d["bloqueado"] and d["datos"] == a["datos"]:
                rep["iguales"] += 1
            else:
                detalle = _diferencia(a["datos"], d["datos"]) if "datos" in d and not d["bloqueado"] else _estado(d)
                rep["regresiones"].append(dict(base, antes="lee", despues=detalle))
        elif d["bloqueado"]:
            rep["ahora_bloqueo"].append(dict(base, antes=_estado(a)))
        elif "datos" in d:
            rep["arreglos"].append(dict(base, antes=_estado(a)))
        else:
            rep["siguen_fallando"].append(dict(base, antes=_estado(a), despues=_estado(d)))
        ruta = lecturas / p["fuente"] / p["tipo"] / f"{p['sha256']}.json" if lecturas else None
        if ruta and ruta.is_file() and "datos" in d and not d["bloqueado"]:
            lectura = json.loads(ruta.read_text(encoding="utf-8"))["datos"]
            if d["datos"] == lectura:
                rep["contra_lectura"]["coinciden"].append(base)
            else:
                rep["contra_lectura"]["difieren"].append(dict(
                    base, diferencia=_diferencia(lectura, d["datos"], ("en la lectura", "en el parser")), nuevo=a.get("datos") != d["datos"]))
    return rep


def correr(cache: Path, antes: str, repo: Path, despues: Path, fallos: Path | None, lecturas: Path | None,
           tipos: set | None = None) -> dict:
    tipos = tipos if tipos is not None else tipos_conocidos()
    paginas = unir(paginas_del_cache(cache, tipos) + paginas_de_fallos(fallos, tipos))
    with tempfile.TemporaryDirectory(prefix="regresion-") as tmp:
        sha = extraer(repo, antes, Path(tmp))
        leidas_antes = leer_con(Path(tmp), paginas) if paginas else {}
    leidas_despues = leer_con(despues, paginas) if paginas else {}
    return {"antes": sha, **comparar(paginas, leidas_antes, leidas_despues, lecturas)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cache", type=Path, required=True, help="caché de descargas (CONGRESO_CACHE)")
    ap.add_argument("--antes", default="HEAD", help="revisión de git con el código de antes")
    ap.add_argument("--repo", type=Path, default=RAIZ, help="repo del extractor (su árbol de trabajo es el después)")
    ap.add_argument("--fallos", type=Path, help="carpeta de fallos (CONGRESO_FALLOS)")
    ap.add_argument("--lecturas", type=Path, help="registro de lecturas verificadas (por omisión, lecturas/ del repo)")
    ap.add_argument("--salida", type=Path, help="escribe aquí el reporte (si no, a stdout)")
    a = ap.parse_args(argv)
    try:
        rep = correr(a.cache, a.antes, a.repo, a.repo, a.fallos, a.lecturas or a.repo / "lecturas")
    except (RuntimeError, subprocess.SubprocessError, OSError, ValueError) as e:
        print(f"regresion: {e}", file=sys.stderr)
        return 2
    texto = json.dumps(rep, ensure_ascii=False, indent=2) + "\n"
    if a.salida:
        a.salida.write_text(texto, encoding="utf-8")
    else:
        sys.stdout.write(texto)
    print(f"regresion: {rep['paginas']} páginas · iguales {rep['iguales']} · regresiones {len(rep['regresiones'])}"
          f" · arreglos {len(rep['arreglos'])} · siguen fallando {len(rep['siguen_fallando'])}"
          f" · ahora bloqueo {len(rep['ahora_bloqueo'])} · bloqueos ignorados {rep['ignoradas_bloqueo']}"
          f" · contra lectura: {len(rep['contra_lectura']['coinciden'])} coinciden,"
          f" {len(rep['contra_lectura']['difieren'])} difieren", file=sys.stderr)
    return 1 if rep["regresiones"] else 0


if __name__ == "__main__":
    sys.exit(main())
