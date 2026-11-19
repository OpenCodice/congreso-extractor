"""Lo común a las fuentes de votos nominales de cada cámara (Senado, Gaceta).

Cada votación de esas fuentes es un VoteEvent propio. Se liga al expediente y
a la votación del SIL cuando el par es inequívoco:

1. misma fecha, y la denominación del asunto en el SIL contenida en el título
   de la fuente, con un único mejor candidato;
2. la fuente tiene para ese asunto tantas votaciones como el SIL trámites
   nominales: se emparejan en orden. Si no, se cuentan sin las mociones
   (suspensivas, de discusión) que el SIL registra como nominales y las otras
   fuentes no publican; si así coinciden, se emparejan en orden sin ellas.

Si las dos fuentes difieren (conteos o votos individuales), ambas se
conservan y la diferencia queda en `discrepancias`.
"""
from __future__ import annotations

import re
from collections import Counter

from . import catalogos, red
from .decretos import _palabras

UMBRAL = 0.7
MARGEN = 0.15

# «Se rechazó admitir la moción suspensiva…», «Se rechazó ponerse a discusión
# la propuesta de moción…»: votaciones de trámite, no del dictamen.
MOCION = re.compile(r"\bmoci[oó]n\b", re.I)
DICTAMEN = re.compile(r"\ben lo (general|particular)\b", re.I)


def es_mocion(e: dict) -> bool:
    texto = (e.get("motion") or {}).get("text") or ""
    return bool(MOCION.search(texto)) and not DICTAMEN.search(texto)


class Omitida(RuntimeError):
    pass


def contencion(denominacion: str, titulo: str) -> float:
    x = _palabras(denominacion)
    return len(x & _palabras(titulo)) / len(x) if x else 0.0


def emparejar(votaciones: list[dict], eventos_sil: list[dict], fuente: str) -> dict[str, dict]:
    """clave de la fuente → {expediente_id, asunto, votacion_sil?, criterio}.

    Cada votación trae `clave`, `fecha`, `asunto` y `orden` (cronológico)."""
    por_fecha: dict[str, list[dict]] = {}
    for e in eventos_sil:
        por_fecha.setdefault(e["start_date"], []).append(e)
    asignadas: dict[str, list[dict]] = {}
    for v in votaciones:
        candidatos = {}
        for e in por_fecha.get(v["fecha"], []):
            candidatos.setdefault(e["asunto"], (contencion(e["motion"]["denominacion"] or "", v["asunto"]), e))
        orden = sorted(candidatos.values(), key=lambda x: -x[0])
        if not orden or orden[0][0] < UMBRAL or (len(orden) > 1 and orden[0][0] - orden[1][0] < MARGEN):
            continue
        asignadas.setdefault(orden[0][1]["asunto"], []).append(v)

    enlaces = {}
    for asunto, vs in asignadas.items():
        sil = sorted((e for e in eventos_sil if e["asunto"] == asunto), key=lambda e: e["orden"])
        base = {"expediente_id": sil[0]["expediente_id"], "asunto": asunto}
        vs = sorted(vs, key=lambda v: v["orden"])
        pares = len(vs) == len(sil)
        sin = ""
        if not pares:
            sin_mociones = [e for e in sil if not es_mocion(e)]
            if len(sin_mociones) < len(sil) and len(vs) == len(sin_mociones):
                sil, pares = sin_mociones, True
                sin = " sin contar las mociones que registra el SIL"
        for i, v in enumerate(vs):
            enlace = dict(base, criterio=f"misma fecha y el asunto del SIL contenido en el título de {fuente}")
            if pares:
                enlace["votacion_sil"] = sil[i]["id"]
                enlace["criterio"] += f"; votación {i + 1} de {len(vs)} del asunto en ambas fuentes{sin}"
            enlaces[v["clave"]] = enlace
    return enlaces


