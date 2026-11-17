from collections import Counter
from pathlib import Path

from congreso import senado, votaciones_senado

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


def _indice(*nombres):
    return [(Counter(senado.clave_tokens(n)), {"id": f"m{i}", "person_id": n}) for i, n in enumerate(nombres)]


def test_nombre_abreviado_unico():
    idx = _indice("José Gerardo Rodolfo Fernández Noroña", "María Lilly del Carmen Téllez García")
    assert votaciones_senado.mandato("Fernández Noroña, Gerardo", idx)[1] == "nombre abreviado"
    assert votaciones_senado.mandato("Téllez , Lilly", idx)[0]["id"] == "m1"


def test_nombre_abreviado_ambiguo_no_se_liga():
    idx = _indice("Ana María López Pérez", "Ana Sofía López Pérez")
    assert votaciones_senado.mandato("López Pérez, Ana", idx) is None


def _sil(asunto, orden, fecha, denominacion):
    return {"id": f"sil-{asunto}-{orden}", "asunto": asunto, "orden": orden, "start_date": fecha,
            "expediente_id": "sil-1", "motion": {"denominacion": denominacion}}


def test_emparejar_en_orden():
    vs = [dict(senado.votacion(leer(f"votacion_{n}.html")), clave=n) for n in ("5140", "5139")]
    den = ("Con proyecto de decreto por el que reforma y adiciona los artículos 82, 116 y 122 de la Constitución "
           "Política de los Estados Unidos Mexicanos, en materia de nacionalidad única para el ejercicio de la "
           "titularidad de los Poderes Ejecutivos Federal y Locales.")
    sil = [_sil("5146374", 1, "2026-09-29", den), _sil("5146374", 2, "2026-09-29", den),
           _sil("9", 1, "2026-09-29", "Que reforma la Ley de Inversión Extranjera.")]
    e = votaciones_senado.emparejar(vs, sil)
    assert e["5139"]["votacion_sil"] == "sil-5146374-1" and e["5140"]["votacion_sil"] == "sil-5146374-2"


def test_sin_par_en_otra_fecha():
    vs = [dict(senado.votacion(leer("votacion_5139.html")), clave="5139")]
    assert votaciones_senado.emparejar(vs, [_sil("5146374", 1, "2026-09-30", "nacionalidad única")]) == {}
