"""Páginas que el parser no pudo leer: fallos, lecturas del agente y su verificación.

El parser determinista lee cada página. Si falla con una página que sí se
descargó (un formato nuevo, una frase que no conoce), la página se guarda como
**fallo** en `CONGRESO_FALLOS/{sha256}/` (`pagina.html` y `fallo.json`), con
lo que ya se sabe de la votación por las otras páginas (`contexto`).

Un agente lee cada fallo y propone los datos con la misma forma que daría el
parser (`propuesta.json`). La propuesta solo se acepta si pasa `verificar`,
que el agente no controla: cada nombre y cada cifra está en la página, las
listas suman los totales que la misma página (o la otra página de la votación,
leída por el parser) declara, y las etiquetas son las que el catálogo conoce.
Lo aceptado queda en el registro `lecturas/{fuente}/{tipo}/{sha256}.json` de
este repo y se usa solo para esa página exacta (misma huella). Mientras tanto,
otro agente corrige el parser (`reparar-parsers.yml`); cuando el parser ya lee
la página, su resultado manda y se compara con la lectura.
"""
from __future__ import annotations

import html
import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import catalogos, gaceta, red, senado
from .texto import sin_acentos

REGISTRO = Path(__file__).resolve().parent.parent / "lecturas"

# (fuente, tipo) → (decodificar, parser). Lo que el parser devuelve es la forma
# que debe tener la lectura del agente.
PARSERS = {
    ("senado", "votacion"): (senado.decodificar, senado.votacion),
    ("senado", "tabla"): (senado.decodificar, senado.tabla),
    ("gaceta", "tabla"): (gaceta.decodificar, gaceta.tabla),
    ("gaceta", "lista"): (gaceta.decodificar, gaceta.lista),
}
OPCIONES_SENADO = {"yes", "no", "abstain"}
OPCIONES_GACETA = {o for _, o in gaceta.SENTIDOS}


class SinLectura(ValueError):
    """El parser no pudo y no hay lectura verificada para esa página."""


def carpeta_fallos() -> Path | None:
    d = os.environ.get("CONGRESO_FALLOS")
    return Path(d) if d else None


def registrar_fallo(fuente: str, tipo: str, clave: str, r: red.Respuesta, error: str, contexto: dict) -> None:
    base = carpeta_fallos()
    if base is None:
        return
    d = base / r.sha256
    d.mkdir(parents=True, exist_ok=True)
    (d / "pagina.html").write_bytes(r.contenido)
    (d / "fallo.json").write_text(json.dumps({
        "fuente": fuente, "tipo": tipo, "clave": clave, "url": r.url, "datos": r.datos, "sha256": r.sha256,
        "error": error, "contexto": contexto}, ensure_ascii=False, indent=2), encoding="utf-8")


def _ruta(fuente: str, tipo: str, sha: str, base: Path = REGISTRO) -> Path:
    return base / fuente / tipo / f"{sha}.json"


# Páginas que el parser ya lee y cuya lectura del agente dice otra cosa: se
# publica lo del parser y se avisa en el PR (una de las dos está mal).
AVISOS: list[str] = []


def intentar(fuente: str, tipo: str, r: red.Respuesta):
    """Lo que da el parser, o None si no puede (sin registrar nada)."""
    decodificar, parser = PARSERS[(fuente, tipo)]
    try:
        return parser(decodificar(r.contenido))
    except (ValueError, KeyError):
        return None


def leer(fuente: str, tipo: str, clave: str, r: red.Respuesta, contexto: dict, base: Path = REGISTRO):
    """(datos, lectura): lo que da el parser o, si falla, la lectura verificada
    de esa misma página (`lectura` dice de dónde salió). Sin ninguna de las
    dos, guarda el fallo y lanza SinLectura."""
    decodificar, parser = PARSERS[(fuente, tipo)]
    ruta = _ruta(fuente, tipo, r.sha256, base)
    try:
        datos = parser(decodificar(r.contenido))
        if ruta.exists() and json.loads(ruta.read_text(encoding="utf-8"))["datos"] != json.loads(json.dumps(datos)):
            AVISOS.append(f"{fuente} {clave}: el parser y la lectura del agente difieren en la {tipo} "
                          f"({ruta.relative_to(base.parent).as_posix()}); se publica lo del parser")
        return datos, None
    except (ValueError, KeyError) as e:
        error = f"{type(e).__name__}: {e}"
    if ruta.exists():
        lectura = json.loads(ruta.read_text(encoding="utf-8"))
        return lectura["datos"], {"pagina": tipo, "por": "agente",
                                  "registro": f"OpenCodice/congreso-extractor:{ruta.relative_to(base.parent).as_posix()}",
                                  "verificacion": lectura["verificacion"]}
    registrar_fallo(fuente, tipo, clave, r, error, contexto)
    raise SinLectura(f"{fuente} {clave}: el parser no leyó la {tipo} ({error}); queda para el agente")


