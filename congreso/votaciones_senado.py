"""Votaciones nominales del Senado desde su sitio, ligadas a las del SIL.

Cada votación del sitio del Senado es un VoteEvent propio (`senado-{clave}`)
con el voto de cada senador: así quedan también las de lo particular, que el
SIL solo da como conteos. El enlace con el SIL y el cotejo, en `cotejo`.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from . import cotejo, datos, nombres, red, senado, validar
from .cotejo import Omitida
from .texto import romano


# Esperas ante el firewall del Senado antes de dejar el resto para otra corrida.
ESPERAS = (120, 600)


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
    }
    validar.declarar_diferencias(e)
    return e


def construir(raiz: Path, legislatura: int, solo: set[str] | None = None) -> dict:
    leg = romano(legislatura).lower()
    rl = red.obtener(senado.url_listado(legislatura, romano(legislatura)))
    listado = senado.listado(senado.decodificar(rl.contenido))
    if not listado:
        raise RuntimeError("el listado de votaciones del Senado está vacío")
    vigentes = None if solo else {f"senado-{x['clave']}" for x in listado}
    if solo:
        listado = [x for x in listado if x["clave"] in solo]
    eventos_sil = [e for e in datos.todos(raiz, f"votaciones/{leg}/senado") if e["id"].startswith("sil-")]

    leidas, errores = [], []
    for i, x in enumerate(listado):
        try:
            # Una votación publicada no cambia: se descarga una vez al mes a lo más.
            rv = red.obtener(senado.url_votacion(x["clave"], legislatura), vigencia_horas=24 * 30, bloqueos=ESPERAS)
            v = dict(senado.votacion(senado.decodificar(rv.contenido)), clave=x["clave"], orden=int(x["clave"]))
            rt = red.obtener(senado.url_tabla(x["clave"], legislatura), vigencia_horas=24 * 30, bloqueos=ESPERAS)
            leidas.append((v, senado.tabla(senado.decodificar(rt.contenido)), [rv, rt]))
        except red.Bloqueado:
            # El firewall del sitio no cede: lo que falta queda para la siguiente
            # corrida (lo ya descargado está en el caché) y no se marca retirado.
            errores.append(f"el sitio del Senado bloqueó las peticiones; quedan {len(listado) - i} "
                           f"votaciones para la siguiente corrida")
            break
        except (ValueError, RuntimeError, KeyError) as e:
            errores.append(f"senado {x['clave']}: {e}")

    enlaces = cotejo.emparejar([v for v, _, _ in leidas], eventos_sil, "la votación del Senado")
    return escribir(raiz, leg, "senado", leidas, enlaces, eventos_sil, evento, errores,
                    {"listado": rl.procedencia()}, "senado-", vigentes)


def escribir(raiz: Path, leg: str, camara: str, leidas, enlaces, eventos_sil, hacer_evento, errores,
             extra: dict, prefijo: str, vigentes: set[str] | None) -> dict:
    """Escribe los eventos leídos; con `vigentes` (todo lo que la fuente lista
    hoy), marca como retirado lo publicado antes que ya no aparece."""
    sil_por_id = {e["id"]: e for e in eventos_sil}
    escritas = ligadas = 0
    for v, filas, respuestas in leidas:
        fuentes, copias = cotejo.procedencias(respuestas)
        try:
            e = hacer_evento(leg, v, filas, idx_por_camara(raiz, leg, camara), fuentes)
        except (Omitida, KeyError) as err:
            errores.append(str(err))
            continue
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


_INDICES: dict[tuple[Path, str, str], nombres.Indice] = {}


def idx_por_camara(raiz: Path, leg: str, camara: str) -> nombres.Indice:
    clave = (raiz, leg, camara)
    if clave not in _INDICES:
        _INDICES[clave] = indice(raiz, leg, camara)
    return _INDICES[clave]
