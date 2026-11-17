"""Votaciones nominales de la Cámara de Diputados en la Gaceta Parlamentaria.

La Gaceta (gaceta.diputados.gob.mx) publica cada votación nominal de la
legislatura, incluidas las de lo particular, con el sentido del voto de cada
diputado. Solo responde desde México (ver `red.VIA_MX`).

- Índice: `/gp_votaciones.html`, una página por periodo de sesiones.
- Periodo: cada asunto con su fecha de sesión y un enlace por votación a
  `/Gaceta/Votaciones/66/tabla{...}.php3`.
- Tabla: conteos por grupo y sentido, y el formulario que pide las listas.
- Lista: un POST al formulario con `lola[{g}{s}]` devuelve, para el sentido
  `s`, los diputados de todos los grupos; con varias claves, varios sentidos.
"""
from __future__ import annotations

import html
import re

from .texto import sin_acentos

BASE = "https://gaceta.diputados.gob.mx"
URL_INDICE = f"{BASE}/gp_votaciones.html"

_MESES = {m: i for i, m in enumerate(
    ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
     "septiembre", "octubre", "noviembre", "diciembre"), 1)}
_FECHA = re.compile(r"(\d{1,2})\s+de\s+([a-z]+)\s+de\s+(\d{4})")

# Filas de la tabla, en el orden del dígito `s` de `lola[{g}{s}]`.
SENTIDOS = (("favor", "yes"), ("contra", "no"), ("abstencion", "abstain"), ("quorum", "not voting"),
            ("ausente", "absent"))
_FRASES = {"votaron a favor": "yes", "votaron en contra": "no", "se abstuvieron": "abstain", "votaron en abstencion": "abstain",
           "votaron por quorum": "not voting", "solo asistencia": "not voting", "estuvieron ausentes": "absent"}

# Encabezados de la tabla y nombres de los grupos en las listas → etiqueta del catálogo.
GRUPOS = {"mrn": "Morena", "morena": "Morena", "pan": "PAN", "partido accion nacional": "PAN",
          "pri": "PRI", "partido revolucionario institucional": "PRI",
          "pvem": "PVEM", "partido verde ecologista de mexico": "PVEM",
          "pt": "PT", "partido del trabajo": "PT", "mc": "MC", "movimiento ciudadano": "MC",
          "prd": "PRD", "partido de la revolucion democratica": "PRD",
          "ind": "Ind.", "independientes": "Ind.", "sin partido": "Ind."}


def decodificar(contenido: bytes) -> str:
    return contenido.decode("latin-1")


def _plano(fragmento: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragmento)).split())


def _clave(s: str) -> str:
    return " ".join(re.sub(r"[^a-z ]", " ", sin_acentos(s).lower()).split())


def fecha(texto: str) -> str | None:
    m = _FECHA.search(sin_acentos(texto).lower())
    if not m or m[2] not in _MESES:
        return None
    return f"{m[3]}-{_MESES[m[2]]:02d}-{int(m[1]):02d}"


def grupo(etiqueta: str) -> str:
    clave = _clave(etiqueta)
    if clave not in GRUPOS:
        raise KeyError(f"grupo desconocido en la Gaceta: {etiqueta!r}")
    return GRUPOS[clave]


def periodos(documento: str, legislatura: int = 66) -> list[str]:
    """URL de las páginas de periodo publicadas (las comentadas aún no existen)."""
    visible = re.sub(r"<!--.*?-->", "", documento, flags=re.S)
    rutas = re.findall(rf'href="(/Gaceta/Votaciones/{legislatura}/vot{legislatura}_[^"]+\.html)"', visible, re.I)
    return [BASE + r for r in dict.fromkeys(rutas)]


def periodo(documento: str) -> list[dict]:
    """Votaciones del periodo: tabla, fecha de sesión, asunto y descripción."""
    salida = []
    piezas = re.split(r'(<font color="#CC0000">[^<]*</font>)', documento, flags=re.I)
    sesion = None
    for pieza in piezas:
        if pieza.lower().startswith('<font color="#cc0000">'):
            sesion = fecha(_plano(pieza)) or sesion
            continue
        for li in re.findall(r"<li>(.*?)</li>", pieza, re.S | re.I):
            lineas = re.split(r"<br\s*/?>", li, flags=re.I)
            asunto = _plano(lineas[0])
            for linea in lineas[1:]:
                m = re.search(r'href="(/Gaceta/Votaciones/\d+/(tabla[^"]+)\.php3)"', linea, re.I)
                if m:
                    descripcion = _plano(linea[:m.start()].rsplit("<a", 1)[0])
                    salida.append({"tabla": m[2], "url": BASE + m[1], "fecha_sesion": sesion,
                                   "asunto": asunto, "descripcion": descripcion})
    return salida


