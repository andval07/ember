"""Reference build: the same C program compiled by zig cc (clang) for
riscv32 through flint's toolchain, then run on flint's ISS."""

import tempfile
from pathlib import Path

from ember import target

SHIM = """\
#include "flint.h"
int putchar(int c) { flint_putc(c); return c; }

/* -nostdlib leaves out compiler-rt, so clang's helper calls land here. */
unsigned __mulsi3(unsigned a, unsigned b) {
    unsigned r = 0;
    for (; b; b >>= 1, a <<= 1) if (b & 1) r += a;
    return r;
}
static unsigned udivmod(unsigned n, unsigned d, unsigned *rem) {
    unsigned q = 0, r = 0;
    for (int i = 31; i >= 0; i--) {
        r = (r << 1) | ((n >> i) & 1);
        if (r >= d) { r -= d; q |= 1u << i; }
    }
    *rem = r;
    return q;
}
unsigned __udivsi3(unsigned n, unsigned d) { unsigned r; return udivmod(n, d, &r); }
unsigned __umodsi3(unsigned n, unsigned d) { unsigned r; udivmod(n, d, &r); return r; }
int __divsi3(int a, int b) {
    unsigned r, q = udivmod(a < 0 ? -(unsigned)a : a, b < 0 ? -(unsigned)b : b, &r);
    return (a < 0) != (b < 0) ? -(int)q : (int)q;
}
int __modsi3(int a, int b) {
    unsigned r;
    udivmod(a < 0 ? -(unsigned)a : a, b < 0 ? -(unsigned)b : b, &r);
    return a < 0 ? -(int)r : (int)r;
}
"""


def build(source: str, opt: str = "-O2") -> bytes:
    """ember's char is signed; clang's riscv32 default is unsigned, so the
    reference is built with -fsigned-char to match."""
    from flint.toolchain import RUNTIME, TARGET, zig

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        prog = work / "prog.c"
        prog.write_text("int putchar(int c);\n" + source)
        shim = work / "shim.c"
        shim.write_text(SHIM)
        elf, binary = work / "out.elf", work / "out.bin"
        zig("cc", *TARGET, "-nostdlib", "-ffreestanding", opt, "-fsigned-char",
            "-fno-sanitize=all", f"-I{RUNTIME}", f"-Wl,-T,{RUNTIME / 'link.ld'}",
            str(RUNTIME / "start.s"), str(RUNTIME / "flint.c"), str(prog), str(shim),
            "-o", str(elf))
        zig("objcopy", "-O", "binary", str(elf), str(binary))
        return binary.read_bytes()


def run(source: str) -> tuple[int, bytes]:
    code, out, _ = target.run_iss(build(source))
    return code, out
