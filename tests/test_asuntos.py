from datetime import date
from pathlib import Path

import pytest

from congreso import asuntos, datos, red, sil
from congreso.tablas import Celda

FIX = Path(__file__).parent / "fixtures" / "sil"


def leer(nombre: str) -> str:
    return sil.decodificar((FIX / nombre).read_bytes())


def test_listado_de_iniciativas():
    total, filas = sil.asuntos(leer("iniciativas_2025-10-01_07.html"))
    assert total == len(filas) == 148
    f = filas[0]
    assert (f["clave"], f["seguimiento"], f["fecha"]) == ("4943046", "4946425", "2025-10-07")
    assert f["presentadores"] == [{"nombre": "Dip. Ana Karina Rojo Pimentel", "referencia": "9228238"}]
    assert f["comisiones"] == [{"texto": "1.-Diputados -Régimen, Reglamentos y Prácticas Parlamentarias .-Para dictamen",
                                "camara": "Diputados", "comision": "Régimen, Reglamentos y Prácticas Parlamentarias",
                                "turno": "Para dictamen", "referencia": "2085586"}]
    assert f["estatus"] == {"texto": "Pendiente en comisión(es) de origen el 07-OCT-2025",
                            "estado": "Pendiente en comisión(es) de origen", "fecha": "2025-10-07"}
    dos = next(x for x in filas if len(x["presentadores"]) == 2)
    assert [p["referencia"] for p in dos["presentadores"]] == ["9228764", "9228768"]


def test_sin_resultados():
    assert sil.asuntos(leer("asuntos_sin_resultados.html")) == (0, [])


def _celda(texto, refs=()):
    return Celda(texto=texto, enlaces=[f'x("/L/pp_PerfilLegislador.php?Referencia={r}")' for r in refs])


def test_grupos_antes_de_los_legisladores():
    assert sil._presentadores(_celda("PAN Morena Dip. Ana López", ["1"])) == [
        {"nombre": "PAN"}, {"nombre": "Morena"}, {"nombre": "Dip. Ana López", "referencia": "1"}]
    assert sil._presentadores(_celda("Congreso de Nuevo León")) == [{"nombre": "Congreso de Nuevo León"}]
    # Más nombres que enlaces: no se emparejan a ciegas.
    assert sil._presentadores(_celda("Dip. A Dip. B", ["1"])) == [{"nombre": "Dip. A Dip. B", "referencias": ["1"]}]


def test_presentador_se_liga_por_referencia():
    mandatos = {"sil-1": {"id": "sil-1", "person_id": "ana"}}
    assert asuntos.presentador({"nombre": "Dip. Ana", "referencia": "1"}, mandatos) == {
        "nombre_fuente": "Dip. Ana", "tipo": "legislador", "referencia_sil": "1", "mandato_id": "sil-1", "person_id": "ana"}
    assert "mandato_id" not in asuntos.presentador({"nombre": "Dip. X", "referencia": "2"}, mandatos)
    assert asuntos.presentador({"nombre": "PAN"}, {})["organization_id"] == "partido-pan"
    assert asuntos.presentador({"nombre": "Congreso de la Ciudad de México"}, {})["organization_id"] == "congreso-cdmx"
    assert asuntos.presentador({"nombre": "Ejecutivo Federal"}, {})["tipo"] == "ejecutivo_federal"


@pytest.mark.parametrize("estado,esperado", [
    ("Pendiente en comisión(es) de origen", "pendiente"), ("Desechado en origen", "desechado"),
    ("Retirada", "retirado"), ("Publicado en DOF", "aprobado"), ("De primera lectura en origen", "pendiente"),
    ("Algo nuevo", None)])
def test_resultado(estado, esperado):
    assert asuntos.resultado(estado) == esperado


def test_meses_cubren_el_rango_sin_huecos():
    m = asuntos.meses(date(2024, 8, 29), date(2024, 10, 3))
    assert m == [(date(2024, 8, 29), date(2024, 8, 31)), (date(2024, 9, 1), date(2024, 9, 30)),
                 (date(2024, 10, 1), date(2024, 10, 3))]


def _respuesta(total, n):
    return red.Respuesta("u", f"{total}:{n}".encode(), "2026-11-17T00:00:00Z", f"{total}{n}".ljust(64, "0"))


def test_rango_que_pasa_del_tope_se_parte(monkeypatch):
    llamadas = []

    def obtener(url, datos_=None, **k):
        llamadas.append((datos_["FECHA_INIC"], datos_["FECHA_FIN"]))
        return _respuesta(0, 0)

    def parsear(doc):
        # El rango completo pasa del tope; cada mitad cabe.
        return (1500, [{}] * sil.MAX_FILAS) if len(llamadas) == 1 else (700, [{}] * 700)

    monkeypatch.setattr(red, "obtener", obtener)
    monkeypatch.setattr(sil, "asuntos", parsear)
    paginas = asuntos.consultar(66, "11", date(2025, 1, 1), date(2025, 1, 31))
    assert len(paginas) == 2
    assert llamadas[1:] == [("01/01/2025", "16/01/2025"), ("17/01/2025", "31/01/2025")]


def _fila(clave, estado="Pendiente en comisión(es) de origen"):
    return {"clave": clave, "seguimiento": "9", "tipo": "Iniciativa", "denominacion": "Que reforma la Ley X.",
            "subclasificacion": "Ley Secundaria", "camara": "Cámara de Diputados", "fecha": "2025-01-02",
            "presentadores": [{"nombre": "Dip. Ana", "referencia": "1"}], "partido": "PAN", "legislatura": "LXVI",
            "comisiones": [], "estatus": {"texto": estado, "estado": estado, "fecha": "2025-01-02"}, "temas": []}


def test_solo_se_reescribe_lo_que_cambia_y_lo_retirado_se_marca(tmp_path, monkeypatch):
    datos.escribir(tmp_path, "mandatos/lxvi/diputados/1.json", {"id": "sil-1", "person_id": "ana"})
    filas = [_fila("100"), _fila("200")]
    monkeypatch.setattr(asuntos, "consultar", lambda leg, tipo, d, h: [(list(filas), _respuesta(len(filas), 0))])
    hoy = date(2024, 9, 5)
    asuntos.construir(tmp_path, 66, ["11"], hoy)
    assert asuntos.construir(tmp_path, 66, ["11"], hoy)["iniciativas"]["escritos"] == 0

    filas[:] = [_fila("100", "Desechado")]
    r = asuntos.construir(tmp_path, 66, ["11"], hoy)["iniciativas"]
    assert (r["escritos"], r["retirados_de_la_fuente"]) == (1, 1)
    assert datos.leer(tmp_path, "iniciativas/lxvi/sil-100.json")["estatus"]["resultado"] == "desechado"
    retirada = datos.leer(tmp_path, "iniciativas/lxvi/sil-200.json")
    assert retirada["estatus"]["resultado"] == "pendiente" and "retirada_de_la_fuente" in retirada
