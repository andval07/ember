"""Source to image: the whole pipeline in one place."""

from ember import asm, codegen
from ember.check import check
from ember.lower import lower
from ember.parser import parse


def compile_c(source: str, opt: int = 0) -> str:
    """C source to assembly text."""
    program = parse(source)
    check(program)
    module = lower(program, promote=opt > 0)
    allocations = None
    if opt > 0:
        from ember import opt as optimizer
        allocations = optimizer.optimize(module)
    return codegen.generate(module, allocations)


def build(source: str, opt: int = 0) -> bytes:
    return asm.assemble(compile_c(source, opt))
