from congreso import datos, votaciones
from congreso.votaciones_senado import escribir


def test_retiro_se_marca_y_no_se_borra(tmp_path):
    datos.escribir(tmp_path, "votaciones/lxvi/senado/senado-1.json", {"id": "senado-1", "votes": [1]})
    datos.escribir(tmp_path, "votaciones/lxvi/senado/senado-2.json", {"id": "senado-2"})
    r = escribir(tmp_path, "lxvi", "senado", [], {}, [], None, [], {}, "senado-", {"senado-2"})
    assert r["retiradas_de_la_fuente"] == 1
    v = datos.leer(tmp_path, "votaciones/lxvi/senado/senado-1.json")
    assert v["votes"] == [1] and "detectada" in v["retirada_de_la_fuente"]
    assert "retirada_de_la_fuente" not in datos.leer(tmp_path, "votaciones/lxvi/senado/senado-2.json")
    # Se marca una vez: la fecha es la del primer aviso.
    assert not datos.marcar_retirada(tmp_path, "votaciones/lxvi/senado/senado-1.json", "2099-01-01")


def test_sin_listado_completo_no_se_marca_nada(tmp_path):
    datos.escribir(tmp_path, "votaciones/lxvi/senado/senado-1.json", {"id": "senado-1"})
    r = escribir(tmp_path, "lxvi", "senado", [], {}, [], None, [], {}, "senado-", None)
    assert r["retiradas_de_la_fuente"] == 0


def test_votaciones_economicas_del_dictamen():
    fila = {"clave": "5070192", "camara": "Cámara de Diputados", "fecha": "2026-04-15"}
    tramites = [{"tipo": "Votación económica", "texto": "Aprobado considerar suficientemente discutido."},
                {"tipo": "Votación nominal", "texto": "Aprobado en lo general.", "conteos": {}},
                {"tipo": "Votación económica", "texto": "Desechada la propuesta de modificación."}]
    assert votaciones.economicas(fila, tramites) == [
        {"asunto": "5070192", "camara": "diputados", "fecha": "2026-04-15",
         "texto": "Aprobado considerar suficientemente discutido.", "result": "pass"},
        {"asunto": "5070192", "camara": "diputados", "fecha": "2026-04-15",
         "texto": "Desechada la propuesta de modificación.", "result": "fail"}]
