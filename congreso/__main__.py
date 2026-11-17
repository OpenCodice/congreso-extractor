"""Línea de comandos.

    python -m congreso padron     --out ../congreso-mexicano --legislatura 66 --camara diputados
    python -m congreso votaciones --out ../congreso-mexicano --legislatura 66 [--asunto 5135887]
    python -m congreso senado     --out ../congreso-mexicano --legislatura 66 [--votacion 5139]
    python -m congreso gaceta     --out ../congreso-mexicano --legislatura 66 [--tabla tabla3or1-3]
    python -m congreso decretos   --out ../congreso-mexicano --repos ..
    python -m congreso validar    --out ../congreso-mexicano
    python -m congreso residuos   {pendientes,para-juicio,verificar} --out ../congreso-mexicano --trabajo /tmp/r [--repos ..]
"""
from __future__ import annotations

import argparse
import json
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

    a = sub.add_parser("decretos")
    a.add_argument("--out", type=Path, required=True)
    a.add_argument("--repos", type=Path, required=True, help="carpeta con los repos de leyes")

    a = sub.add_parser("residuos", help="decretos sin expediente, para el agente (ver congreso/residuos.py)")
    a.add_argument("etapa", choices=["pendientes", "para-juicio", "verificar"])
    a.add_argument("--out", type=Path, required=True)
    a.add_argument("--trabajo", type=Path, required=True)
    a.add_argument("--repos", type=Path, help="carpeta con los repos de leyes (para `pendientes`)")

    a = sub.add_parser("validar")
    a.add_argument("--out", type=Path, required=True)

    args = p.parse_args(argv)
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
    elif args.orden == "decretos":
        from . import decretos
        r = decretos.construir(args.out, args.repos)
    elif args.orden == "residuos":
        from . import residuos
        if args.etapa == "pendientes":
            r = residuos.pendientes(args.out, args.repos, args.trabajo)
        elif args.etapa == "para-juicio":
            r = residuos.para_juicio(args.out, args.trabajo)
        else:
            r = residuos.verificar(args.out, args.trabajo)
    else:
        from . import validar
        errores = validar.validar(args.out)
        for e in errores:
            print(e)
        print(f"{len(errores)} errores")
        return 1 if errores else 0
    # Un expediente omitido no es una falla: se anota y el resto se publica.
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
