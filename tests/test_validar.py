from congreso import datos, validar


def _repo(tmp_path, **votacion):
    datos.escribir(tmp_path, "organizaciones/senado.json", {"id": "senado"})
    datos.escribir(tmp_path, "organizaciones/partido-pan.json", {"id": "partido-pan"})
    for p in ("ana", "beto"):
        datos.escribir(tmp_path, f"personas/{p}.json", {"id": p})
        datos.escribir(tmp_path, f"mandatos/lxvi/senado/{p}.json", {
            "id": f"m-{p}", "person_id": p, "organization_id": "senado", "legislative_period_id": "lxvi",
            "sources": [{"url": "u"}]})
    v = {"id": "senado-1", "organization_id": "senado", "legislative_period_id": "lxvi", "expediente_id": None,
         "votos_publicados": True, "sources": [{"url": "u"}],
         "votes": [{"voter_id": p, "mandato_id": f"m-{p}", "option": "yes", "grupo_fuente": "PAN",
                    "group_id": "partido-pan"} for p in ("ana", "beto")],
         "counts": [{"option": "yes", "value": 3}],
         "group_results": [{"grupo": "PAN", "yes": 3}]}
    v.update(votacion)
    datos.escribir(tmp_path, "votaciones/lxvi/senado/senado-1.json", v)
    return v


def test_diferencia_sin_declarar_no_pasa_aunque_haya_una_nota(tmp_path):
    _repo(tmp_path, inconsistencias=["2 filas se ligan a la misma persona x; no se atribuyen"])
    errores = validar.validar(tmp_path)
    assert any("difieren de los conteos en {'yes': -1}" in e for e in errores)
    assert any("difieren del resumen por grupo en {'PAN': -1}" in e for e in errores)


def test_diferencia_declarada_exacta_y_explicada_pasa(tmp_path):
    v = _repo(tmp_path, inconsistencias=["yes: 2 en la tabla nominal, 3 en el conteo de la votación"])
    validar.declarar_diferencias(v)
    assert v["diferencia_conteos"] == {"yes": -1} and v["diferencia_grupos"] == {"PAN": -1}
    datos.escribir(tmp_path, "votaciones/lxvi/senado/senado-1.json", v)
    assert validar.validar(tmp_path) == []


def test_diferencia_mal_declarada(tmp_path):
    _repo(tmp_path, inconsistencias=["no cuadra"], diferencia_conteos={"yes": -2}, diferencia_grupos={"PAN": -1})
    assert any("declarado {'yes': -2}" in e for e in validar.validar(tmp_path))


def test_diferencia_sin_explicar(tmp_path):
    _repo(tmp_path, diferencia_conteos={"yes": -1}, diferencia_grupos={"PAN": -1})
    assert any("no dice por qué" in e for e in validar.validar(tmp_path))


def test_cuadra_sin_declarar_nada(tmp_path):
    _repo(tmp_path, counts=[{"option": "yes", "value": 2}], group_results=[{"grupo": "PAN", "yes": 2}])
    assert validar.validar(tmp_path) == []
