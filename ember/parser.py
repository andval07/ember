"""Recursive descent parser: tokens to AST.

Binary operators use precedence climbing with the C precedence table.
"""

from ember import ast
from ember.ctypes import CHAR, INT, VOID, ArrayType, PtrType, Type
from ember.errors import CompileError
from ember.fold import eval_const
from ember.lexer import Token, tokenize

PRECEDENCE = {
    "||": 1, "&&": 2, "|": 3, "^": 4, "&": 5, "==": 6, "!=": 6,
    "<": 7, "<=": 7, ">": 7, ">=": 7, "<<": 8, ">>": 8,
    "+": 9, "-": 9, "*": 10, "/": 10, "%": 10,
}
ASSIGN_OPS = {"=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>="}
BASE_TYPES = {"int": INT, "char": CHAR, "void": VOID}


def parse(source: str) -> ast.Program:
    return Parser(tokenize(source)).program()


class Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.pos = 0

    # --- helpers -----------------------------------------------------------

    @property
    def tok(self) -> Token:
        return self.tokens[self.pos]

    def peek(self, offset: int = 1) -> Token:
        return self.tokens[min(self.pos + offset, len(self.tokens) - 1)]

    def advance(self) -> Token:
        tok = self.tok
        self.pos += 1
        return tok

    def at(self, value: str) -> bool:
        return self.tok.kind in ("op", "kw") and self.tok.value == value

    def accept(self, value: str) -> bool:
        if self.at(value):
            self.pos += 1
            return True
        return False

    def expect(self, value: str) -> Token:
        if not self.at(value):
            raise CompileError(f"expected {value!r}, got {self.describe()}", self.tok.line)
        return self.advance()

    def ident(self) -> str:
        if self.tok.kind != "ident":
            raise CompileError(f"expected a name, got {self.describe()}", self.tok.line)
        return self.advance().value

    def describe(self) -> str:
        return "end of file" if self.tok.kind == "eof" else repr(self.tok.value)

    def at_type(self, offset: int = 0) -> bool:
        tok = self.peek(offset)
        return tok.kind == "kw" and tok.value in BASE_TYPES

    # --- declarations ------------------------------------------------------

    def program(self) -> ast.Program:
        decls: list[ast.Function | ast.VarDecl] = []
        while self.tok.kind != "eof":
            decls.extend(self.top_level())
        return ast.Program(1, decls)

    def base_type(self) -> Type:
        if not self.at_type():
            raise CompileError(f"expected a type, got {self.describe()}", self.tok.line)
        return BASE_TYPES[self.advance().value]

    def pointers(self, ty: Type) -> Type:
        while self.accept("*"):
            ty = PtrType(ty)
        return ty

    def array_suffix(self, ty: Type, allow_empty: bool = False) -> tuple[Type, bool]:
        """Parse [N][M]... after a name. Returns the type and whether the
        first dimension was left empty (char s[] = "...")."""
        dims: list[int | None] = []
        while self.at("["):
            line = self.advance().line
            if self.at("]") and not dims and allow_empty:
                dims.append(None)
            else:
                size = eval_const(self.expression())
                if size is None or size <= 0:
                    raise CompileError("array size must be a positive constant", line)
                dims.append(size)
            self.expect("]")
        for size in reversed(dims[1:] if dims and dims[0] is None else dims):
            ty = ArrayType(ty, size)
        return ty, bool(dims) and dims[0] is None

    def top_level(self) -> list[ast.Function | ast.VarDecl]:
        line = self.tok.line
        base = self.base_type()
        ty = self.pointers(base)
        name = self.ident()
        if self.at("("):
            return [self.function(line, ty, name)]
        decls = [self.declarator_rest(line, base, ty, name)]
        while self.accept(","):
            ty = self.pointers(base)
            decls.append(self.declarator_rest(self.tok.line, base, ty, self.ident()))
        self.expect(";")
        return decls

    def function(self, line: int, ret: Type, name: str) -> ast.Function:
        self.expect("(")
        params: list[ast.Param] = []
        if self.at("void") and self.peek().value == ")":
            self.advance()
        elif not self.at(")"):
            while True:
                pline = self.tok.line
                ty = self.pointers(self.base_type())
                pname = self.ident()
                if self.accept("["):
                    # int a[] and int a[N] as parameters are pointers.
                    while not self.at("]"):
                        self.advance()
                    self.expect("]")
                    ty, _ = self.array_suffix(ty)
                    ty = PtrType(ty)
                params.append(ast.Param(pline, pname, ty))
                if not self.accept(","):
                    break
        self.expect(")")
        if self.accept(";"):
            return ast.Function(line, name, ret, params, None)
        return ast.Function(line, name, ret, params, self.block())

    def declarator_rest(self, line: int, base: Type, ty: Type, name: str) -> ast.VarDecl:
        ty, open_size = self.array_suffix(ty, allow_empty=True)
        init: ast.Expr | list[ast.Expr] | None = None
        if self.accept("="):
            init = self.initializer()
        if open_size:
            if isinstance(init, list):
                length = len(init)
            elif isinstance(init, ast.Str):
                length = len(init.data) + 1
            else:
                raise CompileError(f"array {name!r} needs a size or an initializer", line)
            ty = ArrayType(ty, length)
        return ast.VarDecl(line, name, ty, init)

    def initializer(self) -> ast.Expr | list[ast.Expr]:
        if not self.accept("{"):
            return self.assignment()
        items: list[ast.Expr] = []
        while not self.at("}"):
            items.append(self.assignment())
            if not self.accept(","):
                break
        self.expect("}")
        return items

    def local_decl(self) -> list[ast.Stmt]:
        base = self.base_type()
        decls: list[ast.Stmt] = []
        while True:
            line = self.tok.line
            ty = self.pointers(base)
            decls.append(self.declarator_rest(line, base, ty, self.ident()))
            if not self.accept(","):
                break
        self.expect(";")
        return decls

    # --- statements --------------------------------------------------------

    def block(self) -> ast.Block:
        line = self.expect("{").line
        items: list[ast.Stmt] = []
        while not self.accept("}"):
            if self.tok.kind == "eof":
                raise CompileError("missing '}'", line)
            if self.at_type():
                items.extend(self.local_decl())
            else:
                items.append(self.statement())
        return ast.Block(line, items)

    def statement(self) -> ast.Stmt:
        line = self.tok.line
        if self.at("{"):
            return self.block()
        if self.accept("if"):
            self.expect("(")
            cond = self.expression()
            self.expect(")")
            then = self.statement()
            other = self.statement() if self.accept("else") else None
            return ast.If(line, cond, then, other)
        if self.accept("while"):
            self.expect("(")
            cond = self.expression()
            self.expect(")")
            return ast.While(line, cond, self.statement())
        if self.accept("do"):
            body = self.statement()
            self.expect("while")
            self.expect("(")
            cond = self.expression()
            self.expect(")")
            self.expect(";")
            return ast.DoWhile(line, body, cond)
        if self.accept("for"):
            return self.for_statement(line)
        if self.accept("return"):
            value = None if self.at(";") else self.expression()
            self.expect(";")
            return ast.Return(line, value)
        if self.accept("break"):
            self.expect(";")
            return ast.Break(line)
        if self.accept("continue"):
            self.expect(";")
            return ast.Continue(line)
        if self.accept(";"):
            return ast.ExprStmt(line, None)
        expr = self.expression()
        self.expect(";")
        return ast.ExprStmt(line, expr)

    def for_statement(self, line: int) -> ast.Stmt:
        self.expect("(")
        init: ast.Stmt | None = None
        if self.at_type():
            init = ast.Block(line, self.local_decl())
        elif not self.accept(";"):
            init = ast.ExprStmt(line, self.expression())
            self.expect(";")
        cond = None if self.at(";") else self.expression()
        self.expect(";")
        step = None if self.at(")") else self.expression()
        self.expect(")")
        loop = ast.For(line, init, cond, step, self.statement())
        # The init declaration is scoped to the loop: wrap it in a block.
        return ast.Block(line, [loop]) if init is not None else loop

    # --- expressions -------------------------------------------------------

    def expression(self) -> ast.Expr:
        return self.assignment()

    def assignment(self) -> ast.Expr:
        left = self.conditional()
        if self.tok.kind == "op" and self.tok.value in ASSIGN_OPS:
            tok = self.advance()
            return ast.Assign(tok.line, tok.value, left, self.assignment())
        return left

    def conditional(self) -> ast.Expr:
        cond = self.binary(1)
        if self.at("?"):
            line = self.advance().line
            then = self.expression()
            self.expect(":")
            return ast.Cond(line, cond, then, self.conditional())
        return cond

    def binary(self, min_prec: int) -> ast.Expr:
        left = self.unary()
        while self.tok.kind == "op" and PRECEDENCE.get(self.tok.value, 0) >= min_prec:
            tok = self.advance()
            right = self.binary(PRECEDENCE[tok.value] + 1)
            left = ast.Binary(tok.line, tok.value, left, right)
        return left

    def unary(self) -> ast.Expr:
        tok = self.tok
        if tok.kind == "op" and tok.value in ("-", "+", "!", "~", "*", "&"):
            self.advance()
            return ast.Unary(tok.line, tok.value, self.unary())
        if tok.kind == "op" and tok.value in ("++", "--"):
            self.advance()
            return ast.IncDec(tok.line, tok.value, True, self.unary())
        if self.accept("sizeof"):
            if self.at("(") and self.at_type(1):
                self.advance()
                ty = self.type_name()
                self.expect(")")
                return ast.SizeofType(tok.line, ty)
            return ast.SizeofExpr(tok.line, self.unary())
        if self.at("(") and self.at_type(1):
            self.advance()
            ty = self.type_name()
            self.expect(")")
            return ast.Cast(tok.line, ty, self.unary())
        return self.postfix()

    def type_name(self) -> Type:
        ty = self.pointers(self.base_type())
        ty, _ = self.array_suffix(ty)
        return ty

    def postfix(self) -> ast.Expr:
        expr = self.primary()
        while True:
            line = self.tok.line
            if self.accept("["):
                index = self.expression()
                self.expect("]")
                expr = ast.Index(line, expr, index)
            elif self.at("("):
                if not isinstance(expr, ast.Name):
                    raise CompileError("only named functions can be called", line)
                self.advance()
                args: list[ast.Expr] = []
                if not self.at(")"):
                    args.append(self.assignment())
                    while self.accept(","):
                        args.append(self.assignment())
                self.expect(")")
                expr = ast.Call(line, expr.name, args)
            elif self.tok.kind == "op" and self.tok.value in ("++", "--"):
                expr = ast.IncDec(line, self.advance().value, False, expr)
            else:
                return expr

    def primary(self) -> ast.Expr:
        tok = self.tok
        if tok.kind == "num":
            self.advance()
            return ast.Num(tok.line, tok.value)
        if tok.kind == "str":
            data = b""
            while self.tok.kind == "str":  # "ab" "cd" is "abcd"
                data += self.advance().value
            return ast.Str(tok.line, data)
        if tok.kind == "ident":
            self.advance()
            return ast.Name(tok.line, tok.value)
        if self.accept("("):
            expr = self.expression()
            self.expect(")")
            return expr
        raise CompileError(f"expected an expression, got {self.describe()}", tok.line)
