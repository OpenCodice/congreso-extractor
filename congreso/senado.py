"""Votaciones nominales del sitio del Senado (www.senado.gob.mx/66/votaciones).

El sitio publica el voto de cada senador en cada votación nominal, incluidas
las de lo particular que el SIL solo da como conteos. Solo responde desde
México: se descarga por egress-mx (ver `red.VIA_MX`).

- Listado de la legislatura: `/66/votaciones/por_legislatura/LXVI/`, un enlace
  `/66/votacion/{id}` por votación.
- Página de la votación: fecha, asunto, qué se vota y los conteos.
- Tabla de votos: `/66/app/votaciones/functions/viewTableVot.php`, que la
  página carga por AJAX; una fila por senador, con su clave del sitio.
"""
from __future__ import annotations

import html
import re

from .texto import sin_acentos

BASE = "https://www.senado.gob.mx"

_MESES = {m: i for i, m in enumerate(
    ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
     "septiembre", "octubre", "noviembre", "diciembre"), 1)}
_FECHA = re.compile(r"(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)\s+(\d{1,2})\s+de\s+"
                    r"([a-záéíóú]+)\s+de\s+(\d{4})", re.I)
OPCIONES = {"PRO": "yes", "CONTRA": "no", "ABSTENCION": "abstain", "ABSTENCIÓN": "abstain"}


def url_listado(legislatura: int = 66, romano: str = "LXVI") -> str:
    return f"{BASE}/{legislatura}/votaciones/por_legislatura/{romano}/"


def url_votacion(clave: str, legislatura: int = 66) -> str:
    return f"{BASE}/{legislatura}/votacion/{clave}"


def url_tabla(clave: str, legislatura: int = 66) -> str:
    return (f"{BASE}/{legislatura}/app/votaciones/functions/viewTableVot.php"
            f"?action=ajax&cell=1&order=DESC&votacion={clave}&q=")


def decodificar(contenido: bytes) -> str:
    return contenido.decode("utf-8")


def _texto(fragmento: str, bloques: bool = False) -> str:
    """Texto plano; `<br>` (y con `bloques`, cada div, celda o encabezado) abre línea."""
    corte = r"<br\s*/?>|</?(?:div|td|th|tr|p|h\d|li)\b[^>]*>" if bloques else r"<br\s*/?>"
    sin_etiquetas = re.sub(corte, "\n", fragmento)
    sin_etiquetas = re.sub(r"<[^>]+>", " ", sin_etiquetas)
    return "\n".join(" ".join(l.split()) for l in html.unescape(sin_etiquetas).split("\n") if l.strip())


def _fecha(texto: str) -> str | None:
    m = _FECHA.search(texto)
    if not m or m[2].lower() not in _MESES:
        return None
    return f"{m[3]}-{_MESES[m[2].lower()]:02d}-{int(m[1]):02d}"


def listado(documento: str) -> list[dict]:
    """Votaciones de la legislatura: clave, asunto y qué se votó."""
    salida, vistas = [], set()
    for m in re.finditer(r'<a href="/\d+/votacion/(\d+)">(.*?)</a>', documento, re.S):
        if m[1] in vistas:
            continue
        vistas.add(m[1])
        partes = _texto(m[2]).split("\n")
        salida.append({"clave": m[1], "asunto": partes[0], "motion": " ".join(partes[1:]) or None})
    return salida


def votacion(documento: str) -> dict:
    """Fecha, asunto, qué se vota y conteos de la página de una votación."""
    cuerpo = documento[documento.find("PERIODO"):] if "PERIODO" in documento else documento
    cuerpo = cuerpo[:cuerpo.find("Senador (a)")] if "Senador (a)" in cuerpo else cuerpo
    lineas = [l for l in _texto(re.sub(r"<!--|-->", " ", cuerpo), bloques=True).split("\n") if l]
    fecha = next((_fecha(l) for l in lineas if _fecha(l)), None)
    i = next((k for k, l in enumerate(lineas) if _fecha(l)), None)
    conteos = {}
    for etiqueta, clave in (("EN PRO", "yes"), ("EN CONTRA", "no"), ("ABSTENCI", "abstain")):
        k = next((k for k, l in enumerate(lineas) if sin_acentos(l).upper().startswith(sin_acentos(etiqueta))), None)
        if k is None or k + 1 >= len(lineas) or not lineas[k + 1].isdigit():
            raise ValueError(f"votación sin conteo {etiqueta!r}")
        conteos[clave] = int(lineas[k + 1])
    if fecha is None or i is None:
        raise ValueError("votación sin fecha")
    resto = lineas[i + 1:next(k for k, l in enumerate(lineas) if l.upper().startswith("EN PRO"))]
    if not resto:
        raise ValueError("votación sin asunto")
    return {"fecha": fecha, "asunto": resto[0], "motion": " ".join(resto[1:]) or None, "conteos": conteos}


_FILA = re.compile(
    r'<tr><td[^>]*>\s*(\d+)\s*</td><td[^>]*><a href="/\d+/votaciones/(\d+)#info">(.*?)</a></td>'
    r'<td[^>]*>(?:<a[^>]*>)?(.*?)(?:</a>)?</td><td[^>]*>(.*?)</td></tr>', re.S)


def tabla(documento: str) -> list[dict]:
    """Una fila por senador: clave del sitio, nombre ('Apellidos, Nombres'), grupo y voto."""
    filas = []
    for m in _FILA.finditer(documento):
        nombre = " ".join(html.unescape(m[3]).split())
        if not nombre.startswith("Sen. "):
            raise ValueError(f"fila sin 'Sen.': {nombre!r}")
        voto = sin_acentos(" ".join(html.unescape(m[5]).split())).upper()
        if voto not in {sin_acentos(k) for k in OPCIONES}:
            raise ValueError(f"voto desconocido: {voto!r}")
        filas.append({
            "numero": int(m[1]),
            "senado_id": m[2],
            "nombre": nombre[5:],
            "grupo": " ".join(html.unescape(m[4]).split()),
            "opcion": OPCIONES["ABSTENCION" if voto.startswith("ABSTENCION") else voto],
        })
    if [f["numero"] for f in filas] != list(range(1, len(filas) + 1)):
        raise ValueError("la tabla del Senado no se leyó completa")
    return filas


def clave_tokens(nombre: str) -> tuple[str, ...]:
    """Los nombres como multiconjunto de palabras: el Senado escribe
    'Apellidos, Nombres' y el SIL 'Nombres Apellidos'."""
    limpio = re.sub(r"[^a-z0-9 ]", " ", sin_acentos(nombre).lower())
    return tuple(sorted(limpio.split()))
