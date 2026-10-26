"""C types: int, char, void, pointers, arrays and function types."""

from dataclasses import dataclass


class Type:
    def size(self) -> int:
        raise NotImplementedError

    @property
    def is_integer(self) -> bool:
        return isinstance(self, (IntType, CharType))

    @property
    def is_pointer(self) -> bool:
        return isinstance(self, PtrType)

    @property
    def is_scalar(self) -> bool:
        return self.is_integer or self.is_pointer

    def decay(self) -> "Type":
        """Arrays used as values become pointers to their first element."""
        return PtrType(self.base) if isinstance(self, ArrayType) else self


@dataclass(frozen=True)
class IntType(Type):
    def size(self) -> int:
        return 4

    def __str__(self) -> str:
        return "int"


@dataclass(frozen=True)
class CharType(Type):
    def size(self) -> int:
        return 1

    def __str__(self) -> str:
        return "char"


@dataclass(frozen=True)
class VoidType(Type):
    def size(self) -> int:
        raise TypeError("void has no size")

    def __str__(self) -> str:
        return "void"


@dataclass(frozen=True)
class PtrType(Type):
    base: Type

    def size(self) -> int:
        return 4

    def __str__(self) -> str:
        return f"{self.base}*"


@dataclass(frozen=True)
class ArrayType(Type):
    base: Type
    length: int

    def size(self) -> int:
        return self.base.size() * self.length

    def __str__(self) -> str:
        return f"{self.base}[{self.length}]"


@dataclass(frozen=True)
class FuncType(Type):
    ret: Type
    params: tuple[Type, ...]

    def size(self) -> int:
        raise TypeError("function has no size")

    def __str__(self) -> str:
        return f"{self.ret}({', '.join(map(str, self.params))})"


INT = IntType()
CHAR = CharType()
VOID = VoidType()


def align_of(ty: Type) -> int:
    while isinstance(ty, ArrayType):
        ty = ty.base
    return ty.size()
