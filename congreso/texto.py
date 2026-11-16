"""Normalización de nombres, fechas e identificadores."""
from __future__ import annotations

import re
import unicodedata

_NO_ALFANUM = re.compile(r"[^a-z0-9]+")
_FECHA_DMY = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")


def sin_acentos(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def clave_nombre(nombre: str) -> str:
    """Forma comparable de un nombre: sin acentos, minúsculas, un espacio."""
    return " ".join(_NO_ALFANUM.sub(" ", sin_acentos(nombre).lower()).split())


def slug(s: str) -> str:
    return _NO_ALFANUM.sub("-", sin_acentos(s).lower()).strip("-")


def fecha_iso(dmy: str) -> str | None:
    """'29/08/2024' → '2024-08-29'; cualquier otra cosa → None."""
    m = _FECHA_DMY.match(dmy.strip())
    return f"{m[3]}-{m[2]}-{m[1]}" if m else None


ROMANOS = {"LXIV": 64, "LXV": 65, "LXVI": 66, "LXVII": 67}


def romano(n: int) -> str:
    valores = ((50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"))
    r = ""
    for v, s in valores:
        while n >= v:
            r, n = r + s, n - v
    return r
