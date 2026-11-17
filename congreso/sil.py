"""Parsers del Sistema de Información Legislativa (sil.gobernacion.gob.mx).

Cada función recibe el HTML ya decodificado de una página y devuelve datos
planos, sin interpretar: los nombres, partidos y fechas tal como los publica
el SIL (las fechas en ISO). Las URL de cada página están en `url_*`.
"""
from __future__ import annotations

import re
from urllib.parse import urlencode

from .tablas import Celda, filas
from .texto import fecha_iso

BASE = "http://sil.gobernacion.gob.mx"
CAMARAS = {"diputados": 1, "senado": 2}

_REFERENCIA = re.compile(r"Referencia=(\d+)")
_ASUNTO = re.compile(r"AbrirAsunto\(\"(\d+)\"\)")
_TRAMITE = re.compile(r"ClaveTramite=(\d+)")
_CONTEOS = re.compile(r"A Favor:\s*(\d+)\s*En contra:\s*(\d+)\s*Abstenci(?:ón|ones|on):?\s*(\d+)", re.I)


# ---------------------------------------------------------------- URL

def url_padron(legislatura: int, camara: str) -> str:
    q = dict(SID="", Nombre="", APaterno="", AMaterno="", Estudios="", Experiencia="",
             Prin_El="", Circuns="", Entidad="", Distrito="", Legislatura=legislatura,
             Camara=CAMARAS[camara], Partido="", Estatus="", Orden=11)
    return f"{BASE}/Busquedas/Legislador/ProcesoBusquedaLegislador.php?{urlencode(q)}"


def url_perfil(referencia: str) -> str:
    return f"{BASE}/Librerias/pp_PerfilLegislador.php?SID=&Referencia={referencia}"


def url_seguimiento(seguimiento: str, asunto: str) -> str:
    return f"{BASE}/Librerias/pp_ReporteSeguimiento.php?SID=&Seguimiento={seguimiento}&Asunto={asunto}"


def url_historial(seguimiento: str, asunto: str) -> str:
    return f"{BASE}/Librerias/pp_HProcesoLegislativo.php?SID=&Asunto={asunto}&Seguimiento={seguimiento}"


def url_tramites(asunto: str) -> str:
    return f"{BASE}/Librerias/pp_TramitesAnteriores.php?Asunto={asunto}"


def url_detalle_votacion(asunto: str) -> str:
    return f"{BASE}/ActividadLegislativa/Votacion/DetalleVotacion.php?SID=&ClaveAsunto={asunto}"


def url_votos(asunto: str, tramite: str) -> str:
    return (f"{BASE}/ActividadLegislativa/Votacion/LegisladoresVotacionAsunto.php"
            f"?SID=&ClaveAsunto={asunto}&ClaveTramite={tramite}")


def decodificar(contenido: bytes) -> str:
    # El SIL declara ISO-8859-1 pero sirve cp1252 (comillas tipográficas, guiones).
    return contenido.decode("cp1252", errors="replace")


# ---------------------------------------------------------------- padrón

def _referencia(celdas: list[Celda]) -> str | None:
    for c in celdas:
        for e in c.enlaces:
            m = _REFERENCIA.search(e)
            if m:
                return m[1]
    return None


def padron(documento: str) -> list[dict]:
    """Filas del buscador de legisladores: una por mandato (propietario o suplente).

    Columnas: nº, foto, nombre (nombre<br>paterno<br>materno), cargo, partido,
    principio de elección, entidad, toma de protesta, calidad y la otra mitad
    de la fórmula (el suplente de un propietario, o al revés).
    """
    salida = []
    for fila in filas(documento):
        if len(fila) < 10 or "tddatosazulrep" not in fila[0].clases:
            continue
        ref = _referencia(fila)
        if not ref:
            continue
        partes = fila[2].lineas()
        salida.append({
            "referencia": ref,
            "nombre": " ".join(partes),
            "nombre_partes": partes,
            "cargo": fila[3].plano,
            "partido": fila[4].plano,
            "principio": fila[5].plano,
            "entidad": fila[6].plano or None,
            "protesta": fecha_iso(fila[7].plano),
            "calidad": fila[8].plano,
            "formula": fila[9].plano or None,
        })
    return salida


