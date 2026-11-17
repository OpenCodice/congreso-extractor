"""Ligar el nombre de un legislador, como lo escribe una fuente, a su mandato.

Cada fuente escribe distinto al mismo legislador: el SIL "Nombres Apellidos",
el Senado "Apellidos, Nombres" y abreviado, la Gaceta "Apellidos Nombres" con
iniciales y variantes ortográficas (Aracelly/Aracely, Vásquez/Vázquez). Se
comparan como multiconjuntos de palabras, con criterios cada vez más amplios;
cada uno debe dar un único mandato de la cámara y legislatura, y si da más de
uno, el nombre no se liga (no se pasa al siguiente). El criterio usado queda
en el voto.
"""
from __future__ import annotations

import re
from collections import Counter

from .texto import sin_acentos

_ABREVIATURAS = {"ma": "maria", "ma.": "maria", "ma.del": "maria del"}


def palabras(nombre: str) -> list[str]:
    texto = sin_acentos(nombre).lower()
    for corta, larga in _ABREVIATURAS.items():
        texto = re.sub(rf"(?<![a-z]){re.escape(corta)}(?![a-z])", larga, texto)
    return re.sub(r"[^a-z0-9 ]", " ", texto).split()


def _fonetica(palabra: str) -> str:
    """Variantes de escritura del español que no distinguen a dos personas."""
    p = palabra.replace("ll", "l").replace("z", "s").replace("y", "i").replace("v", "b")
    p = re.sub(r"(.)\1", r"\1", p)
    return p[1:] if p.startswith("h") else p


def _formas(nombre: str, fonetica: bool) -> tuple[Counter, Counter]:
    ps = palabras(nombre)
    if fonetica:
        ps = [_fonetica(p) for p in ps]
    return Counter(ps), Counter(p for p in ps if len(p) > 1)


class Indice:
    def __init__(self, mandatos: list[dict], personas: dict[str, dict]):
        self.mandatos = mandatos
        self._formas = {f: [(_formas(personas[m["person_id"]]["name"], f), m) for m in mandatos]
                        for f in (False, True)}

    def buscar(self, nombre: str) -> tuple[dict, str] | None:
        for fonetica in (False, True):
            todas, sin_iniciales = _formas(nombre, fonetica)
            sufijo = " (variante ortográfica)" if fonetica else ""
            criterios = (
                ("nombre", lambda k: k[0] == todas),
                ("nombre sin iniciales", lambda k: k[1] == sin_iniciales),
                ("nombre abreviado", lambda k: not (sin_iniciales - k[1])),
                ("nombre ampliado", lambda k: not (k[1] - sin_iniciales)),
            )
            for criterio, cumple in criterios:
                hallados = [m for k, m in self._formas[fonetica] if cumple(k)]
                if len(hallados) == 1:
                    return hallados[0], criterio + sufijo
                if len(hallados) > 1:
                    return None
        return None
