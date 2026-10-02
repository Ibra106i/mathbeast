"""Symbolic comparison worker, run as its own process.

SymPy's `simplify` can run forever, so the symbolic step has to be killable. A
thread cannot be killed, and `multiprocessing` with the `spawn` context re-imports
`__main__` in every worker -- which means a plain `python myscript.py` that calls
`verify()` re-runs the whole script in each child. That produced triplicated
output and nondeterministic verdicts.

Running a fresh interpreter instead avoids re-importing the caller's module
entirely. It costs ~100ms, which only matters on the slow path; the numeric
fast path in `verify()` handles most calls without leaving the process at all.
"""

from __future__ import annotations

import json
import sys


def main() -> int:
    payload = json.loads(sys.stdin.read())
    from mathbeast.verify import _symbolic_decision

    state, reason = _symbolic_decision(payload["expected"], payload["given"])
    json.dump({"state": state, "reason": reason}, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
