import json
from pathlib import Path

import pytest

from congreso import gaceta, lecturas, red, senado

FIX = Path(__file__).parent / "fixtures"


def _r(ruta: Path, url="https://x/y"):
    c = ruta.read_bytes()
    import hashlib
    return red.Respuesta(url, c, "2026-11-17T00:00:00Z", hashlib.sha256(c).hexdigest())


def _gaceta():
    pagina = (FIX / "gaceta" / "lista_1or1_evento31.html").read_bytes()
    tabla = gaceta.tabla(gaceta.decodificar((FIX / "gaceta" / "tabla1or1-31.html").read_bytes()))
    fallo = {"fuente": "gaceta", "tipo": "lista", "clave": "1or1-31", "contexto": {"conteos": tabla["conteos"]}}
    return fallo, pagina, gaceta.lista(gaceta.decodificar(pagina))


def test_lectura_fiel_de_la_gaceta_pasa():
    fallo, pagina, filas = _gaceta()
    assert lecturas.verificar(fallo, pagina, filas) == []


def test_nombre_cambiado_o_voto_movido_no_pasa():
    fallo, pagina, filas = _gaceta()
    otro = [dict(f) for f in filas]
    otro[0]["nombre"] = "Pérez Inventado Juan"
    assert any("no está en la página" in x for x in lecturas.verificar(fallo, pagina, otro))
    movido = [dict(f) for f in filas]
    i = next(k for k, f in enumerate(movido) if f["opcion"] == "yes")
    movido[i]["opcion"] = "no"
    assert any("en la lectura" in x for x in lecturas.verificar(fallo, pagina, movido))


def test_senado_votacion_y_tabla():
    pv = (FIX / "senado" / "votacion_5139.html").read_bytes()
    pt = (FIX / "senado" / "tabla_5139.html").read_bytes()
    v = senado.votacion(senado.decodificar(pv))
    t = senado.tabla(senado.decodificar(pt))
    assert lecturas.verificar({"fuente": "senado", "tipo": "votacion", "contexto": {
        "conteo_tabla": {"yes": 86, "no": 42, "abstain": 0}}}, pv, v) == []
    assert lecturas.verificar({"fuente": "senado", "tipo": "tabla", "contexto": {"conteos": v["conteos"]}}, pt, t) == []
    inflado = dict(v, conteos=dict(v["conteos"], yes=87))
    assert lecturas.verificar({"fuente": "senado", "tipo": "votacion", "contexto": {
        "conteo_tabla": {"yes": 86, "no": 42, "abstain": 0}}}, pv, inflado)


def test_fallo_se_guarda_y_la_lectura_verificada_se_usa(tmp_path, monkeypatch):
    monkeypatch.setenv("CONGRESO_FALLOS", str(tmp_path / "fallos"))
    registro = tmp_path / "repo" / "lecturas"
    monkeypatch.setitem(lecturas.PARSERS, ("gaceta", "lista"),
                        (gaceta.decodificar, lambda d: (_ for _ in ()).throw(ValueError("frase nueva"))))
    fallo, pagina, filas = _gaceta()
    r = _r(FIX / "gaceta" / "lista_1or1_evento31.html")
    with pytest.raises(lecturas.SinLectura):
        lecturas.leer("gaceta", "lista", "1or1-31", r, fallo["contexto"], registro)
    d = tmp_path / "fallos" / r.sha256
    assert json.loads((d / "fallo.json").read_text())["error"] == "ValueError: frase nueva"
    (d / "propuesta.json").write_text(json.dumps({"datos": filas}))
    assert lecturas.verificar_fallos(tmp_path / "fallos", registro)["aceptadas"] == ["gaceta lista 1or1-31"]
    datos, lectura = lecturas.leer("gaceta", "lista", "1or1-31", r, fallo["contexto"], registro)
    assert datos == filas and lectura["por"] == "agente"


def test_no_legible_se_rechaza(tmp_path):
    d = tmp_path / "abc"
    d.mkdir()
    (d / "fallo.json").write_text(json.dumps({"fuente": "senado", "tipo": "tabla", "clave": "1", "sha256": "abc",
                                              "url": "u", "error": "e"}))
    (d / "pagina.html").write_bytes(b"<html>Request unsuccessful</html>")
    (d / "propuesta.json").write_text(json.dumps({"no_legible": "es una página de bloqueo"}))
    r = lecturas.verificar_fallos(tmp_path, tmp_path / "registro")
    assert r["aceptadas"] == [] and "no la pudo leer" in r["rechazadas"][0]
