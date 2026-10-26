import pytest

from ember.errors import CompileError
from ember.lexer import tokenize


def kinds(src):
    return [(t.kind, t.value) for t in tokenize(src)][:-1]


def test_keywords_identifiers_and_numbers():
    assert kinds("int x = 0x1F;") == [
        ("kw", "int"), ("ident", "x"), ("op", "="), ("num", 31), ("op", ";")]


def test_longest_operator_wins():
    assert [v for _, v in kinds("a<<=b>>c&&d||e--")] == [
        "a", "<<=", "b", ">>", "c", "&&", "d", "||", "e", "--"]


def test_char_and_string_escapes():
    toks = tokenize(r"'\n' '\0' \"a\tb\"".replace('\\"', '"'))
    assert toks[0].value == 10 and toks[1].value == 0
    assert toks[2].kind == "str"


def test_comments_are_skipped_and_lines_counted():
    toks = tokenize("// one\n/* two\n three */ x")
    assert toks[0].value == "x" and toks[0].line == 3


def test_bad_character_is_an_error():
    with pytest.raises(CompileError):
        tokenize("int $x;")
