"""Línea de comandos.

    python -m congreso padron     --out ../congreso-mexicano --legislatura 66 --camara diputados
    python -m congreso votaciones --out ../congreso-mexicano --legislatura 66 [--asunto 5135887]
    python -m congreso decretos   --out ../congreso-mexicano --repos ..
    python -m congreso validar    --out ../congreso-mexicano
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

    a = sub.add_parser("decretos")
    a.add_argument("--out", type=Path, required=True)
    a.add_argument("--repos", type=Path, required=True, help="carpeta con los repos de leyes")

    a = sub.add_parser("validar")
    a.add_argument("--out", type=Path, required=True)

    args = p.parse_args(argv)
    if args.orden == "padron":
        from . import padron
        r = padron.construir(args.out, args.legislatura, args.camara, perfiles=not args.sin_perfiles)
    elif args.orden == "votaciones":
        from . import votaciones
        r = votaciones.construir(args.out, args.legislatura, set(args.asunto) if args.asunto else None)
    elif args.orden == "decretos":
        from . import decretos
        r = decretos.construir(args.out, args.repos)
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
