"""Diario Oficial de la Federación, por la API de datos abiertos de SIDOF.

Sirve para pasar de lo que dicen los commits de los repos de leyes
(`Documento` + `Publicacion`) al decreto concreto que se publicó ese día.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .texto import clave_nombre

API = "https://sidof.segob.gob.mx/dof/sidof"
EDICIONES = (("NotasMatutinas", "MAT"), ("NotasVespertinas", "VES"), ("NotasExtraordinarias", "EXT"))

_NO_DECRETO = re.compile(r"^(fe de erratas|aclaraci[oó]n|aviso)", re.I)
_VERBO = re.compile(r"\b(reforma|reforman|adiciona|adicionan|deroga|derogan|expide|abroga)\b")
_PRECEDE = (" reglamento de la", " reglamento del", " reglamento de", " reglamento interior de la")


def _dmy(fecha_iso: str) -> str:
    a, m, d = fecha_iso.split("-")
    return f"{d}-{m}-{a}"


def url_sumario(fecha_iso: str) -> str:
    return f"{API}/notas/{_dmy(fecha_iso)}"


def url_nota_api(cod: int) -> str:
    return f"{API}/notas/nota/{cod}"


def url_nota(cod: int, fecha_iso: str) -> str:
    """URL citable de la nota en dof.gob.mx."""
    a, m, d = fecha_iso.split("-")
    return f"https://dof.gob.mx/nota_detalle.php?codigo={cod}&fecha={d}/{m}/{a}"


@dataclass
class Nota:
    codigo: int
    titulo: str
    fecha: str
    edicion: str
    dependencia: str | None
    pagina: int | None


def sumario(contenido: bytes, fecha_iso: str) -> list[Nota]:
    """Las notas con título del día, en las tres ediciones."""
    datos = json.loads(contenido)
    notas = []
    for campo, edicion in EDICIONES:
        for n in datos.get(campo) or []:
            titulo = n.get("titulo")
            if not titulo or titulo == "null":
                continue
            notas.append(Nota(int(n["codNota"]), " ".join(titulo.split()), fecha_iso, edicion,
                              n.get("codOrgaDos"), n.get("pagina")))
    return notas


def es_decreto(titulo: str) -> bool:
    """Un decreto que reforma, adiciona, deroga, expide o abroga algo."""
    t = titulo.strip()
    return (t.lower().startswith("decreto") and not _NO_DECRETO.match(t)
            and bool(_VERBO.search(clave_nombre(t))))


def menciones(titulo: str, nombres: dict[str, str]) -> set[str]:
    """Documentos que nombra un título. `nombres`: documento → nombre oficial.

    Si un nombre está contenido en otro que también aparece en el mismo lugar
    ("Ley General de Salud" dentro de "Ley General de Salud Mental"), solo
    cuenta el más largo.
    """
    t = " " + clave_nombre(titulo) + " "
    tramos = []
    for doc, nombre in nombres.items():
        n = " " + clave_nombre(nombre) + " "
        inicio = t.find(n)
        while inicio != -1:
            # "Reglamento de la Ley X" nombra al reglamento, no a la ley.
            if not t[:inicio].endswith(_PRECEDE):
                tramos.append((inicio, inicio + len(n), doc))
            inicio = t.find(n, inicio + 1)
    return {doc for a, b, doc in tramos
            if not any(a2 <= a and b <= b2 and (b2 - a2) > (b - a) for a2, b2, _ in tramos)}


def candidatos(notas: list[Nota], documento: str, nombres: dict[str, str]) -> list[Nota]:
    """Decretos del día que nombran al documento. Puede haber varios."""
    return [n for n in notas if es_decreto(n.titulo) and documento in menciones(n.titulo, nombres)]