# ---------------------------------------------------------------- perfil

def _tabla_tras(fs: list[list[Celda]], encabezado: str) -> list[list[str]]:
    """Filas de datos de la tabla cuyo encabezado empieza con `encabezado`."""
    datos, dentro, ancho = [], False, 0
    for fila in fs:
        if fila and fila[0].encabezado:
            dentro = fila[0].plano.startswith(encabezado)
            ancho = len(fila)
            continue
        if dentro:
            if len(fila) != ancho:
                dentro = False
                continue
            datos.append([c.plano for c in fila])
    return datos


def perfil(documento: str) -> dict:
    fs = filas(documento, con_comentarios=True)
    campos: dict[str, Celda] = {}
    for fila in fs:
        if len(fila) == 2 and fila[0].plano.endswith(":"):
            campos.setdefault(fila[0].plano.rstrip(":").strip(), fila[1])
    region = campos.get("Región de elección")
    distrito = circunscripcion = None
    if region:
        m = re.search(r"Distrito:\s*(\d+)\s*(?:\(([^)]*)\))?", region.plano)
        if m:
            distrito = {"numero": int(m[1]), "cabecera": (m[2] or "").strip() or None}
        m = re.search(r"Circunscripci[oó]n:\s*(\d+)", region.plano)
        if m:
            circunscripcion = int(m[1])
    suplente = campos.get("Suplente")
    periodo = campos.get("Periodo de la legislatura")
    m = re.search(r"Del (\S+) al (\S+)", periodo.plano) if periodo else None

    def valor(k):
        c = campos.get(k)
        return c.plano if c and c.plano else None

    if not valor("Partido") and not valor("Principio de elección"):
        raise ValueError("perfil sin datos: la página no es un perfil de legislador")
    return {
        "estatus": valor("Estatus"),
        "partido": valor("Partido"),
        "entidad": valor("Entidad"),
        "principio": valor("Principio de elección"),
        "distrito": distrito,
        "circunscripcion": circunscripcion,
        "protesta": fecha_iso(valor("Toma de protesta") or ""),
        "periodo": [fecha_iso(m[1]), fecha_iso(m[2])] if m else None,
        "suplente": {"nombre": suplente.plano, "referencia": _referencia([suplente])} if suplente and suplente.plano else None,
        "comisiones": [
            {"comision": f[0], "puesto": f[1], "inicio": fecha_iso(f[2]), "fin": fecha_iso(f[3]), "estatus": f[4]}
            for f in _tabla_tras(fs, "Comisi")
        ],
        "licencias": [
            {"tipo": f[0], "inicio": fecha_iso(f[1]), "fin": fecha_iso(f[2]), "estatus": f[3], "en_funciones": f[4]}
            for f in _tabla_tras(fs, "Tipo")
        ],
    }


# ---------------------------------------------------------------- expediente

def seguimiento(documento: str) -> dict:
    """Reporte de seguimiento de un asunto: campos, presentador y cronología."""
    campos, cronologia, presentador_refs = {}, [], []
    for fila in filas(documento):
        textos = [c.plano for c in fila]
        if len(fila) == 2 and textos[0]:
            campos.setdefault(textos[0], textos[1])
            if textos[0] == "Presentador":
                presentador_refs = [e for e in fila[1].enlaces if "Presentador=" in e or "Referencia=" in e]
        elif len(fila) == 3 and textos[0].isdigit():
            cronologia.append({"estatus": textos[1], "fecha": fecha_iso(textos[2])})
    tipo = next((k for k in campos if k not in _CAMPOS_FIJOS), None)
    return {
        "camara_origen": campos.get("Cámara Origen"),
        "camara_revisora": campos.get("Cámara Revisora"),
        "fecha_presentacion": fecha_iso(campos.get("Fecha de Presentación", "")),
        "legislatura": campos.get("Legislatura"),
        "tipo": tipo,
        "denominacion": campos.get(tipo) if tipo else None,
        "presentador": campos.get("Presentador"),
        "presentador_enlaces": presentador_refs,
        "aspectos_relevantes": campos.get("Aspectos Relevantes"),
        "ultimo_estatus": campos.get("Último Estatus"),
        "cronologia": cronologia,
    }