# ------------------------------------------------------------------ verificación

def _plano(contenido: str) -> str:
    texto = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", contenido, flags=re.S | re.I)
    texto = html.unescape(re.sub(r"<[^>]+>", " ", texto))
    return " ".join(sin_acentos(texto).lower().split())


def _norm(s: str) -> str:
    return " ".join(sin_acentos(html.unescape(str(s))).lower().split())


def _numeros(plano: str) -> Counter:
    return Counter(re.findall(r"\b\d+\b", plano))


def _filas_verificadas(filas, plano, opciones, grupo_valido, fallas, extra=(), crudo="") -> None:
    if not isinstance(filas, list) or not filas:
        fallas.append("la lista está vacía o no es una lista")
        return
    vistos = Counter()
    for f in filas:
        nombre = f.get("nombre") or ""
        if len(_norm(nombre)) < 5 or _norm(nombre) not in plano:
            fallas.append(f"nombre que no está en la página: {nombre!r}")
        if f.get("opcion") not in opciones:
            fallas.append(f"sentido desconocido: {f.get('opcion')!r}")
        if not grupo_valido(f.get("grupo")):
            fallas.append(f"grupo desconocido: {f.get('grupo')!r}")
        # Los identificadores van en los enlaces: se buscan en el HTML, no en el texto.
        for k in extra:
            if not re.search(rf"\b{re.escape(str(f.get(k, '')))}\b", crudo) or not str(f.get(k, "")):
                fallas.append(f"{k} que no está en la página: {f.get(k)!r}")
        vistos[_norm(nombre)] += 1
    repetidos = [n for n, k in vistos.items() if k > 1]
    if repetidos:
        fallas.append(f"nombres repetidos: {repetidos[:5]}")


def _grupo_senado(g) -> bool:
    return isinstance(g, str) and (g in catalogos.PARTIDOS or g in catalogos.SIN_PARTIDO)


def _grupo_gaceta(g) -> bool:
    return isinstance(g, str) and g in set(gaceta.GRUPOS.values())


