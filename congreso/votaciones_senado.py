"""Votaciones nominales del Senado desde su sitio, ligadas a las del SIL.

Cada votación del sitio del Senado es un VoteEvent propio (`senado-{clave}`)
con el voto de cada senador: así quedan también las de lo particular, que el
SIL solo da como conteos. El enlace con el SIL y el cotejo, en `cotejo`.
"""
from __future__ import annotations

import os
import time
from collections import Counter
from pathlib import Path

from . import cotejo, datos, lecturas, nombres, red, senado, validar
from .cotejo import Omitida
from .texto import romano


# Una votación publicada no cambia: se descarga una vez al año a lo más (el
# Senado bloquea si se le pide rápido, así que volver a bajarlas cuesta horas).
VIGENCIA = 24 * 365
# Esperas ante el firewall del Senado antes de dejar el resto para otra corrida.
ESPERAS = (120, 600)
# Minutos de descarga por corrida: con el firewall, bajar todo de cero toma más
# que una corrida; lo que falte sigue en la siguiente, desde el caché, y así no
# se quedan sin correr los pasos de después.
PRESUPUESTO = float(os.environ.get("CONGRESO_PRESUPUESTO_SENADO", "120"))
FUENTE = "la votación del Senado"


def indice(raiz: Path, leg: str, camara: str) -> nombres.Indice:
    personas = {p["id"]: p for p in datos.todos(raiz, "personas")}
    return nombres.Indice(list(datos.todos(raiz, f"mandatos/{leg}/{camara}")), personas)


def evento(leg: str, v: dict, filas: list[dict], idx: nombres.Indice, fuentes: list[dict]) -> dict:
    conteo = Counter(f["opcion"] for f in filas)
    inconsistencias = [f"{k}: {conteo[k]} en la tabla nominal, {v['conteos'][k]} en el conteo de la votación"
                       for k in ("yes", "no", "abstain") if conteo[k] != v["conteos"][k]]
    votos, sin_mandato, otras = cotejo.votos(filas, idx, lambda f: {"senado_id": f["senado_id"]})
    e = {
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
        **({"votos_faltantes": cotejo.faltantes(sin_mandato)} if sin_mandato else {}),
        **({"inconsistencias": list(dict.fromkeys(inconsistencias + otras))} if inconsistencias + otras else {}),
        **({"lecturas": v["lecturas"]} if v.get("lecturas") else {}),
    }
    validar.declarar_diferencias(e)
    return e


def leer_votacion(clave: str, rv: red.Respuesta, rt: red.Respuesta) -> tuple[dict, list[dict]]:
    """Página de la votación y tabla nominal, por el parser o por una lectura
    verificada. Cada página que falle sin lectura se guarda como fallo, con lo
    que la otra página ya dice para que el agente y la verificación lo usen."""
    tabla = lecturas.intentar("senado", "tabla", rt)
    conteo_tabla = ({k: sum(1 for f in tabla if f["opcion"] == k) for k in ("yes", "no", "abstain")}
                    if tabla else None)
    usadas, pendiente = [], None
    try:
        v, lv = lecturas.leer("senado", "votacion", clave, rv, {"conteo_tabla": conteo_tabla} if tabla else {})
        usadas += [lv] if lv else []
    except lecturas.SinLectura as e:
        v, pendiente = None, e
    try:
        filas, lt = lecturas.leer("senado", "tabla", clave, rt, {"conteos": v["conteos"]} if v else {})
        usadas += [lt] if lt else []
    except lecturas.SinLectura as e:
        pendiente = pendiente or e
    if pendiente:
        raise pendiente
    return (dict(v, lecturas=usadas) if usadas else v), filas


def construir(raiz: Path, legislatura: int, solo: set[str] | None = None) -> dict:
    leg = romano(legislatura).lower()
    rl = red.obtener(senado.url_listado(romano(legislatura)))
    listado = senado.listado(senado.decodificar(rl.contenido))
    if not listado:
        raise RuntimeError("el listado de votaciones del Senado está vacío")
    vigentes = None if solo else {f"senado-{x['clave']}" for x in listado}
    listadas = [(x["clave"], int(x["clave"])) for x in listado]
    if solo:
        listado = [x for x in listado if x["clave"] in solo]
    eventos_sil = [e for e in datos.todos(raiz, f"votaciones/{leg}/senado") if e["id"].startswith("sil-")]

    leidas, errores, pendientes = [], [], 0
    inicio = time.monotonic()
    for i, x in enumerate(listado):
        if time.monotonic() - inicio > PRESUPUESTO * 60:
            errores.append(f"se agotaron los {PRESUPUESTO:g} min de descarga del Senado; quedan "
                           f"{len(listado) - i} votaciones para la siguiente corrida")
            break
        red.anticipar(senado.url_tabla(x["clave"]))
        try:
            rv = red.obtener(senado.url_votacion(x["clave"]), vigencia_horas=VIGENCIA, bloqueos=ESPERAS)
            rt = red.obtener(senado.url_tabla(x["clave"]), vigencia_horas=VIGENCIA, bloqueos=ESPERAS)
            v, filas = leer_votacion(x["clave"], rv, rt)
            leidas.append((dict(v, clave=x["clave"], orden=int(x["clave"])), filas, [rv, rt]))
        except red.Bloqueado:
            # El firewall del sitio no cede: lo que falta queda para la siguiente
            # corrida (lo ya descargado está en el caché) y no se marca retirado.
            errores.append(f"el sitio del Senado bloqueó las peticiones; quedan {len(listado) - i} "
                           f"votaciones para la siguiente corrida")
            break
        except red.Pendiente:
            pendientes += 1
        except (ValueError, RuntimeError, KeyError) as e:
            errores.append(f"senado {x['clave']}: {e}")

    errores += lecturas.AVISOS
    lecturas.AVISOS.clear()
    enlaces = cotejo.emparejar([v for v, _, _ in leidas], eventos_sil, FUENTE)
    return dict(escribir(raiz, leg, "senado", leidas, enlaces, eventos_sil, evento, errores,
                         {"listado": rl.procedencia()}, "senado-", vigentes, FUENTE, listadas),
                pendientes_de_descarga=pendientes)


