"""Tests for the operator-flatten marker.

The script carries its own `--self-test`, and the wrapper runs it as a
precondition. These tests exist because a self-test the WRAPPER runs is not the
same as one CI runs: if the wrapper's precondition line were ever dropped,
nothing would notice. So this asserts both the behaviour AND the wiring.
"""
import importlib.util
import json
import pathlib
import sqlite3
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "ops" / "mark_operator_flattened.py"
WRAPPER = REPO / "scripts" / "ops" / "mark_operator_flattened_action.sh"


def _mod():
    spec = importlib.util.spec_from_file_location("mof", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _db(tmp_path):
    """Fixture on the CANONICAL schema, not a hand-rolled subset.

    `Database.create_tables()` gives real `trades` AND `order_packages` — the
    second matters now that a repair reads `order_packages.close_reason` as its
    independent evidence. A fixture declaring a schema production does not have
    is how the pairs tests passed against a fictional `order_packages`
    (BL-20260810-PAIRS-MAX-HOLD-BARS-NOT-ENFORCED).
    """
    sys.path.insert(0, str(REPO))
    from src.units.db.database import Database
    p = tmp_path / "j.db"
    Database(str(p)).create_tables()
    c = sqlite3.connect(p)
    c.execute(
        "INSERT INTO trades (id, timestamp, symbol, direction, entry_price, "
        "position_size, account_id, status, exit_reason, notes, is_backtest, "
        "pnl, exit_price) VALUES (4934, '2026-08-21T21:54:54+00:00', 'XRPUSDT', "
        "'long', 1.4983, 16.0, 'bybit_2', 'closed', 'reconciler_filled', ?, 0, "
        "-2.4509, 1.3866)",
        (json.dumps({"exit_price_source": "bybit_closed_pnl",
                     "closed_by": "monitor_reconciler"}),))
    c.commit()
    return c


def _add_marked_notes_shed_row(c, trade_id, close_reason):
    """A row in the live 5238/5239 state: `exit_reason` carries the mark, the
    notes keys are gone. `close_reason=''` models an unrecoverable prior."""
    c.execute(
        "INSERT INTO trades (id, timestamp, symbol, direction, entry_price, "
        "position_size, account_id, status, exit_reason, notes, is_backtest) "
        "VALUES (?, '2026-08-30T09:30:00+00:00', 'BNBUSDT', 'long', 800.0, 1.0, "
        "'bybit_1', 'closed', ?, ?, 0)",
        (trade_id, "operator_flatten_reconciled",
         json.dumps({"_truncated": True})))
    c.execute(
        "INSERT INTO order_packages (order_package_id, strategy_name, symbol, "
        "direction, entry, sl, tp, created_at, updated_at, status, "
        "linked_trade_id, close_reason) VALUES (?, 's', 'BNBUSDT', 'long', "
        "800.0, 790.0, 820.0, '2026-08-30T09:00:00+00:00', "
        "'2026-08-30T09:33:26+00:00', 'closed', ?, ?)",
        (f"pkg-{trade_id}", trade_id, close_reason))
    c.commit()


def test_the_script_self_test_passes():
    r = subprocess.run([sys.executable, str(SCRIPT), "--self-test"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_wrapper_runs_the_self_test_as_a_precondition():
    """The wiring, not the behaviour. A dropped precondition is silent."""
    body = WRAPPER.read_text()
    assert "--self-test" in body, "wrapper no longer runs the self-test"


def test_marking_sets_the_reason_and_preserves_broker_truth(tmp_path):
    m = _mod()
    conn = _db(tmp_path)
    ups, refs = m.plan(conn, [4934], "hedge switch flat-symbol guard")
    assert refs == []
    m.apply(conn, ups)
    row = conn.execute("SELECT exit_reason, notes, pnl, exit_price FROM trades "
                       "WHERE id=4934").fetchone()
    assert row[0] == "operator_flatten_reconciled"
    notes = json.loads(row[1])
    assert notes["closed_by_operator"] is True
    assert notes["operator_close_reason"] == "hedge switch flat-symbol guard"
    assert notes["pre_mark_exit_reason"] == "reconciler_filled"
    # The PRICE's provenance is a different question from the CLOSE's cause.
    assert notes["exit_price_source"] == "bybit_closed_pnl"
    # And no monetary field moved.
    assert row[2] == -2.4509 and row[3] == 1.3866


def test_a_bad_id_refuses_the_whole_batch(tmp_path):
    m = _mod()
    conn = _db(tmp_path)
    ups, refs = m.plan(conn, [4934, 999999], "x")
    assert len(refs) == 1 and "no such trade" in refs[0]
    # The CLI must write nothing at all when any id is bad.
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--trade-ids", "4934,999999",
         "--reason", "x", "--db", str(tmp_path / "j.db"), "--apply"],
        capture_output=True, text=True)
    assert r.returncode == 2, r.stdout
    still = conn.execute("SELECT exit_reason FROM trades WHERE id=4934").fetchone()[0]
    assert still == "reconciler_filled", "a bad sibling id must not stop a write silently"


def test_the_fixture_columns_exist_in_the_real_ddl():
    """The self-test builds its own in-memory `trades`. A fixture declaring a
    schema production does not have is how the pairs tests passed against a
    fictional `order_packages` (BL-20260810-PAIRS-MAX-HOLD-BARS-NOT-ENFORCED),
    so pin the fixture's columns as a SUBSET of the canonical DDL.

    This test is what makes the `# data-wiring:` annotation in the script true
    rather than merely present.
    """
    ddl = (REPO / "src" / "units" / "db" / "database.py").read_text()
    start = ddl.index("CREATE TABLE IF NOT EXISTS trades (")
    real = set()
    for line in ddl[start:start + 6000].splitlines()[1:]:
        st = line.strip()
        if st.startswith(")"):
            break
        tok = st.split()
        if tok and tok[0].isidentifier():
            real.add(tok[0])

    fixture = {"id", "status", "exit_reason", "notes", "is_backtest", "symbol",
               "account_id", "pnl", "exit_price"}
    missing = fixture - real
    assert not missing, (
        f"the self-test fixture declares column(s) production's trades table "
        f"does not have: {sorted(missing)} (known real columns: {len(real)})")
    # And the two columns the script actually WRITES must be among them.
    assert {"exit_reason", "notes"} <= real

    # Same pin for the `order_packages` fixture the self-test gained when the
    # repair path started READING `close_reason` as independent evidence. It is
    # read-only for this script, which makes a wrong column set worse, not
    # better: it would silently recover nothing and the row would be refused.
    start_op = ddl.index("CREATE TABLE IF NOT EXISTS order_packages (")
    real_op = set()
    for line in ddl[start_op:start_op + 6000].splitlines()[1:]:
        st = line.strip()
        if st.startswith(")"):
            break
        tok = st.split()
        if tok and tok[0].isidentifier() and tok[0] != "FOREIGN":
            real_op.add(tok[0])
    fixture_op = {"order_package_id", "linked_trade_id", "close_reason",
                  "updated_at"}
    assert fixture_op <= real_op, (
        f"self-test order_packages fixture has column(s) production lacks: "
        f"{sorted(fixture_op - real_op)}")


def test_a_marked_but_notes_shed_row_is_repaired_from_the_package(tmp_path):
    """Trades 5238/5239, live. The flag's ABSENCE does not mean unmarked.

    Without this, a re-run reads `row["exit_reason"]` — already the MARK — and
    records it as `pre_mark_exit_reason`, destroying the one field that makes
    the marking reversible. The prior must come from independent evidence.
    """
    m = _mod()
    conn = _db(tmp_path)
    _add_marked_notes_shed_row(conn, 5238, "reconciler_filled")
    ups, refs = m.plan(conn, [5238], "repair after the notes cap shed the keys")
    assert refs == [] and len(ups) == 1
    notes = json.loads(ups[0]["notes"])
    assert notes["pre_mark_exit_reason"] == "reconciler_filled", (
        "must NOT record the mark as its own prior"
    )
    assert notes["pre_mark_exit_reason_source"] == "order_packages.close_reason"
    assert notes["closed_by_operator"] is True


def test_an_unrecoverable_prior_refuses_rather_than_inventing_one(tmp_path):
    """CONTROL for the row above: same state, no evidence. Refuse."""
    m = _mod()
    conn = _db(tmp_path)
    _add_marked_notes_shed_row(conn, 5239, "")
    ups, refs = m.plan(conn, [5239], "x")
    assert ups == []
    assert len(refs) == 1 and "NOT recoverable" in refs[0]


def test_a_first_time_mark_records_where_its_prior_came_from(tmp_path):
    """The source key is on BOTH paths, or a repaired row is indistinguishable
    from a first-time mark — and those are different claims about evidence."""
    m = _mod()
    conn = _db(tmp_path)
    ups, _ = m.plan(conn, [4934], "x")
    assert json.loads(ups[0]["notes"])["pre_mark_exit_reason_source"] \
        == "trades.exit_reason"


# ── --exit-reason account_reset (PI-20261120-XGESYDCD-0002) ─────────────────────────────────
# The 2026-11-16 14:32:33Z paper close-all shape (alpaca_order_history): rows opened days before,
# all closed by detectors within ~1 minute of each other.
_RESET_ROWS = [
    (7029, "IAUM", "stuck_strategy_watchdog", "2026-11-10T14:32:52+00:00", "2026-11-16T14:35:52+00:00"),
    (7031, "GDX", "stuck_strategy_watchdog", "2026-11-10T14:43:32+00:00", "2026-11-16T14:35:52+00:00"),
    (7131, "USO", "sl", "2026-11-12T19:04:00+00:00", "2026-11-16T14:35:52+00:00"),
]


def _reset_db(tmp_path, rows=_RESET_ROWS, account_class="paper", is_demo=1, account="alpaca_paper"):
    c = _db(tmp_path)          # canonical schema (+ the unrelated fixture row 4934)
    for tid, sym, er, opened, closed in rows:
        c.execute("INSERT INTO trades (id, timestamp, symbol, direction, entry_price, position_size, status, "
                  "exit_reason, notes, is_backtest, is_demo, account_class, account_id, created_at, closed_at, "
                  "pnl, exit_price) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (tid, opened, sym, "short", 87.0, 10.0, "closed", er,
                   json.dumps({"closed_by": "stuck_strategy_watchdog"}), 0, is_demo,
                   account_class, account, opened, closed, 12.5, 80.26))
    c.commit()
    c.close()
    return tmp_path / "j.db"


