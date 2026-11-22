from congreso import cotejo
from congreso.votaciones_senado import escribir

FECHA = "2026-10-27"
SENADORES = [f"p{i}" for i in range(10)]


def _votos(en_contra=(), ausentes=()):
    return [{"voter_id": p, "option": "no" if p in en_contra else "absent" if p in ausentes else "yes"}
            for p in SENADORES]


def _cuentas(votos):
    return [{"option": o, "value": sum(1 for x in votos if x["option"] == o)} for o in ("yes", "no", "abstain")]


def _sil(asunto, orden, votos, nominal=True, fecha=FECHA):
    return {"id": f"sil-{asunto}-{orden}", "asunto": asunto, "orden": orden, "start_date": fecha,
            "expediente_id": f"sil-exp-{asunto}", "counts": _cuentas(votos), "votes": votos if nominal else [],
            "motion": {"denominacion": f"Denominación del asunto {asunto} en el SIL.", "text": None}}


def _propia(clave, votos, asunto="Dictamen con otro título.", fecha=FECHA):
    v = {"clave": clave, "orden": int(clave), "fecha": fecha, "asunto": asunto}
    return v, {"id": f"senado-{clave}", "start_date": fecha, "counts": _cuentas(votos), "votes": votos}


def _completar(propias, sil, enlaces=None, publicadas=(), incierta=lambda fecha: False):
    enlaces = {} if enlaces is None else enlaces
    cotejo.completar(enlaces, {v["clave"]: (v, e) for v, e in propias}, list(publicadas), sil, "el Senado", incierta)
    return enlaces


def test_liga_por_cuentas_y_votos_nominales():
    # El título no alcanza la contención, pero es la única votación de cada
    # fuente con esa fecha y esas cuentas y los senadores votan igual.
    votos = _votos(en_contra=("p1", "p2"))
    e = _completar([_propia("1", votos)], [_sil("7", 1, votos), _sil("8", 1, _votos())])
    assert e["1"]["votacion_sil"] == "sil-7-1" and e["1"]["expediente_id"] == "sil-exp-7" and e["1"]["asunto"] == "7"
    assert "votos nominales coinciden" in e["1"]["criterio"]


def test_tolera_dos_legisladores_en_otro_sentido_y_no_mas():
    votos = _votos(en_contra=("p1", "p2"))
    # Mismas cuentas, dos personas cambiadas: lo que el SIL corrige fuera del tablero.
    e = _completar([_propia("1", votos)], [_sil("7", 1, _votos(en_contra=("p1", "p3")))])
    assert e["1"]["votacion_sil"] == "sil-7-1" and e["1"]["criterio"].endswith("salvo en 2")
    # Cuatro personas cambiadas: otra votación con las mismas cuentas.
    assert _completar([_propia("1", votos)], [_sil("7", 1, _votos(en_contra=("p3", "p4")))]) == {}


def test_cuentas_identicas_sin_mas_evidencia_no_ligan():
    # El SIL no publica los votos nominales y nada dice que sea el mismo asunto.
    votos = _votos()
    assert _completar([_propia("1", votos)], [_sil("7", 1, votos, nominal=False)]) == {}


def test_no_liga_si_hay_mas_de_una_candidata():
    votos = _votos()
    # Tres unánimes del SIL el mismo día con las mismas cuentas.
    assert _completar([_propia("1", votos)], [_sil(a, 1, votos) for a in ("7", "8", "9")]) == {}
    # Dos votaciones de la fuente con las mismas cuentas y una sola del SIL.
    assert _completar([_propia("1", votos), _propia("2", votos)], [_sil("7", 1, votos)]) == {}
    # La otra está publicada y esta corrida no la volvió a leer.
    publicada = {"id": "senado-2", "start_date": FECHA, "counts": _cuentas(votos), "votes": votos}
    assert _completar([_propia("1", votos)], [_sil("7", 1, votos)], publicadas=[publicada]) == {}


def test_la_del_sil_que_ya_tiene_par_no_es_candidata():
    votos = _votos()
    sil = [_sil("7", 1, votos), _sil("8", 1, votos)]
    ya = {"2": {"expediente_id": "sil-exp-7", "asunto": "7", "votacion_sil": "sil-7-1", "criterio": "título"}}
    e = _completar([_propia("1", votos), _propia("2", votos)], sil, dict(ya))
    assert e["1"]["votacion_sil"] == "sil-8-1" and e["2"] == ya["2"]
    # También si su par es una votación publicada que no se volvió a leer.
    publicada = {"id": "senado-2", "start_date": FECHA, "counts": _cuentas(votos), "votes": votos,
                 "votacion_sil": "sil-7-1"}
    assert _completar([_propia("1", votos)], sil, publicadas=[publicada])["1"]["votacion_sil"] == "sil-8-1"
    # Si la única del SIL con esas cuentas ya es de otra, no hay candidata.
    assert "1" not in _completar([_propia("1", votos), _propia("2", votos)], sil[:1], dict(ya))