def verificar(fallo: dict, pagina: bytes, datos) -> list[str]:
    """Lo que la lectura propuesta no cumple (vacío si se acepta)."""
    fuente, tipo, ctx = fallo["fuente"], fallo["tipo"], fallo.get("contexto") or {}
    decodificar, _ = PARSERS[(fuente, tipo)]
    plano = _plano(decodificar(pagina))
    numeros = _numeros(plano)
    fallas: list[str] = []

    def cifra(n, que):
        if not isinstance(n, int) or n < 0:
            fallas.append(f"{que}: {n!r} no es una cifra")
        elif n and str(n) not in numeros:
            fallas.append(f"{que}: {n} no aparece en la página")

    if (fuente, tipo) == ("senado", "votacion"):
        conteos = datos.get("conteos") or {}
        if set(conteos) != OPCIONES_SENADO:
            fallas.append(f"conteos con sentidos {sorted(conteos)}")
        for k, n in conteos.items():
            cifra(n, f"conteo {k}")
        for k in ("asunto", "motion"):
            if not datos.get(k) or _norm(datos[k]) not in plano:
                fallas.append(f"{k} que no está en la página")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(datos.get("fecha"))):
            fallas.append(f"fecha mal formada: {datos.get('fecha')!r}")
        # La tabla nominal, leída por el parser, tiene que dar los mismos conteos.
        if ctx.get("conteo_tabla") and ctx["conteo_tabla"] != conteos:
            fallas.append(f"los conteos {conteos} no son los de la tabla nominal {ctx['conteo_tabla']}")
    elif (fuente, tipo) == ("senado", "tabla"):
        _filas_verificadas(datos, plano, OPCIONES_SENADO, _grupo_senado, fallas, extra=("senado_id",),
                           crudo=decodificar(pagina))
        if ctx.get("conteos") and dict(Counter(f.get("opcion") for f in datos)) != {k: v for k, v in ctx["conteos"].items() if v}:
            fallas.append(f"la tabla no suma los conteos de la votación {ctx['conteos']}")
        if [f.get("numero") for f in datos] != list(range(1, len(datos) + 1)):
            fallas.append("la numeración de la tabla no es 1..N")
    elif (fuente, tipo) == ("gaceta", "tabla"):
        for k in ("accion", "evento"):
            if not datos.get(k) or str(datos[k]) not in decodificar(pagina):
                fallas.append(f"{k} que no está en el formulario de la página")
        conteos = datos.get("conteos") or {}
        if "Total" not in conteos:
            fallas.append("sin fila Total")
        for g, cs in conteos.items():
            if g != "Total" and not _grupo_gaceta(g):
                fallas.append(f"grupo desconocido: {g!r}")
            if set(cs) != OPCIONES_GACETA:
                fallas.append(f"{g}: sentidos {sorted(cs)}")
            for k, n in cs.items():
                cifra(n, f"{g} {k}")
        if "Total" in conteos:
            for k in OPCIONES_GACETA:
                if sum(cs.get(k, 0) for g, cs in conteos.items() if g != "Total") != conteos["Total"].get(k):
                    fallas.append(f"los grupos no suman el Total en {k}")
    elif (fuente, tipo) == ("gaceta", "lista"):
        _filas_verificadas(datos, plano, OPCIONES_GACETA, _grupo_gaceta, fallas)
        # Los totales los da la tabla de la votación (parser o lectura verificada).
        tabla = ctx.get("conteos")
        if not tabla:
            fallas.append("sin los conteos de la tabla para comparar")
        else:
            lista = Counter((f.get("grupo"), f.get("opcion")) for f in datos)
            for g, cs in tabla.items():
                if g == "Total":
                    continue
                for k, n in cs.items():
                    if lista[(g, k)] != n:
                        fallas.append(f"{g} {k}: {lista[(g, k)]} en la lectura, {n} en la tabla")
    else:
        fallas.append(f"tipo de página desconocido: {fuente}/{tipo}")
    return fallas


def verificar_fallos(base_fallos: Path, base: Path = REGISTRO) -> dict:
    """Revisa cada `propuesta.json` de los fallos y registra las aceptadas."""
    aceptadas, rechazadas, sin_propuesta = [], [], []
    for d in sorted(p for p in base_fallos.iterdir() if (p / "fallo.json").exists()) if base_fallos.exists() else []:
        fallo = json.loads((d / "fallo.json").read_text(encoding="utf-8"))
        if not (d / "propuesta.json").exists():
            sin_propuesta.append(fallo["sha256"])
            continue
        try:
            propuesta = json.loads((d / "propuesta.json").read_text(encoding="utf-8"))
            if "no_legible" in propuesta:
                rechazadas.append(f"{fallo['fuente']} {fallo['tipo']} {fallo['clave']}: el agente no la pudo leer "
                                  f"({str(propuesta['no_legible'])[:200]})")
                continue
            datos = propuesta["datos"]
            fallas = verificar(fallo, (d / "pagina.html").read_bytes(), datos)
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            fallas, datos = [f"propuesta mal formada: {e}"], None
        etiqueta = f"{fallo['fuente']} {fallo['tipo']} {fallo['clave']}"
        if fallas:
            rechazadas.append(f"{etiqueta}: {'; '.join(fallas[:5])}")
            continue
        ruta = _ruta(fallo["fuente"], fallo["tipo"], fallo["sha256"], base)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(json.dumps({
            "fuente": fallo["fuente"], "tipo": fallo["tipo"], "clave": fallo["clave"], "url": fallo["url"],
            "datos_formulario": fallo.get("datos"), "sha256": fallo["sha256"], "error_del_parser": fallo["error"],
            "datos": datos, "fecha": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "verificacion": ["cada nombre y cada cifra están en la página",
                             "las listas suman los totales que declara la fuente",
                             "las etiquetas de grupo y sentido son las del catálogo"],
        }, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        aceptadas.append(etiqueta)
    return {"aceptadas": aceptadas, "rechazadas": rechazadas, "sin_propuesta": len(sin_propuesta)}
