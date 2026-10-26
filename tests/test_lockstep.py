"""The RTL core must retire exactly what the ISS retires."""

import pytest

from conftest import PROGRAMS
from ember import driver, target

SMALL = [p for p in PROGRAMS if p.stem in ("pointers", "strings", "operators")]


def entries(log):
    return [(e.pc, e.rd, e.value) for e in log]


@pytest.mark.parametrize("path", SMALL, ids=lambda p: p.stem)
@pytest.mark.parametrize("opt", [0, 1])
def test_iss_and_rtl_agree(path, opt):
    image = driver.build(path.read_text(), opt)
    code, _, log = target.run_iss(image)
    rtl = target.run_rtl(image)
    assert rtl.exit_code == code
    assert entries(rtl.log) == entries(log)
