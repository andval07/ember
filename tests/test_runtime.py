"""Software * / % against Python, on the edge cases."""

import pytest

from ember import driver, target

EDGES = [0, 1, -1, 2, -2, 7, -7, 255, 65535, 46341, 2**31 - 1, -2**31]


def c_div(a, b):
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def wrap(v):
    v &= 0xFFFFFFFF
    return v - 2**32 if v >= 2**31 else v


@pytest.mark.parametrize("op", ["*", "/", "%"])
def test_against_python(op):
    pairs = [(a, b) for a in EDGES for b in EDGES
             if op == "*" or (b != 0 and not (a == -2**31 and b == -1))]
    vals = ", ".join(f"{a}" if a != -2**31 else "-2147483647-1" for a, _ in pairs)
    divs = ", ".join(f"{b}" if b != -2**31 else "-2147483647-1" for _, b in pairs)
    want = 0
    for a, b in pairs:
        r = a * b if op == "*" else c_div(a, b) if op == "/" else a - b * c_div(a, b)
        want = wrap(want * 31 + wrap(r))
    src = f"""int xs[{len(pairs)}] = {{{vals}}}; int ys[{len(pairs)}] = {{{divs}}};
    int main(void) {{ int i, h = 0;
      for (i = 0; i < {len(pairs)}; i++) h = h * 31 + (xs[i] {op} ys[i]);
      return h; }}"""
    for opt in (0, 1):
        code, _, _ = target.run_iss(driver.build(src, opt))
        assert wrap(code) == want