def test_asunto_por_titulo_y_cuentas_cuando_el_orden_no_empareja():
    # El SIL registra tres trámites nominales del asunto y la fuente dos: no
    # se emparejan en orden, pero las cuentas dicen cuál es cuál.
    general, reserva, particular = _votos(), _votos(en_contra=SENADORES[:6]), _votos(en_contra=("p1",))
    sil = [_sil("7", 1, general, nominal=False), _sil("7", 2, reserva, nominal=False),
           _sil("7", 3, particular, nominal=False)]
    titulo = {"expediente_id": "sil-exp-7", "asunto": "7", "criterio": "misma fecha y el asunto del SIL contenido"}
    e = _completar([_propia("1", general), _propia("2", particular)], sil, {"1": dict(titulo), "2": dict(titulo)})
    assert (e["1"]["votacion_sil"], e["2"]["votacion_sil"]) == ("sil-7-1", "sil-7-3")
    assert "mismas cuentas" in e["2"]["criterio"]
    # Si el título la asignó a otro asunto, las cuentas no la mueven.
    otro = {"1": {"expediente_id": "sil-exp-9", "asunto": "9", "criterio": "título"}}
    assert "votacion_sil" not in _completar([_propia("1", general)], [_sil("7", 1, general)], otro)["1"]


def test_la_de_lo_particular_sigue_a_su_hermana_ligada_por_votos():
    # El SIL no lista los votos de lo particular; la fuente le da el mismo
    # asunto y la misma fecha que a la de lo general, ligada por sus votos.
    general, particular = _votos(en_contra=("p1",)), _votos(en_contra=("p1", "p2"))
    sil = [_sil("7", 1, general), _sil("7", 2, particular, nominal=False)]
    e = _completar([_propia("1", general, "Dictamen A."), _propia("2", particular, "Dictamen  A.")], sil)
    assert e["2"]["votacion_sil"] == "sil-7-2" and "senado-1" in e["2"]["criterio"]
    # Con otro asunto en la fuente, o si la del SIL es de otro asunto, no.
    assert "2" not in _completar([_propia("1", general, "Dictamen A."), _propia("2", particular, "Dictamen B.")], sil)
    sil[1] = _sil("8", 1, particular, nominal=False)
    assert "2" not in _completar([_propia("1", general, "Dictamen A."), _propia("2", particular, "Dictamen A.")], sil)


def test_no_liga_en_fechas_con_votaciones_sin_leer():
    votos = _votos()
    assert _completar([_propia("1", votos)], [_sil("7", 1, votos)], incierta=lambda f: f == FECHA) == {}
    # La 5 no se leyó: puede ser de cualquier fecha entre la 4 y la 6.
    incierta = cotejo.inciertas([5], [(3, "2026-10-20"), (4, "2026-10-22"), (6, "2026-10-27"), (7, "2026-10-28")])
    assert [incierta(f) for f in ("2026-10-20", "2026-10-22", "2026-10-27", "2026-10-28")] == [False, True, True, False]
    # Sin vecina posterior, puede ser de cualquier fecha desde la anterior.
    assert cotejo.inciertas([8], [(7, "2026-10-28")])("2027-01-01")
    assert not cotejo.inciertas([], [(7, "2026-10-28")])("2026-10-28")


def test_escribir_liga_por_cuentas_y_cuenta_lo_publicado(tmp_path):
    from congreso import datos
    votos = _votos(en_contra=("p1",))
    sil = _sil("7", 1, _votos(en_contra=("p2",)))
    datos.escribir(tmp_path, "votaciones/lxvi/senado/sil-7-1.json", sil)

    def hacer(leg, v, filas, idx, fuentes):
        return dict(_propia(v["clave"], votos)[1], expediente_id=None, asunto=None)

    leidas = [(_propia("5", votos)[0], [], [])]
    r = escribir(tmp_path, "lxvi", "senado", leidas, {}, [sil], hacer, [], {}, "senado-", None, "el Senado", [("5", 5)])
    e = datos.leer(tmp_path, "votaciones/lxvi/senado/senado-5.json")
    assert (r["ligadas"], r["con_par_sil"], e["votacion_sil"], e["expediente_id"]) == (1, 1, "sil-7-1", "sil-exp-7")
    assert e["discrepancias"] == [{"votacion": "sil-7-1", "votantes_distintos": ["p1", "p2"]}]

    # Una votación listada que no se leyó ni está publicada: su fecha es incierta.
    r = escribir(tmp_path, "lxvi", "senado", leidas, {}, [sil], hacer, [], {}, "senado-", None, "el Senado",
                 [("5", 5), ("6", 6)])
    assert r["ligadas"] == 0 and "votacion_sil" not in datos.leer(tmp_path, "votaciones/lxvi/senado/senado-5.json")

    # Otra publicada con las mismas cuentas y sin par, que no se volvió a leer.
    datos.escribir(tmp_path, "votaciones/lxvi/senado/senado-6.json", dict(_propia("6", votos)[1], expediente_id=None))
    r = escribir(tmp_path, "lxvi", "senado", leidas, {}, [sil], hacer, [], {}, "senado-", None, "el Senado",
                 [("5", 5), ("6", 6)])
    assert r["ligadas"] == 0
