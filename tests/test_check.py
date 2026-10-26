import pytest

from ember.check import check
from ember.errors import CompileError
from ember.parser import parse


def ok(src):
    check(parse(src + " int main(void) { return 0; }"))


@pytest.mark.parametrize("src", [
    "int f(void) { return y; }",
    "int f(void) { int x; int x; return 0; }",
    "int f(int a) { return a; } int g(void) { return f(1, 2); }",
    "int f(void) { break; }",
    "int f(void) { 3 = 4; return 0; }",
    "int f(void) { int *p; char c; p = c + 1; return 0; }",
    "int f(void) { int a[2]; a = 0; return 0; }",
    "int f(void) { return *5; }",
])
def test_rejects(src):
    with pytest.raises(CompileError):
        ok(src)


def test_accepts_pointer_arithmetic_and_decay():
    ok("int a[3]; int f(int *p) { return *(p + 1) + (p - a) + a[2]; }"
       " int g(void) { char s[] = \"hi\"; char *t = s; return f(a) + *t; }")


def test_requires_main():
    with pytest.raises(CompileError, match="main"):
        check(parse("int f(void) { return 0; }"))


def test_null_pointer_constant():
    ok("int f(void) { int *p = 0; return p == 0; }")
