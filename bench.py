"""Retired instructions and code size per program: ember -O0, ember -O1,
and zig cc -O2 for scale. Prints a Markdown table."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from ember import driver, reference, target  # noqa: E402


def main() -> None:
    print("| program | O0 instr | O1 instr | O1/O0 | zig -O2 instr |")
    print("|---|---:|---:|---:|---:|")
    for path in sorted((ROOT / "programs").glob("*.c")):
        src = path.read_text()
        n0 = len(target.run_iss(driver.build(src, 0))[2])
        n1 = len(target.run_iss(driver.build(src, 1))[2])
        nz = len(target.run_iss(reference.build(src))[2])
        print(f"| {path.stem} | {n0} | {n1} | {n1 / n0:.2f} | {nz} |")


if __name__ == "__main__":
    main()
