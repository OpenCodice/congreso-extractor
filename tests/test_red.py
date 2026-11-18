import json

from congreso import red

INCAPSULA = b'<html><body><iframe id="main-iframe" src="/_Incapsula_Resource?SWUDNSAI=31">Request unsuccessful.</iframe>'


def test_pagina_de_bloqueo_en_cache_no_cuenta(tmp_path, monkeypatch):
    monkeypatch.setattr(red, "CACHE", tmp_path)
    monkeypatch.setattr(red, "PAUSA", 0)
    url = "http://sil.gobernacion.gob.mx/x"
    ruta = red._ruta(url, None)
    ruta.parent.mkdir(parents=True)
    ruta.write_bytes(INCAPSULA)
    ruta.with_suffix(".json").write_text(json.dumps({"consultado": "2026-01-01T00:00:00Z"}))
    monkeypatch.setattr(red, "_pedir", lambda u, c: b"<html>bien</html>")
    assert red.obtener(url).contenido == b"<html>bien</html>"
    assert ruta.read_bytes() == b"<html>bien</html>"


def test_bloqueo_que_no_cede_no_se_guarda(tmp_path, monkeypatch):
    monkeypatch.setattr(red, "CACHE", tmp_path)
    monkeypatch.setattr(red, "PAUSA", 0)
    monkeypatch.setattr(red.time, "sleep", lambda s: None)
    monkeypatch.setattr(red, "_pedir", lambda u, c: INCAPSULA)
    url = "http://sil.gobernacion.gob.mx/y"
    try:
        red.obtener(url, bloqueos=(1,))
        assert False, "debió bloquearse"
    except red.Bloqueado:
        pass
    assert not red._ruta(url, None).exists()


def test_respuesta_cortada_se_reintenta(tmp_path, monkeypatch):
    import http.client
    monkeypatch.setattr(red, "CACHE", tmp_path)
    monkeypatch.setattr(red, "PAUSA", 0)
    monkeypatch.setattr(red.time, "sleep", lambda s: None)
    respuestas = [http.client.IncompleteRead(b"a medias"), b"<html>completa</html>"]

    def pedir(u, c):
        r = respuestas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(red, "_pedir", pedir)
    assert red.obtener("http://sil.gobernacion.gob.mx/z").contenido == b"<html>completa</html>"


def test_corte_durante_el_bloqueo_cuenta_como_bloqueo(tmp_path, monkeypatch):
    import http.client
    monkeypatch.setattr(red, "CACHE", tmp_path)
    monkeypatch.setattr(red, "PAUSA", 0)
    monkeypatch.setattr(red.time, "sleep", lambda s: None)
    respuestas = [INCAPSULA, http.client.IncompleteRead(b""), b"<html>ya</html>"]

    def pedir(u, c):
        r = respuestas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(red, "_pedir", pedir)
    assert red.obtener("http://sil.gobernacion.gob.mx/w", bloqueos=(1, 1)).contenido == b"<html>ya</html>"


class _Archivo:
    """El Worker congreso-archivo, en memoria."""

    def __init__(self, paginas=None, fallidas=()):
        self.paginas = paginas or {}
        self.fallidas = set(fallidas)
        self.pedidas = []

    def __call__(self, ruta, cuerpo=None):
        if ruta == "/pedir":
            self.pedidas += json.loads(cuerpo)
            return 200, b"{}", {}
        clave = ruta.removeprefix("/pagina/")
        if clave in self.paginas:
            contenido, consultado = self.paginas[clave]
            return 200, contenido, {"X-Consultado": consultado}
        return (410, b"estado 404", {}) if clave in self.fallidas else (404, b"pendiente", {})


def _modo_archivo(tmp_path, monkeypatch, archivo):
    monkeypatch.setattr(red, "CACHE", tmp_path)
    monkeypatch.setattr(red, "ARCHIVO", "https://archivo")
    monkeypatch.setattr(red, "PEDIDAS", {})
    monkeypatch.setattr(red, "_api", archivo)
    monkeypatch.setattr(red, "_pedir", lambda u, c: (_ for _ in ()).throw(AssertionError("no debe tocar la red")))


def _clave(url, datos=None):
    return red._ruta(url, datos).name


def test_archivo_sin_la_pagina_la_pide_y_no_toca_la_red(tmp_path, monkeypatch):
    a = _Archivo()
    _modo_archivo(tmp_path, monkeypatch, a)
    datos = {"lola[]": "11", "x": "á"}
    try:
        red.obtener("https://gaceta.diputados.gob.mx/lista", datos)
        assert False, "debió quedar pendiente"
    except red.Pendiente:
        pass
    assert red.enviar_pedidas() == 1
    p = a.pedidas[0]
    import base64, hashlib
    assert p["clave"] == hashlib.sha256(p["texto"].encode()).hexdigest() == _clave(p["url"], datos)
    assert base64.b64decode(p["cuerpo"]) == red._cuerpo(datos) and p["prioridad"] == 1


def test_archivo_copia_vieja_se_usa_y_se_pide_otra(tmp_path, monkeypatch):
    url = "http://sil.gobernacion.gob.mx/a"
    a = _Archivo({_clave(url): (b"<html>vieja</html>", "2020-01-01T00:00:00Z")})
    _modo_archivo(tmp_path, monkeypatch, a)
    r = red.obtener(url)
    assert r.contenido == b"<html>vieja</html>" and r.consultado == "2020-01-01T00:00:00Z"
    red.enviar_pedidas()
    assert [(p["url"], p["prioridad"]) for p in a.pedidas] == [(url, 0)]
    # La copia local queda con la fecha de consulta del archivo.
    assert json.loads(red._ruta(url, None).with_suffix(".json").read_text())["consultado"] == "2020-01-01T00:00:00Z"


def test_archivo_copia_reciente_no_se_pide(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    url = "http://sil.gobernacion.gob.mx/b"
    hoy = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    a = _Archivo({_clave(url): (b"<html>nueva</html>", hoy)})
    _modo_archivo(tmp_path, monkeypatch, a)
    assert red.obtener(url).contenido == b"<html>nueva</html>"
    assert red.enviar_pedidas() == 0


def test_archivo_error_definitivo_de_la_fuente(tmp_path, monkeypatch):
    url = "http://sil.gobernacion.gob.mx/c"
    _modo_archivo(tmp_path, monkeypatch, _Archivo(fallidas={_clave(url)}))
    try:
        red.obtener(url)
        assert False
    except red.Pendiente:
        assert False, "un 404 de la fuente no es pendiente"
    except RuntimeError as e:
        assert "estado 404" in str(e)
