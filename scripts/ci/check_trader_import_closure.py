#!/usr/bin/env python3
"""Guard ``trader-import-closure`` (TRADER-RESTART-GATE).

``config/trader_import_closure.txt`` must equal the static import closure of
``src/main.py``. ``scripts/deploy_pull_restart.sh`` leaves ``ict-trader-live``
running when a deploy's src/ and scripts/ .py changes are all OUTSIDE that list,
so a stale list is how the trader could be left on code it loads. (The deploy
also recomputes the closure live and uses the union, so drift on main can only
add restarts -- this guard keeps the committed file honest and the reviewable
diff visible.)

  python3 scripts/ci/check_trader_import_closure.py              # check the repo
  python3 scripts/ci/check_trader_import_closure.py --self-test  # prove it can go red

Fix a failure with: python3 scripts/ops/trader_import_closure.py generate
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _tool():
    spec = importlib.util.spec_from_file_location(
        "trader_import_closure", REPO / "scripts" / "ops" / "trader_import_closure.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["trader_import_closure"] = mod
    spec.loader.exec_module(mod)
    return mod


def check(root: Path) -> int:
    return _tool().main(["generate", "--check", "--root", str(root)])


def self_test() -> int:
    tool = _tool()
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "src").mkdir()
        (root / "config").mkdir()
        (root / "src" / "__init__.py").write_text("")
        (root / "src" / "main.py").write_text("def f():\n    from src import a\n")
        (root / "src" / "a.py").write_text("")
        tool.main(["generate", "--root", str(root)])
        if check(root) != 0:
            print("self-test FAILED: a freshly generated closure did not pass", file=sys.stderr)
            return 1
        # plant drift: the trader starts importing a module the list lacks
        (root / "src" / "b.py").write_text("")
        (root / "src" / "main.py").write_text("def f():\n    from src import a, b\n")
        if check(root) != 1:
            print("self-test FAILED: a new import missing from the list did not go red",
                  file=sys.stderr)
            return 1
        (root / "config" / "trader_import_closure.txt").unlink()
        if check(root) != 1:
            print("self-test FAILED: a missing closure file did not go red", file=sys.stderr)
            return 1
    print("trader-import-closure self-test: OK (fresh=green, planted drift=red, missing=red)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    return self_test() if args.self_test else check(REPO)


if __name__ == "__main__":
    sys.exit(main())
