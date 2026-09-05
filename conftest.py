"""Put the repository root on ``sys.path`` for the test run.

``python -m pytest`` happens to work because the interpreter puts the working
directory on the path itself. The bare ``pytest`` console script does not, so
CI collected every test module and failed on ``import vehreg`` before running a
single assertion. Doing it here makes both invocations, and any working
directory, behave the same.
"""

import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parent)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
