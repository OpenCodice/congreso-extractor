"""Iniciativas, proposiciones con punto de acuerdo y dictámenes en sentido
negativo de una legislatura, desde el buscador avanzado del SIL.

Las votaciones solo dicen lo que llegó al Pleno. Aquí está todo lo que se
presentó: quién lo presentó, a qué comisiones se turnó y en qué quedó,
incluidas las que nunca se dictaminaron y las que se desecharon sin votación
nominal. El buscador da hasta 999 filas por consulta; la legislatura se pide
por meses y un mes que pasa del tope se parte en dos.

Cada asunto liga a su autor por la `Referencia` del SIL (la misma del padrón),
no por nombre. Un registro solo se reescribe cuando cambia lo que dice la
fuente: así el historial muestra cambios de estatus, no consultas. Lo que la
fuente deja de listar se conserva con `retirada_de_la_fuente`.
"""
from __future__ import annotations

import gzip
from datetime import date, timedelta
from pathlib import Path

from . import catalogos, datos, red, sil
from .texto import romano

TIPOS = {
    sil.TIPO_INICIATIVA: "iniciativas",
    sil.TIPO_PROPOSICION: "proposiciones",
    sil.TIPO_DICTAMEN_NEGATIVO: "dictamenes-negativos",
}
LEGISLATURAS = {66: ("2024-08-29", "2027-08-31")}
_CAMARA = {"Cámara de Diputados": "diputados", "Cámara de Senadores": "senado", "Comisión Permanente": "permanente"}


def resultado(estado: str) -> str | None:
    """Desenlace del asunto según el texto de su estatus en el SIL."""
    e = estado.lower()
    for prefijo, r in (("pendiente", "pendiente"), ("de primera lectura", "pendiente"),
                       ("presentad", "pendiente"), ("turnado a revisora", "pendiente"),
                       ("desechad", "desechado"), ("retirad", "retirado"),
                       ("atendid", "atendido"), ("concluid", "concluido"), ("publicad", "aprobado"),
                       ("enviado para publicaci", "aprobado"), ("aprobad", "aprobado"), ("resuelto", "aprobado"),
                       ("turnado al ejecutivo", "aprobado"), ("recibid", "aprobado"),
                       ("devuelt", "devuelto")):
        if e.startswith(prefijo):
            return r
    return None


