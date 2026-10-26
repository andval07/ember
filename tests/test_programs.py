"""Every program in programs/ must match zig cc, at -O0 and -O1, and -O1
must retire fewer instructions."""

import pytest

from conftest import PROGRAMS
from ember import driver, reference, target


@pytest.fixture(scope="module", params=PROGRAMS, ids=lambda p: p.stem)
def program(request):
    src = request.param.read_text()
    return src, reference.run(src)


@pytest.mark.parametrize("opt", [0, 1])
def test_matches_zig_cc(program, opt):
    src, want = program
    code, out, _ = target.run_iss(driver.build(src, opt))
    assert (code, out) == want


def test_o1_runs_fewer_instructions(program):
    src, _ = program
    n0 = len(target.run_iss(driver.build(src, 0))[2])
    n1 = len(target.run_iss(driver.build(src, 1))[2])
    assert n1 < n0
