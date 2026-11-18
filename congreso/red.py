"""Descargas de las fuentes oficiales, con caché local y huella de cada respuesta.

Cada respuesta se guarda en la caché por su URL (para no repetir peticiones a
sitios lentos) y se describe con su procedencia: URL, fecha de consulta y
sha256 del contenido. Esa procedencia acompaña a cada dato en el repo.
"""
from __future__ import annotations

import base64
import hashlib
import http.client
import json
import os
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

AGENTE = "Mozilla/5.0 (compatible; OpenCodice/1.0; +https://github.com/OpenCodice)"
PAUSA = float(os.environ.get("CONGRESO_PAUSA", "3.0"))
# Páginas que sirven los firewalls (con estado 200) cuando limitan las
# peticiones: la del SIL y la de Incapsula (sitio del Senado). Nunca se guardan.
BLOQUEOS = (b"This page can't be displayed", b"_Incapsula_Resource")
ESPERAS_BLOQUEO = (60, 180, 600, 1200)
# El Senado bloquea tras unas diez peticiones seguidas a 3 s.
PAUSAS = {"www.senado.gob.mx": float(os.environ.get("CONGRESO_PAUSA_SENADO", "12"))}


def bloqueado(contenido: bytes) -> bool:
    return any(b in contenido[:3000] for b in BLOQUEOS)


# Sitios que rechazan conexiones de fuera de México: se piden por el Worker
# egress-mx de constitucion-extractor, que corre allá.
VIA_MX = {"sitl.diputados.gob.mx", "gaceta.diputados.gob.mx", "www.senado.gob.mx", "senado.gob.mx"}
EGRESS_MX = "https://egress-mx.danielcardeenas.workers.dev/"


class Bloqueado(RuntimeError):
    pass


# Fallas de red que se reintentan; una respuesta cortada a medias
# (IncompleteRead) es HTTPException, no URLError.
ERRORES_RED = (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException)


CACHE = Path(os.environ.get("CONGRESO_CACHE", Path(__file__).resolve().parent.parent / ".cache"))

# Con CONGRESO_ARCHIVO (la URL del Worker congreso-archivo, `archivo/`), nada
# se descarga de las fuentes: las páginas se leen del archivo, que las baja
# solo y sin prisa, y lo que falta o ya está viejo se le pide al terminar
# (`enviar_pedidas`). `.cache/` queda como copia local del archivo.
ARCHIVO = os.environ.get("CONGRESO_ARCHIVO", "").rstrip("/")
PEDIDAS: dict[str, dict] = {}
REFRESCO_MIN = 24


class Pendiente(RuntimeError):
    """La página todavía no está en el archivo; ya quedó pedida."""


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


def _texto_clave(url: str, datos: dict | None) -> str:
    return url + ("\n" + json.dumps(datos, sort_keys=True) if datos else "")


def _ruta(url: str, datos: dict | None) -> Path:
    h = hashlib.sha256(_texto_clave(url, datos).encode()).hexdigest()
    return CACHE / h[:2] / h


def _cuerpo(datos: dict | None) -> bytes | None:
    if datos is None:
        return None
    from urllib.parse import urlencode
    return urlencode(datos, doseq=True, encoding="cp1252").encode()


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
    if ARCHIVO:
        return _del_archivo(url, datos, vigencia_horas)
    ruta = _ruta(url, datos)
    meta = ruta.with_suffix(".json")
    if ruta.exists() and meta.exists() and time.time() - meta.stat().st_mtime < vigencia_horas * 3600:
        contenido = ruta.read_bytes()
        # Una página de bloqueo que haya quedado en el caché no cuenta.
        if not bloqueado(contenido):
            m = json.loads(meta.read_text())
            return Respuesta(url, contenido, m["consultado"], hashlib.sha256(contenido).hexdigest(), datos)

    cuerpo = _cuerpo(datos)
    error = None
    for intento in range(intentos):
        espera = PAUSAS.get(urlsplit(url).hostname, PAUSA) - (time.monotonic() - _ultima)
        if espera > 0:
            time.sleep(espera)
        try:
            contenido = _pedir(url, cuerpo)
            _ultima = time.monotonic()
            if bloqueado(contenido):
                contenido = _esperar_bloqueo(url, cuerpo, bloqueos)
            break
        except ERRORES_RED as e:
            _ultima = time.monotonic()
            error = e
            time.sleep(PAUSA * (2 ** intento) * 3)
    else:
        raise RuntimeError(f"no se pudo descargar {url}: {error}")

    if bloqueado(contenido):
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
        try:
            contenido = _pedir(url, cuerpo)
        except ERRORES_RED:
            # Mientras bloquea, el firewall también corta conexiones.
            contenido = BLOQUEOS[0]
        _ultima = time.monotonic()
        if not bloqueado(contenido):
            return contenido
    raise Bloqueado(url)


# ---------------------------------------------------------------- archivo

