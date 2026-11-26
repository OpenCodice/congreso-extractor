import json
from pathlib import Path

import pytest

from congreso import cronologia, datos, red, validar

FIXTURES = Path(__file__).parent / "fixtures" / "leyesbiblio"
REF = cronologia.BASE + "ref/"


def _leer(nombre):
    return cronologia.leer(cronologia.decodificar((FIXTURES / nombre).read_bytes()), REF + nombre)


def test_ley_con_decretos_escaneados_y_fe_de_erratas():
    r = _leer("lft.htm")
    assert [d["numero"] for d in r["decretos"]] == list(range(1, 55))
    assert r["original"]["fecha"] == "1970-04-01" and r["original"]["escaneado"]
    assert [(p["fecha"], p.get("etiqueta")) for p in r["original"]["publicaciones"]] == [
        ("1970-04-01", None), ("1970-04-30", "Fe de erratas"), ("1970-06-05", "Complemento a la fe de erratas")]
    primero, ultimo = r["decretos"][0], r["decretos"][-1]
    assert primero["fecha"] == "1972-04-24" and primero["escaneado"]
    assert primero["publicaciones"][0]["archivos"] == [
        {"formato": "imagen", "url": REF + "lft/LFT_ref01_24abr72_ima.pdf"}]
    assert ultimo["fecha"] == "2026-05-14" and not ultimo["escaneado"]
    assert [a["formato"] for a in ultimo["publicaciones"][0]["archivos"]] == ["pdf", "word"]
    assert ultimo["titulo"].startswith("DECRETO por el que se reforman y adicionan diversas disposiciones de la Ley Federal del Trabajo")


def test_cpeum_lleva_la_fecha_y_los_archivos_en_columnas_propias():
    r = _leer("cpeum_crono.htm")
    assert len(r["decretos"]) == 285
    assert r["original"]["fecha"] == "1917-02-05"
    d = r["decretos"][0]
    assert d["fecha"] == "1921-07-08" and d["escaneado"]
    assert d["titulo"].startswith("DECRETO reformando el artículo 14 transitorio")
    assert d["descripcion"].startswith("Faculta al Congreso para establecer")
    ultimo = r["decretos"][-1]
    assert ultimo["fecha"] == "2026-10-07"
    assert ultimo["publicaciones"][0]["archivos"][0]["url"] == REF + "dof/CPEUM_ref_285_07oct26.pdf"
    assert "Nuevo" not in ultimo.get("descripcion", "")


def test_sentencias_y_otras_secciones_no_se_cuentan_como_decretos():
    r = _leer("cnpp.htm")
    assert [d["numero"] for d in r["decretos"]] == list(range(1, 14))
    sentencias = [o for o in r["otras"] if o.get("clase") == "Sentencia de la SCJN"]
    assert len(sentencias) == 2 and all("numero" not in s for s in sentencias)
    # «| Notificación para efectos legales 25/11/2022 | DOF 20/08/2025 | Word |»
    s = next(s for s in sentencias if "130/2019" in s["titulo"])
    assert s["fecha"] == "2025-08-20"
    assert [(p["fecha"], p.get("etiqueta"), len(p["archivos"])) for p in s["publicaciones"]] == [
        ("2022-11-25", "Notificación para efectos legales", 1), ("2025-08-20", None, 2)]
    declaratorias = [o for o in r["otras"] if o.get("seccion")]
    assert len(declaratorias) == 6
    assert {o["seccion"] for o in declaratorias} == {"Declaratorias de Entrada en Vigor a nivel federal"}


def test_publicacion_en_varios_dias():
    original = _leer("oga.htm")["original"]
    assert original["fecha"] == "1912-01-01"
    assert original["publicaciones"] == [{"fecha": "1912-01-01", "fecha_fin": "1912-01-08", "archivos": []}]


