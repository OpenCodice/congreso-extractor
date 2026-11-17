import json
from pathlib import Path

from congreso import residuos

FIX = Path(__file__).parent / "fixtures" / "dof"
DEN = ("Que reforma, adiciona y deroga diversas disposiciones de Ley de Fiscalización y Rendición de Cuentas de la "
       "Federación, de la Ley General de Contabilidad Gubernamental y de la Ley de Coordinación Fiscal.")
CITA_DOF = {"fuente": "dof", "texto": "Ciudad de México, a 21 de abril de 2026 .- Dip. Kenia López Rabadán, Presidenta"}
CITA_EXP = {"fuente": "expediente", "texto": "Ley General de Contabilidad Gubernamental y de la Ley de Coordinación"}


def test_texto_de_la_nota_incluye_las_firmas():
    t = residuos.texto_nota((FIX / "nota_5787417.json").read_bytes())
    assert t.startswith("DECRETO por el que se reforman")
    assert "Sen. Laura Itzel Castillo Juárez, Presidenta" in t and "<" not in t


def _decreto(**k):
    return dict({"id": "dof-5787417", "fecha": "2026-05-14", "expedientes": [], "candidatos_expediente": [],
                 "documentos": [{"documento": "lgcg"}], "sources": []}, **k)


def _expediente(eid, pub):
    return {"id": eid, "denominacion": DEN, "publicado_dof": pub}


def test_candidatos_admiten_un_desfase_corto():
    nombres = {"lgcg": "Ley General de Contabilidad Gubernamental"}
    ex = [_expediente("sil-1", "2026-05-15"), _expediente("sil-2", "2026-07-01"), _expediente("sil-3", None),
          _expediente("sil-4", None)]
    assert [e["id"] for e in residuos.candidatos(_decreto(), ex, nombres, {"sil-4"})] == ["sil-1", "sil-3"]


def _trabajo(tmp_path, propuesta, juicio=None):
    raiz = tmp_path / "datos"
    (raiz / "expedientes").mkdir(parents=True)
    for e in (_expediente("sil-1", "2026-05-15"), _expediente("sil-3", None)):
        (raiz / "expedientes" / f"{e['id']}.json").write_text(json.dumps(e), encoding="utf-8")
    t = tmp_path / "trabajo"
    t.mkdir()
    (t / "dof-5787417.txt").write_text(residuos.texto_nota((FIX / "nota_5787417.json").read_bytes()), encoding="utf-8")
    pend = {"decreto": "dof-5787417", "huella": "h", "texto_dof": str(t / "dof-5787417.txt"),
            "fuente_dof": {"url": "u", "sha256": "s"}, "candidatos": [{"id": "sil-1"}, {"id": "sil-3"}]}
    (t / "pendientes.json").write_text(json.dumps({"decretos": [pend]}), encoding="utf-8")
    (t / "propuestas.json").write_text(json.dumps({"decretos": [propuesta]}), encoding="utf-8")
    if juicio:
        (t / "juicio.json").write_text(json.dumps({"decretos": [juicio]}), encoding="utf-8")
    return raiz, t


def test_cita_inventada_se_rechaza_sin_juicio(tmp_path):
    falsa = {"fuente": "dof", "texto": "aprobado por unanimidad en la sesión del 3 de mayo"}
    raiz, t = _trabajo(tmp_path, {"decreto": "dof-5787417", "expediente": "sil-1", "citas": [falsa, CITA_EXP]})
    assert residuos.para_juicio(raiz, t) == {"para_juicio": 0}
    base = tmp_path / "registro"
    assert residuos.verificar(raiz, t, base)["rechazadas"] == 1
    assert residuos.registro(base)["dof-5787417"]["estado"] == "rechazada"


def test_confirmada_solo_con_juicio_y_se_aplica(tmp_path):
    propuesta = {"decreto": "dof-5787417", "expediente": "sil-1", "citas": [CITA_DOF, CITA_EXP], "nota": "n"}
    raiz, t = _trabajo(tmp_path, propuesta)
    base = tmp_path / "registro"
    assert residuos.verificar(raiz, t, base)["sin_veredicto"] == 1 and not base.exists()
    residuos.para_juicio(raiz, t)
    juicio = json.loads((t / "propuestas-juicio.json").read_text())
    assert juicio["decretos"][0] == {k: propuesta[k] for k in ("decreto", "expediente", "citas")}

    raiz, t = _trabajo(tmp_path / "b", propuesta, {"decreto": "dof-5787417", "veredicto": "confirmado"})
    assert residuos.verificar(raiz, t, base)["confirmadas"] == 1
    decs = [_decreto(candidatos_expediente=[{"id": "sil-1"}, {"id": "sil-3"}])]
    assert residuos.aplicar(decs, [{"id": "sil-1"}, {"id": "sil-3"}], base) == []
    enlace = decs[0]["expedientes"][0]
    assert enlace["id"] == "sil-1" and enlace["evidencia"] == [CITA_DOF, CITA_EXP]
    assert enlace["resolucion"].startswith("OpenCodice/congreso-extractor:resoluciones/decretos/") and decs[0]["candidatos_expediente"] == []


def test_resolucion_no_pisa_un_expediente_ya_ligado(tmp_path):
    propuesta = {"decreto": "dof-5787417", "expediente": "sil-1", "citas": [CITA_DOF, CITA_EXP]}
    raiz, t = _trabajo(tmp_path, propuesta, {"decreto": "dof-5787417", "veredicto": "confirmado"})
    base = tmp_path / "registro"
    residuos.verificar(raiz, t, base)
    otro = _decreto(id="dof-1", expedientes=[{"id": "sil-1", "criterio": "x"}])
    avisos = residuos.aplicar([_decreto(), otro], [{"id": "sil-1"}], base)
    assert len(avisos) == 1 and "ya no aplica" in avisos[0]