_CAMPOS_FIJOS = {"Cámara Origen", "Cámara Revisora", "Fecha de Presentación", "Legislatura", "Año",
                 "Periodo de sesiones", "Presentador", "Aspectos Relevantes", "Último Trámite",
                 "Último Estatus", "Turno", "Fecha de Turno", "Tema", "Subclasificación",
                 "Clasificación", "Presentada por", ""}


def historial(documento: str) -> list[dict]:
    """Los asuntos de un expediente (iniciativas, dictámenes, minuta, declaratorias)."""
    asuntos = []
    for fila in filas(documento):
        if len(fila) != 6 or not fila[0].plano.isdigit():
            continue
        clave = next((m[1] for c in fila for e in c.enlaces for m in [_ASUNTO.search(e)] if m), None)
        pdf = next((e for e in fila[5].enlaces + fila[3].enlaces if e.lower().endswith(".pdf")), None)
        asuntos.append({
            "clave": clave,
            "fecha": fecha_iso(fila[1].plano),
            "tipo": fila[2].plano,
            "denominacion": fila[3].plano,
            "estatus": fila[4].plano,
            "pdf": BASE + pdf if pdf and pdf.startswith("/") else pdf,
        })
    return asuntos


def tramites(documento: str) -> list[dict]:
    """Trámites de un asunto en el pleno: mociones, reservas y votaciones.

    Una votación nominal lleva sus conteos; una económica, solo su resultado.
    """
    from .tablas import texto
    cuerpo = texto(documento)
    partes = re.split(r"Trámite:\s*", cuerpo)[1:]
    salida = []
    for p in partes:
        p = p.strip()
        tipo, _, resto = p.partition("\n") if "\n" in p else (p, "", "")
        for t in ("Votación nominal", "Votación económica", "Instrucciones de la Mesa Directiva",
                  "Reserva de artículos", "Turno"):
            if p.startswith(t):
                tipo, resto = t, p[len(t):].strip()
                break
        resto = re.split(r"\n?Cerrar\s+Imprimir", resto)[0].strip()
        resto = " ".join(resto.split())
        item = {"tipo": tipo, "texto": resto}
        m = _CONTEOS.search(resto)
        if m:
            item["conteos"] = {"yes": int(m[1]), "no": int(m[2]), "abstain": int(m[3])}
        salida.append(item)
    return salida


# ---------------------------------------------------------------- votaciones

def detalle_votacion(documento: str) -> dict:
    """Resumen de la votación nominal publicada de un asunto, por grupo."""
    fs = filas(documento)
    denominacion, general, grupos, tramite = None, None, [], None
    for i, fila in enumerate(fs):
        t = [c.plano for c in fila]
        for c in fila:
            for e in c.enlaces:
                m = _TRAMITE.search(e)
                if m:
                    tramite = tramite or m[1]
        if t == ["Denominación"] and i + 1 < len(fs):
            denominacion = fs[i + 1][0].plano
        if len(t) == 4 and all(x.isdigit() for x in t):
            general = {"yes": int(t[0]), "no": int(t[1]), "abstain": int(t[2]), "total": int(t[3])}
        if len(t) == 6 and all(x.isdigit() for x in t[1:]) and t[0]:
            grupos.append({"grupo": t[0], "yes": int(t[1]), "no": int(t[2]), "abstain": int(t[3]),
                           "absent": int(t[4]), "total": int(t[5])})
    return {"denominacion": denominacion, "general": general, "grupos": grupos, "tramite": tramite}