def _dmy(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def meses(desde: date, hasta: date) -> list[tuple[date, date]]:
    salida, inicio = [], desde
    while inicio <= hasta:
        siguiente = (inicio.replace(day=1) + timedelta(days=32)).replace(day=1)
        salida.append((inicio, min(siguiente - timedelta(days=1), hasta)))
        inicio = siguiente
    return salida


def consultar(legislatura: int, tipo: str, desde: date, hasta: date) -> list[tuple[list[dict], red.Respuesta]]:
    """Páginas que cubren el rango completo; parte el rango si pasa del tope."""
    r = red.obtener(sil.URL_BUSQUEDA_ASUNTOS, sil.formulario_asuntos(legislatura, tipo, _dmy(desde), _dmy(hasta)))
    total, filas = sil.asuntos(sil.decodificar(r.contenido))
    if total is None:
        raise RuntimeError(f"el buscador no dijo cuántos asuntos hay ({_dmy(desde)}–{_dmy(hasta)})")
    if total > len(filas):
        if len(filas) < sil.MAX_FILAS:
            raise RuntimeError(f"el buscador dice {total} asuntos y da {len(filas)} ({_dmy(desde)}–{_dmy(hasta)})")
        if desde == hasta:
            raise RuntimeError(f"más de {sil.MAX_FILAS} asuntos en un solo día ({_dmy(desde)})")
        medio = desde + (hasta - desde) // 2
        return consultar(legislatura, tipo, desde, medio) + consultar(legislatura, tipo, medio + timedelta(days=1), hasta)
    if total != len(filas):
        raise RuntimeError(f"el buscador dice {total} asuntos y da {len(filas)} ({_dmy(desde)}–{_dmy(hasta)})")
    return [(filas, r)]


def presentador(p: dict, mandatos: dict[str, dict]) -> dict:
    """El autor tal como lo da el SIL, ligado a su mandato por la Referencia."""
    salida = {"nombre_fuente": p["nombre"]}
    if "referencia" in p:
        m = mandatos.get(f"sil-{p['referencia']}")
        salida.update(tipo="legislador", referencia_sil=p["referencia"])
        if m:
            salida.update(mandato_id=m["id"], person_id=m["person_id"])
        return salida
    if "comision" in p or "comisiones" in p:
        return dict(salida, tipo="comision", referencias_comision=[p["comision"]] if "comision" in p else p["comisiones"])
    if "referencias" in p:
        return dict(salida, tipo="legisladores", referencias_sil=p["referencias"])
    nombre = p["nombre"]
    if nombre in catalogos.PARTIDOS:
        return dict(salida, tipo="grupo_parlamentario", organization_id=catalogos.partido(nombre))
    for prefijo, tipo in (("congreso de", "congreso_local"), ("gobierno de", "gobierno_estatal")):
        if nombre.lower().startswith(prefijo):
            resto = nombre[len(prefijo):].strip()
            clave = catalogos.entidad(resto) or catalogos.entidad(resto.removeprefix("la ").removeprefix("La "))
            if clave:
                return dict(salida, tipo=tipo, entidad=clave,
                            **({"organization_id": f"congreso-{clave}"} if tipo == "congreso_local" else {}))
    if nombre == "Ejecutivo Federal":
        return dict(salida, tipo="ejecutivo_federal")
    if nombre == "Ciudadanos":
        return dict(salida, tipo="ciudadanos")
    if nombre.startswith(("Senado:", "Diputados:", "Comisión Permanente:")):
        return dict(salida, tipo="comision")
    return dict(salida, tipo="otro")


def registro(fila: dict, leg: str, mandatos: dict[str, dict], expedientes: set[str]) -> dict:
    exp = f"sil-{fila['seguimiento']}" if fila["seguimiento"] else None
    estatus = dict(fila["estatus"], resultado=resultado(fila["estatus"]["estado"]))
    return {
        "id": f"sil-{fila['clave']}",
        "clave": fila["clave"],
        "seguimiento": fila["seguimiento"],
        "expediente_id": exp if exp in expedientes else None,
        "legislative_period_id": leg,
        "tipo": fila["tipo"],
        "subclasificacion": fila["subclasificacion"],
        "denominacion": fila["denominacion"],
        "camara_origen": _CAMARA.get(fila["camara"] or ""),
        "fecha_presentacion": fila["fecha"],
        "presentadores": [presentador(p, mandatos) for p in fila["presentadores"]],
        "partido_fuente": fila["partido"] if fila["partido"] not in catalogos.SIN_PARTIDO else None,
        "comisiones": fila["comisiones"],
        "estatus": estatus,
        "temas": fila["temas"],
    }


def construir(raiz: Path, legislatura: int, tipos: list[str] | None = None, hoy: date | None = None) -> dict:
    leg = romano(legislatura).lower()
    inicio, fin = (date.fromisoformat(x) for x in LEGISLATURAS[legislatura])
    fin = min(fin, hoy or date.today())
    mandatos = {m["id"]: m for m in datos.todos(raiz, "mandatos")}
    expedientes = {e["id"] for e in datos.todos(raiz, "expedientes")}
    resumen: dict[str, dict] = {}
    for tipo in tipos or list(TIPOS):
        carpeta = f"{TIPOS[tipo]}/{leg}"
        vistos, escritos, errores, sin_mandato = set(), 0, [], 0
        for desde, hasta in meses(inicio, fin):
            try:
                paginas = consultar(legislatura, tipo, desde, hasta)
            except RuntimeError as e:
                errores.append(str(e))
                continue
            for filas, r in paginas:
                # Una página trae hasta 999 asuntos: se archiva comprimida.
                fuente = dict(r.procedencia(), archivo=f"fuentes/{r.sha256[:2]}/{r.sha256}.html.gz")
                guardada = False
                for f in filas:
                    if not f["clave"]:
                        errores.append(f"fila sin clave de asunto: {f['denominacion'][:80]!r}")
                        continue
                    nuevo = registro(f, leg, mandatos, expedientes)
                    vistos.add(nuevo["id"])
                    sin_mandato += sum(1 for p in nuevo["presentadores"]
                                       if p["tipo"] == "legislador" and "mandato_id" not in p)
                    ruta = f"{carpeta}/{nuevo['id']}.json"
                    viejo = datos.leer(raiz, ruta)
                    if viejo is not None and {k: v for k, v in viejo.items() if k != "sources"} == nuevo:
                        continue
                    if not guardada:
                        datos.guardar_fuente(raiz, r.sha256, gzip.compress(r.contenido, mtime=0), "html.gz")
                        guardada = True
                    datos.escribir(raiz, ruta, dict(nuevo, sources=[fuente]))
                    escritos += 1
        retirados = 0
        # Solo con la legislatura completa leída se sabe qué dejó de listarse.
        if not errores:
            for ruta in sorted((raiz / carpeta).glob("*.json")) if (raiz / carpeta).exists() else []:
                if ruta.stem not in vistos:
                    retirados += datos.marcar_retirada(raiz, ruta.relative_to(raiz).as_posix())
        resumen[TIPOS[tipo]] = {"asuntos": len(vistos), "escritos": escritos, "retirados_de_la_fuente": retirados,
                                "autores_sin_mandato": sin_mandato, "errores": errores}
    return resumen
