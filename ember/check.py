"""Type checker: resolves names, computes expression types, rejects bad programs.

After check() every Expr has `ty` set and every Name/Call/VarDecl/Param has
`sym` pointing at a Symbol.
"""

from dataclasses import dataclass, field

from ember import ast
from ember.ctypes import CHAR, INT, VOID, ArrayType, FuncType, PtrType, Type, VoidType
from ember.errors import CompileError
from ember.fold import eval_const

MAX_ARGS = 8


@dataclass(eq=False)
class Symbol:
    name: str
    ty: Type
    kind: str  # global, local, param, func
    addr_taken: bool = False
    defined: bool = False
    builtin: bool = False
    uid: int = field(default=0)


PUTCHAR = FuncType(INT, (INT,))


def check(program: ast.Program) -> dict[str, Symbol]:
    """Check a program in place. Returns the global symbol table."""
    return Checker().program(program)


def err(msg: str, node: ast.Node) -> CompileError:
    return CompileError(msg, node.line)


def is_null(expr: ast.Expr) -> bool:
    return isinstance(expr, ast.Num) and expr.value == 0


def assignable(to: Type, expr: ast.Expr) -> bool:
    src = expr.ty.decay()
    if to.is_integer and src.is_integer:
        return True
    if to.is_pointer:
        if is_null(expr):
            return True
        if src.is_pointer:
            return src == to or isinstance(to.base, VoidType) or isinstance(src.base, VoidType)
    return False