def escribir(raiz: Path, leg: str, camara: str, leidas, enlaces, eventos_sil, hacer_evento, errores,
             extra: dict, prefijo: str, vigentes: set[str] | None, fuente: str = "la fuente",
             listadas: list[tuple[str, int]] | tuple = ()) -> dict:
    """Escribe los eventos leídos; con `vigentes` (todo lo que la fuente lista
    hoy), marca como retirado lo publicado antes que ya no aparece. `listadas`:
    clave y orden de cada votación que la fuente lista, leída o no."""
    sil_por_id = {e["id"]: e for e in eventos_sil}
    hechos = []
    for v, filas, respuestas in leidas:
        fuentes, copias = cotejo.procedencias(respuestas)
        try:
            e = hacer_evento(leg, v, filas, idx_por_camara(raiz, leg, camara), fuentes)
        except (Omitida, KeyError) as err:
            errores.append(str(err))
            continue
        hechos.append((v, e, copias))

    if hechos:
        completar(raiz, leg, camara, prefijo, hechos, enlaces, eventos_sil, fuente, listadas)

    escritas = ligadas = 0
    for v, e, copias in hechos:
        enlace = enlaces.get(v["clave"])
        if enlace:
            e.update(enlace)
            ligadas += 1
            par = sil_por_id.get(enlace.get("votacion_sil"))
            if par:
                cotejo.cotejar(e, par)
        for sha, contenido in copias:
            datos.guardar_fuente(raiz, sha, contenido)
        datos.escribir(raiz, f"votaciones/{leg}/{camara}/{e['id']}.json", e)
        escritas += 1
    retiradas = 0
    if vigentes is not None:
        ausentes = [r for r in sorted((raiz / "votaciones" / leg / camara).glob(f"{prefijo}*.json"))
                    if r.stem not in vigentes and "retirada_de_la_fuente" not in datos.leer(raiz, r.relative_to(raiz).as_posix())]
        # Muchas de golpe apuntan a una lectura incompleta de la fuente, no a retiros.
        if len(ausentes) > max(5, len(vigentes) // 10):
            errores.append(f"{len(ausentes)} votaciones publicadas no aparecen en la fuente; no se marcan como retiradas")
        else:
            for ruta in ausentes:
                retiradas += datos.marcar_retirada(raiz, ruta.relative_to(raiz).as_posix())
    return {"votaciones": escritas, "ligadas": ligadas, "retiradas_de_la_fuente": retiradas,
            "con_par_sil": sum(1 for x in enlaces.values() if "votacion_sil" in x),
            "omitidas": len(errores), "errores": errores, **extra}


def completar(raiz: Path, leg: str, camara: str, prefijo: str, hechos, enlaces, eventos_sil, fuente: str,
              listadas) -> None:
    """Liga por cuentas lo que quedó sin par (`cotejo.completar`). Para saber
    si una candidata es la única hace falta todo lo que publica la fuente: lo
    que esta corrida no volvió a leer se toma de lo ya publicado, y en las
    fechas donde puede haber una votación que no se conoce, no se liga."""
    propios = {e["id"] for _, e, _ in hechos}
    publicadas = [r for r in datos.todos(raiz, f"votaciones/{leg}/{camara}")
                  if r["id"].startswith(prefijo) and r["id"] not in propios]
    orden = {prefijo + clave: o for clave, o in listadas}
    conocidas = ([(v["orden"], e["start_date"]) for v, e, _ in hechos]
                 + [(orden[r["id"]], r["start_date"]) for r in publicadas if r["id"] in orden])
    vistas = propios | {r["id"] for r in publicadas}
    cotejo.completar(enlaces, {v["clave"]: (v, e) for v, e, _ in hechos}, publicadas, eventos_sil, fuente,
                     cotejo.inciertas([o for i, o in orden.items() if i not in vistas], conocidas))


_INDICES: dict[tuple[Path, str, str], nombres.Indice] = {}


def idx_por_camara(raiz: Path, leg: str, camara: str) -> nombres.Indice:
    clave = (raiz, leg, camara)
    if clave not in _INDICES:
        _INDICES[clave] = indice(raiz, leg, camara)
    return _INDICES[clave]
