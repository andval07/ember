"""Three-address IR.

Operands are Temp (a virtual register), int (a constant), Slot (a frame
object, only as a load/store address or in laddr) or Global (a data label,
only as a load/store address or in gaddr).

Ops:
  mov   dst, [a]
  bin   dst, [a, b]   sub = add sub mul div mod and or xor shl sra shr
                            eq ne lt le gt ge ltu leu gtu geu
  un    dst, [a]      sub = neg not lnot sext8
  load  dst, [addr]   sub = 1 | 4 (1 sign-extends)
  store [addr, v]     sub = 1 | 4
  laddr dst, [Slot]   address of a frame object
  gaddr dst, [Global] address of a data label
  call  dst|None, [args...], sym = function name
  ret   [v] or []
  br    [a, b]        sub = compare, target = taken, target2 = not taken
  jmp   target
  label target
"""

from dataclasses import dataclass, field


class Temp:
    __slots__ = ("id", "hint")

    def __init__(self, id: int, hint: str = "") -> None:
        self.id = id
        self.hint = hint

    def __repr__(self) -> str:
        return f"%{self.hint}{self.id}" if self.hint else f"%{self.id}"


class Slot:
    """A stack object: a local the address of which is needed, an array, or a
    spilled temp. Its frame offset is fixed by the code generator."""

    __slots__ = ("size", "align", "name", "offset")

    def __init__(self, size: int, align: int, name: str = "") -> None:
        self.size = size
        self.align = align
        self.name = name
        self.offset = 0

    def __repr__(self) -> str:
        return f"[{self.name or 'slot'}]"


@dataclass(frozen=True)
class Global:
    name: str

    def __repr__(self) -> str:
        return f"@{self.name}"


Operand = Temp | int | Slot | Global

COMPARES = {"eq", "ne", "lt", "le", "gt", "ge", "ltu", "leu", "gtu", "geu"}
NEGATE = {"eq": "ne", "ne": "eq", "lt": "ge", "ge": "lt", "le": "gt", "gt": "le",
          "ltu": "geu", "geu": "ltu", "leu": "gtu", "gtu": "leu"}
SWAP = {"eq": "eq", "ne": "ne", "lt": "gt", "gt": "lt", "le": "ge", "ge": "le",
        "ltu": "gtu", "gtu": "ltu", "leu": "geu", "geu": "leu"}


@dataclass(eq=False)
class Ins:
    op: str
    dst: Temp | None = None
    args: list = field(default_factory=list)
    sub: object = None
    sym: str | None = None
    target: str | None = None
    target2: str | None = None

    def uses(self) -> list[Temp]:
        return [a for a in self.args if isinstance(a, Temp)]

    def __repr__(self) -> str:
        parts = [self.op if self.sub is None else f"{self.op}.{self.sub}"]
        if self.dst is not None:
            parts.append(f"{self.dst} =")
        if self.sym:
            parts.append(self.sym)
        parts.append(", ".join(map(repr, self.args)))
        if self.target:
            parts.append(f"-> {self.target}")
        if self.target2:
            parts.append(f"/ {self.target2}")
        return " ".join(p for p in parts if p)


@dataclass(eq=False)
class Function:
    name: str
    params: list[Temp]
    body: list[Ins]
    slots: list[Slot]
    ntemps: int

    def dump(self) -> str:
        lines = [f"function {self.name}({', '.join(map(repr, self.params))})"]
        for ins in self.body:
            lines.append(f"{ins.target}:" if ins.op == "label" else f"    {ins!r}")
        return "\n".join(lines)


@dataclass(eq=False)
class Data:
    """A global object: parts are bytes or ('word', label) relocations."""
    name: str
    align: int
    parts: list[bytes | tuple[str, str]]


@dataclass(eq=False)
class Module:
    functions: list[Function]
    data: list[Data]