def test_account_reset_plans_the_episode_and_writes_reversibly(tmp_path):
    m = _mod()
    p = _reset_db(tmp_path)
    c = sqlite3.connect(p)
    ups, refs = m.plan_account_reset(c, [7029, 7031, 7131], "11-16 paper close-all collateral")
    assert refs == [] and [u["id"] for u in ups] == [7029, 7031, 7131]
    n = m.apply(c, ups, m.ACCOUNT_RESET)
    assert n == 3
    for tid, _s, er, *_ in _RESET_ROWS:
        reason, notes, pnl, px = c.execute(
            "SELECT exit_reason, notes, pnl, exit_price FROM trades WHERE id=?", (tid,)).fetchone()
        d = json.loads(notes)
        assert reason == "account_reset" and d["closed_by_account_reset"] is True
        assert d["pre_mark_exit_reason"] == er          # reversible
        assert (pnl, px) == (12.5, 80.26)               # no monetary field touched
    assert m.plan_account_reset(c, [7029, 7031, 7131], "again") == ([], [])   # idempotent


def test_account_reset_refuses_real_money(tmp_path):
    m = _mod()
    p = _reset_db(tmp_path, account_class="real_money", is_demo=0, account="alpaca_live")
    ups, refs = m.plan_account_reset(sqlite3.connect(p), [7029], "x")
    assert ups == [] and any("not a paper row" in r for r in refs)