def faltantes(sin_mandato: list[dict]) -> list[dict]:
    """Votos que la fuente lista pero no se ligan a un único mandato: se
    declaran con el nombre tal como lo escribe la fuente, sin atribuirlos."""
    grupos: dict[tuple[str, str], list[str]] = {}
    for f in sin_mandato:
        grupos.setdefault((f["grupo"], f["opcion"]), []).append(f["nombre"])
    return [{"grupo": g, "option": o, "value": len(n), "nombres_fuente": n} for (g, o), n in sorted(grupos.items())]


def grupo(etiqueta: str) -> tuple[str | None, str | None]:
    """Organización del grupo parlamentario; un grupo que el catálogo no conoce
    no impide publicar el voto: queda sin `group_id` y se anota."""
    try:
        return catalogos.partido(etiqueta), None
    except KeyError:
        return None, f"grupo {etiqueta!r} desconocido en el catálogo"


def votos(filas: list[dict], indice, extra=lambda f: {}) -> tuple[list[dict], list[dict], list[str]]:
    """Filas de la fuente → votos Popolo ligados a su mandato, las filas que no
    se ligan (se declaran con su nombre en `votos_faltantes`) e inconsistencias."""
    ligadas, sin_mandato = [], []
    for f in filas:
        r = indice.buscar(f["nombre"])
        if r is None:
            sin_mandato.append(f)
        else:
            ligadas.append((f, *r))
    # Dos filas que dan con la misma persona: ninguna se le atribuye.
    veces = Counter(m["person_id"] for _, m, _ in ligadas)
    inconsistencias = [f"{n} filas ({', '.join(f['nombre'] for f, m, _ in ligadas if m['person_id'] == p)}) "
                       f"se ligan a la misma persona {p}; no se atribuyen" for p, n in veces.items() if n > 1]
    salida = []
    for f, m, criterio in ligadas:
        if veces[m["person_id"]] > 1:
            sin_mandato.append(f)
            continue
        g, aviso = grupo(f["grupo"])
        if aviso:
            inconsistencias.append(aviso)
        salida.append({"voter_id": m["person_id"], "mandato_id": m["id"], "option": f["opcion"],
                       "group_id": g, "grupo_fuente": f["grupo"], **extra(f),
                       **({"enlace": criterio} if criterio != "nombre" else {})})
    return salida, sin_mandato, inconsistencias


def cotejar(e: dict, par: dict) -> None:
    """Anota en `e` lo que difiere de su par del SIL."""
    propios = {c["option"]: c["value"] for c in e["counts"] if c["option"] in ("yes", "no", "abstain")}
    ajenos = {c["option"]: c["value"] for c in par["counts"] if c["option"] in ("yes", "no", "abstain")}
    diferencia = {}
    if propios != ajenos:
        diferencia["counts_sil"] = par["counts"]
    if par["votes"]:
        del_sil = {x["voter_id"]: x["option"] for x in par["votes"]}
        distintos = sorted(x["voter_id"] for x in e["votes"]
                           if x["voter_id"] in del_sil and del_sil[x["voter_id"]] != x["option"])
        if distintos:
            diferencia["votantes_distintos"] = distintos
        solo_aqui = sorted(x["voter_id"] for x in e["votes"] if x["voter_id"] not in del_sil)
        if solo_aqui and par.get("votos_faltantes"):
            # Los que el SIL cuenta pero no lista: esta fuente sí los nombra.
            diferencia["no_listados_en_sil"] = solo_aqui
        elif solo_aqui:
            diferencia["votantes_ausentes_en_sil"] = solo_aqui
    if diferencia:
        e["discrepancias"] = [dict(diferencia, votacion=par["id"])]


def procedencias(respuestas: list[red.Respuesta]) -> tuple[list[dict], list[tuple[str, bytes]]]:
    fuentes, copias = [], []
    for r in respuestas:
        p = r.procedencia()
        p["archivo"] = f"fuentes/{r.sha256[:2]}/{r.sha256}.html"
        fuentes.append(p)
        copias.append((r.sha256, r.contenido))
    return fuentes, copias
