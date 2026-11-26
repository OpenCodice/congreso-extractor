"""Cronología de cada ley: sus decretos de reforma desde la publicación original.

La Cámara de Diputados publica, por ley, la lista de los decretos que la han
reformado (`LeyesBiblio/ref/{ley}.htm`; la de la CPEUM, `ref/cpeum_crono.htm`):
número, título, fecha del DOF y el archivo del decreto. De ahí sale un
registro por documento, `cronologia/{documento}.json`, que cubre también las
reformas anteriores al texto versionado: cada decreto se enlaza por
(Documento, Publicacion), como los del DOF.

El archivo de un decreto antiguo es la imagen escaneada del Diario: se enlaza
y se dice que lo es (`escaneado`); su texto no se transcribe.
"""
from __future__ import annotations

import html as _html
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

from . import datos, red
from .tablas import limpiar

BASE = "https://www.diputados.gob.mx/LeyesBiblio/"
INDICE = BASE + "index.htm"
# La página de la CPEUM en el índice lista las reformas por artículo; la
# cronológica es otra.
PAGINAS_FIJAS = {"cpeum": "ref/cpeum_crono.htm"}
VIGENCIA_HORAS = 24 * 7

_DIA = r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})"
_FECHA = re.compile(rf"\b{_DIA}\b")
# «DOF 07-10 al 13-12-1889»: una publicación repartida en varios días.
_TRAMO = re.compile(rf"\b(\d{{1,2}})(?:[-/](\d{{1,2}}))?(?:[-/](\d{{4}}))?\s+al\s+{_DIA}\b")
_SOLO_FECHA = re.compile(rf"^{_DIA}$")
_NUMERO = re.compile(r"^\d{1,3}$")
_AVISOS = {"nuevo", "nueva"}
_REFORMAS = re.compile(r"^decretos? de reforma", re.I)
_ARCHIVOS = ("pdf", "doc", "docx", "zip")


class _Parrafo:
    """Trozos de texto en orden, cada uno con el destino de su enlace (o
    None) y si va en cursiva."""

    def __init__(self) -> None:
        self.trozos: list[tuple[str, str | None, bool]] = []

    @property
    def texto(self) -> str:
        return " ".join(limpiar("".join(t for t, _, _ in self.trozos)).split())

    @property
    def enlaces(self) -> list[str]:
        return list(dict.fromkeys(e for _, e, _ in self.trozos if e))


