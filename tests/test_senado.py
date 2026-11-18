from collections import Counter
from pathlib import Path

from congreso import cotejo, nombres, senado

FIX = Path(__file__).parent / "fixtures" / "senado"


def leer(nombre: str) -> str:
    return senado.decodificar((FIX / nombre).read_bytes())


def test_listado_de_la_legislatura():
    l = senado.listado(leer("votaciones_lxvi.html"))
    assert len(l) == 439 and len({x["clave"] for x in l}) == 439
    p = next(x for x in l if x["clave"] == "5140")
    assert "82, 116 y 122" in p["asunto"] and p["motion"].startswith("VOTACIÓN EN LO PARTICULAR")


def test_votacion_general_y_particular():
    g = senado.votacion(leer("votacion_5139.html"))
    p = senado.votacion(leer("votacion_5140.html"))
    assert g["fecha"] == p["fecha"] == "2026-09-29"
    assert g["motion"] == "VOTACIÓN EN LO GENERAL Y LOS ARTÍCULOS NO RESERVADOS"
    assert g["asunto"].startswith("Dictamen de las Comisiones Unidas de Puntos Constitucionales")
    # El Senado da 86-42 en lo particular; el SIL, 86-43.
    assert p["conteos"] == {"yes": 86, "no": 42, "abstain": 0}


def test_tabla_cuadra_con_los_conteos():
    t = senado.tabla(leer("tabla_5139.html"))
    assert len(t) == 128
    assert Counter(x["opcion"] for x in t) == {"yes": 86, "no": 42}
    assert t[0] == {"numero": 1, "senado_id": "1579", "nombre": "Aguilar Castillo, Heriberto Marcelo",
                    "grupo": "MORENA", "opcion": "yes"}


def _indice(*nombres_):
    personas = {n: {"name": n} for n in nombres_}
    return nombres.Indice([{"id": f"m{i}", "person_id": n} for i, n in enumerate(nombres_)], personas)


def test_nombre_abreviado_unico():
    idx = _indice("José Gerardo Rodolfo Fernández Noroña", "María Lilly del Carmen Téllez García")
    assert idx.buscar("Fernández Noroña, Gerardo")[1] == "nombre abreviado"
    assert idx.buscar("Téllez , Lilly")[0]["id"] == "m1"


def test_nombre_abreviado_ambiguo_no_se_liga():
    idx = _indice("Ana María López Pérez", "Ana Sofía López Pérez")
    assert idx.buscar("López Pérez, Ana") is None


def test_variantes_de_la_gaceta():
    idx = _indice("Ivonne Aracely Ortega Pacheco", "J. Jesús Jiménez", "Alonso de Jesús Vázquez Jiménez",
                  "Dulce María Corina Villegas Guarneros", "Arturo Ávila Anaya")
    assert idx.buscar("Ortega Pacheco Ivonne Aracelly") == ({"id": "m0", "person_id": "Ivonne Aracely Ortega Pacheco"},
                                                            "nombre (variante ortográfica)")
    assert idx.buscar("Jiménez J. Jesús")[0]["id"] == "m1"
    assert idx.buscar("Villegas Guarneros Dulce Ma. Corina")[1] == "nombre"
    assert idx.buscar("Avila Anaya Francisco Arturo F.")[1] == "nombre ampliado"


def _sil(asunto, orden, fecha, denominacion):
    return {"id": f"sil-{asunto}-{orden}", "asunto": asunto, "orden": orden, "start_date": fecha,
            "expediente_id": "sil-1", "motion": {"denominacion": denominacion}}


def test_emparejar_en_orden():
    vs = [dict(senado.votacion(leer(f"votacion_{n}.html")), clave=n, orden=int(n)) for n in ("5140", "5139")]
    den = ("Con proyecto de decreto por el que reforma y adiciona los artículos 82, 116 y 122 de la Constitución "
           "Política de los Estados Unidos Mexicanos, en materia de nacionalidad única para el ejercicio de la "
           "titularidad de los Poderes Ejecutivos Federal y Locales.")
    sil = [_sil("5146374", 1, "2026-09-29", den), _sil("5146374", 2, "2026-09-29", den),
           _sil("9", 1, "2026-09-29", "Que reforma la Ley de Inversión Extranjera.")]
    e = cotejo.emparejar(vs, sil, "el Senado")
    assert e["5139"]["votacion_sil"] == "sil-5146374-1" and e["5140"]["votacion_sil"] == "sil-5146374-2"


def test_sin_par_en_otra_fecha():
    vs = [dict(senado.votacion(leer("votacion_5139.html")), clave="5139", orden=5139)]
    assert cotejo.emparejar(vs, [_sil("5146374", 1, "2026-09-30", "nacionalidad única")], "el Senado") == {}


def test_presupuesto_agotado_deja_el_resto_sin_retirar(tmp_path, monkeypatch):
    from congreso import red, senado, votaciones_senado
    monkeypatch.setattr(votaciones_senado, "PRESUPUESTO", -1)
    monkeypatch.setattr(red, "obtener", lambda *a, **k: red.Respuesta("u", b"", "2026-11-18T00:00:00Z", "0"))
    monkeypatch.setattr(senado, "listado", lambda html: [{"clave": "1"}, {"clave": "2"}])
    r = votaciones_senado.construir(tmp_path, 66)
    assert r["votaciones"] == 0 and r["retiradas_de_la_fuente"] == 0
    assert any("quedan 2 votaciones" in e for e in r["errores"])


def test_votaciones_pendientes_de_descarga_no_se_retiran(tmp_path, monkeypatch):
    from congreso import datos, red, senado, votaciones_senado
    listado = senado.url_listado(66, "LXVI")

    def obtener(url, *a, **k):
        if url == listado:
            return red.Respuesta(url, b"", "2026-11-18T00:00:00Z", "0")
        raise red.Pendiente(url)
    monkeypatch.setattr(red, "obtener", obtener)
    monkeypatch.setattr(senado, "listado", lambda html: [{"clave": "1"}, {"clave": "2"}])
    datos.escribir(tmp_path, "votaciones/lxvi/senado/senado-1.json", {"id": "senado-1"})
    r = votaciones_senado.construir(tmp_path, 66)
    assert r["pendientes_de_descarga"] == 2 and r["retiradas_de_la_fuente"] == 0 and not r["errores"]
    assert "retirada_de_la_fuente" not in datos.leer(tmp_path, "votaciones/lxvi/senado/senado-1.json")
