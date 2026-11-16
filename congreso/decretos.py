"""Decretos del DOF: el puente entre los repos de leyes y el proceso legislativo.

Para cada reforma de un documento federal (`Documento` + `Publicacion` en los
trailers de los repos de leyes, o una fecha de su `reformas.json`):

1. busca en el sumario del DOF de ese día los decretos que nombran al
   documento (`dof.candidatos`);
2. liga cada decreto con el expediente del SIL cuyo estatus dice "Publicado en
   DOF" esa misma fecha y cuya denominación nombra al mismo documento;
3. anota los commits de los repos de leyes que trajeron esa reforma.

Cada enlace dice con qué criterio se hizo. Si hay más de un candidato y nada
los distingue, no se elige: quedan como candidatos.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from . import catalogos, datos, dof, red, sil
from .texto import clave_nombre

REPOS_DOF = ("constitucion-mexicana", "leyes-federales", "fiscal-mexicano")
DESDE = "2024-09-01"  # inicio de la LXVI Legislatura: lo que el SIL cubre por ahora


def nombres_documentos(repos: Path) -> dict[str, str]:
    nombres = {"cpeum": "Constitución Política de los Estados Unidos Mexicanos"}
    registro = repos / "leyes-federales" / "fuentes.json"
    for d in json.loads(registro.read_text(encoding="utf-8"))["documentos"]:
        nombres.setdefault(d["clave"], d["etiqueta"])
    return nombres


def _trailers(mensaje: str) -> dict[str, list[str]]:
    t: dict[str, list[str]] = {}
    for linea in mensaje.splitlines():
        m = re.match(r"^([A-Z][A-Za-z-]*): (.+)$", linea)
        if m:
            t.setdefault(m[1], []).append(m[2].strip())
    return t


def commits_por_reforma(repos: Path) -> dict[tuple[str, str], list[dict]]:
    """(documento, publicación) → commits de reforma, de los trailers de cada repo."""
    salida: dict[tuple[str, str], list[dict]] = {}
    for nombre in REPOS_DOF:
        repo = repos / nombre
        if not (repo / ".git").exists():
            continue
        log = subprocess.run(["git", "-C", str(repo), "log", "--format=%H%x00%B%x01"],
                             capture_output=True, text=True, check=True).stdout
        for bloque in log.split("\x01"):
            if "\x00" not in bloque:
                continue
            sha, mensaje = bloque.strip("\n").split("\x00", 1)
            t = _trailers(mensaje)
            if t.get("Tipo") != ["reforma"] or t.get("Medio") != ["DOF"]:
                continue
            for pub in t.get("Publicacion", []):
                salida.setdefault((t["Documento"][0], pub), []).append(
                    {"repo": f"OpenCodice/{nombre}", "sha": sha, "titulo": mensaje.splitlines()[0]})
    return salida


def reformas_en_metadata(repos: Path, documentos: set[str]) -> set[tuple[str, str]]:
    """(documento, fecha) de los `reformas.json` desde `DESDE`."""
    pares = set()
    rutas = [("cpeum", repos / "constitucion-mexicana" / "metadata" / "reformas.json")]
    for base in ("leyes-federales", "fiscal-mexicano"):
        for p in (repos / base / "metadata").glob("*/reformas.json"):
            rutas.append((p.parent.name, p))
    for doc, ruta in rutas:
        if doc not in documentos or not ruta.exists():
            continue
        for fecha in json.loads(ruta.read_text(encoding="utf-8")):
            if fecha >= DESDE:
                pares.add((doc, fecha))
    return pares


def _palabras(s: str) -> set[str]:
    return {w for w in clave_nombre(s).split() if len(w) > 3}


def _parecido(a: str, b: str) -> float:
    x, y = _palabras(a), _palabras(b)
    return len(x & y) / len(x | y) if x | y else 0.0


_NUMEROS = {
    "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8,
    "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15,
    "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20,
    "veintiuno": 21, "veintiun": 21, "veintidos": 22, "veintitres": 23, "veinticuatro": 24,
    "veinticinco": 25, "veintiseis": 26, "veintisiete": 27, "veintiocho": 28,
    "veintinueve": 29, "treinta": 30, "treinta y uno": 31, "treinta y dos": 32,
}


def entidades_en(texto: str) -> list[str]:
    """Claves de las entidades que nombra un texto, por su nombre más largo."""
    t = " " + clave_nombre(texto) + " "
    tramos = []
    for clave, nombres in catalogos.nombres_entidades().items():
        for n in nombres:
            k = " " + n + " "
            i = t.find(k)
            while i != -1:
                tramos.append((i, i + len(k), clave))
                i = t.find(k, i + 1)
    finales = [x for x in tramos if not any(a <= x[0] and x[1] <= b and (b - a) > (x[1] - x[0]) for a, b, _ in tramos)]
    return sorted({c for _, _, c in finales})


def legislaturas_aprobatorias(expediente: dict, aspectos: str | None) -> dict | None:
    """Congresos locales que aprobaron una reforma constitucional (art. 135), según el SIL.

    La declaratoria del Senado dice "escrutinio de N votos aprobatorios ...
    remitidos por los congresos de ...". Solo se afirma la lista si el número
    escrito coincide con las entidades nombradas.
    """
    declaratoria = next((a for a in expediente.get("asuntos", [])
                         if a["tipo"] == "Declaratoria de reforma constitucional"
                         and "congresos" in a["denominacion"].lower()), None)
    if not declaratoria or not aspectos:
        return None
    t = clave_nombre(aspectos)
    m = re.search(r"escrutinio de (.+?) votos aprobatorios", t)
    if not m or m[1] not in _NUMEROS:
        return None
    resto = t[m.end():]
    corte = re.search(r"remitid[oa]s por (?:los|las) (?:congresos|legislaturas)(.+)", resto)
    if not corte:
        return None
    claves = entidades_en(corte[1])
    if len(claves) != _NUMEROS[m[1]]:
        return None
    return {"aprobaron": claves, "votos_aprobatorios": _NUMEROS[m[1]], "asunto": declaratoria["clave"],
            "fecha": declaratoria["fecha"],
            "fuente": "aspectos relevantes de la declaratoria en el SIL",
            "nota": "el SIL solo lista los congresos con voto aprobatorio; el resto no tiene registro"}


def _emparejar(decretos_dia: list[dict], expedientes: list[dict], nombres: dict[str, str]) -> None:
    """Liga decretos y expedientes de una misma fecha, uno a uno, solo si no hay duda."""
    pares = {}
    for d in decretos_dia:
        docs = {x["documento"] for x in d["documentos"]}
        pares[d["id"]] = [e for e in expedientes if docs & dof.menciones(e["denominacion"] or "", nombres)]
    usados = {e["id"] for lista in pares.values() for e in lista}
    if len(decretos_dia) == 1 and len(usados) == 1:
        d = decretos_dia[0]
        d["expedientes"] = [{"id": next(iter(usados)),
                             "criterio": "único decreto y único expediente del SIL publicados en el DOF esa fecha que nombran al documento"}]
        return
    puntaje = {(d["id"], e["id"]): _parecido(d["titulo"], e["denominacion"] or "")
               for d in decretos_dia for e in pares[d["id"]]}
    for d in decretos_dia:
        opciones = sorted(((puntaje[(d["id"], e["id"])], e["id"]) for e in pares[d["id"]]), reverse=True)
        if not opciones:
            continue
        mejor, eid = opciones[0]
        rival_propio = any(p >= mejor - 0.15 for p, _ in opciones[1:])
        rival_ajeno = any(puntaje.get((o["id"], eid), -1) >= mejor - 0.15 for o in decretos_dia if o is not d)
        if mejor >= 0.3 and not rival_propio and not rival_ajeno:
            d["expedientes"] = [{"id": eid, "criterio":
                                 f"publicado en el DOF esa fecha, nombra al documento y su denominación es "
                                 f"claramente la más parecida al título ({mejor:.2f})"}]
        else:
            d["candidatos_expediente"] = [{"id": i, "parecido": round(p, 2)} for p, i in opciones]


def construir(raiz: Path, repos: Path) -> dict:
    nombres = nombres_documentos(repos)
    commits = commits_por_reforma(repos)
    pares = reformas_en_metadata(repos, set(nombres)) | {k for k in commits if k[1] >= DESDE}
    expedientes = datos.todos(raiz, "expedientes")

    decretos: dict[int, dict] = {}
    sin_decreto = []
    for doc, fecha in sorted(pares):
        r = red.obtener(dof.url_sumario(fecha), vigencia_horas=24 * 30)
        candidatos = dof.candidatos(dof.sumario(r.contenido, fecha), doc, nombres)
        if not candidatos:
            sin_decreto.append({"documento": doc, "publicacion": fecha})
            continue
        for n in candidatos:
            d = decretos.setdefault(n.codigo, {
                "id": f"dof-{n.codigo}", "codigo": n.codigo, "fecha": n.fecha, "edicion": n.edicion,
                "titulo": n.titulo, "dependencia": n.dependencia, "pagina": n.pagina,
                "url": dof.url_nota(n.codigo, n.fecha),
                "documentos": [], "expedientes": [], "candidatos_expediente": [],
                "sources": [r.procedencia()],
            })
            enlace = {"documento": doc, "publicacion": fecha}
            if len(candidatos) == 1:
                enlace["commits"] = commits.get((doc, fecha), [])
            else:
                # El commit trae todo lo publicado ese día: no se sabe cuál decreto es.
                enlace["commits_candidatos"] = commits.get((doc, fecha), [])
                enlace["decretos_mismo_dia"] = sorted(f"dof-{c.codigo}" for c in candidatos)
            d["documentos"].append(enlace)

    por_fecha: dict[str, list[dict]] = {}
    for d in decretos.values():
        por_fecha.setdefault(d["fecha"], []).append(d)
    errores = []
    for fecha, lista in por_fecha.items():
        _emparejar(lista, [e for e in expedientes if e.get("publicado_dof") == fecha], nombres)
        for d in lista:
            if "cpeum" not in {x["documento"] for x in d["documentos"]} or not d["expedientes"]:
                continue
            e = next(x for x in expedientes if x["id"] == d["expedientes"][0]["id"])
            dec = next((a for a in e["asuntos"] if a["tipo"] == "Declaratoria de reforma constitucional"
                        and "congresos" in a["denominacion"].lower()), None)
            if not dec:
                continue
            try:
                rs = red.obtener(sil.url_seguimiento(e["seguimiento"], dec["clave"]))
                leg = legislaturas_aprobatorias(e, sil.seguimiento(sil.decodificar(rs.contenido))["aspectos_relevantes"])
            except (RuntimeError, ValueError, KeyError) as ex:
                errores.append(f"{d['id']}: {ex}")
                continue
            if leg:
                leg["sources"] = [rs.procedencia()]
                d["legislaturas_estatales"] = leg
            else:
                errores.append(f"{d['id']}: la declaratoria {dec['clave']} no da una lista de congresos que cuadre")

    for d in decretos.values():
        d["documentos"].sort(key=lambda x: (x["documento"], x["publicacion"]))
        datos.escribir(raiz, f"decretos/{d['fecha'][:4]}/{d['id']}.json", d)
    datos.escribir(raiz, "decretos/sin-decreto.json", {"reformas": sin_decreto,
                   "nota": "reformas de los repos de leyes sin decreto identificable en el sumario del DOF de esa fecha"})
    return {"decretos": len(decretos), "con_expediente": sum(1 for d in decretos.values() if d["expedientes"]),
            "ambiguos": sum(1 for d in decretos.values() if d["candidatos_expediente"]),
            "sin_decreto": len(sin_decreto), "avisos": errores}
