"""Línea de comandos.

    python -m congreso padron     --out ../congreso-mexicano --legislatura 66 --camara diputados
    python -m congreso votaciones --out ../congreso-mexicano --legislatura 66 [--asunto 5135887]
    python -m congreso senado     --out ../congreso-mexicano --legislatura 66 [--votacion 5139]
    python -m congreso gaceta     --out ../congreso-mexicano --legislatura 66 [--tabla tabla3or1-3]
    python -m congreso asuntos    --out ../congreso-mexicano --legislatura 66 [--tipo 11]
    python -m congreso decretos   --out ../congreso-mexicano --repos ..
    python -m congreso cronologia --out ../congreso-mexicano --repos ..
    python -m congreso validar    --out ../congreso-mexicano
    python -m congreso lecturas verificar --fallos /tmp/fallos
    python -m congreso residuos   {pendientes,para-juicio,verificar} --out ../congreso-mexicano --trabajo /tmp/r [--repos ..]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="congreso")
    sub = p.add_subparsers(dest="orden", required=True)

    a = sub.add_parser("padron")
    a.add_argument("--out", type=Path, required=True)
    a.add_argument("--legislatura", type=int, required=True)
    a.add_argument("--camara", choices=["diputados", "senado"], required=True)
    a.add_argument("--sin-perfiles", action="store_true")

    a = sub.add_parser("votaciones")
    a.add_argument("--out", type=Path, required=True)
    a.add_argument("--legislatura", type=int, required=True)
    a.add_argument("--asunto", action="append")

    a = sub.add_parser("senado", help="votaciones del sitio del Senado (solo desde México: EGRESS_MX_TOKEN)")
    a.add_argument("--out", type=Path, required=True)
    a.add_argument("--legislatura", type=int, required=True)
    a.add_argument("--votacion", action="append")

    a = sub.add_parser("gaceta", help="votaciones de Diputados en la Gaceta (solo desde México: EGRESS_MX_TOKEN)")
    a.add_argument("--out", type=Path, required=True)
    a.add_argument("--legislatura", type=int, required=True)
    a.add_argument("--tabla", action="append", help="p. ej. tabla3or1-3")

    a = sub.add_parser("asuntos", help="iniciativas, proposiciones y dictámenes negativos del SIL")
    a.add_argument("--out", type=Path, required=True)
    a.add_argument("--legislatura", type=int, required=True)
    a.add_argument("--tipo", action="append", help="tipo de asunto del SIL (11, 19, 74639); todos por omisión")

    a = sub.add_parser("decretos")
    a.add_argument("--out", type=Path, required=True)
    a.add_argument("--repos", type=Path, required=True, help="carpeta con los repos de leyes")

    a = sub.add_parser("cronologia", help="decretos de reforma de cada ley desde su publicación (LeyesBiblio)")
    a.add_argument("--out", type=Path, required=True)
    a.add_argument("--repos", type=Path, required=True, help="carpeta con los repos de leyes")

    a = sub.add_parser("residuos", help="decretos sin expediente, para el agente (ver congreso/residuos.py)")
    a.add_argument("etapa", choices=["pendientes", "para-juicio", "verificar"])
    a.add_argument("--out", type=Path, required=True)
    a.add_argument("--trabajo", type=Path, required=True)
    a.add_argument("--repos", type=Path, help="carpeta con los repos de leyes (para `pendientes`)")

    a = sub.add_parser("lecturas", help="verifica las lecturas del agente de páginas que el parser no leyó")
    a.add_argument("etapa", choices=["verificar"])
    a.add_argument("--fallos", type=Path, required=True)

    a = sub.add_parser("archivo", help="siembra el archivo (Worker congreso-archivo) con una copia local")
    a.add_argument("etapa", choices=["sembrar"])
    a.add_argument("--cache", type=Path, required=True)

    a = sub.add_parser("validar")
    a.add_argument("--out", type=Path, required=True)

    args = p.parse_args(argv)
    from . import red
    try:
        r = ejecutar(args)
    except red.Pendiente as e:
        # Falta una página de la que depende todo el paso (un listado, un
        # buscador): no se escribe nada y se reintenta cuando el archivo la tenga.
        r = {"pendiente": str(e), "errores": []}
    finally:
        pedidas = red.enviar_pedidas()
        if pedidas:
            print(f"{pedidas} páginas pedidas al archivo", file=sys.stderr)
    if isinstance(r, int):
        return r
    # Un expediente omitido no es una falla: se anota y el resto se publica.
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0


def ejecutar(args):
    if args.orden == "padron":
        from . import padron
        r = padron.construir(args.out, args.legislatura, args.camara, perfiles=not args.sin_perfiles)
    elif args.orden == "votaciones":
        from . import votaciones
        r = votaciones.construir(args.out, args.legislatura, set(args.asunto) if args.asunto else None)
    elif args.orden == "senado":
        from . import votaciones_senado
        r = votaciones_senado.construir(args.out, args.legislatura, set(args.votacion) if args.votacion else None)
    elif args.orden == "gaceta":
        from . import votaciones_gaceta
        r = votaciones_gaceta.construir(args.out, args.legislatura, set(args.tabla) if args.tabla else None)
    elif args.orden == "asuntos":
        from . import asuntos
        r = asuntos.construir(args.out, args.legislatura, args.tipo)
    elif args.orden == "decretos":
        from . import decretos
        r = decretos.construir(args.out, args.repos)
    elif args.orden == "cronologia":
        from . import cronologia
        r = cronologia.construir(args.out, args.repos)
    elif args.orden == "residuos":
        from . import residuos
        if args.etapa == "pendientes":
            r = residuos.pendientes(args.out, args.repos, args.trabajo)
        elif args.etapa == "para-juicio":
            r = residuos.para_juicio(args.out, args.trabajo)
        else:
            r = residuos.verificar(args.out, args.trabajo)
    elif args.orden == "archivo":
        from . import red
        r = red.sembrar(args.cache, os.environ["CONGRESO_SIEMBRA"])
    elif args.orden == "lecturas":
        from . import lecturas
        r = lecturas.verificar_fallos(args.fallos)
    else:
        from . import validar
        errores = validar.validar(args.out)
        for e in errores:
            print(e)
        print(f"{len(errores)} errores")
        return 1 if errores else 0
    return r


if __name__ == "__main__":
    sys.exit(main())