def test_account_reset_refuses_rows_that_are_not_one_episode(tmp_path):
    m = _mod()
    rows = _RESET_ROWS[:2] + [(7202, "QQQ", "stuck_strategy_watchdog",
                               "2026-11-13T16:30:00+00:00", "2026-11-16T16:00:00+00:00")]
    p = _reset_db(tmp_path, rows=rows)
    ups, refs = m.plan_account_reset(sqlite3.connect(p), [7029, 7031, 7202], "x")
    assert ups == [] and any("not one close-all episode" in r for r in refs)


def test_account_reset_refuses_a_row_opened_after_the_close(tmp_path):
    m = _mod()
    rows = _RESET_ROWS[:2] + [(7617, "GDX", "max_hold", "2026-11-16T20:04:00+00:00", "2026-11-16T14:36:00+00:00")]
    p = _reset_db(tmp_path, rows=rows)
    ups, refs = m.plan_account_reset(sqlite3.connect(p), [7029, 7031, 7617], "x")
    assert ups == []
    assert any("decision" in r for r in refs)          # max_hold is never overwritten


def test_account_reset_refuses_a_decision_label(tmp_path):
    m = _mod()
    rows = [(7814, "GDX", "live_review_close", "2026-11-10T16:01:00+00:00", "2026-11-16T14:35:52+00:00")]
    p = _reset_db(tmp_path, rows=rows)
    ups, refs = m.plan_account_reset(sqlite3.connect(p), [7814], "x")
    assert ups == [] and any("decision" in r for r in refs)


