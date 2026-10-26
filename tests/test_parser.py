import pytest

from ember import ast
from ember.errors import CompileError
from ember.parser import parse


def expr(src):
    fn = parse(f"int f(int a, int b, int c) {{ return {src}; }}").decls[0]
    return fn.body.items[0].value


def shape(e):
    if isinstance(e, ast.Binary):
        return f"({shape(e.left)}{e.op}{shape(e.right)})"
    if isinstance(e, ast.Name):
        return e.name
    if isinstance(e, ast.Num):
        return str(e.value)
    return type(e).__name__


@pytest.mark.parametrize("src, want", [
    ("a + b * c", "(a+(b*c))"),
    ("a - b - c", "((a-b)-c)"),
    ("a << 1 + b", "(a<<(1+b))"),
    ("a & b == c", "(a&(b==c))"),
    ("a || b && c", "(a||(b&&c))"),
    ("a < b == b < c", "((a<b)==(b<c))"),
])
def test_precedence_and_associativity(src, want):
    assert shape(expr(src)) == want


def test_assignment_is_right_associative():
    e = expr("a = b = c")
    assert isinstance(e, ast.Assign) and isinstance(e.value, ast.Assign)


def test_conditional_nests_to_the_right():
    e = expr("a ? b : c ? a : b")
    assert isinstance(e, ast.Cond) and isinstance(e.other, ast.Cond) \
        if hasattr(e, "other") else isinstance(e, ast.Cond)


def test_declarations_and_statements():
    prog = parse("int g[4]; char *s = \"x\"; int main(void) {"
                 " int i; for (i = 0; i < 4; i++) { if (i) continue; else break; }"
                 " while (0) {} do {} while (0); return sizeof(int); }")
    assert [type(d).__name__ for d in prog.decls] == ["VarDecl", "VarDecl", "Function"]


@pytest.mark.parametrize("src", ["int f( { }", "int x = ;", "int f() { return 1 }"])
def test_syntax_errors(src):
    with pytest.raises(CompileError):
        parse(src)
