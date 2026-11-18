"""Ningún workflow ni script de este repo lanza una corrida: el único que
lanza es OpenCodice/supervisor. Un paso que necesita otra corrida la pide con
una salida `pedir*`, que el supervisor lee del artefacto `cadena`."""
import json
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
WORKFLOWS = RAIZ / ".github" / "workflows"

LANZAMIENTOS = {
    "gh workflow run": re.compile(r"\bgh\s+workflow\s+run\b"),
    "gh run rerun": re.compile(r"\bgh\s+run\s+rerun\b"),
    "/dispatches": re.compile(r"/dispatches\b"),
    "repository_dispatch": re.compile(r"repository_dispatch"),
    "createWorkflowDispatch": re.compile(r"createWorkflowDispatch|createDispatchEvent|reRunWorkflow"),
}
PEDIR = re.compile(r"""echo\s+'pedir=(.+)'\s*>>\s*"\$GITHUB_OUTPUT\"""")


def _archivos():
    for carpeta in (RAIZ / ".github", RAIZ / "scripts"):
        for ruta in sorted(carpeta.rglob("*")):
            if ruta.is_file() and "__pycache__" not in ruta.parts:
                yield ruta


def _workflows():
    return {ruta.name: ruta.read_text(encoding="utf-8") for ruta in sorted(WORKFLOWS.glob("*.yml"))}


def _inputs(texto: str) -> set[str]:
    """Los inputs de `workflow_dispatch`, por su sangría."""
    m = re.search(r"^  workflow_dispatch:\n    inputs:\n((?:      .*\n|\n)+)", texto, re.M)
    return set(re.findall(r"^      ([a-z_]+):", m[1], re.M)) if m else set()


def test_nada_lanza_corridas():
    hallazgos = []
    for ruta in _archivos():
        try:
            lineas = ruta.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for n, linea in enumerate(lineas, 1):
            for nombre, patron in LANZAMIENTOS.items():
                if patron.search(linea):
                    hallazgos.append(f"{ruta.relative_to(RAIZ)}:{n}: {nombre}")
    assert not hallazgos, "Solo el supervisor lanza corridas:\n" + "\n".join(hallazgos)


def test_ningun_job_puede_lanzar():
    con_permiso = [nombre for nombre, texto in _workflows().items() if re.search(r"\bactions:\s*write\b", texto)]
    assert not con_permiso, f"`actions: write` solo servía para lanzar: {con_permiso}"


def test_las_peticiones_son_validas():
    workflows = _workflows()
    peticiones = {}
    for nombre, texto in workflows.items():
        assert texto.count("pedir=") == len(PEDIR.findall(texto)), f"{nombre}: una petición con otra forma"
        for cruda in PEDIR.findall(texto):
            valor = json.loads(cruda)
            peticiones[nombre] = valor if isinstance(valor, list) else [valor]
    assert list(peticiones) == ["reparar-parsers.yml"]
    for origen, lista in peticiones.items():
        for p in lista:
            assert set(p) <= {"workflow", "inputs", "repo"} and "repo" not in p
            assert p["workflow"] in workflows, f"{origen} pide {p['workflow']}, que no existe"
            declarados = _inputs(workflows[p["workflow"]])
            assert "origen" not in p["inputs"]
            assert set(p["inputs"]) <= declarados, f"{p['workflow']} no declara {set(p['inputs']) - declarados}"
            assert all(isinstance(v, str) for v in p["inputs"].values())
    assert peticiones["reparar-parsers.yml"] == [{"workflow": "actualizar-congreso.yml", "inputs": {"publicar": "si"}}]


def test_la_peticion_sale_del_job_y_llega_a_cadena():
    texto = _workflows()["reparar-parsers.yml"]
    assert "pedir_actualizar: ${{ steps.pedir.outputs.pedir }}" in texto
    assert "if: steps.publicar.outputs.relanzar == 'true'" in texto


def test_cada_cadena_termina_en_estado_con_su_artefacto():
    for nombre in ("actualizar-congreso.yml", "reparar-parsers.yml", "resolver-residuos.yml"):
        texto = _workflows()[nombre]
        jobs = re.findall(r"^  ([a-z][a-z0-9_-]*):\n", texto.split("\njobs:\n", 1)[1], re.M)
        assert jobs[-1] == "estado", nombre
        final = texto.split("\n  estado:\n", 1)[1]
        assert re.search(r'name: "estado pendiente=\[(true|false|\$\{\{.*\}\})\]"', final), nombre
        assert f"needs: [{', '.join(jobs[:-1])}]" in final, f"{nombre}: `estado` depende de todos los demás jobs"
        assert "if: ${{ always() }}" in final and "permissions: {}" in final, nombre
        assert "NEEDS: ${{ toJSON(needs) }}" in final and "name: cadena" in final, nombre
        assert "${{" not in "".join(re.findall(r"^\s+run: .*$", final, re.M)), f"{nombre}: `needs` va por env"


def test_el_titulo_dice_si_la_corrida_publica():
    """reparar-parsers y resolver-residuos filtran por ` publicar=[si] ` en el
    título de la actualización, lance quien lance: `origen` va después."""
    workflows = _workflows()
    titulo = re.search(r'^run-name: "(.*)"$', workflows["actualizar-congreso.yml"], re.M)[1]
    assert " publicar=[${{ inputs.publicar }}] origen=[${{ inputs.origen }}]" in titulo
    assert titulo.replace("${{ inputs.publicar }}", "si").count(" publicar=[si] ") == 1
    for nombre in ("reparar-parsers.yml", "resolver-residuos.yml"):
        assert "contains(github.event.workflow_run.display_title, ' publicar=[si] ')" in workflows[nombre], nombre
