"""Turns C source text into a list of tokens."""

from dataclasses import dataclass

from ember.errors import CompileError

KEYWORDS = {
    "int", "char", "void", "if", "else", "while", "do", "for", "return",
    "break", "continue", "sizeof",
}

# Longest first, so "<<=" wins over "<<" and "<".
OPERATORS = sorted(
    """<<= >>= ++ -- && || == != <= >= << >> += -= *= /= %= &= |= ^=
    + - * / % & | ^ ~ ! < > = ? : ; , ( ) [ ] { }""".split(),
    key=len, reverse=True,
)

ESCAPES = {"n": 10, "t": 9, "r": 13, "0": 0, "\\": 92, "'": 39, '"': 34, "a": 7,
           "b": 8, "f": 12, "v": 11}


@dataclass(frozen=True)
class Token:
    kind: str  # num, str, ident, kw, op, eof
    value: object
    line: int

    def __repr__(self) -> str:
        return f"{self.kind}:{self.value!r}"


def tokenize(source: str) -> list[Token]:
    tokens: list[Token] = []
    i, line, n = 0, 1, len(source)
    while i < n:
        c = source[i]
        if c == "\n":
            line += 1
            i += 1
        elif c.isspace():
            i += 1
        elif source.startswith("//", i):
            while i < n and source[i] != "\n":
                i += 1
        elif source.startswith("/*", i):
            end = source.find("*/", i + 2)
            if end < 0:
                raise CompileError("unterminated comment", line)
            line += source.count("\n", i, end)
            i = end + 2
        elif c == "#":
            # Lines like #include <stdio.h> are there so the same file also
            # builds with a host compiler. ember has no preprocessor.
            while i < n and source[i] != "\n":
                i += 1
        elif c.isdigit():
            j = i
            while j < n and (source[j].isalnum() or source[j] == "_"):
                j += 1
            text = source[i:j]
            try:
                value = int(text, 16) if text.lower().startswith("0x") else int(text, 10)
            except ValueError:
                raise CompileError(f"bad number {text!r}", line) from None
            if value > 0xFFFF_FFFF:
                raise CompileError(f"number {text} does not fit in 32 bits", line)
            tokens.append(Token("num", value, line))
            i = j
        elif c.isalpha() or c == "_":
            j = i
            while j < n and (source[j].isalnum() or source[j] == "_"):
                j += 1
            word = source[i:j]
            tokens.append(Token("kw" if word in KEYWORDS else "ident", word, line))
            i = j
        elif c == "'":
            value, i = read_char(source, i + 1, line)
            if i >= n or source[i] != "'":
                raise CompileError("unterminated character literal", line)
            tokens.append(Token("num", value, line))
            i += 1
        elif c == '"':
            data = bytearray()
            i += 1
            while True:
                if i >= n or source[i] == "\n":
                    raise CompileError("unterminated string", line)
                if source[i] == '"':
                    i += 1
                    break
                value, i = read_char(source, i, line)
                data.append(value)
            tokens.append(Token("str", bytes(data), line))
        else:
            for op in OPERATORS:
                if source.startswith(op, i):
                    tokens.append(Token("op", op, line))
                    i += len(op)
                    break
            else:
                raise CompileError(f"unexpected character {c!r}", line)
    tokens.append(Token("eof", None, line))
    return tokens


def read_char(source: str, i: int, line: int) -> tuple[int, int]:
    """Read one possibly escaped character, return (byte value, next index)."""
    if i >= len(source):
        raise CompileError("unexpected end of file", line)
    c = source[i]
    if c != "\\":
        if ord(c) > 127:
            raise CompileError("only ASCII characters are supported", line)
        return ord(c), i + 1
    esc = source[i + 1] if i + 1 < len(source) else ""
    if esc == "x":
        j = i + 2
        while j < len(source) and source[j] in "0123456789abcdefABCDEF":
            j += 1
        if j == i + 2:
            raise CompileError("bad \\x escape", line)
        return int(source[i + 2:j], 16) & 0xFF, j
    if esc not in ESCAPES:
        raise CompileError(f"unknown escape \\{esc}", line)
    return ESCAPES[esc], i + 2
