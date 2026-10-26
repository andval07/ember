"""AST to IR.

With promote=False (-O0) every variable lives in memory. With promote=True
(-O1) scalar locals and parameters whose address is never taken become temps,
so the register allocator can keep them in registers.
"""

from ember import ast
from ember.check import Symbol
from ember.ctypes import CHAR, INT, VOID, ArrayType, Type, align_of
from ember.fold import C_BINOPS
from ember.ir import Data, Function, Global, Ins, Module, Slot, Temp


def lower(program: ast.Program, promote: bool) -> Module:
    return Lowerer(promote).module(program)


def is_pow2(n: int) -> bool:
    return n > 0 and n & (n - 1) == 0


class Lowerer:
    def __init__(self, promote: bool) -> None:
        self.promote = promote
        self.data: list[Data] = []
        self.strings: dict[bytes, str] = {}
        self.labels = 0

    # --- module ------------------------------------------------------------

    def module(self, program: ast.Program) -> Module:
        functions = []
        for decl in program.decls:
            if isinstance(decl, ast.VarDecl):
                self.global_data(decl)
            elif decl.body is not None:
                functions.append(self.function(decl))
        return Module(functions, self.data)

    def string(self, data: bytes) -> str:
        if data not in self.strings:
            name = f".Lstr{len(self.strings)}"
            self.strings[data] = name
            self.data.append(Data(name, 1, [data + b"\0"]))
        return self.strings[data]

    def global_data(self, decl: ast.VarDecl) -> None:
        ty, init = decl.ty, decl.init
        parts: list[bytes | tuple[str, str]] = []
        if init is None:
            parts.append(bytes(ty.size()))
        elif isinstance(ty, ArrayType) and isinstance(init, ast.Str):
            parts.append(init.data.ljust(ty.size(), b"\0"))
        elif isinstance(init, list):
            esize = ty.base.size()
            for item in init:
                parts.append(const_bytes(item, esize))
            parts.append(bytes(esize * (ty.length - len(init))))
        elif isinstance(init, ast.Str):  # char *p = "..."
            parts.append(("word", self.string(init.data)))
        else:
            parts.append(const_bytes(init, ty.size()))
        self.data.append(Data(decl.name, align_of(ty), parts))

    # --- function ----------------------------------------------------------

    def function(self, fn: ast.Function) -> Function:
        self.body: list[Ins] = []
        self.slots: list[Slot] = []
        self.ntemps = 0
        self.vars: dict[Symbol, Temp | Slot] = {}
        self.loops: list[tuple[str, str]] = []
        self.ret_type = fn.ret
        params = []
        for p in fn.params:
            t = self.temp(p.name)
            params.append(t)
            if self.keeps_in_temp(p.sym):
                self.vars[p.sym] = t
            else:
                slot = self.slot(p.ty, p.name)
                self.vars[p.sym] = slot
                self.emit("store", args=[slot, t], sub=p.ty.size())
        self.stmt(fn.body)
        if not self.body or self.body[-1].op != "ret":
            self.emit("ret", args=[] if fn.ret == VOID else [0])
        return Function(fn.name, params, self.body, self.slots, self.ntemps)

    def keeps_in_temp(self, sym: Symbol) -> bool:
        return self.promote and sym.ty.is_scalar and not sym.addr_taken

    def temp(self, hint: str = "") -> Temp:
        self.ntemps += 1
        return Temp(self.ntemps, hint)

    def slot(self, ty: Type, name: str) -> Slot:
        s = Slot(ty.size(), max(align_of(ty), 1), name)
        self.slots.append(s)
        return s

    def label(self, hint: str) -> str:
        self.labels += 1
        return f".L{hint}{self.labels}"

    def emit(self, op: str, **kw) -> Ins:
        ins = Ins(op, **kw)
        self.body.append(ins)
        return ins

    def place(self, name: str) -> None:
        self.emit("label", target=name)

    def new(self, op: str, args: list, sub=None, hint: str = "") -> Temp:
        t = self.temp(hint)
        self.emit(op, dst=t, args=args, sub=sub)
        return t

    # --- statements --------------------------------------------------------

    def stmt(self, s: ast.Stmt) -> None:
        match s:
            case ast.VarDecl():
                self.local(s)
            case ast.Block():
                for item in s.items:
                    self.stmt(item)
            case ast.ExprStmt(expr=e):
                if e is not None:
                    self.rvalue(e)
            case ast.If():
                then, end = self.label("then"), self.label("endif")
                other = self.label("else") if s.other is not None else end
                self.branch(s.cond, then, other)
                self.place(then)
                self.stmt(s.then)
                if s.other is not None:
                    self.emit("jmp", target=end)
                    self.place(other)
                    self.stmt(s.other)
                self.place(end)
            case ast.While():
                top, body, end = self.label("while"), self.label("body"), self.label("endw")
                self.place(top)
                self.branch(s.cond, body, end)
                self.place(body)
                self.loop(s.body, end, top)
                self.emit("jmp", target=top)
                self.place(end)
            case ast.DoWhile():
                top, cont, end = self.label("do"), self.label("dcond"), self.label("endd")
                self.place(top)
                self.loop(s.body, end, cont)
                self.place(cont)
                self.branch(s.cond, top, end)
                self.place(end)
            case ast.For():
                if s.init is not None:
                    self.stmt(s.init)
                top, body = self.label("for"), self.label("fbody")
                step, end = self.label("fstep"), self.label("endf")
                self.place(top)
                if s.cond is not None:
                    self.branch(s.cond, body, end)
                self.place(body)
                self.loop(s.body, end, step)
                self.place(step)
                if s.step is not None:
                    self.rvalue(s.step)
                self.emit("jmp", target=top)
                self.place(end)
            case ast.Return(value=v):
                if v is None:
                    self.emit("ret", args=[])
                else:
                    self.emit("ret", args=[self.convert(self.rvalue(v), v.ty, self.ret_type)])
                self.place(self.label("dead"))
            case ast.Break():
                self.emit("jmp", target=self.loops[-1][0])
                self.place(self.label("dead"))
            case ast.Continue():
                self.emit("jmp", target=self.loops[-1][1])
                self.place(self.label("dead"))

    def loop(self, body: ast.Stmt, brk: str, cont: str) -> None:
        self.loops.append((brk, cont))
        self.stmt(body)
        self.loops.pop()

    def local(self, decl: ast.VarDecl) -> None:
        sym, ty, init = decl.sym, decl.ty, decl.init
        if self.keeps_in_temp(sym):
            t = self.temp(decl.name)
            self.vars[sym] = t
            if init is not None:
                self.emit("mov", dst=t, args=[self.convert(self.rvalue(init), init.ty, ty)])
            return
        slot = self.slot(ty, decl.name)
        self.vars[sym] = slot
        if init is None:
            return
        if not isinstance(ty, ArrayType):
            self.emit("store", args=[slot, self.rvalue(init)], sub=ty.size())
            return
        base = self.new("laddr", [slot])
        esize = ty.base.size()
        if isinstance(init, ast.Str):
            values = list(init.data.ljust(ty.length, b"\0"))
            items = [(i, v) for i, v in enumerate(values)]
        else:
            items = [(i, self.rvalue(e)) for i, e in enumerate(init)]
            items += [(i, 0) for i in range(len(init), ty.length)]
        for i, v in items:
            addr = base if i == 0 else self.new("bin", [base, i * esize], "add")
            self.emit("store", args=[addr, v], sub=esize)

    # --- conditions --------------------------------------------------------

    def branch(self, e: ast.Expr, yes: str, no: str) -> None:
        """Jump to yes if e is true, else to no. && and || short-circuit."""
        if isinstance(e, ast.Binary) and e.op in ("&&", "||"):
            mid = self.label("sc")
            if e.op == "&&":
                self.branch(e.left, mid, no)
            else:
                self.branch(e.left, yes, mid)
            self.place(mid)
            self.branch(e.right, yes, no)
            return
        if isinstance(e, ast.Unary) and e.op == "!":
            self.branch(e.operand, no, yes)
            return
        if isinstance(e, ast.Binary) and e.op in ("==", "!=", "<", "<=", ">", ">="):
            a, b = self.rvalue(e.left), self.rvalue(e.right)
            self.emit("br", args=[a, b], sub=self.compare_op(e), target=yes, target2=no)
            return
        self.emit("br", args=[self.rvalue(e), 0], sub="ne", target=yes, target2=no)

    def compare_op(self, e: ast.Binary) -> str:
        op = C_BINOPS[e.op]
        pointers = e.left.ty.decay().is_pointer or e.right.ty.decay().is_pointer
        if pointers and op in ("lt", "le", "gt", "ge"):
            op += "u"
        return op

    def bool_value(self, e: ast.Expr) -> Temp:
        t = self.temp("b")
        yes, no, end = self.label("t"), self.label("f"), self.label("endb")
        self.branch(e, yes, no)
        self.place(yes)
        self.emit("mov", dst=t, args=[1])
        self.emit("jmp", target=end)
        self.place(no)
        self.emit("mov", dst=t, args=[0])
        self.place(end)
        return t

    # --- expressions -------------------------------------------------------

    def convert(self, v, src: Type, to: Type):
        if to == CHAR and src != CHAR:
            if isinstance(v, int):
                return ((v & 0xFF) ^ 0x80) - 0x80
            return self.new("un", [v], "sext8")
        return v

    def address(self, e: ast.Expr):
        """Address of an lvalue: a Temp, a Slot or a Global."""
        match e:
            case ast.Name():
                loc = self.vars.get(e.sym)
                if loc is None:
                    return Global(e.name)
                return loc
            case ast.Index():
                return self.pointer_add(self.rvalue(e.base), self.rvalue(e.index),
                                        e.base.ty.decay().base.size(), "add")
            case ast.Unary(op="*"):
                return self.rvalue(e.operand)
            case ast.Str():
                return Global(self.string(e.data))
        raise AssertionError(f"not an lvalue: {e}")

    def addr_value(self, addr):
        """Turn an address from address() into an operand holding it."""
        if isinstance(addr, Slot):
            return self.new("laddr", [addr])
        if isinstance(addr, Global):
            return self.new("gaddr", [addr])
        return addr

    def read(self, e: ast.Expr):
        """Value of a variable or memory location."""
        if isinstance(e, ast.Name) and isinstance(self.vars.get(e.sym), Temp):
            return self.vars[e.sym]
        return self.new("load", [self.address(e)], e.ty.size())

    def write(self, e: ast.Expr, addr, v) -> None:
        if isinstance(addr, Temp) and isinstance(e, ast.Name) and self.vars.get(e.sym) is addr:
            self.emit("mov", dst=addr, args=[v])
        else:
            self.emit("store", args=[addr, v], sub=e.ty.size())

    def scale(self, index, size: int):
        if size == 1:
            return index
        if isinstance(index, int):
            return index * size
        if is_pow2(size):
            return self.new("bin", [index, size.bit_length() - 1], "shl")
        return self.new("bin", [index, size], "mul")

    def pointer_add(self, ptr, index, size: int, op: str):
        return self.new("bin", [ptr, self.scale(index, size)], op)

    def rvalue(self, e: ast.Expr):
        if isinstance(e.ty, ArrayType) and not isinstance(e, ast.Str):
            return self.addr_value(self.address(e))  # array decays to a pointer
        match e:
            case ast.Num():
                return e.value
            case ast.Str():
                return self.new("gaddr", [Global(self.string(e.data))])
            case ast.Name() | ast.Index():
                return self.read(e)
            case ast.Unary():
                return self.unary(e)
            case ast.Binary():
                return self.binary(e)
            case ast.Assign():
                return self.assign(e)
            case ast.IncDec():
                return self.incdec(e)
            case ast.Cond():
                t = self.temp("c")
                yes, no, end = self.label("ct"), self.label("cf"), self.label("endc")
                self.branch(e.cond, yes, no)
                self.place(yes)
                if e.ty != VOID:
                    self.emit("mov", dst=t, args=[self.rvalue(e.then)])
                else:
                    self.rvalue(e.then)
                self.emit("jmp", target=end)
                self.place(no)
                if e.ty != VOID:
                    self.emit("mov", dst=t, args=[self.rvalue(e.other)])
                else:
                    self.rvalue(e.other)
                self.place(end)
                return t
            case ast.Call():
                args = [self.convert(self.rvalue(a), a.ty, p)
                        for a, p in zip(e.args, e.sym.ty.params)]
                dst = None if e.ty == VOID else self.temp("r")
                self.emit("call", dst=dst, args=args, sym=e.name)
                return dst if dst is not None else 0
            case ast.Cast():
                v = self.rvalue(e.operand)
                return v if e.to == VOID else self.convert(v, e.operand.ty, e.to)
            case ast.SizeofType():
                return e.of.size()
            case ast.SizeofExpr():
                return e.operand.ty.size()
        raise AssertionError(f"unknown expression {e}")

    def unary(self, e: ast.Unary):
        if e.op == "&":
            return self.addr_value(self.address(e.operand))
        if e.op == "*":
            return self.read(e)
        if e.op == "+":
            return self.rvalue(e.operand)
        if e.op == "!":
            return self.new("bin", [self.rvalue(e.operand), 0], "eq")
        sub = {"-": "neg", "~": "not"}[e.op]
        return self.new("un", [self.rvalue(e.operand)], sub)

    def binary(self, e: ast.Binary):
        if e.op in ("&&", "||"):
            return self.bool_value(e)
        a, b = self.rvalue(e.left), self.rvalue(e.right)
        lt, rt = e.left.ty.decay(), e.right.ty.decay()
        if e.op in ("==", "!=", "<", "<=", ">", ">="):
            return self.new("bin", [a, b], self.compare_op(e))
        return self.arith(e.op, a, lt, b, rt)

    def arith(self, op: str, a, lt: Type, b, rt: Type):
        """a op b with pointer scaling. op is a C operator like + or <<."""
        if op == "+" and lt.is_integer and rt.is_pointer:
            a, lt, b, rt = b, rt, a, lt
        if op in ("+", "-") and lt.is_pointer and rt.is_integer:
            return self.pointer_add(a, b, lt.base.size(), C_BINOPS[op])
        if op == "-" and lt.is_pointer and rt.is_pointer:
            diff = self.new("bin", [a, b], "sub")
            size = lt.base.size()
            if size == 1:
                return diff
            if is_pow2(size):
                return self.new("bin", [diff, size.bit_length() - 1], "sra")
            return self.new("bin", [diff, size], "div")
        return self.new("bin", [a, b], C_BINOPS[op])

    def assign(self, e: ast.Assign):
        target, to = e.target, e.target.ty
        addr = self.address(target)
        if e.op == "=":
            v = self.convert(self.rvalue(e.value), e.value.ty, to)
        else:
            old = self.read_at(target, addr)
            rhs = self.rvalue(e.value)
            v = self.arith(e.op[:-1], old, to, rhs, e.value.ty.decay())
            v = self.convert(v, INT, to)
        self.write(target, addr, v)
        return v

    def read_at(self, e: ast.Expr, addr):
        if isinstance(addr, Temp) and isinstance(e, ast.Name) and self.vars.get(e.sym) is addr:
            return addr
        return self.new("load", [addr], e.ty.size())

    def incdec(self, e: ast.IncDec):
        target, ty = e.target, e.target.ty
        addr = self.address(target)
        old = self.read_at(target, addr)
        if not e.prefix and isinstance(old, Temp) and old is addr:
            old = self.new("mov", [old])  # keep the old value of a promoted var
        step = ty.base.size() if ty.is_pointer else 1
        new = self.new("bin", [old, step], "add" if e.op == "++" else "sub")
        new = self.convert(new, INT, ty)
        self.write(target, addr, new)
        return new if e.prefix else old


def const_bytes(expr: ast.Expr, size: int) -> bytes:
    from ember.fold import eval_const

    value = eval_const(expr)
    return (value & ((1 << (8 * size)) - 1)).to_bytes(size, "little")
