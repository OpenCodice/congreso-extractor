"""Lectura y escritura del repo de datos `congreso-mexicano`.

Un registro por archivo JSON, con claves ordenadas y sangría fija, para que
cada cambio en git sea un diff legible de un dato.
"""
from __future__ import annotations

import json
from pathlib import Path


def escribir(raiz: Path, relativa: str, registro: dict) -> bool:
    """Escribe el registro; devuelve True si cambió el archivo."""
    ruta = raiz / relativa
    texto = json.dumps(registro, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if ruta.exists() and ruta.read_text(encoding="utf-8") == texto:
        return False
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(texto, encoding="utf-8")
    return True


def leer(raiz: Path, relativa: str) -> dict | None:
    ruta = raiz / relativa
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else None


def todos(raiz: Path, carpeta: str) -> list[dict]:
    base = raiz / carpeta
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(base.rglob("*.json"))] if base.exists() else []


def guardar_fuente(raiz: Path, sha256: str, contenido: bytes, extension: str = "html") -> str:
    """Copia de la página oficial, por su huella. Devuelve la ruta relativa."""
    relativa = f"fuentes/{sha256[:2]}/{sha256}.{extension}"
    ruta = raiz / relativa
    if not ruta.exists():
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(contenido)
    return relativa
