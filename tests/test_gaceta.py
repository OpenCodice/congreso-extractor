from collections import Counter
from pathlib import Path

from congreso import cotejo, gaceta
from congreso.votaciones_gaceta import evento

FIX = Path(__file__).parent / "fixtures" / "gaceta"


def leer(nombre: str) -> str:
    return gaceta.decodificar((FIX / nombre).read_bytes())


def test_periodos_publicados():
    p = gaceta.periodos(leer("gp_votaciones.html"))
    assert p[0].endswith("/vot66_a1primero.html") and p[-1].endswith("/vot66_a3primero.html")
    assert len(p) == 7


def test_periodo_da_general_y_particular():
    vs = {x["tabla"]: x for x in gaceta.periodo(leer("vot66_a3primero.html"))}
    g, p = vs["tabla3or1-3"], vs["tabla3or1-4"]
    assert g["fecha_sesion"] == p["fecha_sesion"] == "2026-09-22"
    assert "82, 116 y 122" in g["asunto"] and g["asunto"] == p["asunto"]
    assert p["descripcion"] == "En lo particular los artículos reservados, en términos del dictamen."


def test_tabla_conteos_por_grupo():
    t = gaceta.tabla(leer("tabla3or1-3.html"))
    assert (t["accion"], t["evento"], t["fecha"]) == ("/voto66/ordi31/lanordi31.php3", "3", "2026-09-22")
    # La tabla dice 344; el texto del periodo, 334 (errata de la Gaceta).
    assert t["conteos"]["Total"] == {"yes": 344, "no": 116, "abstain": 1, "not voting": 0, "absent": 38}
    assert t["conteos"]["PAN"]["no"] == 59
    assert gaceta.tabla(leer("tabla3or1-4.html"))["conteos"]["Total"]["yes"] == 334


def test_lista_con_varios_sentidos():
    filas = gaceta.lista(leer("lista_3or1_evento3_contra.html"))
    assert Counter(f["opcion"] for f in filas) == {"no": 116, "abstain": 1, "absent": 38}
    assert {"grupo": "PAN", "opcion": "absent", "nombre": "Anaya Llamas José Guillermo"} in filas


def test_datos_lista_pide_todos_los_sentidos():
    assert gaceta.datos_lista("3") == {"evento": "3", "lola[11]": "1", "lola[12]": "1", "lola[13]": "1",
                                       "lola[14]": "1", "lola[15]": "1"}


class _Indice:
    def buscar(self, nombre):
        return {"id": f"m-{nombre}", "person_id": nombre}, "nombre"


def _v(tabla_html):
    t = gaceta.tabla(leer(tabla_html))
    return dict(t, clave="3or1-3", orden=0, descripcion="", asunto=t["titulo"])


def test_evento_cuadra_con_la_tabla():
    filas = gaceta.lista(leer("lista_3or1_evento3_favor.html")) + gaceta.lista(leer("lista_3or1_evento3_contra.html"))
    e = evento("lxvi", _v("tabla3or1-3.html"), filas, _Indice(), [])
    assert len(e["votes"]) == 499 and e["counts"][0] == {"option": "yes", "value": 344}


def test_evento_con_lista_incompleta_se_publica_con_inconsistencias():
    filas = gaceta.lista(leer("lista_3or1_evento3_contra.html"))
    e = evento("lxvi", _v("tabla3or1-3.html"), filas, _Indice(), [])
    assert len(e["votes"]) == 155 and "Total yes: 0 en la lista, 344 en la tabla" in e["inconsistencias"]
    assert e["counts"][0] == {"option": "yes", "value": 344}
    assert e["diferencia_conteos"] == {"yes": -344}


class _IndiceRepetido:
    def buscar(self, nombre):
        return {"id": "m-x", "person_id": "x"}, "nombre"


def test_dos_filas_de_la_misma_persona_no_se_atribuyen():
    filas = gaceta.lista(leer("lista_3or1_evento3_favor.html"))[:2]
    votos, sin_mandato, inconsistencias = cotejo.votos(filas, _IndiceRepetido())
    assert votos == [] and sin_mandato == filas and "misma persona x" in inconsistencias[0]
