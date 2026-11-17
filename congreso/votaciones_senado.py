"""Votaciones nominales del Senado desde su sitio, ligadas a las del SIL.

Cada votación del sitio del Senado es un VoteEvent propio (`senado-{clave}`)
con el voto de cada senador: así quedan también las de lo particular, que el
SIL solo da como conteos. Se liga al expediente y a la votación del SIL cuando
el par es inequívoco:

1. misma fecha, y el asunto del SIL (su denominación) contenido en el título
   del Senado, con un único mejor candidato;
2. el Senado tiene para ese asunto tantas votaciones como el SIL trámites
   nominales: se emparejan en orden.

Si los conteos de las dos fuentes difieren, ambas se conservan y la
diferencia queda en `discrepancias`. Un senador que no se liga a un único
mandato deja fuera esa votación.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from . import catalogos, datos, red, senado
from .decretos import _palabras
from .texto import romano

UMBRAL = 0.7
MARGEN = 0.15


class Omitida(RuntimeError):
    pass


def indice_senadores(raiz: Path, leg: str) -> list[tuple[Counter, dict]]:
    personas = {p["id"]: p for p in datos.todos(raiz, "personas")}
    return [(Counter(senado.clave_tokens(personas[m["person_id"]]["name"])), m)
            for m in datos.todos(raiz, f"mandatos/{leg}/senado")]


def mandato(nombre: str, indice: list[tuple[Counter, dict]]) -> tuple[dict, str] | None:
    """El mandato de un senador: mismo nombre o, si el Senado lo abrevia, el
    único cuyo nombre contiene todas sus palabras."""
    c = Counter(senado.clave_tokens(nombre))
    exactos = [m for k, m in indice if k == c]
    if len(exactos) == 1:
        return exactos[0], "nombre"
    if exactos:
        return None
    contenidos = [m for k, m in indice if not (c - k)]
    return (contenidos[0], "nombre abreviado") if len(contenidos) == 1 else None


def contencion(denominacion: str, titulo: str) -> float:
    x = _palabras(denominacion)
    return len(x & _palabras(titulo)) / len(x) if x else 0.0


def emparejar(votaciones: list[dict], eventos_sil: list[dict]) -> dict[str, dict]:
    """clave del Senado → {expediente_id, asunto, votacion_sil?, criterio}."""
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
        vs = sorted(vs, key=lambda v: int(v["clave"]))
        pares = len(vs) == len(sil)
        for i, v in enumerate(vs):
            enlace = dict(base, criterio="misma fecha y el asunto del SIL contenido en el título del Senado")
            if pares:
                enlace["votacion_sil"] = sil[i]["id"]
                enlace["criterio"] += f"; votación {i + 1} de {len(vs)} del asunto en ambas fuentes"
            enlaces[v["clave"]] = enlace
    return enlaces


def evento(leg: str, v: dict, filas: list[dict], indice, fuentes: list[dict]) -> dict:
    conteo = Counter(f["opcion"] for f in filas)
    if any(conteo[k] != v["conteos"][k] for k in ("yes", "no", "abstain")) or \
            sum(conteo.values()) != sum(v["conteos"].values()) + conteo["absent"]:
        raise Omitida(f"senado {v['clave']}: la tabla {dict(conteo)} no suma los conteos {v['conteos']}")
    votos, faltan = [], []
    for f in filas:
        r = mandato(f["nombre"], indice)
        if r is None:
            faltan.append(f["nombre"])
            continue
        m, criterio = r
        votos.append({"voter_id": m["person_id"], "mandato_id": m["id"], "option": f["opcion"],
                      "group_id": catalogos.partido(f["grupo"]), "grupo_fuente": f["grupo"],
                      "senado_id": f["senado_id"], **({"enlace": criterio} if criterio != "nombre" else {})})
    if faltan:
        raise Omitida(f"senado {v['clave']}: sin mandato único {faltan[:5]} ({len(faltan)})")
    return {
        "id": f"senado-{v['clave']}",
        "organization_id": "senado",
        "legislative_period_id": leg,
        "camara": "senado",
        "start_date": v["fecha"],
        "fecha_fuente": "fecha de la sesión en el sitio del Senado",
        "expediente_id": None,
        "asunto": None,
        "motion": {"text": v["motion"], "denominacion": v["asunto"]},
        "result": None,
        "counts": [{"option": k, "value": v["conteos"][k]} for k in ("yes", "no", "abstain")]
                  + [{"option": "absent", "value": conteo["absent"]}],
        "votos_publicados": True,
        "votes": votos,
        "sources": fuentes,
    }


def construir(raiz: Path, legislatura: int, solo: set[str] | None = None) -> dict:
    leg = romano(legislatura).lower()
    rl = red.obtener(senado.url_listado(legislatura, romano(legislatura)))
    listado = senado.listado(senado.decodificar(rl.contenido))
    if not listado:
        raise RuntimeError("el listado de votaciones del Senado está vacío")
    if solo:
        listado = [x for x in listado if x["clave"] in solo]
    indice = indice_senadores(raiz, leg)
    eventos_sil = [e for e in datos.todos(raiz, f"votaciones/{leg}/senado") if e["id"].startswith("sil-")]

    leidas, errores = [], []
    for x in listado:
        try:
            rv = red.obtener(senado.url_votacion(x["clave"], legislatura), vigencia_horas=24 * 30)
            v = dict(senado.votacion(senado.decodificar(rv.contenido)), clave=x["clave"])
            rt = red.obtener(senado.url_tabla(x["clave"], legislatura), vigencia_horas=24 * 30)
            filas = senado.tabla(senado.decodificar(rt.contenido))
            leidas.append((v, filas, (rv, rt)))
        except (ValueError, RuntimeError, KeyError) as e:
            errores.append(f"senado {x['clave']}: {e}")

    enlaces = emparejar([v for v, _, _ in leidas], eventos_sil)
    sil_por_id = {e["id"]: e for e in eventos_sil}
    escritas = ligadas = 0
    for v, filas, respuestas in leidas:
        fuentes, copias = [], []
        for r in respuestas:
            p = r.procedencia()
            p["archivo"] = f"fuentes/{r.sha256[:2]}/{r.sha256}.html"
            fuentes.append(p)
            copias.append((r.sha256, r.contenido))
        try:
            e = evento(leg, v, filas, indice, fuentes)
        except (Omitida, KeyError) as err:
            errores.append(str(err))
            continue
        enlace = enlaces.get(v["clave"])
        if enlace:
            e.update(enlace)
            ligadas += 1
            par = sil_por_id.get(enlace.get("votacion_sil"))
            if par:
                propios = {c["option"]: c["value"] for c in e["counts"] if c["option"] != "absent"}
                ajenos = {c["option"]: c["value"] for c in par["counts"] if c["option"] != "absent"}
                diferencia = {}
                if propios != ajenos:
                    diferencia["counts_sil"] = par["counts"]
                if par["votes"]:
                    del_sil = {x["voter_id"]: x["option"] for x in par["votes"]}
                    distintos = sorted(x["voter_id"] for x in e["votes"] if del_sil.get(x["voter_id"]) != x["option"])
                    if distintos:
                        diferencia["votantes_distintos"] = distintos
                if diferencia:
                    e["discrepancias"] = [dict(diferencia, votacion=par["id"])]
        for sha, contenido in copias:
            datos.guardar_fuente(raiz, sha, contenido)
        datos.escribir(raiz, f"votaciones/{leg}/senado/{e['id']}.json", e)
        escritas += 1
    return {"votaciones": escritas, "ligadas": ligadas,
            "con_par_sil": sum(1 for x in enlaces.values() if "votacion_sil" in x),
            "omitidas": len(errores), "errores": errores, "listado": rl.procedencia()}
