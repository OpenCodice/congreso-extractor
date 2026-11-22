import hashlib

from congreso import datos, padron, red, sil

FOTO = "http://sil.gobernacion.gob.mx/Archivos/Fotos/{}.jpg"
JPG = b"\xff\xd8foto"


class _R:
    def __init__(self, url, contenido):
        self.url, self.contenido = url, contenido
        self.sha256 = hashlib.sha256(contenido).hexdigest()

    def procedencia(self):
        return {"url": self.url, "consultado": "2026-11-22T00:00:00Z", "sha256": self.sha256}


def _simular(monkeypatch, filas, fotos, pendientes=(), jpg=JPG):
    """`fotos`: referencia → URL de su foto en el perfil (o None)."""
    def obtener(url, **k):
        if url in pendientes:
            raise red.Pendiente(url)
        return _R(url, jpg + url.encode() if "/Fotos/" in url else url.encode())
    monkeypatch.setattr(red, "obtener", obtener)
    monkeypatch.setattr(sil, "decodificar", lambda c: c.decode())
    monkeypatch.setattr(sil, "padron", lambda d: filas)
    monkeypatch.setattr(sil, "perfil", lambda d: {
        "foto": fotos[d.rsplit("=", 1)[1]], "estatus": "Activo(a)", "distrito": None, "circunscripcion": None,
        "suplente": None, "licencias": [], "comisiones": []})


def _fila(ref, nombre):
    return {"referencia": ref, "nombre": nombre, "nombre_partes": nombre.split(), "cargo": "Senadora",
            "partido": "MORENA", "principio": "Mayoría Relativa", "entidad": None, "protesta": "2024-09-01",
            "calidad": "Propietario", "formula": None}


def test_foto_se_copia_y_es_la_image_de_la_persona(tmp_path, monkeypatch):
    _simular(monkeypatch, [_fila("1", "Ana Uno"), _fila("2", "Beto Dos")], {"1": FOTO.format(1), "2": None})
    padron.construir(tmp_path, 66, "senado")
    m = datos.leer(tmp_path, "mandatos/lxvi/senado/1.json")
    foto = next(f for f in m["sources"] if padron.es_foto(f))
    assert (tmp_path / foto["archivo"]).read_bytes() == JPG + FOTO.format(1).encode()
    assert foto["archivo"].endswith(".jpg")
    assert datos.leer(tmp_path, "personas/ana-uno.json")["image"] == FOTO.format(1)
    assert "image" not in datos.leer(tmp_path, "personas/beto-dos.json")


def test_foto_pendiente_conserva_la_copia_anterior(tmp_path, monkeypatch):
    filas = [_fila("1", "Ana Uno")]
    _simular(monkeypatch, filas, {"1": FOTO.format(1)})
    padron.construir(tmp_path, 66, "senado")
    antes = datos.leer(tmp_path, "mandatos/lxvi/senado/1.json")
    _simular(monkeypatch, filas, {"1": FOTO.format(1)}, pendientes={FOTO.format(1)})
    padron.construir(tmp_path, 66, "senado")
    assert datos.leer(tmp_path, "mandatos/lxvi/senado/1.json") == antes
    assert datos.leer(tmp_path, "personas/ana-uno.json")["image"] == FOTO.format(1)


def test_foto_en_png_se_copia_como_png(tmp_path, monkeypatch):
    _simular(monkeypatch, [_fila("1", "Ana Uno")], {"1": FOTO.format(1)}, jpg=b"\x89PNG\r\n")
    padron.construir(tmp_path, 66, "senado")
    foto = next(f for f in datos.leer(tmp_path, "mandatos/lxvi/senado/1.json")["sources"] if padron.es_foto(f))
    assert foto["archivo"].endswith(".png")
    assert datos.leer(tmp_path, "personas/ana-uno.json")["image"] == FOTO.format(1)


def test_lo_que_no_es_imagen_no_se_publica(tmp_path, monkeypatch):
    _simular(monkeypatch, [_fila("1", "Ana Uno")], {"1": FOTO.format(1)}, jpg=b"<html>error</html>")
    padron.construir(tmp_path, 66, "senado")
    assert not any(padron.es_foto(f) for f in datos.leer(tmp_path, "mandatos/lxvi/senado/1.json")["sources"])
    assert "image" not in datos.leer(tmp_path, "personas/ana-uno.json")
