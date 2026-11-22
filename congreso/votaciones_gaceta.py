"""Votaciones nominales de la Cámara de Diputados desde la Gaceta, ligadas al SIL.

Cada votación de la Gaceta es un VoteEvent propio (`gaceta-{tabla}`) con el
voto de cada diputado: así quedan también las de lo particular, que el SIL
solo da como conteos. El enlace con el SIL y el cotejo, en `cotejo`.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from . import cotejo, datos, gaceta, lecturas, red, validar
from .texto import romano
from .votaciones_senado import VIGENCIA, escribir

FUENTE = "la votación de la Gaceta"


def evento(leg: str, v: dict, filas: list[dict], idx, fuentes: list[dict]) -> dict:
    lista = Counter((f["grupo"], f["opcion"]) for f in filas)
    inconsistencias = []
    for g, conteos in v["conteos"].items():
        for o, n in conteos.items():
            if g == "Total":
                listados = sum(c for (_, op), c in lista.items() if op == o)
            else:
                listados = lista[(g, o)]
            if listados != n:
                inconsistencias.append(f"{g} {o}: {listados} en la lista, {n} en la tabla")
    votos, sin_mandato, otras = cotejo.votos(filas, idx)
    total = v["conteos"]["Total"]
    e = {
        "id": f"gaceta-{v['clave']}",
        "organization_id": "camara-de-diputados",
        "legislative_period_id": leg,
        "camara": "diputados",
        "start_date": v["fecha"],
        "fecha_fuente": "fecha de la votación en la Gaceta Parlamentaria",
        "expediente_id": None,
        "asunto": None,
        "motion": {"text": v["descripcion"] or None, "denominacion": v["titulo"]},
        "result": None,
        "counts": [{"option": o, "value": total[o]} for _, o in gaceta.SENTIDOS],
        "votos_publicados": True,
        "votes": votos,
        "group_results": [dict(grupo=g, **c) for g, c in v["conteos"].items() if g != "Total"],
        "sources": fuentes,
        **({"votos_faltantes": cotejo.faltantes(sin_mandato)} if sin_mandato else {}),
        **({"inconsistencias": list(dict.fromkeys(inconsistencias + otras))} if inconsistencias + otras else {}),
        **({"lecturas": v["lecturas"]} if v.get("lecturas") else {}),
    }
    validar.declarar_diferencias(e)
    return e


def construir(raiz: Path, legislatura: int, solo: set[str] | None = None) -> dict:
    leg = romano(legislatura).lower()
    ri = red.obtener(gaceta.URL_INDICE)
    urls = gaceta.periodos(gaceta.decodificar(ri.contenido), legislatura)
    if not urls:
        raise RuntimeError("el índice de votaciones de la Gaceta está vacío")
    votaciones, errores = [], []
    completo = True
    for url in urls:
        red.anticipar(url)
    pendientes = 0
    for url in urls:
        try:
            rp = red.obtener(url)
        except red.Pendiente:
            pendientes += 1
            completo = False
            continue
        del_periodo = gaceta.periodo(gaceta.decodificar(rp.contenido))
        if not del_periodo:
            # Un periodo publicado sin votaciones es una página que no se leyó bien.
            errores.append(f"la página del periodo {url} no trae votaciones")
            completo = False
        votaciones += del_periodo
    # Con el índice y todos los periodos leídos, es todo lo que la Gaceta publica hoy.
    vigentes = None if solo or not completo else {f"gaceta-{x['tabla'].removeprefix('tabla')}" for x in votaciones}
    listadas = [(x["tabla"].removeprefix("tabla"), orden) for orden, x in enumerate(votaciones)]
    eventos_sil = [e for e in datos.todos(raiz, f"votaciones/{leg}/diputados") if e["id"].startswith("sil-")]

    leidas = []
    for orden, x in enumerate(votaciones):
        if solo and x["tabla"] not in solo:
            continue
        clave = x["tabla"].removeprefix("tabla")
        try:
            rt = red.obtener(x["url"], vigencia_horas=VIGENCIA)
            t, lt = lecturas.leer("gaceta", "tabla", clave, rt, {})
            cuerpo = gaceta.datos_lista(t["evento"])
            rl = red.obtener(gaceta.BASE + t["accion"], cuerpo, vigencia_horas=VIGENCIA)
            filas, ll = lecturas.leer("gaceta", "lista", clave, rl, {"conteos": t["conteos"]})
            usadas = [l for l in (lt, ll) if l]
            if usadas:
                t = dict(t, lecturas=usadas)
        except red.Pendiente:
            pendientes += 1
            continue
        except (ValueError, RuntimeError, KeyError) as e:
            errores.append(f"gaceta {clave}: {e}")
            continue
        v = dict(t, clave=clave, orden=orden, descripcion=x["descripcion"],
                 asunto=x["asunto"], fecha=t["fecha"] or x["fecha_sesion"])
        leidas.append((v, filas, [rt, rl]))

    errores += lecturas.AVISOS
    lecturas.AVISOS.clear()
    enlaces = cotejo.emparejar([v for v, _, _ in leidas], eventos_sil, FUENTE)
    return dict(escribir(raiz, leg, "diputados", leidas, enlaces, eventos_sil, evento, errores,
                         {"indice": ri.procedencia()}, "gaceta-", vigentes, FUENTE, listadas),
                pendientes_de_descarga=pendientes)
