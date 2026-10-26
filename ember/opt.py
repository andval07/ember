"""-O1: IR clean-up passes and a linear-scan register allocator.

Passes, repeated until nothing changes:
  - constant and copy propagation inside a basic block
  - constant folding and simple algebra (x+0, x*1, x*2^k -> shift, ...)
  - branch folding when both sides are constants
  - dead code elimination from liveness
  - unreachable code removal, jump threading, unused label removal

Register allocation: s1-s11 can hold any interval; t3-t6 only intervals that
do not cross a call (the runtime's * / % routines keep t-registers intact).
When registers run out, the interval that ends last is spilled to the stack.
"""

from ember.fold import binop, unop, wrap
from ember.ir import Function, Ins, Module, Temp

PURE = {"mov", "bin", "un", "load", "laddr", "gaddr"}
SAVED_REGS = [f"s{i}" for i in range(1, 12)]
TEMP_REGS = ["t3", "t4", "t5", "t6"]
CALL_SUBS = {"mul", "div", "mod"}


def optimize(module: Module) -> dict[str, dict[Temp, str]]:
    allocations = {}
    for fn in module.functions:
        simplify(fn)
        allocations[fn.name] = allocate(fn)
    return allocations


def simplify(fn: Function) -> None:
    for _ in range(50):
        changed = propagate(fn)
        changed |= fold(fn)
        changed |= tidy_jumps(fn)
        changed |= dead_code(fn)
        if not changed:
            return


# --- propagation -----------------------------------------------------------

def propagate(fn: Function) -> bool:
    """Replace uses of temps known to hold a constant or a copy of another
    temp. Facts are kept only inside a basic block."""
    changed = False
    known: dict[Temp, int | Temp] = {}
    for ins in fn.body:
        if ins.op == "label":
            known.clear()
            continue
        new_args = [known.get(a, a) if isinstance(a, Temp) else a for a in ins.args]
        if any(x is not y for x, y in zip(new_args, ins.args)):
            ins.args = new_args
            changed = True
        d = ins.dst
        if d is None:
            continue
        known.pop(d, None)
        for k in [k for k, v in known.items() if v is d]:
            del known[k]
        if ins.op == "mov" and ins.args[0] is not d:
            known[d] = ins.args[0]
    return changed


# --- folding ---------------------------------------------------------------

def fold(fn: Function) -> bool:
    changed = False
    body = []
    for ins in fn.body:
        new = fold_one(ins)
        changed |= new is not ins
        body.append(new)
    fn.body = body
    return changed


def mov(d: Temp, v) -> Ins:
    return Ins("mov", dst=d, args=[v])


def fold_one(ins: Ins) -> Ins:
    if ins.op == "bin":
        a, b = ins.args
        if isinstance(a, int) and isinstance(b, int):
            value = binop(ins.sub, a, b)
            if value is not None:
                return mov(ins.dst, wrap(value))
        return algebra(ins, a, b)
    if ins.op == "un" and isinstance(ins.args[0], int):
        return mov(ins.dst, unop(ins.sub, ins.args[0]))
    if ins.op == "br" and all(isinstance(a, int) for a in ins.args):
        taken = binop(ins.sub, *ins.args)
        return Ins("jmp", target=ins.target if taken else ins.target2)
    return ins


def algebra(ins: Ins, a, b) -> Ins:
    sub, d = ins.sub, ins.dst
    commutes = sub in ("add", "mul", "and", "or", "xor", "eq", "ne")
    if isinstance(a, int) and not isinstance(b, int) and commutes:
        return Ins("bin", dst=d, args=[b, a], sub=sub)
    if not isinstance(b, int):
        return ins
    if b == 0 and sub in ("add", "sub", "or", "xor", "shl", "sra", "shr"):
        return mov(d, a)
    if b == 0 and sub in ("mul", "and"):
        return mov(d, 0)
    if b == 1 and sub in ("mul", "div"):
        return mov(d, a)
    if b == 1 and sub == "mod":
        return mov(d, 0)
    if sub == "mul" and b > 0 and b & (b - 1) == 0:
        return Ins("bin", dst=d, args=[a, b.bit_length() - 1], sub="shl")
    return ins


# --- control flow ----------------------------------------------------------

