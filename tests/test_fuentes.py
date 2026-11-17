from collections import Counter
from pathlib import Path

from congreso import catalogos, decretos, dof, sil

FIX = Path(__file__).parent / "fixtures"


def html(nombre: str) -> str:
    return sil.decodificar((FIX / "sil" / nombre).read_bytes())


def test_padron_diputados():
    filas = sil.padron(html("legisladores_dip_66_todos.html"))
    assert len(filas) == 580
    yerico = next(f for f in filas if f["referencia"] == "9228260")
    assert yerico["nombre_partes"] == ["Yerico", "Abramo", "Masso"]
    assert yerico["partido"] == "PRI" and yerico["entidad"] == "Coahuila"
    assert yerico["protesta"] == "2024-08-29" and yerico["calidad"] == "Propietario"
    assert Counter(f["calidad"].rstrip("a").rstrip("o") for f in filas)["Suplente"] == 85


def test_padron_senado_primera_minoria_y_rp_sin_entidad():
    filas = sil.padron(html("legisladores_sen_66_todos.html"))
    assert len(filas) == 203
    assert Counter(f["principio"] for f in filas)["Primera Minoría"] == 52
    assert all(f["entidad"] is None for f in filas if f["principio"] == "Representación Proporcional")


def test_todas_las_etiquetas_conocidas():
    for nombre in ("legisladores_dip_66_todos.html", "legisladores_sen_66_todos.html"):
        for f in sil.padron(html(nombre)):
            catalogos.partido(f["partido"])
            assert f["entidad"] is None or catalogos.entidad(f["entidad"]), f["entidad"]


def test_perfil_con_baja_y_distrito():
    p = sil.perfil(html("perfil_9228248.html"))
    assert p["estatus"].startswith("Baja por deceso")
    assert p["distrito"] == {"numero": 18, "cabecera": "Zongolica"}
    assert p["suplente"]["referencia"] == "9228249"
    assert p["licencias"][0]["inicio"] == "2024-12-09"
    assert p["licencias"][0]["en_funciones"] == "Suplente"
    assert len(p["comisiones"]) == 3


def test_perfil_estatus_comentado():
    # El SIL comenta el estatus de los activos; sigue siendo el dato oficial.
    assert sil.perfil(html("perfil_9228260.html"))["estatus"] == "Activo(a)"


def test_votos_cuadran_con_el_resumen():
    for votos, detalle in (("piloto_votos_nominales_dip_5135887.html", "piloto_votacion_dip_5135887.html"),
                           ("piloto_votos_nominales_sen_5146374.html", "piloto_votacion_sen_5146374.html")):
        v = sil.votos(html(votos))
        d = sil.detalle_votacion(html(detalle))
        c = Counter(x["opcion"] for x in v)
        assert (c["yes"], c["no"], c["abstain"]) == (d["general"]["yes"], d["general"]["no"], d["general"]["abstain"])
        total = next(g for g in d["grupos"] if g["grupo"] == "Total")
        assert len(v) == total["total"] and c["absent"] == total["absent"]
        assert d["tramite"]


def test_tramites_dos_nominales():
    t = sil.tramites(html("piloto_tramites_5135887.html"))
    nominales = [x["conteos"] for x in t if "conteos" in x]
    assert nominales == [{"yes": 344, "no": 116, "abstain": 1}, {"yes": 334, "no": 109, "abstain": 1}]
    assert sum(1 for x in t if x["tipo"] == "Votación económica") > 20


def test_historial_y_seguimiento():
    asuntos = sil.historial(html("piloto_historial_5135887.html"))
    assert [a["clave"] for a in asuntos][:3] == ["5119840", "4999620", "5120255"]
    assert asuntos[-2]["tipo"] == "Declaratoria de reforma constitucional"
    s = sil.seguimiento(html("piloto_seguimiento_5128211.html"))
    assert s["camara_origen"] == "Cámara de Diputados"
    assert s["cronologia"][-1] == {"estatus": "Publicado en DOF", "fecha": "2026-10-07"}


def test_resultados_votacion():
    r = sil.resultados_votacion(html("votacion_busqueda_dip_sep_nov_2026_p999.html"))
    assert r and all(x["clave"] and x["seguimiento"] for x in r)
    piloto = next(x for x in r if x["clave"] == "5135887")
    assert piloto["seguimiento"] == "5128211" and piloto["publicado_dof"] == "2026-10-07"


def test_legislaturas_de_la_declaratoria():
    exp = {"asuntos": sil.historial(html("piloto_historial_5135887.html"))}
    aspectos = sil.seguimiento(html("piloto_seguimiento_declaratoria_5151086.html"))["aspectos_relevantes"]
    leg = decretos.legislaturas_aprobatorias(exp, aspectos)
    assert leg["votos_aprobatorios"] == 22 and len(leg["aprobaron"]) == 22
    assert {"edomex", "cdmx", "michoacan", "veracruz", "baja-california"} <= set(leg["aprobaron"])
    assert "baja-california-sur" not in leg["aprobaron"]


