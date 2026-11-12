"""TRADER-RESTART-CHURN (2026-11-12): non-.py paths the trader never loads
(.sh scripts, other units' deploy/ files, the closure list itself) do not
restart the trader. The trader's own unit, its drop-ins and the sparse-checkout
spec still do, as do config files the trader reads."""
from scripts.ops.trader_import_closure import RESTART, SKIP, classify_path, decide

CLOSURE = {"src/main.py"}


def test_unloaded_non_py_paths_skip():
    for p in ("scripts/ops/notify_run.sh", "scripts/deploy_pull_restart.sh",
              "scripts/install_systemd_units.sh", "deploy/ict-web-api.service",
              "deploy/ict-ops-runner.path", "deploy/ict-ml-decision-shadow.timer",
              "deploy/ict-desk-build@.service", "deploy/caddy/Caddyfile",
              "config/trader_import_closure.txt"):
        assert classify_path(p, CLOSURE) is None, p
    assert decide(["scripts/ops/amend_prop_bracket_action.sh"], CLOSURE)[0] == SKIP


def test_trader_unit_dropins_sparse_and_config_still_restart():
    for p in ("deploy/ict-trader-live.service", "deploy/dropins/data-dir.conf",
              "deploy/vm-sparse-checkout", "deploy/opt-in/ict-prop-executor.timer",
              "config/accounts.yaml", "config/strategies.yaml", "ml/configs/x.yaml",
              "comms/ml_universe/u.json"):
        assert classify_path(p, CLOSURE) == "non_py_runtime", p


def test_a_py_in_closure_still_wins_over_a_skipped_sh():
    assert decide(["scripts/ops/notify_run.sh", "src/main.py"], CLOSURE)[0] == RESTART
