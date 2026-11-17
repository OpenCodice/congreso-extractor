"""Votaciones nominales de la Cámara de Diputados desde la Gaceta, ligadas al SIL.

Cada votación de la Gaceta es un VoteEvent propio (`gaceta-{tabla}`) con el
voto de cada diputado: así quedan también las de lo particular, que el SIL
solo da como conteos. El enlace con el SIL y el cotejo, en `cotejo`.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from . import cotejo, datos, gaceta, red, validar
from .texto import romano
from .votaciones_senado import escribir


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
        rp = red.obtener(url)
        del_periodo = gaceta.periodo(gaceta.decodificar(rp.contenido))
        if not del_periodo:
            # Un periodo publicado sin votaciones es una página que no se leyó bien.
            errores.append(f"la página del periodo {url} no trae votaciones")
            completo = False
        votaciones += del_periodo
    # Con el índice y todos los periodos leídos, es todo lo que la Gaceta publica hoy.
    vigentes = None if solo or not completo else {f"gaceta-{x['tabla'].removeprefix('tabla')}" for x in votaciones}
    if solo:
        votaciones = [x for x in votaciones if x["tabla"] in solo]
    eventos_sil = [e for e in datos.todos(raiz, f"votaciones/{leg}/diputados") if e["id"].startswith("sil-")]

    leidas = []
    for orden, x in enumerate(votaciones):
        clave = x["tabla"].removeprefix("tabla")
        try:
            # Una votación publicada no cambia: se descarga una vez al mes a lo más.
            rt = red.obtener(x["url"], vigencia_horas=24 * 30)
            t = gaceta.tabla(gaceta.decodificar(rt.contenido))
            cuerpo = gaceta.datos_lista(t["evento"])
            rl = red.obtener(gaceta.BASE + t["accion"], cuerpo, vigencia_horas=24 * 30)
            filas = gaceta.lista(gaceta.decodificar(rl.contenido))
        except (ValueError, RuntimeError, KeyError) as e:
            errores.append(f"gaceta {clave}: {e}")
            continue
        v = dict(t, clave=clave, orden=orden, descripcion=x["descripcion"],
                 asunto=x["asunto"], fecha=t["fecha"] or x["fecha_sesion"])
        leidas.append((v, filas, [rt, rl]))

    enlaces = cotejo.emparejar([v for v, _, _ in leidas], eventos_sil, "la votación de la Gaceta")
    return escribir(raiz, leg, "diputados", leidas, enlaces, eventos_sil, evento, errores,
                    {"indice": ri.procedencia()}, "gaceta-", vigentes)
