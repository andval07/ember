"""Where flint lives, and how to run an image on it.

ember does not copy flint: it imports the ISS, the encoders and the RTL
runner from the flint checkout (FLINT_DIR, default ../flint).
"""

import os
import sys
from pathlib import Path

FLINT_DIR = Path(os.environ.get("FLINT_DIR", Path(__file__).resolve().parents[2] / "flint"))
if str(FLINT_DIR) not in sys.path:
    sys.path.insert(0, str(FLINT_DIR))

MAX_STEPS = 20_000_000


def run_iss(image: bytes, max_steps: int = MAX_STEPS):
    """Run on flint's ISS. Returns (exit code, output bytes, retired log)."""
    from flint.iss import Iss

    iss = Iss(image)
    log = iss.run(max_steps)
    return iss.exit_code, bytes(iss.output), log


def run_rtl(image: bytes, max_cycles: int = MAX_STEPS):
    from flint import rtlsim

    return rtlsim.run(image, max_cycles)
