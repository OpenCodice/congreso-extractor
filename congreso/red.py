"""Descargas de las fuentes oficiales, con caché local y huella de cada respuesta.

Cada respuesta se guarda en la caché por su URL (para no repetir peticiones a
sitios lentos) y se describe con su procedencia: URL, fecha de consulta y
sha256 del contenido. Esa procedencia acompaña a cada dato en el repo.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

AGENTE = "Mozilla/5.0 (compatible; OpenCodice/1.0; +https://github.com/OpenCodice)"
PAUSA = float(os.environ.get("CONGRESO_PAUSA", "3.0"))
# Página que sirve el firewall del SIL (con estado 200) cuando limita las peticiones.
BLOQUEO = b"This page can't be displayed"
ESPERAS_BLOQUEO = (60, 180, 600, 1200)


# Sitios que rechazan conexiones de fuera de México: se piden por el Worker
# egress-mx de constitucion-extractor, que corre allá.
VIA_MX = {"sitl.diputados.gob.mx", "gaceta.diputados.gob.mx", "www.senado.gob.mx", "senado.gob.mx"}
EGRESS_MX = "https://egress-mx.danielcardeenas.workers.dev/"


class Bloqueado(RuntimeError):
    pass


CACHE = Path(os.environ.get("CONGRESO_CACHE", Path(__file__).resolve().parent.parent / ".cache"))


@dataclass
class Respuesta:
    url: str
    contenido: bytes
    consultado: str
    sha256: str
    datos: dict | None = None

    def procedencia(self) -> dict:
        p = {"url": self.url, "consultado": self.consultado, "sha256": self.sha256}
        if self.datos:
            p["datos"] = self.datos
        return p


_ultima = 0.0


def _ruta(url: str, datos: dict | None) -> Path:
    clave = url + ("\n" + json.dumps(datos, sort_keys=True) if datos else "")
    h = hashlib.sha256(clave.encode()).hexdigest()
    return CACHE / h[:2] / h


def _pedir(url: str, cuerpo: bytes | None) -> bytes:
    from urllib.parse import quote, urlsplit
    cabeceras = {"User-Agent": AGENTE}
    if cuerpo is not None:
        cabeceras["Content-Type"] = "application/x-www-form-urlencoded"
    destino = url
    if urlsplit(url).hostname in VIA_MX:
        token = os.environ.get("EGRESS_MX_TOKEN")
        if not token:
            raise RuntimeError(f"{url} solo responde desde México: hace falta EGRESS_MX_TOKEN")
        destino = EGRESS_MX + "?url=" + quote(url, safe="")
        cabeceras["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(destino, data=cuerpo, headers=cabeceras)
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def obtener(url: str, datos: dict | None = None, vigencia_horas: float = 12, intentos: int = 3,
            bloqueos: tuple[int, ...] = ESPERAS_BLOQUEO) -> Respuesta:
    """GET (o POST con `datos`) con caché de `vigencia_horas` (0: siempre descarga)."""
    global _ultima
    ruta = _ruta(url, datos)
    meta = ruta.with_suffix(".json")
    if ruta.exists() and meta.exists() and time.time() - meta.stat().st_mtime < vigencia_horas * 3600:
        contenido = ruta.read_bytes()
        m = json.loads(meta.read_text())
        return Respuesta(url, contenido, m["consultado"], hashlib.sha256(contenido).hexdigest(), datos)

    cuerpo = None
    if datos is not None:
        from urllib.parse import urlencode
        cuerpo = urlencode(datos, doseq=True, encoding="cp1252").encode()
    error = None
    for intento in range(intentos):
        espera = PAUSA - (time.monotonic() - _ultima)
        if espera > 0:
            time.sleep(espera)
        try:
            contenido = _pedir(url, cuerpo)
            _ultima = time.monotonic()
            if BLOQUEO in contenido[:2000]:
                contenido = _esperar_bloqueo(url, cuerpo, bloqueos)
            break
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            _ultima = time.monotonic()
            error = e
            time.sleep(PAUSA * (2 ** intento) * 3)
    else:
        raise RuntimeError(f"no se pudo descargar {url}: {error}")

    if BLOQUEO in contenido[:2000]:
        raise Bloqueado(url)
    consultado = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(contenido)
    meta.write_text(json.dumps({"url": url, "datos": datos, "consultado": consultado}))
    return Respuesta(url, contenido, consultado, hashlib.sha256(contenido).hexdigest(), datos)


def _esperar_bloqueo(url: str, cuerpo: bytes | None, esperas: tuple[int, ...]) -> bytes:
    """Reintenta tras esperas crecientes mientras el firewall siga bloqueando."""
    global _ultima
    for espera in esperas:
        print(f"bloqueado por el firewall; espero {espera} s: {url}", file=sys.stderr, flush=True)
        time.sleep(espera)
        contenido = _pedir(url, cuerpo)
        _ultima = time.monotonic()
        if BLOQUEO not in contenido[:2000]:
            return contenido
    raise Bloqueado(url)
