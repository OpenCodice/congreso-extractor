"""Votaciones y expedientes de una legislatura (Popolo: VoteEvent, Vote; extensión: expediente).

Por cada expediente con dictámenes votados que lista el buscador del SIL:

- el expediente (`Seguimiento`): sus asuntos, su cronología y su estatus;
- una votación por cada trámite de votación nominal de cada dictamen, con sus
  conteos;
- el voto de cada legislador en la votación nominal que el SIL desglosa (una
  por asunto). Las demás quedan solo con conteos y `votos_publicados: false`.

Los votos se ligan al mandato por nombre, dentro de la cámara que indica el
prefijo ("Dip."/"Sen.") y de la legislatura. Un nombre que no se encuentra, o
que se encuentra dos veces, deja fuera el expediente completo: un voto mal
atribuido es peor que uno faltante. Un expediente se escribe completo o no se
escribe.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from . import catalogos, datos, red, sil
from .texto import clave_nombre, romano

_CAMARA = {"Cámara de Diputados": "diputados", "Cámara de Senadores": "senado",
           "Comisión Permanente": "permanente"}


class Omitido(RuntimeError):
    """El asunto no se publica: algo no cuadra con la certeza que se exige."""


def indice_mandatos(raiz: Path, leg: str) -> dict[tuple[str, str], list[dict]]:
    """(cámara, nombre normalizado) → mandatos."""
    indice: dict[tuple[str, str], list[dict]] = {}
    personas = {p["id"]: p for p in datos.todos(raiz, "personas")}
    for camara in ("diputados", "senado"):
        for m in datos.todos(raiz, f"mandatos/{leg}/{camara}"):
            indice.setdefault((camara, clave_nombre(personas[m["person_id"]]["name"])), []).append(m)
    return indice


def _resultado(texto: str) -> str | None:
    t = texto.lower()
    if t.startswith("aprobad"):
        return "pass"
    if t.startswith(("desechad", "rechazad", "se rechaz")):
        return "fail"
    return None


def _procedencia(r: red.Respuesta) -> tuple[dict, tuple[str, bytes]]:
    p = r.procedencia()
    p["archivo"] = f"fuentes/{r.sha256[:2]}/{r.sha256}.html"
    return p, (r.sha256, r.contenido)


def atribuir(votos: list[dict], indice: dict, camaras: set[str], contexto: str) -> list[dict]:
    salida, faltan, dobles = [], [], []
    for v in votos:
        if v["camara"] not in camaras:
            raise Omitido(f"{contexto}: votante de {v['camara']} en una votación de {sorted(camaras)}")
        candidatos = indice.get((v["camara"], clave_nombre(v["nombre"])), [])
        if not candidatos:
            faltan.append(v["fuente_nombre"])
        elif len(candidatos) > 1:
            dobles.append(v["fuente_nombre"])
        else:
            m = candidatos[0]
            salida.append({
                "voter_id": m["person_id"],
                "mandato_id": m["id"],
                "option": v["opcion"],
                "group_id": catalogos.partido(v["partido"]),
                "grupo_fuente": v["partido"],
            })
    if faltan or dobles:
        raise Omitido(f"{contexto}: sin mandato {faltan[:5]} ({len(faltan)}); ambiguos {dobles[:5]}")
    return salida


OPCIONES = ("yes", "no", "abstain", "absent")


def faltantes_en_lista(votos: list[dict], detalle: dict, contexto: str) -> list[dict]:
    """Lo que el resumen por grupo cuenta y la lista nominal no trae.

    El SIL a veces deja fuera de la lista a un legislador que su propio resumen
    sí cuenta. Cada voto listado sigue siendo oficial, así que la lista se
    publica si es un subconjunto del resumen y lo que falta queda declarado. Un
    voto de más, un grupo que el resumen no conoce o un resumen que no suma no
    tienen explicación: el asunto se omite.
    """
    grupos = [g for g in detalle["grupos"] if g["grupo"] != "Total"]
    if not grupos:
        raise Omitido(f"{contexto}: sin resumen por grupo")
    lista = Counter((v["partido"], v["opcion"]) for v in votos)
    ajenos = {p for p, _ in lista} - {g["grupo"] for g in grupos}
    if ajenos:
        raise Omitido(f"{contexto}: grupos {sorted(ajenos)} en la lista y no en el resumen")
    general = detalle["general"]
    for k in ("yes", "no", "abstain"):
        if sum(g[k] for g in grupos) != general[k]:
            raise Omitido(f"{contexto}: los grupos no suman {k} = {general[k]}")
    total = next((g for g in detalle["grupos"] if g["grupo"] == "Total"), None)
    if total and any(sum(g[k] for g in grupos) != total[k] for k in OPCIONES):
        raise Omitido(f"{contexto}: los grupos no suman la fila Total")
    faltan = []
    for g in grupos:
        for k in OPCIONES:
            dif = g[k] - lista[(g["grupo"], k)]
            if dif < 0:
                raise Omitido(f"{contexto}: {g['grupo']} {k} = {lista[(g['grupo'], k)]} en la lista, {g[k]} en el resumen")
            if dif:
                faltan.append({"grupo": g["grupo"], "option": k, "value": dif})
    return faltan


def eventos_de_asunto(leg: str, fila: dict, indice: dict) -> tuple[list[dict], list[tuple[str, bytes]], list[dict]]:
    """Las votaciones nominales de un dictamen, en memoria, las copias de sus fuentes y sus trámites."""
    camara = _CAMARA.get(fila["camara"] or "")
    if camara is None:
        raise Omitido(f"cámara desconocida: {fila['camara']!r}")
    organizacion = "comision-permanente" if camara == "permanente" else catalogos.CAMARAS[camara][0]
    camaras = {"diputados", "senado"} if camara == "permanente" else {camara}
    asunto = fila["clave"]
    copias = []

    rt = red.obtener(sil.url_tramites(asunto))
    tramites = sil.tramites(sil.decodificar(rt.contenido))
    rd = red.obtener(sil.url_detalle_votacion(asunto))
    detalle = sil.detalle_votacion(sil.decodificar(rd.contenido))

    nominales = [t for t in tramites if t["tipo"] == "Votación nominal"]
    if any("conteos" not in t for t in nominales):
        raise Omitido(f"asunto {asunto}: una votación nominal sin conteos legibles")
    if not nominales and fila["conteos"]:
        nominales = [{"tipo": "Votación nominal", "texto": "", "conteos": fila["conteos"]}]

    general = detalle["general"]
    con_votos = None
    if general and detalle["tramite"]:
        clave = (general["yes"], general["no"], general["abstain"])
        iguales = [i for i, t in enumerate(nominales)
                   if (t["conteos"]["yes"], t["conteos"]["no"], t["conteos"]["abstain"]) == clave]
        if len(iguales) == 1:
            con_votos = iguales[0]
        elif not nominales:
            nominales = [{"tipo": "Votación nominal", "texto": "",
                          "conteos": {k: general[k] for k in ("yes", "no", "abstain")}}]
            con_votos = 0

    p_tramites, c = _procedencia(rt)
    copias.append(c)
    eventos = []
    for i, t in enumerate(nominales, 1):
        evento = {
            "id": f"sil-{asunto}-{i}",
            "organization_id": organizacion,
            "legislative_period_id": leg,
            "camara": camara,
            "start_date": fila["fecha"],
            "fecha_fuente": "fecha del dictamen a discusión en el SIL",
            "expediente_id": f"sil-{fila['seguimiento']}",
            "asunto": asunto,
            "orden": i,
            "motion": {"text": t["texto"] or None, "denominacion": fila["denominacion"],
                       "clasificacion": fila["clasificacion"]},
            "result": _resultado(t["texto"]),
            "counts": [{"option": k, "value": v} for k, v in t["conteos"].items()],
            "votos_publicados": False,
            "votes": [],
            "sources": [p_tramites],
        }
        if con_votos == i - 1:
            rv = red.obtener(sil.url_votos(asunto, detalle["tramite"]))
            votos = sil.votos(sil.decodificar(rv.contenido))
            faltan = faltantes_en_lista(votos, detalle, f"asunto {asunto}")
            evento["votes"] = atribuir(votos, indice, camaras, f"asunto {asunto}")
            evento["votos_publicados"] = True
            evento["tramite"] = detalle["tramite"]
            ausentes = sum(g["absent"] for g in detalle["grupos"] if g["grupo"] != "Total")
            evento["counts"].append({"option": "absent", "value": ausentes})
            if faltan:
                evento["votos_faltantes"] = faltan
            evento["group_results"] = [g for g in detalle["grupos"] if g["grupo"] != "Total"]
            for r in (rd, rv):
                p, c = _procedencia(r)
                evento["sources"].append(p)
                copias.append(c)
        eventos.append(evento)
    return eventos, copias, tramites


def expediente(seguimiento: str, fila: dict) -> tuple[dict, list[tuple[str, bytes]]]:
    rs = red.obtener(sil.url_seguimiento(seguimiento, fila["clave"]))
    seg = sil.seguimiento(sil.decodificar(rs.contenido))
    rh = red.obtener(sil.url_historial(seguimiento, fila["clave"]))
    asuntos = sil.historial(sil.decodificar(rh.contenido))
    if not asuntos:
        raise Omitido(f"expediente {seguimiento}: historial vacío")
    ps, cs = _procedencia(rs)
    ph, ch = _procedencia(rh)
    return {
        "id": f"sil-{seguimiento}",
        "seguimiento": seguimiento,
        "denominacion": seg["denominacion"],
        "camara_origen": seg["camara_origen"],
        "camara_revisora": seg["camara_revisora"],
        "legislatura": seg["legislatura"],
        "ultimo_estatus": seg["ultimo_estatus"],
        "publicado_dof": fila["publicado_dof"],
        "cronologia": seg["cronologia"],
        "asuntos": asuntos,
        "votaciones": [],
        "tramites": {},
        "sources": [ps, ph],
    }, [cs, ch]


def construir(raiz: Path, legislatura: int, solo: set[str] | None = None) -> dict:
    """Todas las votaciones de la legislatura (o solo los asuntos de `solo`)."""
    leg = romano(legislatura).lower()
    datos.escribir(raiz, "organizaciones/comision-permanente.json", {
        "id": "comision-permanente", "name": "Comisión Permanente", "classification": "committee",
        "parent_id": "congreso-de-la-union"})
    r = red.obtener(sil.URL_BUSQUEDA_VOTACIONES, sil.formulario_votaciones(legislatura))
    filas = sil.resultados_votacion(sil.decodificar(r.contenido))
    if not filas:
        raise RuntimeError("el buscador de votaciones no devolvió filas")
    if solo:
        # Un expediente se escribe completo: se toman todos sus dictámenes.
        seguimientos = {f["seguimiento"] for f in filas if f["clave"] in solo}
        filas = [f for f in filas if f["seguimiento"] in seguimientos]
    indice = indice_mandatos(raiz, leg)

    por_seguimiento: dict[str, list[dict]] = {}
    for f in filas:
        por_seguimiento.setdefault(f["seguimiento"], []).append(f)

    errores, escritos = [], 0
    for seg, dictamenes in sorted(por_seguimiento.items()):
        principal = next((f for f in dictamenes if f["publicado_dof"]), dictamenes[0])
        try:
            exp, copias = expediente(seg, principal)
            eventos = []
            for f in dictamenes:
                ev, cp, tr = eventos_de_asunto(leg, f, indice)
                eventos += ev
                copias += cp
                exp["tramites"][f["clave"]] = tr
        except (Omitido, ValueError, KeyError) as e:
            errores.append(f"expediente {seg}: {e}")
            continue
        exp["votaciones"] = sorted(e["id"] for e in eventos)
        for sha, contenido in copias:
            datos.guardar_fuente(raiz, sha, contenido)
        for f in dictamenes:
            # Una votación que el SIL ya no reporta no se queda con datos viejos.
            for viejo in (raiz / "votaciones" / leg).glob(f"*/sil-{f['clave']}-*.json"):
                if viejo.stem not in exp["votaciones"]:
                    viejo.unlink()
        for e in eventos:
            datos.escribir(raiz, f"votaciones/{leg}/{e['camara']}/{e['id']}.json", e)
            escritos += 1
        datos.escribir(raiz, f"expedientes/sil-{seg}.json", exp)
    return {"expedientes": len(por_seguimiento) - len(errores), "votaciones": escritos,
            "omitidos": len(errores), "errores": errores, "busqueda": r.procedencia()}
