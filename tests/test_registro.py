import pytest

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


class _R:
    contenido, sha256 = b"x", "0" * 64

    def procedencia(self):
        return {"url": "u", "sha256": self.sha256, "consultado": "c"}


def _sil_simulado(monkeypatch, filas):
    from congreso import red, sil
    monkeypatch.setattr(red, "obtener", lambda *a, **k: _R())
    monkeypatch.setattr(sil, "decodificar", lambda c: "")
    monkeypatch.setattr(sil, "resultados_votacion", lambda d: list(filas))
    monkeypatch.setattr(votaciones, "indice_mandatos", lambda r, l: {})
    monkeypatch.setattr(datos, "guardar_fuente", lambda *a, **k: None)
    monkeypatch.setattr(votaciones, "expediente", lambda seg, f: (
        {"id": f"sil-{seg}", "seguimiento": seg, "votaciones": [], "votaciones_economicas": [], "tramites": {},
         "sources": []}, []))
    monkeypatch.setattr(votaciones, "eventos_de_asunto", lambda leg, f, idx: (
        [{"id": f"sil-{f['clave']}-1", "camara": "diputados", "expediente_id": f"sil-{f['seguimiento']}"}], [], []))


def _corrida(tmp_path, filas, por_seg):
    filas[:] = [{"seguimiento": s, "clave": c, "publicado_dof": None, "camara": "x", "fecha": "f"}
                for s, claves in por_seg.items() for c in claves]
    return votaciones.construir(tmp_path, 66)


def test_retiros_semana_a_semana_no_se_acumulan(tmp_path, monkeypatch):
    filas = []
    _sil_simulado(monkeypatch, filas)
    vivos = {str(1000 + i): [str(1000 + i) + "0"] for i in range(60)}
    _corrida(tmp_path, filas, vivos)
    for _ in range(3):
        for s in list(vivos)[-3:]:
            del vivos[s]
        r = _corrida(tmp_path, filas, vivos)
        assert r["retirados_de_la_fuente"] == 3 and r["errores"] == []


def test_dictamen_que_sale_del_expediente_se_marca(tmp_path, monkeypatch):
    filas = []
    _sil_simulado(monkeypatch, filas)
    _corrida(tmp_path, filas, {"5": ["51", "52"]})
    _corrida(tmp_path, filas, {"5": ["51"]})
    assert "retirada_de_la_fuente" in datos.leer(tmp_path, "votaciones/lxvi/diputados/sil-52-1.json")
    assert "retirada_de_la_fuente" not in datos.leer(tmp_path, "votaciones/lxvi/diputados/sil-51-1.json")


def test_muchas_ausencias_de_golpe_no_se_marcan(tmp_path):
    for i in range(20):
        datos.escribir(tmp_path, f"votaciones/lxvi/senado/senado-{i}.json", {"id": f"senado-{i}"})
    errores = []
    r = escribir(tmp_path, "lxvi", "senado", [], {}, [], None, errores, {}, "senado-", {"senado-0"})
    assert r["retiradas_de_la_fuente"] == 0 and "no se marcan" in errores[0]


def test_sil_dos_filas_de_la_misma_persona_no_se_atribuyen():
    votos = [{"camara": "diputados", "nombre": "Juan Pérez López", "fuente_nombre": "Dip. Juan Pérez López",
              "partido": "PAN", "opcion": "yes"},
             {"camara": "diputados", "nombre": "Juan Perez Lopez", "fuente_nombre": "Dip. Juan Perez Lopez",
              "partido": "PAN", "opcion": "no"}]
    indice = {("diputados", votaciones.clave_nombre("Juan Pérez López")): [{"id": "m1", "person_id": "p1"}]}
    salida, sin_ligar, inconsistencias = votaciones.atribuir(votos, indice, {"diputados"})
    assert salida == [] and len(sin_ligar) == 2 and "misma persona p1" in inconsistencias[0]


def test_grupo_desconocido_no_impide_publicar_el_voto():
    votos = [{"camara": "diputados", "nombre": "Ana", "fuente_nombre": "Dip. Ana", "partido": "XYZ", "opcion": "yes"}]
    indice = {("diputados", "ana"): [{"id": "m1", "person_id": "p1"}]}
    salida, _, inconsistencias = votaciones.atribuir(votos, indice, {"diputados"})
    assert salida[0]["group_id"] is None and "XYZ" in inconsistencias[0]


def test_busqueda_que_no_cabe_en_una_pagina_se_pide_por_anio_legislativo(monkeypatch):
    """El buscador da a lo más 999 filas: una legislatura con más se arma de
    sus años, y tiene que sumar lo que dice la búsqueda completa."""
    por_tramo = {"": ([{"clave": "1"}], 5), "29/08/2021": ([], None), "01/09/2021": ([{"clave": "1"}, {"clave": "2"}], 2),
                 "01/09/2022": ([{"clave": "3"}], 1), "01/09/2023": ([{"clave": "4"}, {"clave": "5"}], 2)}
    pedidos = []

    def buscar(legislatura, desde="", hasta=""):
        pedidos.append((desde, hasta))
        filas, dice = por_tramo[desde]
        return filas, dice, {"url": desde}

    monkeypatch.setattr(votaciones, "_buscar", buscar)
    filas, procedencia = votaciones.dictamenes_votados(65)
    assert sorted(f["clave"] for f in filas) == ["1", "2", "3", "4", "5"]
    assert pedidos[1:] == [("29/08/2021", "31/08/2021"), ("01/09/2021", "31/08/2022"),
                           ("01/09/2022", "31/08/2023"), ("01/09/2023", "31/08/2024")]
    assert procedencia == {"url": ""}

    por_tramo["01/09/2023"] = ([{"clave": "4"}], 1)
    with pytest.raises(RuntimeError, match="sus años suman 4"):
        votaciones.dictamenes_votados(65)