def tidy_jumps(fn: Function) -> bool:
    body = fn.body
    # A label followed directly by "jmp X" can be replaced by X.
    alias: dict[str, str] = {}
    for i, ins in enumerate(body[:-1]):
        nxt = body[i + 1]
        if ins.op == "label" and nxt.op == "jmp" and nxt.target != ins.target:
            alias[ins.target] = nxt.target

    def final(name: str) -> str:
        seen = set()
        while name in alias and name not in seen:
            seen.add(name)
            name = alias[name]
        return name

    changed = False
    for ins in body:
        if ins.op in ("jmp", "br"):
            for attr in ("target", "target2"):
                old = getattr(ins, attr)
                if old is not None and final(old) != old:
                    setattr(ins, attr, final(old))
                    changed = True
        if ins.op == "br" and ins.target == ins.target2:
            ins.op, ins.args, ins.sub, ins.target2 = "jmp", [], None, None
            changed = True
    used = {t for ins in body if ins.op in ("jmp", "br")
            for t in (ins.target, ins.target2) if t}
    out: list[Ins] = []
    reachable = True
    for ins in body:
        if ins.op == "label":
            if ins.target not in used:
                changed = True
                continue
            reachable = True
        if not reachable:
            changed = True
            continue
        out.append(ins)
        if ins.op in ("jmp", "ret"):
            reachable = False
    # Drop "jmp L" right before "L:".
    final_body = []
    for i, ins in enumerate(out):
        nxt = out[i + 1] if i + 1 < len(out) else None
        if ins.op == "jmp" and nxt is not None and nxt.op == "label" and nxt.target == ins.target:
            changed = True
            continue
        final_body.append(ins)
    fn.body = final_body
    return changed


# --- liveness --------------------------------------------------------------

def successors(body: list[Ins]) -> list[list[int]]:
    where = {ins.target: i for i, ins in enumerate(body) if ins.op == "label"}
    succ = []
    for i, ins in enumerate(body):
        if ins.op == "jmp":
            succ.append([where[ins.target]])
        elif ins.op == "br":
            succ.append([where[ins.target], where[ins.target2]])
        elif ins.op == "ret" or i + 1 == len(body):
            succ.append([])
        else:
            succ.append([i + 1])
    return succ


def liveness(body: list[Ins]) -> list[set[Temp]]:
    """Temps live after each instruction."""
    succ = successors(body)
    live_in: list[set[Temp]] = [set() for _ in body]
    live_out: list[set[Temp]] = [set() for _ in body]
    changed = True
    while changed:
        changed = False
        for i in range(len(body) - 1, -1, -1):
            out = set()
            for s in succ[i]:
                out |= live_in[s]
            ins = body[i]
            new_in = (out - {ins.dst}) | set(ins.uses())
            if out != live_out[i] or new_in != live_in[i]:
                live_out[i], live_in[i] = out, new_in
                changed = True
    return live_out


def dead_code(fn: Function) -> bool:
    live_out = liveness(fn.body)
    body = [ins for ins, out in zip(fn.body, live_out)
            if not (ins.op in PURE and ins.dst not in out)]
    changed = len(body) != len(fn.body)
    fn.body = body
    return changed


# --- register allocation ---------------------------------------------------

def is_call(ins: Ins) -> bool:
    return ins.op == "call" or (ins.op == "bin" and ins.sub in CALL_SUBS)


def intervals(fn: Function) -> dict[Temp, list[int]]:
    """[first, last] instruction index where each temp is defined or live.
    Parameters start at -1 (they arrive in a-registers before the body)."""
    span: dict[Temp, list[int]] = {}

    def touch(t: Temp, i: int) -> None:
        if t in span:
            span[t][0] = min(span[t][0], i)
            span[t][1] = max(span[t][1], i)
        else:
            span[t] = [i, i]

    for t in fn.params:
        touch(t, -1)
    for i, (ins, out) in enumerate(zip(fn.body, liveness(fn.body))):
        for t in ins.uses():
            touch(t, i)
        if ins.dst is not None:
            touch(ins.dst, i)
        for t in out:
            touch(t, i)
    return span


def allocate(fn: Function) -> dict[Temp, str]:
    span = intervals(fn)
    calls = [i for i, ins in enumerate(fn.body) if is_call(ins)]

    def crosses_call(t: Temp) -> bool:
        lo, hi = span[t]
        return any(lo < c < hi for c in calls)

    regs: dict[Temp, str] = {}
    active: list[Temp] = []
    free_s, free_t = list(SAVED_REGS), list(TEMP_REGS)
    for t in sorted(span, key=lambda t: (span[t][0], t.id)):
        start = span[t][0]
        for old in [a for a in active if span[a][1] < start]:
            active.remove(old)
            (free_s if regs[old].startswith("s") else free_t).insert(0, regs[old])
        pool = free_s if crosses_call(t) else (free_t or free_s)
        if pool:
            regs[t] = pool.pop(0)
            active.append(t)
            continue
        # Spill whichever interval ends last, if it can give t its register.
        victims = [a for a in active if not crosses_call(t) or regs[a].startswith("s")]
        victim = max(victims, key=lambda a: span[a][1], default=None)
        if victim is not None and span[victim][1] > span[t][1]:
            regs[t] = regs.pop(victim)
            active.remove(victim)
            active.append(t)
    return regs