def test_account_reset_cli_is_dry_run_without_apply_and_writes_a_row_backup_with_it(tmp_path):
    p = _reset_db(tmp_path)
    base = [sys.executable, str(SCRIPT), "--db", str(p), "--trade-ids", "7029,7031,7131",
            "--reason", "collateral", "--exit-reason", "account_reset"]
    out = subprocess.run(base, capture_output=True, text=True, cwd=REPO, check=False)
    assert out.returncode == 0 and "DRY-RUN" in out.stdout, out.stdout + out.stderr
    assert sqlite3.connect(p).execute("SELECT exit_reason FROM trades WHERE id=7029").fetchone()[0] \
        == "stuck_strategy_watchdog"
    out = subprocess.run(base + ["--apply"], capture_output=True, text=True, cwd=REPO, check=False)
    assert out.returncode == 0 and "APPLIED: 3" in out.stdout, out.stdout + out.stderr
    baks = list(tmp_path.glob("j.db.rows-mark-account-reset-*.json"))
    assert len(baks) == 1 and len(json.loads(baks[0].read_text())["rows"]) == 3


def test_wrapper_account_reset_mode_is_dry_run_unless_apply_true():
    src = WRAPPER.read_text()
    assert 'account_reset) ;;' in src and '"${ACTION_APPLY:-}" != "true"' in src


def test_account_reset_refuses_a_detector_row_opened_after_the_earliest_close(tmp_path):
    m = _mod()
    rows = _RESET_ROWS[:2] + [(7700, "GDX", "stuck_strategy_watchdog",
                               "2026-11-16T14:36:10+00:00", "2026-11-16T14:40:00+00:00")]
    p = _reset_db(tmp_path, rows=rows)
    ups, refs = m.plan_account_reset(sqlite3.connect(p), [7029, 7031, 7700], "x")
    assert ups == [] and any("cannot be collateral" in r for r in refs)
