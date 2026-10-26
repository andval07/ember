"""32-bit integer arithmetic with C semantics, shared by the parser
(array sizes, global initializers) and the optimizer (constant folding)."""

from ember import ast

MASK = 0xFFFF_FFFF


def wrap(value: int) -> int:
    """Reduce to a signed 32-bit value, the way the CPU sees it."""
    value &= MASK
    return value - (1 << 32) if value & 0x8000_0000 else value


def binop(op: str, a: int, b: int) -> int | None:
    """Evaluate an IR binary op. None when it must not be folded (x / 0)."""
    a, b = wrap(a), wrap(b)
    ua, ub = a & MASK, b & MASK
    match op:
        case "add": return wrap(a + b)
        case "sub": return wrap(a - b)
        case "mul": return wrap(a * b)
        case "div" | "mod":
            if b == 0:
                return None
            q = abs(a) // abs(b)
            if (a < 0) != (b < 0):
                q = -q
            return wrap(q) if op == "div" else wrap(a - b * q)
        case "and": return wrap(a & b)
        case "or": return wrap(a | b)
        case "xor": return wrap(a ^ b)
        case "shl": return wrap(a << (b & 31))
        case "sra": return a >> (b & 31)
        case "shr": return wrap(ua >> (b & 31))
        case "eq": return int(a == b)
        case "ne": return int(a != b)
        case "lt": return int(a < b)
        case "le": return int(a <= b)
        case "gt": return int(a > b)
        case "ge": return int(a >= b)
        case "ltu": return int(ua < ub)
        case "leu": return int(ua <= ub)
        case "gtu": return int(ua > ub)
        case "geu": return int(ua >= ub)
    raise ValueError(f"unknown op {op}")


def unop(op: str, a: int) -> int:
    match op:
        case "neg": return wrap(-a)
        case "not": return wrap(~a)
        case "lnot": return int(wrap(a) == 0)
        case "sext8": return wrap(((a & 0xFF) ^ 0x80) - 0x80)
    raise ValueError(f"unknown op {op}")


# C operator -> IR op, for signed integer operands.
C_BINOPS = {
    "+": "add", "-": "sub", "*": "mul", "/": "div", "%": "mod", "&": "and",
    "|": "or", "^": "xor", "<<": "shl", ">>": "sra", "==": "eq", "!=": "ne",
    "<": "lt", "<=": "le", ">": "gt", ">=": "ge",
}


def eval_const(expr: ast.Expr) -> int | None:
    """Value of an integer constant expression, or None if it is not one."""
    match expr:
        case ast.Num(value=v):
            return wrap(v)
        case ast.SizeofType(of=ty):
            return ty.size()
        case ast.Unary(op=op, operand=x):
            v = eval_const(x)
            if v is None or op not in "-~!+":
                return None
            return {"-": unop("neg", v), "~": unop("not", v), "!": unop("lnot", v),
                    "+": v}[op]
        case ast.Binary(op=op, left=l, right=r):
            a, b = eval_const(l), eval_const(r)
            if a is None or b is None:
                return None
            if op == "&&":
                return int(bool(a) and bool(b))
            if op == "||":
                return int(bool(a) or bool(b))
            return binop(C_BINOPS[op], a, b)
        case ast.Cond(cond=c, then=t, other=o):
            v = eval_const(c)
            return None if v is None else eval_const(t if v else o)
        case ast.Cast(to=ty, operand=x):
            v = eval_const(x)
            if v is None or not ty.is_integer:
                return None
            return unop("sext8", v) if ty.size() == 1 else v
    return None
