"""Enlaces que el código determinista no resuelve, propuestos por un agente.

`decretos` liga un decreto con su expediente solo si no hay duda. Lo que queda
sin ligar (varios candidatos parecidos, una fecha del SIL que no coincide con
la del DOF) lo puede leer un agente como lo haría una persona. El agente nunca
escribe en el repo de datos: el enlace solo entra por el registro
`resoluciones/` de este repo, y solo si pasa tres filtros:

1. propuesta: un agente elige un candidato (o ninguno) y cita, textualmente,
   lo que lo justifica en el decreto del DOF y en el expediente;
2. verificación determinista (`verificar`): el candidato es uno de los
   ofrecidos, cada cita aparece en su fuente y nadie más reclama el expediente;
3. juicio: otro agente, que no propuso, confirma o rechaza cada propuesta.

Lo confirmado y lo rechazado quedan en el registro con sus citas; `decretos`
aplica lo confirmado en cada corrida (siempre después de lo determinista, que
tiene precedencia) y un decreto ya juzgado con los mismos candidatos no vuelve
al agente.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

from . import datos, dof, red
from .texto import sin_acentos

REGISTRO = Path(__file__).resolve().parent.parent / "resoluciones" / "decretos"
# Un expediente cuya publicación en el DOF, según el SIL, dista más que esto del
# decreto no es candidato: el desfase que se ve en la práctica es de un día.
DIAS_DESFASE = 7
CRITERIO = ("propuesto por un agente con citas textuales del decreto y del expediente, verificadas "
            "en sus fuentes, y confirmado por un segundo agente")


def normalizar(texto: str) -> str:
    return " ".join(sin_acentos(html.unescape(texto)).lower().split())


def texto_nota(contenido: bytes) -> str:
    """Texto plano de la nota del DOF (la API la da como HTML dentro de JSON)."""
    nota = json.loads(contenido)["Nota"]
    cuerpo = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", nota.get("cadenaContenido") or "", flags=re.S | re.I)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", cuerpo)).split())


def texto_expediente(e: dict) -> str:
    """Todo el texto del expediente publicado, para buscar en él las citas."""
    piezas: list[str] = []

    def recorrer(x):
        if isinstance(x, str):
            piezas.append(x)
        elif isinstance(x, dict):
            for k, v in x.items():
                if k != "sources":
                    recorrer(v)
        elif isinstance(x, list):
            for v in x:
                recorrer(v)
    recorrer(e)
    return " ".join(piezas)


def _dias(a: str, b: str) -> int:
    return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)


def candidatos(decreto: dict, expedientes: list[dict], nombres: dict[str, str], ocupados: set[str]) -> list[dict]:
    """Expedientes que nombran a un documento del decreto, libres, y publicados
    en el DOF cerca de su fecha según el SIL (o sin fecha de publicación)."""
    docs = {x["documento"] for x in decreto["documentos"]}
    salida = []
    for e in expedientes:
        if e["id"] in ocupados or not docs & dof.menciones(e.get("denominacion") or "", nombres):
            continue
        pub = e.get("publicado_dof")
        if pub and _dias(pub, decreto["fecha"]) > DIAS_DESFASE:
            continue
        salida.append(e)
    return sorted(salida, key=lambda e: e["id"])


def huella(decreto_id: str, ids: list[str]) -> str:
    return hashlib.sha256(json.dumps([decreto_id, sorted(ids)]).encode()).hexdigest()[:16]


def registro(base: Path = REGISTRO) -> dict[str, dict]:
    """decreto → su resolución más reciente (confirmada o rechazada)."""
    salida: dict[str, dict] = {}
    for p in sorted(base.glob("*.json")) if base.exists() else []:
        for r in json.loads(p.read_text(encoding="utf-8"))["resoluciones"]:
            salida[r["decreto"]] = dict(r, lote=p.name)
    return salida


def pendientes(raiz: Path, repos: Path, trabajo: Path, base: Path = REGISTRO) -> dict:
    """Escribe `trabajo/pendientes.json` y el texto de cada decreto del DOF."""
    from .decretos import nombres_documentos
    nombres = nombres_documentos(repos)
    expedientes = datos.todos(raiz, "expedientes")
    decs = [d for d in datos.todos(raiz, "decretos") if "id" in d]
    ocupados = {x["id"] for d in decs for x in d.get("expedientes", [])}
    hechos = registro(base)
    trabajo.mkdir(parents=True, exist_ok=True)
    lista = []
    for d in decs:
        if d.get("expedientes"):
            continue
        cands = candidatos(d, expedientes, nombres, ocupados)
        if not cands:
            continue
        h = huella(d["id"], [e["id"] for e in cands])
        if hechos.get(d["id"], {}).get("huella") == h:
            continue
        r = red.obtener(dof.url_nota_api(d["codigo"]), vigencia_horas=24 * 30)
        ruta = (trabajo / f"{d['id']}.txt").resolve()
        ruta.write_text(texto_nota(r.contenido), encoding="utf-8")
        lista.append({
            "decreto": d["id"], "huella": h, "fecha": d["fecha"], "titulo": d["titulo"], "url": d["url"],
            "documentos": sorted({x["documento"] for x in d["documentos"]}),
            "texto_dof": str(ruta), "fuente_dof": r.procedencia(),
            "candidatos": [{"id": e["id"], "denominacion": e.get("denominacion"),
                            "publicado_dof": e.get("publicado_dof"), "camara_origen": e.get("camara_origen"),
                            "ultimo_estatus": e.get("ultimo_estatus"), "tramites": e.get("tramites"),
                            "archivo": str((raiz / "expedientes" / f"{e['id']}.json").resolve())} for e in cands],
        })
    (trabajo / "pendientes.json").write_text(json.dumps({"decretos": lista}, ensure_ascii=False, indent=2),
                                             encoding="utf-8")
    return {"pendientes": len(lista)}


def _lee(ruta: Path) -> dict:
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def verificar_propuesta(p: dict, pendiente: dict, expedientes: dict[str, dict]) -> list[str]:
    """Lo que la propuesta no cumple (vacío si pasa la verificación determinista)."""
    fallas = []
    ids = {c["id"] for c in pendiente["candidatos"]}
    eid = p.get("expediente")
    if eid not in ids:
        return [f"{eid!r} no es uno de los candidatos"]
    citas = p.get("citas") or []
    fuentes = {"dof": normalizar(Path(pendiente["texto_dof"]).read_text(encoding="utf-8")),
               "expediente": normalizar(texto_expediente(expedientes[eid]))}
    for c in citas:
        texto = normalizar(c.get("texto") or "")
        if c.get("fuente") not in fuentes:
            fallas.append(f"cita con fuente desconocida {c.get('fuente')!r}")
        elif len(texto) < 20:
            fallas.append(f"cita demasiado corta: {c.get('texto')!r}")
        elif texto not in fuentes[c["fuente"]]:
            fallas.append(f"la cita no está en {c['fuente']}: {c['texto'][:120]!r}")
    for f in ("dof", "expediente"):
        if not any(c.get("fuente") == f for c in citas):
            fallas.append(f"sin cita de {f}")
    return fallas


def para_juicio(raiz: Path, trabajo: Path) -> dict:
    """`propuestas-juicio.json`: lo que pasa la verificación determinista, sin la
    nota del que propuso, para que el juicio no se ancle en su razonamiento."""
    pend = {p["decreto"]: p for p in _lee(trabajo / "pendientes.json").get("decretos", [])}
    expedientes = {e["id"]: e for e in datos.todos(raiz, "expedientes")}
    salida = []
    for p in _lee(trabajo / "propuestas.json").get("decretos", []):
        if p.get("decreto") in pend and p.get("expediente") and not verificar_propuesta(p, pend[p["decreto"]], expedientes):
            salida.append({k: p[k] for k in ("decreto", "expediente", "citas")})
    (trabajo / "propuestas-juicio.json").write_text(json.dumps({"decretos": salida}, ensure_ascii=False, indent=2),
                                                    encoding="utf-8")
    return {"para_juicio": len(salida)}


def verificar(raiz: Path, trabajo: Path, base: Path = REGISTRO) -> dict:
    """Cruza propuestas, verificación y juicio; escribe un lote nuevo en el registro."""
    pend = {p["decreto"]: p for p in _lee(trabajo / "pendientes.json").get("decretos", [])}
    propuestas = {p["decreto"]: p for p in _lee(trabajo / "propuestas.json").get("decretos", [])
                  if p.get("decreto") in pend}
    juicios = {j["decreto"]: j for j in _lee(trabajo / "juicio.json").get("decretos", [])
               if j.get("decreto") in pend}
    expedientes = {e["id"]: e for e in datos.todos(raiz, "expedientes")}
    elegidos: dict[str, list[str]] = {}
    for d, p in propuestas.items():
        if p.get("expediente"):
            elegidos.setdefault(p["expediente"], []).append(d)

    resoluciones, resumen = [], {"confirmadas": 0, "rechazadas": 0, "sin_expediente": 0, "sin_veredicto": 0}
    for d, pendiente in pend.items():
        p = propuestas.get(d)
        if p is None:
            resumen["sin_veredicto"] += 1
            continue
        r = {"decreto": d, "huella": pendiente["huella"], "candidatos": [c["id"] for c in pendiente["candidatos"]],
             "propuesta": {k: p.get(k) for k in ("expediente", "citas", "nota")},
             "fuente_dof": pendiente["fuente_dof"]}
        if not p.get("expediente"):
            r["estado"] = "sin_expediente"
            r["motivo"] = "el agente no encontró el expediente entre los candidatos"
        else:
            fallas = verificar_propuesta(p, pendiente, expedientes)
            if len(elegidos[p["expediente"]]) > 1:
                fallas.append(f"el mismo expediente propuesto para {sorted(elegidos[p['expediente']])}")
            j = juicios.get(d)
            if fallas:
                r["estado"], r["motivo"] = "rechazada", "; ".join(fallas)
            elif not j:
                resumen["sin_veredicto"] += 1
                continue
            else:
                r["juicio"] = {k: j.get(k) for k in ("veredicto", "nota")}
                ok = j.get("veredicto") == "confirmado"
                r["estado"] = "confirmada" if ok else "rechazada"
                if not ok:
                    r["motivo"] = "el segundo agente no la confirmó"
        resumen[{"confirmada": "confirmadas", "rechazada": "rechazadas"}.get(r["estado"], r["estado"])] += 1
        resoluciones.append(r)
    if resoluciones:
        base.mkdir(parents=True, exist_ok=True)
        ahora = datetime.now(timezone.utc)
        nombre = f"{ahora:%Y-%m-%d-%H%M%S}.json"
        (base / nombre).write_text(json.dumps({"fecha": ahora.isoformat(timespec="seconds"),
                                               "resoluciones": resoluciones},
                                              ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        resumen["lote"] = nombre
    return resumen


def aplicar(decretos_: list[dict], expedientes: list[dict], base: Path = REGISTRO) -> list[str]:
    """Pone en cada decreto sin expediente su resolución confirmada, si sigue
    siendo válida: el expediente existe, nadie más lo tiene y sus candidatos
    son los mismos que cuando se juzgó."""
    hechos = registro(base)
    existentes = {e["id"] for e in expedientes}
    ocupados = {x["id"] for d in decretos_ for x in d["expedientes"]}
    avisos = []
    for d in decretos_:
        r = hechos.get(d["id"])
        if d["expedientes"] or not r or r["estado"] != "confirmada":
            continue
        eid = r["propuesta"]["expediente"]
        actuales = {c["id"] for c in d["candidatos_expediente"]}
        if eid not in existentes or eid in ocupados:
            avisos.append(f"{d['id']}: la resolución {r['lote']} ya no aplica ({eid} no existe o está ligado)")
            continue
        if actuales and eid not in actuales:
            avisos.append(f"{d['id']}: la resolución {r['lote']} elige {eid}, que ya no es candidato")
            continue
        d["expedientes"] = [{"id": eid, "criterio": CRITERIO,
                             "resolucion": f"OpenCodice/congreso-extractor:resoluciones/decretos/{r['lote']}",
                             "evidencia": r["propuesta"]["citas"]}]
        d["candidatos_expediente"] = []
        d["sources"].append(r["fuente_dof"])
        ocupados.add(eid)
    return avisos
