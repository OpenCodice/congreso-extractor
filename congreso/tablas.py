"""Lectura de las tablas HTML de las fuentes oficiales.

Las páginas del SIL son HTML de los 2000: tablas anidadas, etiquetas sin
cerrar y datos dentro de comentarios. En vez de buscar selectores frágiles,
se aplanan a filas de celdas con su texto, sus clases y las referencias
numéricas de sus enlaces, y cada parser elige las filas por su forma.
"""
from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

_ESPACIOS = re.compile(r"[ \t\r\f\v ]+")
_LINEAS = re.compile(r"\s*\n\s*")


@dataclass
class Celda:
    texto: str = ""
    clases: tuple[str, ...] = ()
    enlaces: list[str] = field(default_factory=list)
    encabezado: bool = False

    def lineas(self) -> list[str]:
        return [l for l in self.texto.split("\n") if l]

    @property
    def plano(self) -> str:
        return " ".join(self.lineas())


def limpiar(texto: str) -> str:
    texto = _ESPACIOS.sub(" ", texto)
    return _LINEAS.sub("\n", texto).strip()


class _Lector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.filas: list[list[Celda]] = []
        self._pila: list[tuple[list[Celda], Celda | None, list[str]]] = []
        self._fila: list[Celda] | None = None
        self._celda: Celda | None = None
        self._partes: list[str] = []
        self._ignorar = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style"):
            self._ignorar += 1
        elif tag == "table":
            self._pila.append((self._fila, self._celda, self._partes))
            self._fila, self._celda, self._partes = None, None, []
        elif tag == "tr":
            self._cerrar_fila()
            self._fila = []
        elif tag in ("td", "th"):
            self._cerrar_celda()
            if self._fila is None:
                self._fila = []
            self._celda = Celda(clases=tuple((a.get("class") or "").split()), encabezado=tag == "th")
            self._partes = []
        elif tag == "br":
            self._partes.append("\n")
        elif tag == "p" or tag == "div":
            self._partes.append("\n")
        for nombre in ("href", "onclick"):
            if a.get(nombre) and self._celda is not None:
                self._celda.enlaces.append(_html.unescape(a[nombre]))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._ignorar = max(0, self._ignorar - 1)
        elif tag in ("td", "th"):
            self._cerrar_celda()
        elif tag == "tr":
            self._cerrar_fila()
        elif tag == "table":
            self._cerrar_fila()
            if self._pila:
                self._fila, self._celda, self._partes = self._pila.pop()

    def handle_data(self, data):
        if not self._ignorar and self._celda is not None:
            self._partes.append(data)

    def _cerrar_celda(self):
        if self._celda is not None:
            self._celda.texto = limpiar("".join(self._partes))
            self._fila.append(self._celda)
            self._celda, self._partes = None, []

    def _cerrar_fila(self):
        self._cerrar_celda()
        if self._fila:
            self.filas.append(self._fila)
        self._fila = None

    def close(self):
        super().close()
        self._cerrar_fila()
        while self._pila:
            self._fila, self._celda, self._partes = self._pila.pop()
            self._cerrar_fila()


def filas(documento: str, con_comentarios: bool = False) -> list[list[Celda]]:
    """Todas las filas de todas las tablas, en orden de aparición.

    Con `con_comentarios`, el contenido de los comentarios HTML se lee como
    parte de la página: el SIL comenta campos (estatus, toma de protesta) que
    siguen siendo el dato oficial.
    """
    if con_comentarios:
        documento = documento.replace("<!--", "").replace("-->", "")
    lector = _Lector()
    lector.feed(documento)
    lector.close()
    return lector.filas


def texto(documento: str) -> str:
    """El texto visible de la página, en una sola cadena."""
    sin = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", documento)
    sin = re.sub(r"(?i)<br\s*/?>", "\n", sin)
    sin = re.sub(r"<[^>]+>", " ", sin)
    return limpiar(_html.unescape(sin))
