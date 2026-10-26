"""IR to RV32I assembly.

Frame (s0 is the frame pointer, the stack grows down):
    s0-4   ra
    s0-8   caller's s0
    ...    callee-saved s-registers this function uses
    ...    Slots and spilled temps
    sp     16-byte aligned

`regs` maps a temp to the register the allocator gave it. A temp that is
not in the map lives in a 4-byte stack slot; at -O0 the map is empty.
t0-t2 are scratch registers and are never allocated.
"""

from ember.ir import COMPARES, Function, Global, Ins, Module, Slot, Temp
from ember.runtime import RUNTIME

ARG_REGS = [f"a{i}" for i in range(8)]
BRANCH = {"eq": "beq", "ne": "bne", "lt": "blt", "ge": "bge", "gt": "bgt",
          "le": "ble", "ltu": "bltu", "geu": "bgeu", "gtu": "bgtu", "leu": "bleu"}
REG_OPS = {"add": "add", "sub": "sub", "and": "and", "or": "or", "xor": "xor",
           "shl": "sll", "sra": "sra", "shr": "srl"}
IMM_OPS = {"add": "addi", "and": "andi", "or": "ori", "xor": "xori",
           "shl": "slli", "sra": "srai", "shr": "srli"}
CALL_OPS = {"mul": "__mulsi3", "div": "__divsi3", "mod": "__modsi3"}


def fits12(v: int) -> bool:
    return -2048 <= v < 2048


def to_signed(v: int) -> int:
    v &= 0xFFFF_FFFF
    return v - (1 << 32) if v & 0x8000_0000 else v


def generate(module: Module, allocations: dict | None = None) -> str:
    """allocations maps a function name to its temp -> register map."""
    allocations = allocations or {}
    out = [RUNTIME]
    for fn in module.functions:
        out.append(FunctionGen(fn, allocations.get(fn.name, {})).run())
    if module.data:
        out.append(".data")
        for d in module.data:
            out.append(f".align {d.align.bit_length() - 1}")
            out.append(f"{d.name}:")
            for part in d.parts:
                if isinstance(part, tuple):
                    out.append(f"    .word {part[1]}")
                else:
                    for i in range(0, len(part), 16):
                        out.append("    .byte " + ", ".join(str(b) for b in part[i:i + 16]))
    return "\n".join(out) + "\n"


