# ember

A small C compiler for RV32I, written in Python with only the standard
library. It compiles a subset of C to assembly, assembles it to a flat image
and runs it on [flint](../flint), my RV32I core: on the instruction set
simulator and on the RTL model, which are checked against each other
instruction by instruction.

```
python -m ember programs/sort.c -O 1 --rtl
[iss] exit 200, 54852 instructions
[rtl] exit 200, 80432 cycles, lockstep ok
YY
```

## Language

- `int` (32 bit), `char` (8 bit, signed), pointers, one-dimensional arrays
- pointer arithmetic and pointer difference, array-to-pointer decay
- string literals, `char s[] = "..."`, global initializers
- globals and locals, functions with up to 8 arguments, recursion,
  forward declarations
- `if`/`else`, `while`, `do`/`while`, `for`, `return`, `break`, `continue`
- all C operators on these types with C precedence, including compound
  assignment, `++`/`--`, `?:`, short-circuit `&&` and `||`, and `sizeof`
- `putchar` is built in and writes to flint's console

RV32I has no multiply or divide. `*`, `/` and `%` call routines in
`ember/runtime.py` (shift-and-add multiply, 32-step restoring division,
signed wrappers). Division rounds toward zero, like C.

## Pipeline

```
source -> lexer -> parser -> AST -> type checker -> three-address IR
       -> (-O1: optimizer, register allocator) -> RV32I assembly -> image
```

| stage | file |
|---|---|
| lexer | `ember/lexer.py` |
| recursive descent parser | `ember/parser.py`, `ember/ast.py` |
| type checker | `ember/check.py`, `ember/ctypes.py` |
| IR and lowering | `ember/ir.py`, `ember/lower.py` |
| optimizer and allocator | `ember/opt.py`, `ember/fold.py` |
| code generator | `ember/codegen.py`, `ember/runtime.py` |
| assembler | `ember/asm.py` (uses flint's instruction encoder) |

The code follows the standard RISC-V calling convention: arguments in
`a0`-`a7`, result in `a0`, `s0` as frame pointer, `s1`-`s11` saved by the
callee, a 16-byte aligned stack.

**-O0** keeps every temporary in a stack slot.

**-O1** runs these passes until nothing changes:
- constant and copy propagation inside basic blocks
- constant folding and simple algebra (`x+0`, `x*1`, `x*2^k` becomes a shift)
- branch folding
- dead code elimination from liveness
- removal of unreachable code and unused labels, jump threading

Scalar locals whose address is never taken become temporaries. A linear-scan
allocator then gives temporaries registers. Values that live across a call
go in `s1`-`s11`; the others go in `t3`-`t6`. When registers run out, the
interval that ends last is spilled.

## Results

Retired instructions on flint's ISS (`python bench.py`). The zig column is
the same program built by `zig cc -O2` (clang) for riscv32 and linked with
flint's startup code, for scale.

| program | -O0 | -O1 | -O1/-O0 | zig cc -O2 |
|---|---:|---:|---:|---:|
| fib | 847506 | 650454 | 0.77 | 352260 |
| muldiv | 48653 | 43725 | 0.90 | 86 |
| operators | 2720 | 729 | 0.27 | 37 |
| pointers | 406 | 209 | 0.51 | 154 |
| recursion | 98936 | 67410 | 0.68 | 30294 |
| sieve | 147775 | 54493 | 0.37 | 38157 |
| sort | 82260 | 54852 | 0.67 | 28984 |
| strings | 2395 | 1029 | 0.43 | 1130 |

clang folds `muldiv` and `operators` down to a constant at compile time, so
those two rows only show how much of the work is left at run time. ember's
`strings` at -O1 runs fewer instructions than clang's -O2 build, but the
gap is small and comes from clang's longer startup and helper code.

## Tests

```
python -m pytest tests
```

61 tests, about 15 s:
- unit tests for the lexer, the parser (precedence, associativity, errors)
  and the type checker (what it must reject and accept)
- every program in `programs/`, at -O0 and at -O1, gives the same exit code
  and output as the zig cc build; -O1 retires fewer instructions than -O0
- ISS and RTL retire the same (pc, rd, value) sequence for three programs at
  both levels
- `*`, `/`, `%` against Python on edge cases, including `INT_MIN` and
  `INT_MAX`

The reference build needs `pip install ziglang`. clang's riscv32 `char` is
unsigned by default, so the reference is built with `-fsigned-char`.

## Not implemented

- `struct`, `union`, `enum`, `typedef`, `float`, `unsigned`, `short`,
  `long`
- multi-dimensional arrays, function pointers, variadic functions
- the preprocessor: no `#include`, no `#define`
- more than 8 function arguments
- `switch`, `goto`, labels
- a standard library (only `putchar`)
- register coalescing: -O1 still emits moves between registers that a
  coalescing pass would remove
- optimization across basic blocks beyond dead code elimination: no common
  subexpression elimination, no loop-invariant code motion, no inlining
- division by zero is not trapped; it gives the same result as the M
  extension (quotient all ones, remainder the dividend)

## Layout

ember imports flint from `../flint` (set `FLINT_DIR` to change it) and does
not modify it.
