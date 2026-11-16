"""Catálogos fijos: entidades federativas, partidos y cámaras.

Las claves de entidad son las mismas carpetas de `leyes-estatales`, para que
un congreso local y su constitución se enlacen sin traducción.
"""
from __future__ import annotations

from .texto import clave_nombre

# clave → (nombre corto, nombre oficial)
ENTIDADES = {
    "aguascalientes": ("Aguascalientes", "Aguascalientes"),
    "baja-california": ("Baja California", "Baja California"),
    "baja-california-sur": ("Baja California Sur", "Baja California Sur"),
    "campeche": ("Campeche", "Campeche"),
    "cdmx": ("Ciudad de México", "Ciudad de México"),
    "chiapas": ("Chiapas", "Chiapas"),
    "chihuahua": ("Chihuahua", "Chihuahua"),
    "coahuila": ("Coahuila", "Coahuila de Zaragoza"),
    "colima": ("Colima", "Colima"),
    "durango": ("Durango", "Durango"),
    "edomex": ("México", "Estado de México"),
    "guanajuato": ("Guanajuato", "Guanajuato"),
    "guerrero": ("Guerrero", "Guerrero"),
    "hidalgo": ("Hidalgo", "Hidalgo"),
    "jalisco": ("Jalisco", "Jalisco"),
    "michoacan": ("Michoacán", "Michoacán de Ocampo"),
    "morelos": ("Morelos", "Morelos"),
    "nayarit": ("Nayarit", "Nayarit"),
    "nuevo-leon": ("Nuevo León", "Nuevo León"),
    "oaxaca": ("Oaxaca", "Oaxaca"),
    "puebla": ("Puebla", "Puebla"),
    "queretaro": ("Querétaro", "Querétaro"),
    "quintana-roo": ("Quintana Roo", "Quintana Roo"),
    "san-luis-potosi": ("San Luis Potosí", "San Luis Potosí"),
    "sinaloa": ("Sinaloa", "Sinaloa"),
    "sonora": ("Sonora", "Sonora"),
    "tabasco": ("Tabasco", "Tabasco"),
    "tamaulipas": ("Tamaulipas", "Tamaulipas"),
    "tlaxcala": ("Tlaxcala", "Tlaxcala"),
    "veracruz": ("Veracruz", "Veracruz de Ignacio de la Llave"),
    "yucatan": ("Yucatán", "Yucatán"),
    "zacatecas": ("Zacatecas", "Zacatecas"),
}

_ALIAS = {
    "distrito federal": "cdmx",
    "ciudad de mexico": "cdmx",
    "estado de mexico": "edomex",
    "mexico": "edomex",
}


def nombres_entidades() -> dict[str, set[str]]:
    """Clave → todas sus formas normalizadas."""
    salida = {c: {clave_nombre(corto), clave_nombre(oficial)} for c, (corto, oficial) in ENTIDADES.items()}
    for alias, c in _ALIAS.items():
        salida[c].add(alias)
    salida["queretaro"].add("queretaro de arteaga")
    salida["coahuila"].add("coahuila de zaragoza")
    return salida


def entidad(nombre: str) -> str | None:
    """Clave de una entidad por cualquiera de sus nombres; None si no la reconoce."""
    k = clave_nombre(nombre)
    if k in _ALIAS:
        return _ALIAS[k]
    for clave, (corto, oficial) in ENTIDADES.items():
        if k in (clave_nombre(corto), clave_nombre(oficial)):
            return clave
    return None


# Etiqueta del SIL → (clave, nombre oficial). "Ind." y "Sin Partido" no son partidos.
PARTIDOS = {
    "Morena": ("morena", "Morena"),
    "PAN": ("pan", "Partido Acción Nacional"),
    "PRI": ("pri", "Partido Revolucionario Institucional"),
    "PVEM": ("pvem", "Partido Verde Ecologista de México"),
    "PT": ("pt", "Partido del Trabajo"),
    "MC": ("mc", "Movimiento Ciudadano"),
    "PRD": ("prd", "Partido de la Revolución Democrática"),
    "PES": ("pes", "Partido Encuentro Social"),
    "PES.": ("pes", "Partido Encuentro Social"),
}
SIN_PARTIDO = {"Ind.", "Sin Partido", "SP", "-", ""}


def partido(etiqueta: str) -> str | None:
    """ID de organización del grupo parlamentario; None si es independiente."""
    e = etiqueta.strip()
    if e in SIN_PARTIDO:
        return None
    if e in PARTIDOS:
        return "partido-" + PARTIDOS[e][0]
    raise KeyError(f"partido desconocido en la fuente: {etiqueta!r}")


CAMARAS = {
    "diputados": ("camara-de-diputados", "Cámara de Diputados", "Diputado"),
    "senado": ("senado", "Cámara de Senadores", "Senador"),
}