def test_legislaturas_no_cuadran_no_se_afirman():
    exp = {"asuntos": sil.historial(html("piloto_historial_5135887.html"))}
    texto = "Se realiza declaratoria con el escrutinio de veintitres votos aprobatorios remitidos por los congresos de Jalisco y Sonora."
    assert decretos.legislaturas_aprobatorias(exp, texto) is None


def test_entidades_variantes():
    assert decretos.entidades_en("congresos de Querétaro de Arteaga y del Estado de México, remiten") == ["edomex", "queretaro"]
    assert decretos.entidades_en("Sonora, Yucatán, y Zacatecas, así como de la Ciudad de México") == ["cdmx", "sonora", "yucatan", "zacatecas"]
    assert decretos.entidades_en("Baja California Sur y Baja California") == ["baja-california", "baja-california-sur"]


NOMBRES = {"cpeum": "Constitución Política de los Estados Unidos Mexicanos",
           "lgs": "Ley General de Salud", "lgsm": "Ley General de Salud Mental",
           "lft": "Ley Federal del Trabajo"}


def test_decreto_cpeum():
    notas = dof.sumario((FIX / "dof" / "sidof_api_notas_07-10-2026.json").read_bytes(), "2026-10-07")
    c = dof.candidatos(notas, "cpeum", NOMBRES)
    assert [(n.codigo, n.edicion) for n in c] == [(5800617, "VES")]


def test_dos_decretos_el_mismo_dia():
    notas = dof.sumario((FIX / "dof" / "sidof_api_notas_15-01-2026.json").read_bytes(), "2026-01-15")
    assert {n.codigo for n in dof.candidatos(notas, "lgs", NOMBRES)} == {5778297, 5778298}


def test_reglamentos_y_estimulos_no_son_reforma_de_la_ley():
    assert dof.menciones("DECRETO por el que se reforma el Reglamento de la Ley General de Salud en Materia de Publicidad", NOMBRES) == set()
    assert not dof.es_decreto("Decreto por el que se otorgan estímulos fiscales en materia de la Ley General de Salud")


def test_votos_traen_camara():
    v = sil.votos(html("piloto_votos_nominales_sen_5146374.html"))
    assert {x["camara"] for x in v} == {"senado"}


def test_nombre_contenido_en_otro():
    assert dof.menciones("Decreto por el que se reforma la Ley General de Salud Mental.", NOMBRES) == {"lgsm"}
    assert dof.menciones("Decreto que reforma la Ley General de Salud y la Ley Federal del Trabajo", NOMBRES) == {"lgs", "lft"}
    assert not dof.es_decreto("Fe de erratas al Decreto por el que se reforma la Ley General de Salud")


def test_lista_incompleta_se_declara():
    # El resumen cuenta 21 senadores del PAN; la lista nominal trae 20.
    from congreso import votaciones
    v = sil.votos(html("votos_nominales_sen_4820033.html"))
    d = sil.detalle_votacion(html("votacion_sen_4820033.html"))
    assert votaciones.faltantes_en_lista(v, d) == ([{"grupo": "PAN", "option": "yes", "value": 1}], [])


def test_lista_completa_sin_faltantes():
    from congreso import votaciones
    v = sil.votos(html("piloto_votos_nominales_dip_5135887.html"))
    d = sil.detalle_votacion(html("piloto_votacion_dip_5135887.html"))
    assert votaciones.faltantes_en_lista(v, d) == ([], [])


def test_lista_con_votos_de_mas_se_publica_con_inconsistencias():
    from congreso import votaciones
    v = sil.votos(html("votos_nominales_sen_4820033.html"))
    d = sil.detalle_votacion(html("votacion_sen_4820033.html"))
    v += [dict(v[0], nombre="Nadie Ninguno", fuente_nombre="Sen. Nadie Ninguno", partido="PAN", opcion="no")]
    faltan, inconsistencias = votaciones.faltantes_en_lista(v, d)
    assert faltan == [{"grupo": "PAN", "option": "yes", "value": 1}]
    assert inconsistencias == ["PAN no: 1 en la lista, 0 en el resumen"]


def test_nombre_sin_mandato_se_declara_con_su_nombre():
    from congreso import votaciones
    v = sil.votos(html("votos_nominales_sen_4820033.html"))
    indice = {("senado", votaciones.clave_nombre(x["nombre"])): [{"id": f"m{i}", "person_id": f"p{i}"}]
              for i, x in enumerate(v[1:])}
    salida, sin_ligar, inconsistencias = votaciones.atribuir(v, indice, {"senado"})
    assert len(salida) == len(v) - 1 and inconsistencias == []
    assert sin_ligar == [{"grupo": v[0]["partido"], "opcion": v[0]["opcion"], "nombre": v[0]["fuente_nombre"]}]
