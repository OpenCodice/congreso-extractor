"""Invariantes del repo de datos. Lo corre `revisar-pr` antes de fusionar.

- Toda referencia apunta a un registro que existe.
- En una votación con votos publicados, los votos suman exactamente los conteos
  y nadie vota dos veces.
- Cada dato cita al menos una fuente, y las copias guardadas coinciden con su
  huella.
"""
from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path

from . import datos

OPCIONES = {"yes", "no", "abstain", "absent"}


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
                elif hashlib.sha256(ruta.read_bytes()).hexdigest() != s["sha256"]:
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
        if v["expediente_id"] not in expedientes:
            errores.append(f"{d}: expediente {v['expediente_id']} no existe")
        fuentes(v, d)
        if not v["votos_publicados"]:
            if v["votes"]:
                errores.append(f"{d}: tiene votos pero votos_publicados es false")
            continue
        if not v["votes"]:
            errores.append(f"{d}: votos_publicados sin votos")
        conteo = Counter(x["option"] for x in v["votes"])
        if dict(conteo) != {c["option"]: c["value"] for c in v["counts"] if c["value"] or c["option"] in conteo}:
            errores.append(f"{d}: los votos {dict(conteo)} no suman los conteos {v['counts']}")
        por_grupo = Counter(x["grupo_fuente"] for x in v["votes"])
        for g in v.get("group_results", []):
            if por_grupo[g["grupo"]] != g["total"]:
                errores.append(f"{d}: grupo {g['grupo']} con {por_grupo[g['grupo']]} votos, el resumen dice {g['total']}")
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
        fuentes(e, d)

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