class Checker:
    def __init__(self) -> None:
        self.globals: dict[str, Symbol] = {}
        self.scopes: list[dict[str, Symbol]] = []
        self.func: ast.Function | None = None
        self.loops = 0
        self.uid = 0
        self.globals["putchar"] = Symbol("putchar", PUTCHAR, "func", defined=True, builtin=True)

    def new_sym(self, *args, **kw) -> Symbol:
        self.uid += 1
        return Symbol(*args, uid=self.uid, **kw)

    # --- scopes ------------------------------------------------------------

    def lookup(self, name: str, node: ast.Node) -> Symbol:
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        if name in self.globals:
            return self.globals[name]
        raise err(f"{name!r} is not declared", node)

    def declare_local(self, sym: Symbol, node: ast.Node) -> None:
        scope = self.scopes[-1]
        if sym.name in scope:
            raise err(f"{sym.name!r} is already declared in this scope", node)
        scope[sym.name] = sym

    # --- top level ---------------------------------------------------------

    def program(self, program: ast.Program) -> dict[str, Symbol]:
        for decl in program.decls:
            if isinstance(decl, ast.Function):
                self.function(decl)
            else:
                self.global_var(decl)
        main = self.globals.get("main")
        if main is None or main.kind != "func" or not main.defined:
            raise CompileError("no main function", 1)
        if main.ty.params or main.ty.ret != INT:
            raise CompileError("main must be 'int main(void)'", 1)
        return self.globals

    def global_var(self, decl: ast.VarDecl) -> None:
        self.check_object_type(decl.ty, decl)
        if decl.name in self.globals:
            raise err(f"{decl.name!r} is already declared", decl)
        sym = self.new_sym(decl.name, decl.ty, "global", defined=True)
        self.globals[decl.name] = sym
        decl.sym = sym
        if decl.init is not None:
            self.initializer(decl, constant=True)

    def function(self, fn: ast.Function) -> None:
        if fn.ret != VOID:
            self.check_object_type(fn.ret, fn)
            if isinstance(fn.ret, ArrayType):
                raise err("functions cannot return arrays", fn)
        if len(fn.params) > MAX_ARGS:
            raise err(f"at most {MAX_ARGS} parameters are supported", fn)
        for p in fn.params:
            self.check_object_type(p.ty, p)
        ty = FuncType(fn.ret, tuple(p.ty for p in fn.params))
        sym = self.globals.get(fn.name)
        if sym is not None:
            if sym.kind != "func" or sym.ty != ty:
                raise err(f"conflicting declaration of {fn.name!r}", fn)
            if fn.body is not None and (sym.defined or sym.builtin):
                raise err(f"{fn.name!r} is already defined", fn)
        else:
            sym = self.new_sym(fn.name, ty, "func")
            self.globals[fn.name] = sym
        if fn.body is None:
            return
        sym.defined = True
        self.func = fn
        self.scopes = [{}]
        for p in fn.params:
            p.sym = self.new_sym(p.name, p.ty, "param")
            self.declare_local(p.sym, p)
        self.block(fn.body, new_scope=False)
        self.scopes = []
        self.func = None

    def check_object_type(self, ty: Type, node: ast.Node) -> None:
        while isinstance(ty, ArrayType):
            ty = ty.base
        if isinstance(ty, VoidType):
            raise err("variables cannot have type void", node)

    def initializer(self, decl: ast.VarDecl, constant: bool) -> None:
        ty, init = decl.ty, decl.init
        if isinstance(ty, ArrayType):
            if isinstance(init, ast.Str):
                if ty.base != CHAR:
                    raise err("only char arrays take a string initializer", decl)
                if len(init.data) > ty.length:
                    raise err("string is longer than the array", decl)
                init.ty = ArrayType(CHAR, len(init.data) + 1)
                return
            if not isinstance(init, list):
                raise err("an array needs a {...} initializer", decl)
            if isinstance(ty.base, ArrayType):
                raise err("initializers for multi-dimensional arrays are not supported", decl)
            if len(init) > ty.length:
                raise err("too many initializers", decl)
            for item in init:
                self.init_value(ty.base, item, decl, constant)
            return
        if isinstance(init, list):
            raise err("a scalar needs a single initializer", decl)
        self.init_value(ty, init, decl, constant)

    def init_value(self, ty: Type, expr: ast.Expr, decl: ast.VarDecl, constant: bool) -> None:
        self.expr(expr)
        if not assignable(ty, expr):
            raise err(f"cannot initialize {ty} with {expr.ty}", decl)
        if constant:
            if isinstance(expr, ast.Str) and ty == PtrType(CHAR):
                return
            if eval_const(expr) is None or (ty.is_pointer and not is_null(expr)):
                raise err("global initializers must be constants", decl)

    # --- statements --------------------------------------------------------

    def block(self, block: ast.Block, new_scope: bool = True) -> None:
        if new_scope:
            self.scopes.append({})
        for item in block.items:
            self.stmt(item)
        if new_scope:
            self.scopes.pop()

    def stmt(self, s: ast.Stmt) -> None:
        match s:
            case ast.VarDecl():
                self.check_object_type(s.ty, s)
                s.sym = self.new_sym(s.name, s.ty, "local")
                # The name is visible in its own initializer, as in C.
                self.declare_local(s.sym, s)
                if s.init is not None:
                    self.initializer(s, constant=False)
            case ast.Block():
                self.block(s)
            case ast.ExprStmt(expr=e):
                if e is not None:
                    self.expr(e)
            case ast.If():
                self.cond(s.cond)
                self.stmt(s.then)
                if s.other is not None:
                    self.stmt(s.other)
            case ast.While() | ast.DoWhile():
                self.cond(s.cond)
                self.loop_body(s.body)
            case ast.For():
                if s.init is not None:
                    self.stmt(s.init)
                if s.cond is not None:
                    self.cond(s.cond)
                if s.step is not None:
                    self.expr(s.step)
                self.loop_body(s.body)
            case ast.Return(value=v):
                ret = self.func.ret
                if v is None:
                    if ret != VOID:
                        raise err("this function must return a value", s)
                    return
                self.expr(v)
                if ret == VOID:
                    raise err("a void function cannot return a value", s)
                if not assignable(ret, v):
                    raise err(f"cannot return {v.ty} from a function returning {ret}", s)
            case ast.Break() | ast.Continue():
                if self.loops == 0:
                    word = "break" if isinstance(s, ast.Break) else "continue"
                    raise err(f"{word} outside a loop", s)
            case _:
                raise err(f"unknown statement {type(s).__name__}", s)

    def loop_body(self, body: ast.Stmt) -> None:
        self.loops += 1
        self.stmt(body)
        self.loops -= 1

    def cond(self, e: ast.Expr) -> None:
        self.expr(e)
        if not e.ty.is_scalar:
            raise err(f"condition has type {e.ty}", e)

    # --- expressions -------------------------------------------------------

    def value(self, e: ast.Expr) -> Type:
        """Check e and return its type after array-to-pointer decay."""
        self.expr(e)
        return e.ty.decay()

    def scalar(self, e: ast.Expr, what: str) -> Type:
        ty = self.value(e)
        if not ty.is_scalar:
            raise err(f"{what} needs a scalar, got {ty}", e)
        return ty

    def integer(self, e: ast.Expr, what: str) -> Type:
        ty = self.value(e)
        if not ty.is_integer:
            raise err(f"{what} needs an integer, got {ty}", e)
        return ty

    def lvalue(self, e: ast.Expr, what: str) -> None:
        ok = (
            (isinstance(e, ast.Name) and e.sym.kind != "func")
            or isinstance(e, ast.Index)
            or (isinstance(e, ast.Unary) and e.op == "*")
        )
        if not ok:
            raise err(f"{what} needs a variable or memory location", e)
        if isinstance(e.ty, ArrayType):
            raise err(f"cannot assign to array {e.ty}", e)

    def expr(self, e: ast.Expr) -> None:
        e.ty = self.compute(e)

    def compute(self, e: ast.Expr) -> Type:
        match e:
            case ast.Num():
                return INT
            case ast.Str():
                return ArrayType(CHAR, len(e.data) + 1)
            case ast.Name():
                e.sym = self.lookup(e.name, e)
                if e.sym.kind == "func":
                    raise err(f"function {e.name!r} used as a value", e)
                return e.sym.ty
            case ast.Unary():
                return self.unary(e)
            case ast.Binary():
                return self.binary(e)
            case ast.Assign():
                return self.assign(e)
            case ast.IncDec():
                ty = self.scalar(e.target, e.op)
                self.lvalue(e.target, e.op)
                return ty
            case ast.Cond():
                self.scalar(e.cond, "?:")
                a, b = self.value(e.then), self.value(e.other)
                if a.is_integer and b.is_integer:
                    return INT
                if a.is_pointer and (b == a or is_null(e.other)):
                    return a
                if b.is_pointer and is_null(e.then):
                    return b
                if a == VOID and b == VOID:
                    return VOID
                raise err(f"?: branches have types {a} and {b}", e)
            case ast.Call():
                return self.call(e)
            case ast.Index():
                base, index = self.value(e.base), self.value(e.index)
                if index.is_pointer and base.is_integer:  # i[a] is a[i]
                    e.base, e.index = e.index, e.base
                    base, index = index, base
                if not base.is_pointer or not index.is_integer:
                    raise err(f"cannot index {base} with {index}", e)
                if base.base == VOID:
                    raise err("cannot index a void pointer", e)
                return base.base
            case ast.Cast():
                src = self.value(e.operand)
                if e.to == VOID:
                    return VOID
                if not e.to.is_scalar or not src.is_scalar:
                    raise err(f"cannot cast {src} to {e.to}", e)
                return e.to
            case ast.SizeofType():
                if e.of == VOID:
                    raise err("sizeof(void) is not allowed", e)
                return INT
            case ast.SizeofExpr():
                self.expr(e.operand)  # no decay: sizeof(array) is the full size
                if e.operand.ty == VOID:
                    raise err("sizeof of a void expression", e)
                return INT
        raise err(f"unknown expression {type(e).__name__}", e)

    def unary(self, e: ast.Unary) -> Type:
        if e.op == "&":
            self.expr(e.operand)
            x = e.operand
            if isinstance(x, ast.Name) and x.sym.kind != "func":
                x.sym.addr_taken = True
            elif not (isinstance(x, ast.Index) or (isinstance(x, ast.Unary) and x.op == "*")):
                raise err("& needs a variable or memory location", e)
            return PtrType(x.ty)
        if e.op == "*":
            ty = self.value(e.operand)
            if not ty.is_pointer:
                raise err(f"cannot dereference {ty}", e)
            if ty.base == VOID:
                raise err("cannot dereference a void pointer", e)
            return ty.base
        if e.op == "!":
            self.scalar(e.operand, "!")
            return INT
        self.integer(e.operand, e.op)
        return INT

    def binary(self, e: ast.Binary) -> Type:
        op = e.op
        if op in ("&&", "||"):
            self.scalar(e.left, op)
            self.scalar(e.right, op)
            return INT
        a, b = self.scalar(e.left, op), self.scalar(e.right, op)
        if op in ("==", "!=", "<", "<=", ">", ">="):
            if a.is_integer and b.is_integer:
                return INT
            if a.is_pointer and b.is_pointer and (a == b or VOID in (a.base, b.base)):
                return INT
            if (a.is_pointer and is_null(e.right)) or (b.is_pointer and is_null(e.left)):
                return INT
            raise err(f"cannot compare {a} and {b}", e)
        if op == "+":
            if a.is_pointer and b.is_integer:
                return self.ptr_arith(a, e)
            if a.is_integer and b.is_pointer:
                return self.ptr_arith(b, e)
        if op == "-":
            if a.is_pointer and b.is_integer:
                return self.ptr_arith(a, e)
            if a.is_pointer and b.is_pointer:
                if a != b:
                    raise err(f"cannot subtract {b} from {a}", e)
                self.ptr_arith(a, e)
                return INT
        if a.is_integer and b.is_integer:
            return INT
        raise err(f"invalid operands {a} {op} {b}", e)

    def ptr_arith(self, ty: PtrType, e: ast.Node) -> Type:
        if ty.base == VOID:
            raise err("arithmetic on a void pointer", e)
        return ty

    def assign(self, e: ast.Assign) -> Type:
        self.expr(e.target)
        self.lvalue(e.target, e.op)
        to = e.target.ty
        self.value(e.value)
        if e.op == "=":
            if not assignable(to, e.value):
                raise err(f"cannot assign {e.value.ty.decay()} to {to}", e)
            return to
        # Compound: check as the binary operation it stands for.
        src = e.value.ty.decay()
        if to.is_pointer and e.op in ("+=", "-=") and src.is_integer:
            return to
        if to.is_integer and src.is_integer:
            return to
        raise err(f"invalid operands {to} {e.op} {src}", e)

    def call(self, e: ast.Call) -> Type:
        sym = self.lookup(e.name, e)
        if sym.kind != "func":
            raise err(f"{e.name!r} is not a function", e)
        e.sym = sym
        params = sym.ty.params
        if len(e.args) != len(params):
            raise err(f"{e.name} takes {len(params)} arguments, got {len(e.args)}", e)
        for i, (arg, pty) in enumerate(zip(e.args, params), 1):
            self.value(arg)
            if not assignable(pty, arg):
                raise err(f"argument {i} of {e.name}: cannot pass {arg.ty.decay()} as {pty}", arg)
        return sym.ty.ret