class FunctionGen:
    def __init__(self, fn: Function, regs: dict[Temp, str]) -> None:
        self.fn = fn
        self.regs = regs
        self.lines: list[str] = []
        self.homes: dict[Temp, int] = {}  # spilled temp -> s0 offset
        self.saved = sorted({r for r in regs.values() if r.startswith("s")},
                            key=lambda r: int(r[1:]))
        self.exit = f".Lret_{fn.name}"

    # --- frame -------------------------------------------------------------

    def layout(self) -> int:
        offset = 8 + 4 * len(self.saved)
        for slot in self.fn.slots:
            offset += slot.size
            offset += -offset % slot.align
            slot.offset = -offset
        temps = {t for ins in self.fn.body for t in ins.uses()}
        temps |= {ins.dst for ins in self.fn.body if ins.dst is not None}
        temps |= set(self.fn.params)
        for t in sorted(temps, key=lambda t: t.id):
            if t not in self.regs:
                offset += 4
                self.homes[t] = -offset
        return offset + (-offset % 16)

    def mem(self, offset: int) -> str:
        """An s0-relative memory operand; large offsets go through t2."""
        if fits12(offset):
            return f"{offset}(s0)"
        self.emit(f"li t2, {offset}")
        self.emit("add t2, t2, s0")
        return "0(t2)"

    # --- operands ----------------------------------------------------------

    def emit(self, line: str) -> None:
        self.lines.append("    " + line)

    def get(self, v, scratch: str) -> str:
        """A register holding v (an int or a Temp)."""
        if isinstance(v, int):
            if v == 0:
                return "zero"
            self.emit(f"li {scratch}, {to_signed(v)}")
            return scratch
        if v in self.regs:
            return self.regs[v]
        self.emit(f"lw {scratch}, {self.mem(self.homes[v])}")
        return scratch

    def dst(self, t: Temp) -> str:
        """The register to compute t into; call put() afterwards."""
        return self.regs.get(t, "t0")

    def put(self, t: Temp, reg: str) -> None:
        home = self.regs.get(t)
        if home is None:
            self.emit(f"sw {reg}, {self.mem(self.homes[t])}")
        elif home != reg:
            self.emit(f"mv {home}, {reg}")

    def addr(self, a, scratch: str) -> str:
        """A memory operand for a load/store address."""
        if isinstance(a, Slot):
            return self.mem(a.offset)
        if isinstance(a, Global):
            self.emit(f"la {scratch}, {a.name}")
            return f"0({scratch})"
        return f"0({self.get(a, scratch)})"

    # --- body --------------------------------------------------------------

    def run(self) -> str:
        frame = self.layout()
        name = self.fn.name
        self.lines.append(f".globl {name}")
        self.lines.append(f"{name}:")
        self.emit("sw ra, -4(sp)")
        self.emit("sw s0, -8(sp)")
        self.emit("mv s0, sp")
        for i, r in enumerate(self.saved):
            self.emit(f"sw {r}, {-12 - 4 * i}(sp)")
        if fits12(-frame):
            self.emit(f"addi sp, sp, {-frame}")
        else:
            self.emit(f"li t0, {frame}")
            self.emit("sub sp, sp, t0")
        for t, reg in zip(self.fn.params, ARG_REGS):
            self.put(t, reg)
        body = self.fn.body
        for i, ins in enumerate(body):
            nxt = body[i + 1] if i + 1 < len(body) else None
            self.ins(ins, nxt)
        self.lines.append(f"{self.exit}:")
        for i, r in enumerate(self.saved):
            self.emit(f"lw {r}, {-12 - 4 * i}(s0)")
        self.emit("mv sp, s0")
        self.emit("lw ra, -4(sp)")
        self.emit("lw s0, -8(sp)")
        self.emit("ret")
        return "\n".join(self.lines)

    def ins(self, ins: Ins, nxt: Ins | None) -> None:
        op, d, args = ins.op, ins.dst, ins.args
        if op == "label":
            self.lines.append(f"{ins.target}:")
        elif op == "jmp":
            if not (nxt and nxt.op == "label" and nxt.target == ins.target):
                self.emit(f"j {ins.target}")
        elif op == "br":
            a, b = self.get(args[0], "t0"), self.get(args[1], "t1")
            self.emit(f"{BRANCH[ins.sub]} {a}, {b}, {ins.target}")
            if not (nxt and nxt.op == "label" and nxt.target == ins.target2):
                self.emit(f"j {ins.target2}")
        elif op == "mov":
            if isinstance(args[0], int) or args[0] not in self.regs:
                self.put(d, self.get(args[0], self.dst(d)))
            else:
                self.put(d, self.regs[args[0]])
        elif op == "bin":
            self.binary(ins)
        elif op == "un":
            self.unary(ins)
        elif op == "load":
            r = self.dst(d)
            where = self.addr(args[0], "t0")
            self.emit(f"{'lb' if ins.sub == 1 else 'lw'} {r}, {where}")
            self.put(d, r)
        elif op == "store":
            v = self.get(args[1], "t1")
            where = self.addr(args[0], "t0")
            self.emit(f"{'sb' if ins.sub == 1 else 'sw'} {v}, {where}")
        elif op == "laddr":
            r = self.dst(d)
            off = args[0].offset
            if fits12(off):
                self.emit(f"addi {r}, s0, {off}")
            else:
                self.emit(f"li {r}, {off}")
                self.emit(f"add {r}, {r}, s0")
            self.put(d, r)
        elif op == "gaddr":
            r = self.dst(d)
            self.emit(f"la {r}, {args[0].name}")
            self.put(d, r)
        elif op == "call":
            self.call(ins.sym, args, d)
        elif op == "ret":
            if args:
                v = self.get(args[0], "a0")
                if v != "a0":
                    self.emit(f"mv a0, {v}")
            if nxt is not None:
                self.emit(f"j {self.exit}")
        else:
            raise AssertionError(f"unknown op {op}")

    def call(self, name: str, args: list, d: Temp | None) -> None:
        # Sources are never a-registers, so filling a0..a7 in order is safe.
        for v, reg in zip(args, ARG_REGS):
            src = self.get(v, reg)
            if src != reg:
                self.emit(f"mv {reg}, {src}")
        self.emit(f"call {name}")
        if d is not None:
            self.put(d, "a0")

    def binary(self, ins: Ins) -> None:
        sub, d = ins.sub, ins.dst
        a, b = ins.args
        if sub in CALL_OPS:
            self.call(CALL_OPS[sub], [a, b], d)
            return
        r = self.dst(d)
        if sub == "sub" and isinstance(b, int) and fits12(-b):
            sub, b = "add", -b
        if sub in IMM_OPS and isinstance(b, int) and fits12(b) and b != 0:
            imm = b & 31 if sub in ("shl", "sra", "shr") else b
            self.emit(f"{IMM_OPS[sub]} {r}, {self.get(a, 't0')}, {imm}")
        elif sub in REG_OPS:
            x, y = self.get(a, "t0"), self.get(b, "t1")
            self.emit(f"{REG_OPS[sub]} {r}, {x}, {y}")
        else:
            assert sub in COMPARES, sub
            self.compare(sub, self.get(a, "t0"), self.get(b, "t1"), r)
        self.put(d, r)

    def compare(self, sub: str, x: str, y: str, r: str) -> None:
        u = "u" if sub.endswith("u") else ""
        base = sub.rstrip("u") if sub != "eq" else sub
        if base in ("eq", "ne"):
            self.emit(f"xor {r}, {x}, {y}")
            self.emit(f"{'seqz' if base == 'eq' else 'snez'} {r}, {r}")
        elif base == "lt":
            self.emit(f"slt{u} {r}, {x}, {y}")
        elif base == "gt":
            self.emit(f"slt{u} {r}, {y}, {x}")
        elif base == "le":  # !(y < x)
            self.emit(f"slt{u} {r}, {y}, {x}")
            self.emit(f"xori {r}, {r}, 1")
        else:  # ge: !(x < y)
            self.emit(f"slt{u} {r}, {x}, {y}")
            self.emit(f"xori {r}, {r}, 1")

    def unary(self, ins: Ins) -> None:
        d = ins.dst
        r = self.dst(d)
        x = self.get(ins.args[0], "t0")
        match ins.sub:
            case "neg":
                self.emit(f"neg {r}, {x}")
            case "not":
                self.emit(f"not {r}, {x}")
            case "lnot":
                self.emit(f"seqz {r}, {x}")
            case "sext8":
                self.emit(f"slli {r}, {x}, 24")
                self.emit(f"srai {r}, {r}, 24")
        self.put(d, r)
