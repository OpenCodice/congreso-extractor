"""Personas y mandatos de una legislatura (Popolo: Person y Membership).

El SIL identifica mandatos, no personas: la misma persona tiene una
`Referencia` distinta en cada legislatura. La persona se identifica por su
nombre completo normalizado; si dos mandatos de la misma cámara y legislatura
comparten nombre, se detiene, porque ahí el nombre no basta.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from . import catalogos, datos, red, sil
from .texto import clave_nombre, romano, slug


def id_persona(nombre: str) -> str:
    return slug(nombre)


def id_mandato(referencia: str) -> str:
    return f"sil-{referencia}"


def _principio(texto: str) -> str:
    return slug(texto)  # mayoria-relativa, representacion-proporcional, primera-minoria


def es_foto(fuente: dict) -> bool:
    return "/Archivos/Fotos/" in fuente["url"]


# El SIL sirve algunas fotos en PNG aunque la URL diga `.jpg`: la copia lleva
# la extensión de su formato real.
FORMATOS_FOTO = {b"\xff\xd8": "jpg", b"\x89PNG": "png"}


def _foto(raiz: Path, url: str) -> dict | None:
    """La foto oficial como una fuente más del mandato: copia en `fuentes/`
    con su huella. None si lo que llegó no es una imagen."""
    r = red.obtener(url, vigencia_horas=24 * 30, bloqueos=(90,))
    ext = next((e for magia, e in FORMATOS_FOTO.items() if r.contenido.startswith(magia)), None)
    if ext is None:
        return None
    return dict(r.procedencia(), archivo=datos.guardar_fuente(raiz, r.sha256, r.contenido, ext))


def imagenes(raiz: Path, personas: set[str]) -> int:
    """`image` (Popolo) de cada persona: la foto de su mandato más reciente que
    tenga una. Se elige sobre todos sus mandatos, de cualquier cámara, para que
    el padrón de una cámara no cambie la que puso el de la otra."""
    por_persona: dict[str, list[dict]] = {}
    for m in datos.todos(raiz, "mandatos"):
        if m["person_id"] in personas:
            por_persona.setdefault(m["person_id"], []).append(m)
    escritos = 0
    for pid in sorted(personas):
        con_foto = [(m.get("start_date") or "", int(m["identifiers"][0]["identifier"]), f["url"])
                    for m in por_persona.get(pid, []) for f in m["sources"] if es_foto(f)]
        persona = datos.leer(raiz, f"personas/{pid}.json")
        if con_foto:
            persona["image"] = max(con_foto)[2]
        else:
            persona.pop("image", None)
        escritos += datos.escribir(raiz, f"personas/{pid}.json", persona)
    return escritos


def organizaciones_base(raiz: Path) -> None:
    for camara, (oid, nombre, _) in catalogos.CAMARAS.items():
        datos.escribir(raiz, f"organizaciones/{oid}.json", {
            "id": oid, "name": nombre, "classification": "chamber",
            "parent_id": "congreso-de-la-union",
        })
    datos.escribir(raiz, "organizaciones/congreso-de-la-union.json", {
        "id": "congreso-de-la-union", "name": "Congreso de la Unión", "classification": "legislature",
    })
    for clave, nombre in {v[0]: v[1] for v in catalogos.PARTIDOS.values()}.items():
        datos.escribir(raiz, f"organizaciones/partido-{clave}.json", {
            "id": f"partido-{clave}", "name": nombre, "classification": "party",
        })
    for clave, (corto, oficial) in catalogos.ENTIDADES.items():
        datos.escribir(raiz, f"organizaciones/congreso-{clave}.json", {
            "id": f"congreso-{clave}", "name": f"Congreso de {oficial}" if clave != "cdmx"
            else "Congreso de la Ciudad de México",
            "classification": "legislature", "area": {"entidad": clave},
        })


def construir(raiz: Path, legislatura: int, camara: str, perfiles: bool = True) -> dict:
    """Descarga el padrón (y los perfiles) y escribe personas y mandatos."""
    organizaciones_base(raiz)
    r = red.obtener(sil.url_padron(legislatura, camara), vigencia_horas=12)
    filas = sil.padron(sil.decodificar(r.contenido))
    if not filas:
        raise RuntimeError(f"padrón vacío: {r.url}")
    # El SIL deja en legislaturas pasadas renglones de un lugar sin persona
    # (nombre «- -»): no son un mandato de nadie.
    sin_nombre = [f for f in filas if not clave_nombre(f["nombre"])]
    filas = [f for f in filas if clave_nombre(f["nombre"])]

    repetidos = [n for n, c in Counter(clave_nombre(f["nombre"]) for f in filas).items() if c > 1]
    if repetidos:
        raise RuntimeError(f"nombres repetidos en {camara} {legislatura}: {repetidos}")

    leg = romano(legislatura).lower()
    oid = catalogos.CAMARAS[camara][0]
    referencias = {f["referencia"] for f in filas}
    bloqueado, pendientes = False, 0
    escritos = 0
    personas: set[str] = set()
    for f in filas:
        pid = id_persona(f["nombre"])
        personas.add(pid)
        persona = datos.leer(raiz, f"personas/{pid}.json") or {
            "id": pid, "name": f["nombre"], "identifiers": []}
        if len(f["nombre_partes"]) >= 2:
            persona["given_name"] = f["nombre_partes"][0]
            persona["family_name"] = " ".join(f["nombre_partes"][1:])
        ident = {"scheme": "sil-referencia", "identifier": f["referencia"]}
        if ident not in persona["identifiers"]:
            persona["identifiers"].append(ident)
            persona["identifiers"].sort(key=lambda i: (i["scheme"], i["identifier"]))
        genero = "female" if f["cargo"].split()[0] in ("Diputada", "Senadora") else (
            "male" if f["cargo"].split()[0] in ("Diputado", "Senador") else None)
        if genero and persona.get("gender") not in (None, genero):
            raise RuntimeError(f"{pid}: dos personas distintas con el mismo nombre ({f['referencia']})")
        if genero:
            persona["gender"] = genero
        escritos += datos.escribir(raiz, f"personas/{pid}.json", persona)

        mandato = {
            "id": id_mandato(f["referencia"]),
            "person_id": pid,
            "organization_id": oid,
            "legislative_period_id": leg,
            "role": catalogos.CAMARAS[camara][2].lower(),
            "on_behalf_of_id": catalogos.partido(f["partido"]),
            "partido_fuente": f["partido"],
            "calidad": "suplente" if f["calidad"].startswith("Suplente") else "propietario",
            "principio": _principio(f["principio"]),
            "area": {"entidad": catalogos.entidad(f["entidad"]) if f["entidad"] else None},
            "start_date": f["protesta"],
            "formula": f["formula"],
            "identifiers": [{"scheme": "sil-referencia", "identifier": f["referencia"]}],
            "sources": [r.procedencia()],
        }
        if f["entidad"] and mandato["area"]["entidad"] is None:
            raise KeyError(f"entidad desconocida: {f['entidad']!r}")
        ruta = f"mandatos/{leg}/{camara}/{f['referencia']}.json"
        previo = datos.leer(raiz, ruta) or {}
        foto_previa = next((x for x in previo.get("sources", []) if es_foto(x)), None)
        p, rp = None, None
        if perfiles and not bloqueado:
            try:
                rp = red.obtener(sil.url_perfil(f["referencia"]), vigencia_horas=24 * 6, bloqueos=(90,))
                p = sil.perfil(sil.decodificar(rp.contenido))
            except red.Pendiente:
                pass
            except red.Bloqueado:
                # El firewall del SIL corta tras muchas peticiones: el resto de los
                # perfiles se queda como estaba y se reintenta en la siguiente corrida.
                bloqueado = True
        if p:
            mandato["estatus"] = p["estatus"]
            if p["distrito"]:
                mandato["area"]["distrito"] = p["distrito"]["numero"]
                mandato["area"]["cabecera"] = p["distrito"]["cabecera"]
            if p["circunscripcion"]:
                mandato["area"]["circunscripcion"] = p["circunscripcion"]
            # El padrón solo lista a los suplentes que entraron en funciones; del
            # resto queda su referencia, sin enlace a un mandato que no existe.
            otra = p["suplente"]["referencia"] if p["suplente"] else None
            if otra and otra in referencias:
                mandato["formula_id"] = id_mandato(otra)
            elif otra:
                mandato["formula_referencia"] = otra
            mandato["licencias"] = p["licencias"]
            mandato["comisiones"] = p["comisiones"]
            mandato["sources"].append(rp.procedencia())
            foto = None
            if p["foto"] and not bloqueado:
                try:
                    foto = _foto(raiz, p["foto"])
                except red.Pendiente:
                    pass
                except red.Bloqueado:
                    bloqueado = True
            # Mientras no se descarga, sigue la copia anterior de la misma foto.
            if foto is None and p["foto"] and foto_previa and foto_previa["url"] == p["foto"]:
                foto = foto_previa
            if foto:
                mandato["sources"].append(foto)
        else:
            perfil_previo = next((x for x in previo.get("sources", []) if "PerfilLegislador" in x["url"]), None)
            if perfil_previo:
                for k in ("estatus", "formula_id", "formula_referencia", "licencias", "comisiones"):
                    if k in previo:
                        mandato[k] = previo[k]
                for k in ("distrito", "cabecera", "circunscripcion"):
                    if k in previo.get("area", {}):
                        mandato["area"][k] = previo["area"][k]
                mandato["sources"].append(perfil_previo)
                if foto_previa:
                    mandato["sources"].append(foto_previa)
            elif perfiles:
                pendientes += 1
        escritos += datos.escribir(raiz, ruta, mandato)
    escritos += imagenes(raiz, personas)
    return {"mandatos": len(filas), "sin_persona": len(sin_nombre), "archivos_cambiados": escritos,
            "perfiles_pendientes": pendientes,
            "errores": [f"{pendientes} perfiles sin descargar (firewall del SIL)"] if pendientes else []}
