"""Invariantes del repo de datos. Lo corre `revisar-pr` antes de fusionar.

- Toda referencia apunta a un registro que existe.
- En una votación con votos publicados, los votos suman exactamente los conteos
  y nadie vota dos veces. Si la fuente no cuadra consigo misma, la diferencia
  exacta está declarada (`diferencia_conteos`, `diferencia_grupos`) y explicada
  en `inconsistencias`.
- Cada dato cita al menos una fuente, y las copias guardadas coinciden con su
  huella.
"""
from __future__ import annotations

import gzip
import hashlib
from collections import Counter
from pathlib import Path

from . import datos

# "not voting": la Gaceta lo registra como quórum (pasó lista y no votó).
OPCIONES = {"yes", "no", "abstain", "absent", "not voting"}


def _contenido(ruta: Path) -> bytes:
    """Lo que se descargó: la huella es del original, no de la copia comprimida."""
    return gzip.decompress(ruta.read_bytes()) if ruta.suffix == ".gz" else ruta.read_bytes()


def diferencias(v: dict) -> tuple[dict[str, int], dict[str, int]]:
    """Votos listados (más los declarados en `votos_faltantes`) menos lo que
    dicen los conteos de la votación, por opción y por grupo; solo lo distinto
    de cero."""
    listados = Counter(x["option"] for x in v["votes"])
    por_grupo = Counter(x["grupo_fuente"] for x in v["votes"])
    for f in v.get("votos_faltantes", []):
        listados[f["option"]] += f["value"]
        por_grupo[f["grupo"]] += f["value"]
    conteos = Counter({c["option"]: c["value"] for c in v["counts"]})
    por_opcion = {o: listados[o] - conteos[o] for o in sorted(set(listados) | set(conteos))
                  if listados[o] != conteos[o]}
    grupos = {}
    for g in v.get("group_results", []):
        total = g["total"] if "total" in g else sum(g.get(o, 0) for o in OPCIONES)
        if por_grupo[g["grupo"]] != total:
            grupos[g["grupo"]] = por_grupo[g["grupo"]] - total
    return por_opcion, grupos


def declarar_diferencias(v: dict) -> None:
    """Anota en la votación lo que sus votos difieren de sus conteos (ver `diferencias`)."""
    por_opcion, por_grupo = diferencias(v)
    for campo, valor in (("diferencia_conteos", por_opcion), ("diferencia_grupos", por_grupo)):
        if valor:
            v[campo] = valor
        else:
            v.pop(campo, None)


