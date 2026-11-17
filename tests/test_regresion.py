import hashlib
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
FIX = Path(__file__).parent / "fixtures"
_spec = importlib.util.spec_from_file_location("regresion", RAIZ / "scripts" / "regresion.py")
regresion = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(regresion)

TIPOS = {("senado", "votacion"), ("senado", "tabla"), ("gaceta", "tabla"), ("gaceta", "lista")}

# Un parser de juguete: lee «VOTOS n» y falla con lo demás.
SENADO_V1 = '''
import re
def decodificar(c): return c.decode("utf-8")
def votacion(d):
    m = re.search(r"VOTOS (\\d+)", d)
    if not m: raise ValueError("sin votos")
    return {"votos": int(m[1])}
def tabla(d): return votacion(d)
'''
RED = 'def bloqueado(c): return b"_Incapsula_Resource" in c[:3000]\n'


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def guardar(cache: Path, url: str, contenido: bytes, datos=None):
    clave = url + ("\n" + json.dumps(datos, sort_keys=True) if datos else "")
    h = hashlib.sha256(clave.encode()).hexdigest()
    (cache / h[:2]).mkdir(parents=True, exist_ok=True)
    (cache / h[:2] / h).write_bytes(contenido)
    (cache / h[:2] / f"{h}.json").write_text(json.dumps({"url": url, "datos": datos, "consultado": "x"}))


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    (r / "congreso").mkdir(parents=True)
    (r / "congreso" / "senado.py").write_text(SENADO_V1)
    (r / "congreso" / "red.py").write_text(RED)
    git(r, "init", "-q")
    git(r, "add", "-A")
    git(r, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "v1")
    return r


def correr(repo, cache, fallos=None, lecturas=None):
    return regresion.correr(cache, "HEAD", repo, repo, fallos, lecturas, TIPOS)


def test_clasificar_por_url():
    c = regresion.clasificar
    assert c("https://www.senado.gob.mx/66/votacion/5139", None) == ("senado", "votacion", "5139")
    assert c("https://www.senado.gob.mx/66/app/votaciones/functions/viewTableVot.php"
             "?action=ajax&cell=1&order=DESC&votacion=5139&q=", None) == ("senado", "tabla", "5139")
    assert c("https://gaceta.diputados.gob.mx/Gaceta/Votaciones/66/tabla3or1-3.php3", None) == ("gaceta", "tabla", "tabla3or1-3")
    assert c("https://gaceta.diputados.gob.mx/voto66/ordi31/lanordi31.php3", {"evento": "3", "lola[11]": "1"}) \
        == ("gaceta", "lista", "/voto66/ordi31/lanordi31.php3#evento=3")
    assert c("https://www.senado.gob.mx/66/votaciones/por_legislatura/LXVI/", None) is None
    assert c("https://gaceta.diputados.gob.mx/gp_votaciones.html", None) is None
    assert c("http://sil.gobernacion.gob.mx/Librerias/Votaciones/x.php?Votacion=1", None) is None


def test_regresiones_arreglos_y_bloqueos(repo, tmp_path):
    cache = tmp_path / "cache"
    s = "https://www.senado.gob.mx/66/votacion/"
    guardar(cache, s + "1", b"VOTOS 10")              # se lee igual
    guardar(cache, s + "2", b"VOTOS 20 PRO")          # v2 la lee distinto: regresión
    guardar(cache, s + "3", b"VOTANTES 30")           # v1 falla, v2 la lee: arreglo
    guardar(cache, s + "4", b"nada")                  # falla con las dos
    guardar(cache, s + "5", b"<html>_Incapsula_Resource</html>")  # bloqueo: no cuenta
    guardar(cache, "http://sil.gobernacion.gob.mx/x.php", b"VOTOS 1")  # no es de estos parsers
    (repo / "congreso" / "senado.py").write_text(SENADO_V1.replace(
        'r"VOTOS (\\d+)"', 'r"VOT(?:OS|ANTES) (\\d+)( PRO)?"').replace(
        'return {"votos": int(m[1])}', 'return {"votos": int(m[1]) + (1 if m[2] else 0)}'))
    rep = correr(repo, cache)
    assert rep["paginas"] == 5 and rep["iguales"] == 1 and rep["ignoradas_bloqueo"] == 1
    assert [(x["clave"], x["despues"]) for x in rep["regresiones"]] == [("2", "cambian: votos")]
    assert [x["clave"] for x in rep["arreglos"]] == ["3"]
    assert [x["clave"] for x in rep["siguen_fallando"]] == ["4"]