class _Lector(HTMLParser):
    """Filas → celdas → párrafos. Las tablas anidadas no se separan: las
    páginas son HTML hecho a mano y una fila de la lista nunca contiene otra
    tabla."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.filas: list[list[list[_Parrafo]]] = []
        self._fila: list[list[_Parrafo]] | None = None
        self._celda: list[_Parrafo] | None = None
        self._enlace: str | None = None
        self._cursiva = 0

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._cerrar_fila()
            self._fila = []
        elif tag in ("td", "th"):
            self._cerrar_celda()
            if self._fila is None:
                self._fila = []
            self._celda = [_Parrafo()]
        elif tag in ("p", "div", "br") and self._celda is not None:
            self._celda.append(_Parrafo())
        elif tag == "a":
            href = dict(attrs).get("href")
            self._enlace = _html.unescape(href).strip() if href else None
            if self._enlace and self._celda is not None:
                # Un enlace sin texto (un icono) también cuenta.
                self._celda[-1].trozos.append(("", self._enlace, False))
        elif tag in ("i", "em"):
            self._cursiva += 1

    def handle_endtag(self, tag):
        if tag == "a":
            self._enlace = None
        elif tag in ("i", "em"):
            self._cursiva = max(0, self._cursiva - 1)
        elif tag in ("td", "th"):
            self._cerrar_celda()
        elif tag in ("tr", "table"):
            self._cerrar_fila()

    def handle_data(self, data):
        if self._celda is not None:
            self._celda[-1].trozos.append((data, self._enlace, bool(self._cursiva)))

    def _cerrar_celda(self):
        if self._celda is not None:
            self._fila.append([p for p in self._celda if p.texto or p.enlaces])
            self._celda = None
        self._enlace, self._cursiva = None, 0

    def _cerrar_fila(self):
        self._cerrar_celda()
        if self._fila:
            self.filas.append(self._fila)
        self._fila = None

    def close(self):
        super().close()
        self._cerrar_fila()


def decodificar(contenido: bytes) -> str:
    """Las páginas declaran utf-8 y muchas siguen en Windows-1252."""
    try:
        return contenido.decode("utf-8")
    except UnicodeDecodeError:
        return contenido.decode("cp1252", errors="replace")


def _iso(d: str, m: str, a: str) -> str | None:
    d, m = int(d), int(m)
    return f"{a}-{m:02d}-{d:02d}" if 1 <= m <= 12 and 1 <= d <= 31 else None


def _fechas(texto: str) -> tuple[re.Match, str | None, str | None] | None:
    """(coincidencia, fecha, fecha final) de la primera fecha de un texto."""
    m = _TRAMO.search(texto)
    if m:
        d1, m1, a1, d2, m2, a2 = m.groups()
        return m, _iso(d1, m1 or m2, a1 or a2), _iso(d2, m2, a2)
    m = _FECHA.search(texto)
    return (m, _iso(*m.groups()), None) if m else None


def _archivo(destino: str, texto: str, base: str) -> dict | None:
    """El archivo de una publicación. La imagen escaneada del Diario se
    reconoce por su nombre (`_ima`) o por el texto de su enlace."""
    nombre = destino.rsplit("/", 1)[-1].lower()
    ext = nombre.rsplit(".", 1)[-1] if "." in nombre else ""
    if ext not in _ARCHIVOS:
        return None
    if ext in ("doc", "docx"):
        formato = "word"
    else:
        formato = "imagen" if "_ima" in nombre or "imagen" in texto.lower() else "pdf"
    return {"formato": formato, "url": urljoin(base, destino)}


def _es_proceso(destino: str, texto: str) -> bool:
    return "/proceso/" in destino or "proceso legislativo" in texto.lower()


def _segmentos(p: _Parrafo) -> list[tuple[str, list[str]]]:
    """Un renglón «| DOF 27-08-2009 | Word |» partido por sus barras: el texto
    de cada parte y los destinos de sus enlaces."""
    partes: list[tuple[list[str], list[str]]] = [([], [])]
    for texto, enlace, _ in p.trozos:
        trozos = texto.split("|") if enlace is None else [texto]
        for k, trozo in enumerate(trozos):
            if k:
                partes.append(([], []))
            partes[-1][0].append(trozo)
            if enlace and enlace not in partes[-1][1]:
                partes[-1][1].append(enlace)
    return [(" ".join(limpiar("".join(t)).split()), e) for t, e in partes]


def _es_renglon(p: _Parrafo) -> bool:
    """Un renglón de publicaciones, no un título: lleva barras o «DOF» y fecha."""
    return bool(_fechas(p.texto)) and ("|" in p.texto or re.search(r"\bDOF\b", p.texto) is not None)


def _publicaciones(p: _Parrafo, base: str) -> tuple[list[dict], str | None]:
    """(publicaciones, proceso legislativo) de un renglón. Cada parte con
    fecha abre una publicación; las que solo enlazan un archivo son de la
    publicación abierta. Lo que precede a la fecha («Fe de erratas»,
    «Notificación para efectos legales») es su etiqueta."""
    salida, proceso, etiqueta = [], None, ""
    for texto, enlaces in _segmentos(p):
        f = _fechas(texto)
        if f:
            m, fecha, fin = f
            propia = re.sub(r"\bDOF\b", "", texto[:m.start()]).strip(" :.-–")
            pub = {"fecha": fecha, "archivos": []}
            if fin:
                pub["fecha_fin"] = fin
            if propia or etiqueta:
                pub["etiqueta"] = propia or etiqueta
            salida.append(pub)
            etiqueta = ""
        elif not enlaces and texto:
            etiqueta = texto.strip(" :.-–")
        for destino in enlaces:
            if _es_proceso(destino, texto):
                proceso = urljoin(base, destino)
                continue
            a = _archivo(destino, texto, base)
            if a and salida and a not in salida[-1]["archivos"]:
                salida[-1]["archivos"].append(a)
    return salida, proceso


def _titulo(p: _Parrafo) -> tuple[str, str]:
    """(clase, título): la clase es lo que el título lleva en cursiva al
    principio («Sentencia de la SCJN.», «Actualización de cantidades.»)."""
    clase, resto, abierto = [], [], True
    for texto, _, cursiva in p.trozos:
        if abierto and (cursiva or not "".join(clase + [texto]).strip(" .: \n\r\t")):
            clase.append(texto)
        else:
            abierto = False
            resto.append(texto)
    limpio = lambda xs: " ".join(limpiar("".join(xs)).split())
    if not limpio(resto):
        return "", limpio(clase)
    return limpio(clase).strip(" .:"), limpio(resto).lstrip(". ")


def _leer_fila(fila: list[list[_Parrafo]], base: str) -> dict | None:
    if len(fila) < 2:
        return None
    numero = " ".join(p.texto for p in fila[0])
    es_original = numero.lower().startswith("orig")
    if numero and not es_original and not _NUMERO.match(numero):
        return None
    titulo, clase, descripcion, publicaciones, proceso = "", "", [], [], None
    for k, celda in enumerate(fila[1:], 1):
        m = _SOLO_FECHA.match(" ".join(p.texto for p in celda))
        if m:
            # La CPEUM lleva la fecha en su columna y los archivos en la siguiente.
            pub = {"fecha": _iso(*m.groups()), "archivos": []}
            for p in (fila[k + 1] if k + 1 < len(fila) else []):
                for texto, destino, _ in p.trozos:
                    if destino and _es_proceso(destino, p.texto):
                        proceso = urljoin(base, destino)
                    elif destino:
                        a = _archivo(destino, p.texto if len(p.enlaces) == 1 else texto, base)
                        if a and a["url"] not in {x["url"] for x in pub["archivos"]}:
                            pub["archivos"].append(a)
            publicaciones.insert(0, pub)
            continue
        if k > 1:
            continue
        for p in celda:
            if _es_renglon(p) or (titulo and p.enlaces):
                pubs, pl = _publicaciones(p, base)
                publicaciones += pubs
                proceso = proceso or pl
            elif p.texto.lower() in _AVISOS or not p.texto.strip("-– "):
                continue
            elif not titulo:
                clase, titulo = _titulo(p)
            else:
                descripcion.append(p.texto)
    if not titulo or not publicaciones:
        return None
    principal = next((p for p in publicaciones if "etiqueta" not in p), publicaciones[0])
    registro = {"titulo": titulo, "fecha": principal["fecha"], "publicaciones": publicaciones}
    if _NUMERO.match(numero):
        registro["numero"] = int(numero)
    elif es_original:
        registro["original"] = True
    if clase:
        registro["clase"] = clase
    if descripcion:
        registro["descripcion"] = " ".join(descripcion)
    if proceso:
        registro["proceso_legislativo"] = proceso
    if principal["archivos"]:
        registro["escaneado"] = all(a["formato"] == "imagen" for a in principal["archivos"])
    return registro


def leer(pagina: str, url: str) -> dict:
    """{original, decretos, otras} de una página de reformas. `decretos` son
    los numerados de la lista de reformas; `otras`, lo demás que la página
    lista (sentencias, acuerdos que actualizan cantidades, declaratorias),
    con su sección. Lanza ValueError si la lista no es coherente: la
    numeración de los decretos debe ser corrida y cada fecha, legible."""
    lector = _Lector()
    lector.feed(pagina)
    lector.close()
    original, decretos, otras, seccion = None, [], [], ""
    for fila in lector.filas:
        if len(fila) == 1:
            # «Decretos de Reforma:», «Declaratorias de Entrada en Vigor…:»
            ultimo = fila[0][-1].texto if fila[0] else ""
            if ultimo.endswith(":") and len(ultimo) < 120:
                seccion = ultimo.rstrip(": ")
            continue
        r = _leer_fila(fila, url)
        if r is None:
            continue
        if r.pop("original", False):
            original = original or r
        elif "numero" in r and (not seccion or _REFORMAS.match(seccion)):
            decretos.append(r)
        else:
            if seccion and not _REFORMAS.match(seccion):
                r["seccion"] = seccion
            otras.append(r)
    decretos.sort(key=lambda d: d["numero"])
    numeros = [d["numero"] for d in decretos]
    if numeros != list(range(1, len(numeros) + 1)):
        faltan = sorted(set(range(1, max(numeros, default=0) + 1)) - set(numeros))
        repetidos = sorted({n for n in numeros if numeros.count(n) > 1})
        raise ValueError(f"numeración no corrida (faltan {faltan[:8]}, repetidos {repetidos[:8]})")
    for d in ([original] if original else []) + decretos + otras:
        if d["fecha"] is None or any(p["fecha"] is None for p in d["publicaciones"]):
            raise ValueError(f"«{d['titulo'][:60]}» sin fecha legible")
    if original is None and not decretos:
        raise ValueError("la página no trae la lista de reformas")
    otras.sort(key=lambda d: (d["fecha"], d["titulo"]))
    return {"original": original, "decretos": decretos, "otras": otras}


def paginas(indice: str, documentos: list[dict]) -> dict[str, str]:
    """clave → página de reformas, de la fila del índice que enlaza el PDF del
    documento. Solo cuenta una fila con una sola página y un solo PDF."""
    por_pdf = {}
    for fila in re.findall(r"(?is)<tr\b.*?</tr>", indice):
        refs = {r for r in re.findall(r'(?i)href="(ref/[\w-]+\.htm)"', fila)}
        pdfs = {p.lower() for p in re.findall(r'(?i)href="pdf/([^"]+\.pdf)"', fila)}
        if len(refs) == 1 and len(pdfs) == 1:
            por_pdf.setdefault(pdfs.pop(), refs.pop())
    salida = dict(PAGINAS_FIJAS)
    for d in documentos:
        pdf = d.get("url", "").rsplit("/", 1)[-1].lower()
        if d["clave"] not in salida and "/LeyesBiblio/pdf/" in d.get("url", "") and pdf in por_pdf:
            salida[d["clave"]] = por_pdf[pdf]
    return salida


def fechas_de_notas(repos: Path, clave: str) -> list[str]:
    """Las fechas de reforma que anota el texto vigente del documento."""
    rutas = [repos / "constitucion-mexicana" / "metadata" / "reformas.json"] if clave == "cpeum" else [
        repos / base / "metadata" / clave / "reformas.json" for base in ("leyes-federales", "fiscal-mexicano")]
    for ruta in rutas:
        if ruta.exists():
            return sorted(json.loads(ruta.read_text(encoding="utf-8")))
    return []


def construir(raiz: Path, repos: Path) -> dict:
    registro = json.loads((repos / "leyes-federales" / "fuentes.json").read_text(encoding="utf-8"))["documentos"]
    nombres = {"cpeum": "Constitución Política de los Estados Unidos Mexicanos"}
    nombres.update((d["clave"], d["etiqueta"]) for d in registro)
    # Sin el índice no se sabe qué página es de qué ley: el paso entero espera.
    indice = red.obtener(INDICE, vigencia_horas=VIGENCIA_HORAS)
    de = paginas(decodificar(indice.contenido), registro)
    for ruta in de.values():
        red.anticipar(BASE + ruta)
    escritos = pendientes = decretos = 0
    errores, sin_cuadrar = [], 0
    for clave, ruta in sorted(de.items()):
        url = BASE + ruta
        try:
            r = red.obtener(url, vigencia_horas=VIGENCIA_HORAS)
        except red.Pendiente:
            pendientes += 1
            continue
        except RuntimeError as e:
            errores.append(f"cronologia {clave}: {e}")
            continue
        try:
            leida = leer(decodificar(r.contenido), url)
        except ValueError as e:
            # Una página que no se lee deja la cronología publicada como estaba.
            errores.append(f"cronologia {clave}: {e}")
            continue
        listadas = leida["decretos"] + leida["otras"] + ([leida["original"]] if leida["original"] else [])
        en_lista = {p["fecha"] for d in listadas for p in d["publicaciones"]}
        sin_decreto = [f for f in fechas_de_notas(repos, clave) if f not in en_lista]
        sin_cuadrar += bool(sin_decreto)
        decretos += len(leida["decretos"])
        escritos += datos.escribir(raiz, f"cronologia/{clave}.json", {
            "documento": clave, "nombre": nombres[clave], "url": url,
            "original": leida["original"], "decretos": leida["decretos"], "otras": leida["otras"],
            "notas_sin_decreto": sin_decreto, "sources": [r.procedencia()]})
    return {"documentos": len(de) - pendientes - len(errores), "decretos": decretos, "escritos": escritos,
            "sin_pagina": len(nombres) - len(de), "con_notas_sin_decreto": sin_cuadrar,
            "pendientes_de_descarga": pendientes, "errores": errores}