def test_numeracion_con_huecos_no_se_lee():
    pagina = cronologia.decodificar((FIXTURES / "lft.htm").read_bytes())
    assert pagina.count(">30</span>") == 1
    with pytest.raises(ValueError, match="numeración no corrida"):
        cronologia.leer(pagina.replace(">30</span>", ">31</span>"), REF + "lft.htm")


def test_paginas_del_indice():
    indice = cronologia.decodificar((FIXTURES / "index.htm").read_bytes())
    documentos = [{"clave": "lft", "url": cronologia.BASE + "pdf/LFT.pdf"},
                  {"clave": "cnpp", "url": cronologia.BASE + "pdf/CNPP.pdf"},
                  {"clave": "ajena", "url": "https://www.sat.gob.mx/rmf.pdf"}]
    assert cronologia.paginas(indice, documentos) == {
        "cpeum": "ref/cpeum_crono.htm", "lft": "ref/lft.htm", "cnpp": "ref/cnpp.htm"}


def _repos(tmp_path):
    repos = tmp_path / "repos"
    (repos / "leyes-federales" / "metadata" / "lft").mkdir(parents=True, exist_ok=True)
    (repos / "leyes-federales" / "fuentes.json").write_text(json.dumps({"documentos": [
        {"clave": "lft", "etiqueta": "Ley Federal del Trabajo", "url": cronologia.BASE + "pdf/LFT.pdf"}]}))
    (repos / "leyes-federales" / "metadata" / "lft" / "reformas.json").write_text(
        json.dumps({"1970-04-30": [], "2026-05-14": [], "1999-09-09": []}))
    return repos


def _red(monkeypatch, faltan=()):
    def obtener(url, vigencia_horas=0):
        nombre = url.rsplit("/", 1)[-1]
        if nombre in faltan:
            raise red.Pendiente(url)
        contenido = (FIXTURES / nombre).read_bytes()
        return red.Respuesta(url, contenido, "2026-11-26T00:00:00Z", "0" * 64)
    monkeypatch.setattr(red, "obtener", obtener)


def test_construir_escribe_un_registro_por_documento_y_coteja_las_notas(tmp_path, monkeypatch):
    _red(monkeypatch)
    raiz = tmp_path / "datos"
    r = cronologia.construir(raiz, _repos(tmp_path))
    assert r["documentos"] == 2 and r["errores"] == [] and r["escritos"] == 2
    lft = datos.leer(raiz, "cronologia/lft.json")
    assert lft["nombre"] == "Ley Federal del Trabajo" and len(lft["decretos"]) == 54
    # La fe de erratas del original está en la lista; el 1999-09-09 no.
    assert lft["notas_sin_decreto"] == ["1999-09-09"]
    assert lft["sources"][0]["url"] == REF + "lft.htm"
    assert [e for e in validar.validar(raiz) if "cronología" in e] == []
    # Volver a correr no cambia nada.
    assert cronologia.construir(raiz, _repos(tmp_path))["escritos"] == 0


def test_una_pagina_pendiente_no_borra_ni_detiene_las_demas(tmp_path, monkeypatch):
    _red(monkeypatch, faltan={"lft.htm"})
    raiz = tmp_path / "datos"
    datos.escribir(raiz, "cronologia/lft.json", {"documento": "lft"})
    r = cronologia.construir(raiz, _repos(tmp_path))
    assert r["pendientes_de_descarga"] == 1 and r["documentos"] == 1
    assert datos.leer(raiz, "cronologia/lft.json") == {"documento": "lft"}
    assert datos.leer(raiz, "cronologia/cpeum.json")["decretos"][-1]["numero"] == 285


def test_validar_rechaza_una_numeracion_con_huecos(tmp_path):
    datos.escribir(tmp_path, "cronologia/x.json", {
        "documento": "x", "sources": [{"url": "u"}], "original": None, "otras": [],
        "decretos": [{"numero": 2, "titulo": "t", "fecha": "2020-01-01",
                      "publicaciones": [{"fecha": "2020-01-01", "archivos": []}]}]})
    assert any("numeración" in e for e in validar.validar(tmp_path))
