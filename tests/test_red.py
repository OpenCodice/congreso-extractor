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
