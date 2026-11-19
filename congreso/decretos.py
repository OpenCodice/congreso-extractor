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

from . import catalogos, datos, dof, red, residuos, sil
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


_N = r"(?P<n>[a-z]+(?: y [a-z]+)?)"
_CONGRESOS = r"(?:los|las) (?:congresos|legislaturas)"
# Las formas en que el SIL dice cuántos congresos aprobaron y cuáles, dentro
# de una oración (sin acentos, en minúsculas).
_UNA_ORACION = [
    # «Se realiza declaratoria … con el escrutinio de veintidós votos
    # aprobatorios … remitidos por los congresos de …»
    rf"escrutinio de {_N} votos aprobatorios .*?remitid[oa]s por {_CONGRESOS} (?P<lista>.+)",
    # «Se comunica de la recepción de diecisiete votos aprobatorios …
    # remitidos por los congresos de …» / «… correspondientes a los congresos de …»
    rf"recepcion de {_N} votos aprobatorios .*?(?:remitid[oa]s por|correspondientes a) {_CONGRESOS} (?P<lista>.+)",
    # «… recepción de veintiséis oficios de los Congresos de los estados de …,
    # con los que remiten su voto aprobatorio …»
    rf"recepcion de {_N} oficios de {_CONGRESOS} (?P<lista>.+?) con los que remiten su voto aprobatorio",
    # «Se da cuenta que se recibió el voto aprobatorio de veintidós congresos …»
    rf"voto aprobatorio de {_N} congresos (?P<lista>.+)",
    # «Los veintisiete votos aprobatorios corresponden a los congresos de …»
    rf"^los {_N} votos aprobatorios corresponden a {_CONGRESOS} (?P<lista>.+)",
]
# «La Mesa Directiva comunica la recepción de veinte oficios de diversos
# congresos estatales con los que remiten su aprobación … Los [veinte] votos
# aprobatorios corresponden a los congresos de …»: el número en una oración y
# la lista en la siguiente.
_RECEPCION = rf"recepcion de {_N} oficios de diversos congresos estatales con los que remiten su aprobacion"
_CORRESPONDEN = rf"^(?:los (?:{_N} )?)?votos aprobatorios corresponden a {_CONGRESOS} (?P<lista>.+)"
# Lo que sigue a la lista y puede nombrar otra cosa.
_FIN_LISTA = re.compile(r" (?:al|a la|para la) (?:proyecto|decreto|minuta|declaratoria)\b.*$")


def _oraciones(texto: str) -> list[str]:
    return [clave_nombre(o) for o in re.split(r"\.\s+(?=[-–]?\s*[A-ZÁÉÍÓÚÑ])", texto)]


def votos_aprobatorios(texto: str | None) -> tuple[int, list[str]] | None:
    """(N, claves) de un texto del SIL que dice cuántos congresos locales
    aprobaron y cuáles, solo si las entidades que nombra son exactamente N.
    Un texto que no dice que los votos sean aprobatorios (las «resoluciones»
    que se remiten) no cuenta."""
    if not texto:
        return None
    os_ = _oraciones(texto)
    hallados = []
    for k, o in enumerate(os_):
        for patron in _UNA_ORACION:
            m = re.search(patron, o)
            if m:
                hallados.append((m["n"], m["lista"]))
        m = re.search(_RECEPCION, o)
        if m and k + 1 < len(os_):
            c = re.search(_CORRESPONDEN, os_[k + 1])
            if c and (c["n"] is None or c["n"] == m["n"]):
                hallados.append((m["n"], c["lista"]))
    for n, lista in hallados:
        if n not in _NUMEROS:
            continue
        claves = entidades_en(_FIN_LISTA.sub("", lista))
        if len(claves) == _NUMEROS[n]:
            return _NUMEROS[n], claves
    return None


# «Asimismo, se informa la recepción del oficio del Congreso de Jalisco que
# remite voto no aprobatorio al proyecto…»: el SIL a veces dice quién votó en
# contra. Solo eso se registra como en contra; el silencio no.
_NO_APROBATORIO = re.compile(r"\bvotos? no aprobatorios?\b")


def votos_no_aprobatorios(texto: str | None) -> list[str]:
    """Claves de los congresos que, según el texto, remitieron voto no aprobatorio."""
    claves = set()
    for o in _oraciones(texto or ""):
        if _NO_APROBATORIO.search(o):
            claves |= set(entidades_en(_FIN_LISTA.sub("", o)))
    return sorted(claves)