_OPCIONES = ("yes", "no", "abstain", "absent")
_COLUMNAS = ["A favor", "En contra", "Abstención", "Ausente"]
_NOMBRE_VOTO = re.compile(r"^(Dip|Sen)\.\s*(.*?)\s*\(([^()]*)\)\s*$")
_PREFIJO = {"Dip": "diputados", "Sen": "senado"}


def votos(documento: str) -> list[dict]:
    """Voto de cada legislador: nombre, cámara y partido tal como los publica el SIL."""
    fs = filas(documento)
    encabezado = [[c.plano for c in f] for f in fs if [c.plano for c in f][:2] == _COLUMNAS[:2]]
    if not encabezado or encabezado[0][:4] != _COLUMNAS:
        raise ValueError(f"columnas de voto inesperadas: {encabezado[:1]}")
    salida = []
    for fila in fs:
        if len(fila) < 6 or "beige" not in fila[0].clases or not fila[0].plano.isdigit():
            continue
        marcas = [c.plano.upper() == "X" for c in fila[2:6]]
        if sum(marcas) != 1:
            raise ValueError(f"fila de voto sin una sola marca: {[c.plano for c in fila]}")
        crudo = fila[1].plano
        m = _NOMBRE_VOTO.match(crudo)
        if not m:
            raise ValueError(f"nombre de votante no reconocido: {crudo!r}")
        salida.append({"numero": int(fila[0].plano), "camara": _PREFIJO[m[1]], "nombre": m[2],
                       "partido": m[3], "fuente_nombre": crudo, "opcion": _OPCIONES[marcas.index(True)]})
    return salida


# ---------------------------------------------------------------- buscador de votaciones

URL_BUSQUEDA_VOTACIONES = f"{BASE}/Busquedas/Votacion/ProcesoBusquedaAvanzada.php?SID="
TIPO_DICTAMEN_A_DISCUSION = "23"


def formulario_votaciones(legislatura: int, desde: str = "", hasta: str = "") -> dict:
    """Campos del buscador de votaciones: todos los dictámenes votados de la legislatura.

    `desde`/`hasta` en dd/mm/aaaa (fecha de presentación del dictamen); vacío
    trae la legislatura completa en una sola página.
    """
    return {
        "LEGISLATURA": str(legislatura), "TASUNTO_AR[]": [TIPO_DICTAMEN_A_DISCUSION],
        "OPCION_TEXTO": "2", "VALOR_TEXTO": "", "PRESENTADOR": "null", "RESULTADO": "9",
        "RESULTADOVOTACION": "T", "CAMARA_PRESENTADOR[]": ["1", "2", "5"],
        "FECHA_INIC": desde, "FECHA_FIN": hasta, "PAGINAS": "999",
    }


_SEGUIMIENTO = re.compile(r"Seguimiento=(\d+)")
_CLAVE = re.compile(r"Clave(?:Asunto)?=(\d+)")
_DOF = re.compile(r"Publicado en DOF el (\d{2})-([A-Z]{3})-(\d{4})")
_MESES = {m: i for i, m in enumerate(
    ["ENE", "FEB", "MAR", "ABR", "MAY", "JUN", "JUL", "AGO", "SEP", "OCT", "NOV", "DIC"], 1)}


def fecha_estatus_dof(estatus: str) -> str | None:
    """'Publicado en DOF el 13-NOV-2026' → '2026-11-13'."""
    m = _DOF.search(estatus)
    return f"{m[3]}-{_MESES[m[2]]:02d}-{m[1]}" if m and m[2] in _MESES else None


