import pytest

from congreso import red


@pytest.fixture(autouse=True)
def _prioridad_del_entorno(monkeypatch):
    """Las pruebas corren también dentro de una carga de otra legislatura,
    que baja la prioridad de lo que pide: aquí no cuenta."""
    monkeypatch.setattr(red, "PRIORIDAD_BASE", 0)