def test_sin_cambios_no_hay_regresion_y_el_cli_sale_en_cero(repo, tmp_path):
    cache = tmp_path / "cache"
    guardar(cache, "https://www.senado.gob.mx/66/votacion/1", b"VOTOS 10")
    salida = tmp_path / "rep.json"
    assert regresion.main(["--cache", str(cache), "--repo", str(repo), "--salida", str(salida)]) == 0
    assert json.loads(salida.read_text())["iguales"] == 1
    (repo / "congreso" / "senado.py").write_text(SENADO_V1.replace("int(m[1])", "int(m[1]) * 2"))
    assert regresion.main(["--cache", str(cache), "--repo", str(repo), "--salida", str(salida)]) == 1


def test_un_parser_que_ya_no_lee_y_un_bloqueo_nuevo_son_regresiones(repo, tmp_path):
    cache = tmp_path / "cache"
    guardar(cache, "https://www.senado.gob.mx/66/votacion/1", b"VOTOS 10")
    guardar(cache, "https://www.senado.gob.mx/66/votacion/2", b"VOTOS 20 aviso")
    guardar(cache, "https://www.senado.gob.mx/66/votacion/3", b"aviso del firewall")
    (repo / "congreso" / "senado.py").write_text(SENADO_V1.replace('if not m:', 'if not m or "10" in d:'))
    (repo / "congreso" / "red.py").write_text(RED.replace("return", 'return b"aviso" in c or'))
    rep = correr(repo, cache)
    assert sorted((x["clave"], x["despues"]) for x in rep["regresiones"]) == [
        ("1", "error: ValueError: sin votos"), ("2", "bloqueo")]
    assert [x["clave"] for x in rep["ahora_bloqueo"]] == ["3"]


def test_fallos_y_lecturas(repo, tmp_path):
    cache, fallos, lecturas = tmp_path / "cache", tmp_path / "fallos", tmp_path / "lecturas"
    paginas = {"3": b"VOTANTES 30", "4": b"VOTANTES 40"}
    for clave, contenido in paginas.items():
        sha = hashlib.sha256(contenido).hexdigest()
        url = f"https://www.senado.gob.mx/66/votacion/{clave}"
        guardar(cache, url, contenido)  # la misma página en el caché y en los fallos: se lee una vez
        (fallos / sha).mkdir(parents=True)
        (fallos / sha / "pagina.html").write_bytes(contenido)
        (fallos / sha / "fallo.json").write_text(json.dumps(
            {"fuente": "senado", "tipo": "votacion", "clave": clave, "url": url, "datos": None, "sha256": sha,
             "error": "ValueError: sin votos", "contexto": {}}))
        (lecturas / "senado" / "votacion").mkdir(parents=True, exist_ok=True)
        (lecturas / "senado" / "votacion" / f"{sha}.json").write_text(json.dumps({"datos": {"votos": 30}}))
    (repo / "congreso" / "senado.py").write_text(SENADO_V1.replace("VOTOS", "VOT(?:OS|ANTES)"))
    rep = correr(repo, cache, fallos, lecturas)
    assert rep["paginas"] == 2
    assert all(x["origen"] == ["cache", "fallo"] for x in rep["arreglos"])
    assert [x["clave"] for x in rep["contra_lectura"]["coinciden"]] == ["3"]
    (difiere,) = rep["contra_lectura"]["difieren"]
    assert difiere["clave"] == "4" and difiere["nuevo"] and difiere["diferencia"] == "cambian: votos"


def test_parsers_reales_sobre_fixtures(tmp_path):
    repo = tmp_path / "repo"
    shutil.copytree(RAIZ / "congreso", repo / "congreso", ignore=shutil.ignore_patterns("__pycache__"))
    git(repo, "init", "-q")
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "v1")
    cache = tmp_path / "cache"
    guardar(cache, "https://www.senado.gob.mx/66/votacion/5139", (FIX / "senado" / "votacion_5139.html").read_bytes())
    guardar(cache, "https://www.senado.gob.mx/66/app/votaciones/functions/viewTableVot.php"
                   "?action=ajax&cell=1&order=DESC&votacion=5139&q=", (FIX / "senado" / "tabla_5139.html").read_bytes())
    guardar(cache, "https://gaceta.diputados.gob.mx/Gaceta/Votaciones/66/tabla3or1-3.php3",
            (FIX / "gaceta" / "tabla3or1-3.html").read_bytes())
    guardar(cache, "https://gaceta.diputados.gob.mx/voto66/ordi31/lanordi31.php3",
            (FIX / "gaceta" / "lista_3or1_evento3_favor.html").read_bytes(), {"evento": "3", "lola[11]": "1"})
    rep = correr(repo, cache)
    assert rep["paginas"] == rep["iguales"] == 4 and not rep["regresiones"]