def resultados_votacion(documento: str) -> list[dict]:
    """Filas del buscador de votaciones: un dictamen votado por fila."""
    salida = []
    for fila in filas(documento):
        if len(fila) != 12 or not fila[0].plano.isdigit():
            continue
        enlaces = [e for c in fila for e in c.enlaces]
        clave = next((m[1] for e in fila[2].enlaces + fila[9].enlaces for m in [_CLAVE.search(e)] if m), None)
        seg = next((m[1] for e in enlaces for m in [_SEGUIMIENTO.search(e)] if m), None)
        conteo = re.search(r"A favor:\s*(\d+)\s*En contra:\s*(\d+)\s*Abstenci[oó]n:\s*(\d+)", fila[9].plano)
        salida.append({
            "clave": clave,
            "seguimiento": seg,
            "tipo": fila[1].plano,
            "denominacion": fila[2].plano,
            "clasificacion": fila[3].plano,
            "camara": fila[4].plano or None,
            "fecha": fecha_iso(fila[5].plano),
            "presentador": fila[6].plano,
            "conteos": {"yes": int(conteo[1]), "no": int(conteo[2]), "abstain": int(conteo[3])} if conteo else None,
            "estatus": fila[10].plano,
            "publicado_dof": fecha_estatus_dof(fila[10].plano),
        })
    return salida


# ---------------------------------------------------------------- asuntos

URL_BUSQUEDA_ASUNTOS = f"{BASE}/Busquedas/Avanzada/ProcesoBusquedaAvanzada.php?SID="
# Tipos de asunto del buscador avanzado (`TASUNTO_AR[]`).
TIPO_INICIATIVA = "11"
TIPO_PROPOSICION = "19"
TIPO_DICTAMEN_NEGATIVO = "74639"
# El buscador da a lo más esto por página.
MAX_FILAS = 999

_CLAVE_ASUNTO = re.compile(r"[?&]Clave=(\d+)")
_SEG_ASUNTO = re.compile(r"Seguimiento=(\d+)&Asunto=(\d+)")
_ENCONTRADOS = re.compile(r"encontrados:\s*(\d+)", re.I)
_FECHA_ESTATUS = re.compile(r"\bel (\d{2})-([A-Z]{3})-(\d{4})\s*$")
_COMISION = re.compile(r"^\d+\.-\s*(.+?)\s+-\s*(.+?)\s*\.-\s*(.+)$")
_NUMERAL = re.compile(r"^\d+\.-\s*")
# Etiquetas de grupo parlamentario que el SIL pone como presentador.
_GRUPOS = {"Morena", "PAN", "PRI", "PVEM", "PT", "MC", "PRD", "PES", "Ind.", "Sin Partido"}


def formulario_asuntos(legislatura: int, tipo: str, desde: str, hasta: str) -> dict:
    """Campos del buscador avanzado: los asuntos de un tipo presentados entre
    `desde` y `hasta` (dd/mm/aaaa), en una sola página."""
    return {
        "LEGISLATURA": str(legislatura), "TASUNTO_AR[]": [tipo], "OPCION_TEXTO": "2", "VALOR_TEXTO": "",
        "PRESENTADOR": "null", "RESULTADO": "9", "CAMARA_PRESENTADOR[]": ["1", "2", "5"],
        "FECHA_INIC": desde, "FECHA_FIN": hasta, "PAGINAS": str(MAX_FILAS),
    }


