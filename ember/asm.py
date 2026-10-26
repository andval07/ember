"""Assembler for the code ember emits.

flint's own assembler has no data directives and its li is always two
instructions, so ember carries this one. Real instructions are still encoded
by flint.asm.encode; this file only adds directives, pseudo instructions,
short li and branch relaxation.
"""

from ember import target  # noqa: F401  (puts flint on sys.path)
from flint.asm import AsmError, encode, split_li  # noqa: E402

BRANCH_INV = {"beq": "bne", "bne": "beq", "blt": "bge", "bge": "blt",
              "bltu": "bgeu", "bgeu": "bltu"}
SWAPPED = {"bgt": "blt", "ble": "bge", "bgtu": "bltu", "bleu": "bgeu"}


def fits12(v: int) -> bool:
    return -2048 <= v < 2048


def parse(source: str) -> list[tuple[str, list[str]]]:
    out = []
    for raw in source.splitlines():
        line = raw.split("#", 1)[0].strip()
        while line:
            head, sep, rest = line.partition(":")
            if sep and head and " " not in head.strip() and "(" not in head:
                out.append(("label", [head.strip()]))
                line = rest.strip()
                continue
            name, _, ops = line.partition(" ")
            args = [a.strip() for a in ops.split(",")] if ops.strip() else []
            out.append((name.lower(), args))
            break
    return out


def expand(name: str, args: list[str]) -> tuple[str, list[str]]:
    """Rewrite simple pseudo instructions to a real one."""
    match name:
        case "ret":
            return "jalr", ["zero", "0(ra)"]
        case "call":
            return "jal", ["ra", args[0]]
        case "beqz" | "bnez":
            return name[:3], [args[0], "zero", args[1]]
        case "bgt" | "ble" | "bgtu" | "bleu":
            return SWAPPED[name], [args[1], args[0], args[2]]
        case "neg":
            return "sub", [args[0], "zero", args[1]]
        case "not":
            return "xori", [args[0], args[1], "-1"]
        case "seqz":
            return "sltiu", [args[0], args[1], "1"]
        case "snez":
            return "sltu", [args[0], "zero", args[1]]
    return name, args


class Item:
    __slots__ = ("name", "args", "section", "size", "long", "pc")

    def __init__(self, name: str, args: list[str], section: str) -> None:
        self.name, self.args, self.section = name, args, section
        self.size = self.pc = 0
        self.long = False  # a branch that needs the far form


def assemble(source: str) -> bytes:
    items = []
    section = "text"
    for name, args in parse(source):
        if name in (".text", ".data"):
            section = name[1:]
            continue
        if name == ".globl":
            continue
        name, args = expand(name, args)
        items.append(Item(name, args, section))
    text = [i for i in items if i.section == "text"]
    data = [i for i in items if i.section == "data"]
    labels: dict[str, int] = {}
    # Grow branches until nothing changes; sizes only ever grow, so it ends.
    while True:
        layout(text, data, labels)
        changed = False
        for it in text:
            if it.name in BRANCH_INV and not it.long:
                off = labels.get(it.args[2], 0) - it.pc
                if not -4096 <= off < 4096:
                    it.long = changed = True
        if not changed:
            break
    out = bytearray()
    for it in text + [None] + data:
        if it is None:
            out.extend(bytes(-len(out) % 4))
            continue
        if it.name == ".align":
            out.extend(bytes(-len(out) % (1 << int(it.args[0]))))
        assert len(out) == it.pc, (it.name, len(out), it.pc)
        out.extend(emit(it, labels))
    return bytes(out)


def size_of(it: Item, labels: dict[str, int]) -> int:
    match it.name:
        case "label" | ".align":
            return 0
        case ".word":
            return 4 * len(it.args)
        case ".byte":
            return len(it.args)
        case ".zero":
            return int(it.args[0], 0)
        case "li":
            v = it.args[1]
            try:
                return 4 if fits12(int(v, 0)) else 8
            except ValueError:
                return 8  # a label
        case "la":
            return 8
    if it.name in BRANCH_INV and it.long:
        return 8
    return 4


def layout(text: list[Item], data: list[Item], labels: dict[str, int]) -> None:
    pc = 0
    for group in (text, data):
        if group is data:
            pc += -pc % 4
        for it in group:
            if it.name == ".align":
                pc += -pc % (1 << int(it.args[0]))
            it.pc = pc
            if it.name == "label":
                labels[it.args[0]] = pc
            it.size = size_of(it, labels)
            pc += it.size


def emit(it: Item, labels: dict[str, int]) -> bytes:
    name, args = it.name, it.args
    try:
        if name in ("label", ".align"):
            return b""
        if name == ".word":
            return b"".join(
                (labels[a] if a in labels else int(a, 0) & 0xFFFF_FFFF).to_bytes(4, "little")
                for a in args)
        if name == ".byte":
            return bytes(int(a, 0) & 0xFF for a in args)
        if name == ".zero":
            return bytes(int(args[0], 0))
        if name in ("li", "la"):
            value = labels[args[1]] if args[1] in labels else int(args[1], 0)
            if it.size == 4:
                words = encode("addi", [args[0], "zero", str(value)], it.pc, labels)
            else:
                upper, low = split_li(value)
                words = encode("lui", [args[0], str(upper)], it.pc, labels)
                words += encode("addi", [args[0], args[0], str(low)], it.pc + 4, labels)
        elif name in BRANCH_INV and it.long:
            inv = BRANCH_INV[name]
            words = encode(inv, [args[0], args[1], "8"], it.pc, {})
            words += encode("jal", ["zero", args[2]], it.pc + 4, labels)
        else:
            words = encode(name, args, it.pc, labels)
    except (AsmError, KeyError, ValueError) as exc:
        raise AsmError(f"{name} {', '.join(args)}: {exc}") from None
    return b"".join(w.to_bytes(4, "little") for w in words)