def validar(raiz: Path) -> list[str]:
    errores: list[str] = []
    orgs = {o["id"] for o in datos.todos(raiz, "organizaciones")}
    personas = {p["id"] for p in datos.todos(raiz, "personas")}
    mandatos = {m["id"]: m for m in datos.todos(raiz, "mandatos")}
    expedientes = {e["id"]: e for e in datos.todos(raiz, "expedientes")}
    votaciones = {v["id"]: v for v in datos.todos(raiz, "votaciones")}

    def fuentes(registro: dict, donde: str) -> None:
        if not registro.get("sources"):
            errores.append(f"{donde}: sin fuentes")
        for s in registro.get("sources", []):
            if "archivo" in s:
                ruta = raiz / s["archivo"]
                if not ruta.exists():
                    errores.append(f"{donde}: falta la copia {s['archivo']}")
                elif hashlib.sha256(_contenido(ruta)).hexdigest() != s["sha256"]:
                    errores.append(f"{donde}: la copia {s['archivo']} no coincide con su huella")

    for m in mandatos.values():
        d = f"mandato {m['id']}"
        if m["person_id"] not in personas:
            errores.append(f"{d}: persona {m['person_id']} no existe")
        for k in ("organization_id", "on_behalf_of_id"):
            if m.get(k) and m[k] not in orgs:
                errores.append(f"{d}: organización {m[k]} no existe")
        if m.get("formula_id") and m["formula_id"] not in mandatos:
            errores.append(f"{d}: fórmula {m['formula_id']} no existe")
        fuentes(m, d)

    for v in votaciones.values():
        d = f"votación {v['id']}"
        if v["organization_id"] not in orgs:
            errores.append(f"{d}: organización {v['organization_id']} no existe")
        # Una votación del Senado o de la Gaceta puede no tener par en el SIL.
        if v["expediente_id"] is None and not v["id"].startswith(("senado-", "gaceta-")):
            errores.append(f"{d}: sin expediente")
        elif v["expediente_id"] is not None and v["expediente_id"] not in expedientes:
            errores.append(f"{d}: expediente {v['expediente_id']} no existe")
        if v.get("votacion_sil") and v["votacion_sil"] not in votaciones:
            errores.append(f"{d}: votacion_sil {v['votacion_sil']} no existe")
        fuentes(v, d)
        if not v["votos_publicados"]:
            if v["votes"]:
                errores.append(f"{d}: tiene votos pero votos_publicados es false")
            continue
        if not v["votes"]:
            errores.append(f"{d}: votos_publicados sin votos")
        # Los votos listados más los que el SIL cuenta y no lista dan los conteos.
        faltan = v.get("votos_faltantes", [])
        if any(f["value"] <= 0 for f in faltan):
            errores.append(f"{d}: votos_faltantes con valores no positivos")
        if any(f.get("nombres_fuente") and len(f["nombres_fuente"]) != f["value"] for f in faltan):
            errores.append(f"{d}: votos_faltantes con nombres que no suman su valor")
        inconsistente = v.get("inconsistencias")
        if inconsistente is not None and not (isinstance(inconsistente, list) and inconsistente
                                              and all(isinstance(x, str) and x for x in inconsistente)):
            errores.append(f"{d}: inconsistencias mal formadas")
        # Si la fuente no cuadra consigo misma, la diferencia exacta va declarada:
        # una nota cualquiera no basta para dejar de sumar.
        por_opcion, por_grupo = diferencias(v)
        if v.get("diferencia_conteos", {}) != por_opcion:
            errores.append(f"{d}: los votos difieren de los conteos en {por_opcion}; "
                           f"declarado {v.get('diferencia_conteos', {})}")
        if v.get("diferencia_grupos", {}) != por_grupo:
            errores.append(f"{d}: los votos difieren del resumen por grupo en {por_grupo}; "
                           f"declarado {v.get('diferencia_grupos', {})}")
        if (por_opcion or por_grupo) and not inconsistente:
            errores.append(f"{d}: los votos no cuadran y no dice por qué en inconsistencias")
        for x in v["votes"]:
            if x["option"] not in OPCIONES:
                errores.append(f"{d}: opción {x['option']!r}")
            if x["voter_id"] not in personas:
                errores.append(f"{d}: votante {x['voter_id']} no existe")
            m = mandatos.get(x["mandato_id"])
            if not m:
                errores.append(f"{d}: mandato {x['mandato_id']} no existe")
            else:
                if m["person_id"] != x["voter_id"]:
                    errores.append(f"{d}: el mandato {m['id']} no es de {x['voter_id']}")
                if m["legislative_period_id"] != v["legislative_period_id"]:
                    errores.append(f"{d}: el mandato {m['id']} es de otra legislatura")
                if v["organization_id"] != "comision-permanente" and m["organization_id"] != v["organization_id"]:
                    errores.append(f"{d}: el mandato {m['id']} es de otra cámara")
            if x.get("group_id") and x["group_id"] not in orgs:
                errores.append(f"{d}: grupo {x['group_id']} no existe")
        repetidos = [k for k, n in Counter(x["voter_id"] for x in v["votes"]).items() if n > 1]
        if repetidos:
            errores.append(f"{d}: votan dos veces {repetidos}")

    for e in expedientes.values():
        d = f"expediente {e['id']}"
        for vid in e.get("votaciones", []):
            if vid not in votaciones:
                errores.append(f"{d}: votación {vid} no existe")
        for x in e.get("votaciones_economicas", []):
            if not x.get("asunto") or x.get("camara") not in ("diputados", "senado", "permanente", None):
                errores.append(f"{d}: votación económica mal formada {x}")
        fuentes(e, d)

    for carpeta in ("iniciativas", "proposiciones", "dictamenes-negativos"):
        for a in datos.todos(raiz, carpeta):
            d = f"{carpeta} {a['id']}"
            if a.get("expediente_id") and a["expediente_id"] not in expedientes:
                errores.append(f"{d}: expediente {a['expediente_id']} no existe")
            for p in a["presentadores"]:
                if "mandato_id" in p:
                    m = mandatos.get(p["mandato_id"])
                    if not m:
                        errores.append(f"{d}: mandato {p['mandato_id']} no existe")
                    elif m["person_id"] != p.get("person_id"):
                        errores.append(f"{d}: el mandato {m['id']} no es de {p.get('person_id')}")
                if p.get("organization_id") and p["organization_id"] not in orgs:
                    errores.append(f"{d}: organización {p['organization_id']} no existe")
            fuentes(a, d)

    ligados = Counter()
    for dec in datos.todos(raiz, "decretos"):
        if "id" not in dec:
            continue
        for ex in dec.get("expedientes", []):
            ligados[ex["id"]] += 1
        d = f"decreto {dec['id']}"
        for ex in dec.get("expedientes", []):
            if ex["id"] not in expedientes:
                errores.append(f"{d}: expediente {ex['id']} no existe")
            if "criterio" not in ex:
                errores.append(f"{d}: enlace a {ex['id']} sin criterio")
            evidencia = ex.get("evidencia") or []
            if "resolucion" in ex and not (evidencia and all(c.get("fuente") in ("dof", "expediente")
                                                             and c.get("texto") for c in evidencia)):
                errores.append(f"{d}: enlace a {ex['id']} resuelto por agente sin evidencia citada")
        for c in dec.get("candidatos_expediente", []):
            if c["id"] not in expedientes:
                errores.append(f"{d}: candidato {c['id']} no existe")
        for clave in dec.get("legislaturas_estatales", {}).get("aprobaron", []):
            if f"congreso-{clave}" not in orgs:
                errores.append(f"{d}: congreso-{clave} no existe")
        fuentes(dec, d)
    for eid, n in ligados.items():
        if n > 1:
            errores.append(f"expediente {eid}: ligado a {n} decretos")
    return errores