def _presentadores(celda: Celda) -> list[dict]:
    """'Dip. A Dip. B' con un enlace de perfil por legislador, o un texto sin
    enlace (un grupo parlamentario, el Ejecutivo, un congreso local)."""
    refs = [m[1] for e in celda.enlaces if "pp_PerfilLegislador" in e for m in [_REFERENCIA.search(e)] if m]
    comisiones = [m[1] for e in celda.enlaces if "pp_ComposicionComisiones" in e for m in [_REFERENCIA.search(e)] if m]
    if comisiones and not refs:
        # Un dictamen lo presentan comisiones: "Senado: Estudios Legislativos, Segunda Senado: Seguridad Pública".
        nombres = [n.strip() for n in re.split(r"(?=\b(?:Senado|Diputados|Comisión Permanente):)", celda.plano)
                   if n.strip()]
        if len(nombres) == len(comisiones):
            return [{"nombre": n, "comision": r} for n, r in zip(nombres, comisiones)]
        return [{"nombre": celda.plano, "comisiones": comisiones}]
    partes = [n.strip() for n in re.split(r"(?=\b(?:Dip|Sen)\.\s)", celda.plano) if n.strip()]
    salida = []
    # Antes de los legisladores pueden venir grupos parlamentarios: "PAN Morena Dip. …".
    if partes and not re.match(r"(?:Dip|Sen)\.\s", partes[0]):
        previo = partes.pop(0)
        etiquetas = previo.split()
        salida += [{"nombre": e} for e in etiquetas] if all(e in _GRUPOS for e in etiquetas) else [{"nombre": previo}]
    if refs and len(refs) == len(partes):
        return salida + [{"nombre": n, "referencia": r} for n, r in zip(partes, refs)]
    if refs or partes:
        # Sin correspondencia uno a uno: se conserva el texto y las referencias, sin emparejar.
        return salida + [{"nombre": " ".join(partes), "referencias": refs}]
    return salida


def _comisiones(celda: Celda) -> list[dict]:
    refs = [m[1] for e in celda.enlaces for m in [_REFERENCIA.search(e)] if m]
    lineas = [l for l in celda.lineas() if _NUMERAL.match(l)]
    salida = []
    for i, l in enumerate(lineas):
        m = _COMISION.match(l)
        c = {"texto": l}
        if m:
            c.update(camara=m[1], comision=m[2], turno=m[3])
        if len(refs) == len(lineas):
            c["referencia"] = refs[i]
        salida.append(c)
    return salida


def estatus_asunto(texto: str) -> dict:
    """'Pendiente en comisión(es) de origen el 07-OCT-2025' → texto, estado y fecha."""
    m = _FECHA_ESTATUS.search(texto)
    fecha = f"{m[3]}-{_MESES[m[2]]:02d}-{m[1]}" if m and m[2] in _MESES else None
    return {"texto": texto, "estado": texto[:m.start()].strip() if m else texto, "fecha": fecha}


def encontrados(documento: str) -> int | None:
    """Cuántos resultados dice tener una página de búsqueda del SIL."""
    m = _ENCONTRADOS.search(re.sub(r"<[^>]+>", " ", documento))
    return int(m[1]) if m else None


def asuntos(documento: str) -> tuple[int | None, list[dict]]:
    """Resultados del buscador avanzado: cuántos dice haber y una fila por asunto."""
    plano = re.sub(r"<[^>]+>", " ", documento)
    if "No hay resultados con los criterios seleccionados" in plano:
        return 0, []
    m = _ENCONTRADOS.search(plano)
    salida = []
    for fila in filas(documento):
        if len(fila) != 12 or not fila[0].plano.isdigit():
            continue
        clave = next((m[1] for e in fila[2].enlaces for m in [_CLAVE_ASUNTO.search(e)] if m), None)
        seg = next((m for e in fila[10].enlaces for m in [_SEG_ASUNTO.search(e)] if m), None)
        salida.append({
            "clave": clave or (seg[2] if seg else None),
            "seguimiento": seg[1] if seg else None,
            "tipo": fila[1].plano,
            "denominacion": fila[2].plano,
            "subclasificacion": fila[3].plano or None,
            "camara": fila[4].plano or None,
            "fecha": fecha_iso(fila[5].plano),
            "presentadores": _presentadores(fila[6]),
            "partido": fila[7].plano,
            "legislatura": fila[8].plano,
            "comisiones": _comisiones(fila[9]),
            "estatus": estatus_asunto(fila[10].plano),
            "temas": [_NUMERAL.sub("", l) for l in fila[11].lineas() if _NUMERAL.match(l)],
        })
    return (int(m[1]) if m else None), salida