def legislaturas_aprobatorias(declaratorias: list[tuple[dict, str | None]]) -> tuple[dict | None, str | None]:
    """Congresos locales que aprobaron una reforma constitucional (art. 135),
    según el SIL, de los asuntos «Declaratoria de reforma constitucional» del
    expediente con el texto de sus aspectos relevantes.

    Cada cámara da cuenta de los votos que le llegaron, a veces en días
    distintos: se toma la lista más larga, solo si las demás están contenidas
    en ella; si dos listas se contradicen, ninguna. Los que alguna declaratoria
    dice que votaron en contra van en `no_aprobaron`, si no están también entre
    los que aprobaron. Devuelve también un aviso cuando ninguna cuadra o se
    contradicen."""
    leidas = []
    for asunto, texto in declaratorias:
        r = votos_aprobatorios(texto)
        if r:
            leidas.append((asunto, *r))
    if not leidas:
        return None, "ninguna declaratoria da una lista de congresos que cuadre con su número"
    # Con empate, la que nombra a los congresos en su denominación (la que se
    # tomaba antes) y, si no, la primera del expediente.
    asunto, n, claves = max(leidas, key=lambda x: (x[1], x[0].get("fecha") or "",
                                                   "congresos" in (x[0].get("denominacion") or "").lower()))
    if any(not set(c) <= set(claves) for _, _, c in leidas):
        return None, "las declaratorias dan listas de congresos que se contradicen"
    leg = {"aprobaron": claves, "votos_aprobatorios": n, "asunto": asunto["clave"],
           "fecha": asunto["fecha"],
           "fuente": "aspectos relevantes de la declaratoria en el SIL",
           "nota": "el SIL solo lista los congresos con voto aprobatorio; el resto no tiene registro"}
    contra = {}
    for a, texto in declaratorias:
        for clave in votos_no_aprobatorios(texto):
            contra.setdefault(clave, a["clave"])
    if set(contra) & set(claves):
        return leg, "una declaratoria da como no aprobatorio el voto de un congreso que otra cuenta como aprobatorio"
    if contra:
        leg["no_aprobaron"] = sorted(contra)
        leg["asuntos_no_aprobaron"] = sorted(set(contra.values()))
        leg["nota"] = ("el SIL lista los congresos con voto aprobatorio y, cuando lo dice, los que votaron en contra; "
                       "el resto no tiene registro")
    return leg, None


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
    for _, fecha in pares:
        red.anticipar(dof.url_sumario(fecha))
    pendientes = 0
    for doc, fecha in sorted(pares):
        try:
            r = red.obtener(dof.url_sumario(fecha), vigencia_horas=24 * 30)
        except red.Pendiente:
            pendientes += 1
            continue
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
    for fecha, lista in por_fecha.items():
        _emparejar(lista, [e for e in expedientes if e.get("publicado_dof") == fecha], nombres)
    # Lo que quedó sin ligar puede tener una resolución confirmada (ver `residuos`).
    errores = residuos.aplicar(list(decretos.values()), expedientes)
    for lista in por_fecha.values():
        for d in lista:
            if "cpeum" not in {x["documento"] for x in d["documentos"]} or not d["expedientes"]:
                continue
            e = next(x for x in expedientes if x["id"] == d["expedientes"][0]["id"])
            decs = [a for a in e["asuntos"] if a["tipo"] == "Declaratoria de reforma constitucional"]
            if not decs:
                continue
            leidas, fuentes = [], {}
            try:
                for dec in decs:
                    rs = red.obtener(sil.url_seguimiento(e["seguimiento"], dec["clave"]))
                    fuentes[dec["clave"]] = rs.procedencia()
                    leidas.append((dec, sil.seguimiento(sil.decodificar(rs.contenido))["aspectos_relevantes"]))
            except red.Pendiente:
                pendientes += 1
                continue
            except (RuntimeError, ValueError, KeyError) as ex:
                errores.append(f"{d['id']}: {ex}")
                continue
            leg, aviso = legislaturas_aprobatorias(leidas)
            if leg:
                leg["sources"] = [fuentes[c] for c in dict.fromkeys([leg["asunto"], *leg.get("asuntos_no_aprobaron", [])])]
                d["legislaturas_estatales"] = leg
            if aviso:
                errores.append(f"{d['id']}: {aviso}")

    # Con una página sin bajar, un decreto quedaría sin él o sin sus congresos:
    # no se escribe nada hasta que el archivo las tenga todas.
    if pendientes:
        raise red.Pendiente(f"{pendientes} páginas del DOF o el SIL pendientes de descarga")
    for d in decretos.values():
        d["documentos"].sort(key=lambda x: (x["documento"], x["publicacion"]))
        datos.escribir(raiz, f"decretos/{d['fecha'][:4]}/{d['id']}.json", d)
    datos.escribir(raiz, "decretos/sin-decreto.json", {"reformas": sin_decreto,
                   "nota": "reformas de los repos de leyes sin decreto identificable en el sumario del DOF de esa fecha"})
    return {"decretos": len(decretos), "con_expediente": sum(1 for d in decretos.values() if d["expedientes"]),
            "ambiguos": sum(1 for d in decretos.values() if d["candidatos_expediente"]),
            "sin_decreto": len(sin_decreto), "avisos": errores}