def _api(ruta: str, cuerpo: bytes | None = None) -> tuple[int, bytes, dict]:
    token = os.environ.get("CONGRESO_ARCHIVO_TOKEN")
    if not token:
        raise RuntimeError("con CONGRESO_ARCHIVO hace falta CONGRESO_ARCHIVO_TOKEN")
    cabeceras = {"Authorization": f"Bearer {token}", "User-Agent": AGENTE}
    if cuerpo is not None:
        cabeceras["Content-Type"] = "application/json"
    error = None
    for intento in range(4):
        try:
            req = urllib.request.Request(ARCHIVO + ruta, data=cuerpo, headers=cabeceras)
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.status, r.read(), dict(r.headers)
        except urllib.error.HTTPError as e:
            if e.code < 500:
                return e.code, e.read(), dict(e.headers)
            error = e
        except ERRORES_RED as e:
            error = e
        time.sleep(2 ** intento)
    raise RuntimeError(f"el archivo no respondió ({ruta}): {error}")


def _horas_desde(consultado: str) -> float:
    t = datetime.strptime(consultado, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds() / 3600


def pedir(url: str, datos: dict | None = None, prioridad: int = 1) -> None:
    """Anota una página para que el archivo la baje (o la vuelva a bajar)."""
    texto = _texto_clave(url, datos)
    clave = hashlib.sha256(texto.encode()).hexdigest()
    cuerpo = _cuerpo(datos)
    previa = PEDIDAS.get(clave)
    if previa is None or previa["prioridad"] < prioridad:
        PEDIDAS[clave] = {"clave": clave, "texto": texto, "url": url, "prioridad": prioridad,
                          "cuerpo": base64.b64encode(cuerpo).decode() if cuerpo is not None else None}


def anticipar(url: str, datos: dict | None = None) -> None:
    """Pide de una vez una página que se va a leer después, para no esperar
    una vuelta del archivo por cada página de una cadena."""
    if ARCHIVO and not _ruta(url, datos).exists():
        pedir(url, datos)


def _del_archivo(url: str, datos: dict | None, vigencia_horas: float) -> Respuesta:
    ruta = _ruta(url, datos)
    meta = ruta.with_suffix(".json")
    copia = None
    if ruta.exists() and meta.exists():
        contenido = ruta.read_bytes()
        if not bloqueado(contenido):
            copia = (contenido, json.loads(meta.read_text())["consultado"])
    if copia is None or _horas_desde(copia[1]) >= vigencia_horas:
        estado, contenido, cabeceras = _api(f"/pagina/{ruta.name}")
        if estado == 200 and (copia is None or cabeceras["X-Consultado"] > copia[1]):
            copia = (contenido, cabeceras["X-Consultado"])
            ruta.parent.mkdir(parents=True, exist_ok=True)
            ruta.write_bytes(contenido)
            meta.write_text(json.dumps({"url": url, "datos": datos, "consultado": copia[1]}))
        elif estado == 410 and copia is None:
            raise RuntimeError(f"no se pudo descargar {url}: {contenido.decode(errors='replace')[:300]}")
        elif estado not in (200, 404, 410):
            raise RuntimeError(f"el archivo respondió {estado} para {url}")
    if copia is None:
        pedir(url, datos, prioridad=1)
        raise Pendiente(f"pendiente de descarga: {url}")
    # Una copia vieja se usa (su fecha de consulta es la real) y se pide otra,
    # a lo más una vez al día: el archivo baja cada sitio a su ritmo y lo nuevo
    # va primero.
    if _horas_desde(copia[1]) >= max(vigencia_horas, REFRESCO_MIN):
        pedir(url, datos, prioridad=0)
    return Respuesta(url, copia[0], copia[1], hashlib.sha256(copia[0]).hexdigest(), datos)


def enviar_pedidas() -> int:
    """Manda al archivo lo que faltó en esta corrida."""
    if not ARCHIVO or not PEDIDAS:
        return 0
    lista = list(PEDIDAS.values())
    for i in range(0, len(lista), 1000):
        estado, contenido, _ = _api("/pedir", json.dumps(lista[i:i + 1000]).encode())
        if estado != 200:
            raise RuntimeError(f"el archivo rechazó las pedidas ({estado}): {contenido[:300]!r}")
    PEDIDAS.clear()
    return len(lista)


def sembrar(cache: Path, token: str) -> dict:
    """Sube al archivo las páginas de una copia local (el caché de Actions de
    antes del archivo); el Worker solo guarda las que no tiene."""
    from urllib.parse import quote
    vistas = nuevas = 0
    for meta in sorted(cache.glob("*/*.json")):
        ruta = meta.with_suffix("")
        if not ruta.exists():
            continue
        m = json.loads(meta.read_text())
        contenido = ruta.read_bytes()
        texto = _texto_clave(m["url"], m.get("datos")) if "url" in m else ""
        if not texto or bloqueado(contenido) or hashlib.sha256(texto.encode()).hexdigest() != ruta.name:
            continue
        req = urllib.request.Request(f"{ARCHIVO}/sembrar/{ruta.name}", data=contenido, method="PUT", headers={
            "Authorization": f"Bearer {token}", "User-Agent": AGENTE, "X-Url": m["url"],
            "X-Texto": quote(texto, safe=""), "X-Consultado": m["consultado"],
            "X-Sha256": hashlib.sha256(contenido).hexdigest()})
        for intento in range(4):
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    nuevas += json.loads(r.read())["nueva"]
                break
            except ERRORES_RED:
                if intento == 3:
                    raise
                time.sleep(2 ** intento)
        vistas += 1
    return {"paginas": vistas, "nuevas": nuevas}
