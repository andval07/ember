"""python -m ember prog.c [-O0|-O1] [-S] [--rtl]"""

import argparse
import sys
from pathlib import Path

from ember.driver import build, compile_c
from ember.errors import CompileError
from ember.target import run_iss, run_rtl


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ember", description="C subset to RV32I")
    ap.add_argument("source", type=Path)
    ap.add_argument("-O", dest="opt", type=int, choices=(0, 1), default=0)
    ap.add_argument("-S", action="store_true", help="print the assembly and stop")
    ap.add_argument("--rtl", action="store_true", help="also run on the RTL in lockstep")
    args = ap.parse_args(argv)
    try:
        source = args.source.read_text()
        if args.S:
            sys.stdout.write(compile_c(source, args.opt))
            return 0
        image = build(source, args.opt)
    except (OSError, CompileError) as exc:
        print(f"ember: {exc}", file=sys.stderr)
        return 2
    code, out, log = run_iss(image)
    sys.stdout.write(out.decode("latin-1"))
    print(f"[iss] exit {code}, {len(log)} instructions", file=sys.stderr)
    if args.rtl:
        rtl = run_rtl(image)
        same = [(r.pc, r.rd, r.value) for r in rtl.log] == [(r.pc, r.rd, r.value) for r in log]
        print(f"[rtl] exit {rtl.exit_code}, {rtl.cycles} cycles, lockstep {'ok' if same else 'MISMATCH'}",
              file=sys.stderr)
        if not same:
            return 1
    return code if code is not None else 1


if __name__ == "__main__":
    sys.exit(main())