def tabla(documento: str) -> dict:
    """Formulario, título, fecha y conteos {grupo: {opción: n}} (con 'Total')."""
    form = re.search(r'<form method="post" action="([^"]+)">', documento, re.I)
    evento = re.search(r'name="evento" value="([^"]+)"', documento, re.I)
    titulo = re.search(r'name="nomtit" value="([^"]*)"', documento, re.I)
    if not (form and evento and titulo):
        raise ValueError("tabla de la Gaceta sin formulario")
    nomtit = html.unescape(titulo[1])
    filas = re.findall(r"<tr[^>]*>(.*?)</tr>", re.sub(r"<!--.*?-->", "", documento, flags=re.S), re.S | re.I)
    encabezado = next((f for f in filas if "Votos" in _plano(f)), None)
    if encabezado is None:
        raise ValueError("tabla de la Gaceta sin encabezado")
    columnas = [_plano(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", encabezado, re.S | re.I)][1:]
    columnas = ["Total"] + [grupo(c) for c in columnas[1:]]
    conteos = {c: {} for c in columnas}
    for f in filas:
        celdas = re.findall(r"<td[^>]*>(.*?)</td>", f, re.S | re.I)
        if not celdas:
            continue
        etiqueta = _clave(_plano(celdas[0]))
        sentido = next((o for k, o in SENTIDOS if etiqueta.startswith(k)), None)
        if sentido is None or len(celdas) < 2:
            continue
        valores = [re.search(r'value="\s*(\d+)\s*"', c, re.I) for c in celdas[1:]]
        if len(valores) != len(columnas) or not all(valores):
            raise ValueError(f"fila {etiqueta!r} de la tabla no se leyó completa")
        for c, v in zip(columnas, valores):
            conteos[c][sentido] = int(v[1])
    for c in conteos.values():
        if set(c) != {o for _, o in SENTIDOS}:
            raise ValueError("a la tabla le falta un sentido")
    return {"accion": form[1], "evento": evento[1], "titulo": re.sub(r"\s*<p>.*", "", nomtit, flags=re.S).strip(),
            "fecha": fecha(nomtit.rsplit("<p>", 1)[-1]), "conteos": conteos}


def datos_lista(evento: str) -> dict:
    """Cuerpo del POST que pide las listas de todos los sentidos y grupos: el
    formulario responde con una sección por cada `lola[1{s}]` que recibe."""
    return {"evento": evento, **{f"lola[1{s}]": "1" for s in range(1, len(SENTIDOS) + 1)}}


def lista(documento: str) -> list[dict]:
    """Diputados de la lista: grupo, sentido y nombre ('Apellidos Nombres')."""
    salida = []
    secciones = re.split(r"<center>([^<]*?:\s*\d+)</center>", documento, flags=re.I)
    for titulo, cuerpo in zip(secciones[1::2], secciones[2::2]):
        m = re.match(r"\s*Diputad[oa]s?\s+(?:(?:del|de)\s+)?(.*?)\s+que\s+(.*?):\s*(\d+)\s*$",
                     html.unescape(titulo), re.I | re.S)
        if not m:
            raise ValueError(f"sección desconocida: {titulo!r}")
        frase = _clave(m[2])
        sentido = next((o for k, o in _FRASES.items() if frase.startswith(k)), None)
        if sentido is None:
            raise ValueError(f"sentido desconocido: {m[2]!r}")
        g = grupo(m[1])
        nombres = [" ".join(html.unescape(n).split()) for n in re.findall(r"\d+:([^<]+)<br>", cuerpo)]
        if len(nombres) != int(m[3]):
            raise ValueError(f"{titulo!r}: {len(nombres)} nombres")
        salida += [{"grupo": g, "opcion": sentido, "nombre": n} for n in nombres]
    if not secciones[1:]:
        raise ValueError("lista de la Gaceta vacía")
    return salida
