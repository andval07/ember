"""AST nodes. The type checker fills in `ty` on expressions and `sym` on names."""

from dataclasses import dataclass, field

from ember.ctypes import Type


@dataclass(eq=False)
class Node:
    line: int


# --- expressions -----------------------------------------------------------


@dataclass(eq=False)
class Expr(Node):
    ty: Type | None = field(default=None, init=False)


@dataclass(eq=False)
class Num(Expr):
    value: int


@dataclass(eq=False)
class Str(Expr):
    data: bytes


@dataclass(eq=False)
class Name(Expr):
    name: str
    sym: object = field(default=None, init=False)


@dataclass(eq=False)
class Unary(Expr):
    op: str  # - + ! ~ * &
    operand: Expr


@dataclass(eq=False)
class Binary(Expr):
    op: str
    left: Expr
    right: Expr


@dataclass(eq=False)
class Assign(Expr):
    op: str  # = += -= ...
    target: Expr
    value: Expr


@dataclass(eq=False)
class IncDec(Expr):
    op: str  # ++ or --
    prefix: bool
    target: Expr


@dataclass(eq=False)
class Cond(Expr):
    cond: Expr
    then: Expr
    other: Expr


@dataclass(eq=False)
class Call(Expr):
    name: str
    args: list[Expr]
    sym: object = field(default=None, init=False)


@dataclass(eq=False)
class Index(Expr):
    base: Expr
    index: Expr


@dataclass(eq=False)
class Cast(Expr):
    to: Type
    operand: Expr


@dataclass(eq=False)
class SizeofType(Expr):
    of: Type


@dataclass(eq=False)
class SizeofExpr(Expr):
    operand: Expr


# --- statements ------------------------------------------------------------


@dataclass(eq=False)
class Stmt(Node):
    pass


@dataclass(eq=False)
class VarDecl(Stmt):
    name: str
    ty: Type
    init: Expr | list[Expr] | None
    sym: object = field(default=None, init=False)


@dataclass(eq=False)
class Block(Stmt):
    items: list[Stmt]


@dataclass(eq=False)
class ExprStmt(Stmt):
    expr: Expr | None


@dataclass(eq=False)
class If(Stmt):
    cond: Expr
    then: Stmt
    other: Stmt | None


@dataclass(eq=False)
class While(Stmt):
    cond: Expr
    body: Stmt


@dataclass(eq=False)
class DoWhile(Stmt):
    body: Stmt
    cond: Expr


@dataclass(eq=False)
class For(Stmt):
    init: Stmt | None
    cond: Expr | None
    step: Expr | None
    body: Stmt


@dataclass(eq=False)
class Return(Stmt):
    value: Expr | None


@dataclass(eq=False)
class Break(Stmt):
    pass


@dataclass(eq=False)
class Continue(Stmt):
    pass


# --- top level -------------------------------------------------------------


@dataclass(eq=False)
class Param(Node):
    name: str
    ty: Type
    sym: object = field(default=None, init=False)


@dataclass(eq=False)
class Function(Node):
    name: str
    ret: Type
    params: list[Param]
    body: Block | None  # None for a prototype


@dataclass(eq=False)
class Program(Node):
    decls: list[Function | VarDecl]
