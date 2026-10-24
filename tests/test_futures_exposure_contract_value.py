"""MGC-SIZING-OVERSIZE: gross-exposure ceiling must count the futures contract
multiplier. ib_paper sized 96/150 MGC (x10/pt) ~ 3.7-5.8x equity because no
ceiling existed; and a ceiling measured as qty*price would have read 1/10 of that."""
import sqlite3

from src.units.accounts.risk import RiskManager


def _rm(tmp_path, max_gross):
    db = tmp_path / "j.db"
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE trades (account_id TEXT, symbol TEXT, status TEXT,"
                  " position_size REAL, entry_price REAL, is_backtest INT)")
        c.execute("INSERT INTO trades VALUES ('a','MGC','open',10,4000.0,0)")
        c.execute("INSERT INTO trades VALUES ('a','ETHUSDT','open',2,2000.0,0)")
    rm = RiskManager({"risk_pct": 0.015, "max_gross_exposure_pct": max_gross},
                     account_id="a")
    rm._risk_db_path = lambda: str(db)
    return rm


def test_open_gross_notional_applies_contract_value(tmp_path):
    rm = _rm(tmp_path, 2.0)
    assert rm._open_gross_notional_from_db() == 10 * 4000.0 * 10.0 + 2 * 2000.0
    assert rm._open_notional_for_symbol("MGC") == 10 * 4000.0 * 10.0


def test_ib_paper_real_config_clamps_mgc_tight_stop_to_1_5x_equity(tmp_path):
    """Row 6610's inputs (entry 4173.8, stop 0.40%) / row 6603's (0.26%) on the
    REAL ib_paper config: notional must not exceed 1.5x equity (operator
    2026-10-24, "1.5× equity (Recommended)"). Unclamped they were 3.7x / 5.8x."""
    import yaml
    from src.core.coordinator import OrderPackage

    cfg = yaml.safe_load(open("config/accounts.yaml"))["accounts"]
    for acct in ("ib_paper", "ib_live"):
        assert cfg[acct]["risk"]["max_gross_exposure_pct"] == 1.5
    equity = 1_000_000.0  # synthetic, not the live balance
    db = tmp_path / "j.db"
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE trades (account_id TEXT, symbol TEXT, status TEXT,"
                  " position_size REAL, entry_price REAL, is_backtest INT)")
    for entry, stop in ((4173.8, 4157.09285714), (4182.4, 4171.55428571)):
        rm = RiskManager(dict(cfg["ib_paper"]["risk"]), account_id="ib_paper")
        rm._risk_db_path = lambda: str(db)
        rm.current_equity = equity
        pkg = OrderPackage(strategy="ict_scalp_mgc_15m", symbol="MGC",
                           direction="long", entry=entry, sl=stop,
                           tp=entry + 40, confidence=0.8)
        qty = rm.position_size(pkg, equity, market_type="futures")
        assert 0 < qty
        assert qty * entry * 10.0 <= 1.5 * equity
        assert qty < 96  # the unclamped size on this entry
