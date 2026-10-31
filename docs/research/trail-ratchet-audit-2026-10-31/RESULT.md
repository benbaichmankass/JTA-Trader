# TRAIL-RATCHET-AUDIT — result (2026-10-31)

> **Doc status:** `live` · category `research` · lane `TRAIL-RATCHET-AUDIT` · read `main` @ `fe356e70ca`.
> Marks: **MEASURED** = read from live data/code this session; **ESTIMATED** = reconstructed from bar-extreme telemetry; **INFERRED** = reasoned from code, not observed.
> **Gates this adds or changes:** none in this PR. The two PRs it links add (Tier 3) a close-on-cross rule and (Tier 2) a per-leg tighten-only guard; both are `landing: hold`.

## Answer first

1. **No stop moved away from price in the live record (MEASURED, narrow window).** 0 of 105 packages show a looser `sl_price` on any later bar (details §2). The window is 2026-10-14 → 2026-10-31 (path-history writes start 2026-10-15), bar-end snapshots, journal stop only. It is not a proof for older trades, for intrabar moves, or for the venue stop.
2. **One path can loosen a stop in code (INFERRED, not observed live):** a leg that already holds a tighter stop than the package stop can be sent a looser trail candidate (§4). Fixed in its own Tier-2 PR.
3. **Live ignores a trail candidate that is through price; the Stage-0 harness does not (MEASURED in code).** Frequency: **0 of 721** bar-rows under base `trail_mult`; **46 of 721 (17 of 105 packages)** is an upper bound under the tightest declared mult. The true count is **not observable** (§3b).
4. **Tier-3 change drafted and pushed as a held PR (§3c).** One more finding: fade/squeeze/htf trail off the forming bar, the harness and `trend_donchian` off closed bars.

## 1. Every live trail implementation and its ratchet

| # | Implementation | file:line | Ratchet condition | Candidate through price |
|---|---|---|---|---|
| 1 | Chandelier, `trend_donchian` family (also levers: trail-decay, vol, ADX, momentum — they only shrink the mult) | `src/units/strategies/trend_donchian.py:962,968` | `candidate > sl` (long) / `candidate < sl` (short) | ignored (old) |
| 2 | Chandelier, `fade_breakout_4h` | `fade_breakout_4h.py:462,467` | same | ignored (old) |
| 3 | Chandelier, `squeeze_breakout_4h` | `squeeze_breakout_4h.py:353,358` | same | ignored (old) |
| 4 | Chandelier, `htf_pullback_trend_2h` (all `*_pullback_*` legs) | `htf_pullback_trend_2h.py:828,833` | same | ignored (old) |
| 5 | Break-even, shared by `turtle_soup`, `vwap` | `src/units/strategies/_base.py:165-171` | acts only if `sl < entry` (long) / `sl > entry` (short), sets `entry ± offset`, which is tighter | n/a (price ≥ entry+1R) |
| 6 | Prop DXtrade/phone trail | `src/prop/prop_trail.py:134-262` (`plan_trail`), `tightens` `:284` | `cand >= resting_sl + step` (long) | **handled**: `action="exit"`, stop moved to price ± buffer (`:249-262`, `exit_stop :270`) |
| 7 | Alpaca amend | `src/units/accounts/alpaca_amend.py:110,309` | `is_tighter` refuses a looser stop | n/a |
| 8 | Live-review amend (tighten/move_sl) | `src/runtime/live_review_intent.py:199-204,273,385` | `is_looser` → refused; leg gets `notes.sl_floor` | n/a |
| 9 | Order-monitor fan-out | `src/runtime/order_monitor.py:1698-1720` | only `notes.sl_floor` (leg), nothing direction-aware vs the leg's own stop (see §4) | n/a |

`ict_scalp`, `fvg_range_15m`, `hf_*` have no stop trail (fixed bracket / research-only). Stale-stop, giveback, momentum-stale and exit-head are **closes**, not stop moves. `interpret_verdict` (`monitor_verdict.py:114`) takes no direction and has no ratchet; the strategy monitors are the only ratchet for Bybit/IB.

## 2. Did any stop move away from price? (MEASURED)

* **Source:** diag `position_path_history?limit=10000` via `scripts/ops/diag_fetch.sh`, read 2026-10-31 ~12:32Z.
* **Population:** 911 rows, 105 `order_package_id`s (one row per package×bar, last pass of that bar), bar window 2026-10-14T04:00Z → 2026-10-31T12:00Z, 39 strategy names, crypto + equities + futures legs on Bybit/IB/Alpaca. Prop tickets (phone/DXtrade) are **not** in this table. `sl_price` is the package stop as the monitor held it; 0 null `sl_price` rows.
* **Test:** per package, bars in order, flag any bar whose `sl_price` is looser than the previous bar (long: lower; short: higher).
* **Result: 0 violations.** 20 of 105 packages had their stop move at least once, and all moves were tightening. That is the positive control for the probe: it sees moves.
* **Could not look (stated, not zero):** (a) intrabar moves (a loosen then re-tighten inside one bar is invisible); (b) venue amend history — `journalctl` for the trader returns only the last ~9 minutes for 2000 lines, and 0 `exchange modify` lines were in it; no per-amend table exists; (c) prop phone/DXtrade tickets; (d) anything before 2026-10-14.
* **Venue vs journal (MEASURED, `venue_protection_snapshot`, 28 measured legs):** 5 legs differ from the package stop by ≤1 tick (venue rounds on the loose side, by design). 1 leg (`bybit_1`, ETHUSDT short, `read_at` 2026-10-30T06:33Z, 30 h stale) shows venue stop 32.6 looser than the journal; that package is not in the fresh reads (17 legs read on 2026-10-31, 2 multi-leg packages, all legs equal). Treated as a stale row of a closed package, **not** a live loosening — not verified against that trade's close.

## 3. The scope add

### (a) Stage-0 harness when the candidate crosses price (MEASURED in code)

`scripts/backtest_trend.py:~896-925` (also `backtest_fade.py:294/313`, `backtest_squeeze.py:228/249`, `backtest_pullback.py:765/787`): after the bar's own stop test, `trail = max(trail, ext - mult*atr)` (short: `min`) on the **closed bar**, with no "below price" constraint. The **next bar** tests it in `_stop_or_target` (`:841-863`): long exits if `low <= trail`, fill `min(trail, open)` (short `max`). So a candidate through the last close means the bar-j+1 open is already through it → **exit at the next bar's open**, unless it gaps back across the trail and the low stays above it. Decision basis = bar close, execution = next open. All four harnesses are the same shape.

### (b) How often live ignored such a candidate

* **Not directly observable**: the ignoring branch returns `None` and logs nothing.
* **ESTIMATED lower figure:** for each of 721 bar-rows with a measured peak, ATR and the leg's base `trail_mult` (from `config/strategies.yaml`, read this session): `candidate = ext ∓ mult×atr`, `ext = entry ± peak_r×risk`. Crossing (`candidate` tighter than `sl_price` and through `last_price`) in **0 of 721 rows**. Smallest margin 0.002 ATR (`mes_trend_long_1d`), so the probe resolves near-misses.
* **ESTIMATED upper bound:** same with the tightest declared lever mult (`trail_decay_tight_mult`/`trail_adx_tight_mult`, assuming it is always armed): **46 of 721 rows, 17 of 105 packages** (`trend_donchian_eth_prop` 32 — prop path, handled by `exit`; `trend_donchian_eth_4h` 6; `mhg_pullback_1d` 2; `ief_pullback_1d` 2; four singletons). The rest of the 721 rows are legs without a trail (`ict_scalp_*`, `e4_oi_shock_1h`: 78 rows excluded).
* **Prop path MEASURED:** `prop_trail.py:249` records a real crossing on 2026-10-15 13:01Z (ETH short, replay 2351.13 vs price 2353.04, resting stop 2504.25). That is the one observed instance, and the prop code already exits there.
* **Reading:** crossing is rare because each ratchet already rests the stop at the previous candidate, so price must fall through the *prior* stop (an `sl_cross` close) or the extreme must rise and reverse inside one bar. Real but small; an exact count needs a candle replay per package (not done; follow-up below).

### (c) The exact Tier-3 change

PR [held, `claude/trail-ratchet-t3-close-on-cross`], new `src/runtime/trail_cross.py::trail_cross_verdict`, and in the four monitors (`candidate > sl` kept; then `candidate < price` → amend as before, otherwise return the close verdict):

```
{"action": "close", "reason": "strategy_close", "exit_price": <current_price>}
```

It rides the existing monitor close path (`order_monitor.py` close branch → `_send_close_to_exchange`, per leg, `exit_reason=strategy_close`; `blind_grade.py:389` already classes it `strategy_close`).

**Timing, matched to the harness:** the harness decides on the closed bar and fills at the next open. So fade, squeeze and htf also switch their trail window to closed bars (`closed_frame(...)`, exactly as `trend_donchian._trail_window` already does, MOMENTUM-LEVERS-PARITY). Without it, a forming-bar wick would close a trade the harness keeps. With it, the close fires on the first ~30 s pass after the bar rolls, i.e. at ≈ the next open. **Residual difference:** the harness requires the next bar's low to touch the trail (it can gap above and survive); live compares the current price, which is the same thing at the open and later intrabar.

Tests: `tests/test_trail_cross.py`, `tests/test_trend_donchian.py` (the old test pinned "returns None" for a through-price candidate; it now pins the close). 35 passed locally. A wider sweep of 1,298 strategy/monitor tests: 1295 passed, 1 skipped, 1 failed (`tests/test_eth4h_mm05_declared.py`), which passes when run alone on this branch and on the Tier-2 branch — an order-dependent failure not examined further (not shown to be pre-existing on `main`).

**Open point for the operator:** the close reason requested is `strategy_close`; a distinct `trail_cross` label would let the book separate these exits from other strategy closes. Left as asked.

## 4. A path that can loosen a stop (INFERRED from code; not observed live)

`order_monitor._apply_update` fans one candidate to every leg. The strategy's ratchet compares it with the **package** stop, which is written only when no leg failed (`not_applied` leaves it unchanged, `:1768-1789`). A sibling that already applied a tighter level keeps it while the package stop stays old; a later candidate between the two (possible when a lever mult returns to base) is then sent to that sibling and **loosens it**. Only legs with `notes.sl_floor` (live-review amends) were protected. Alpaca's `tighten` is protected; Bybit/IB are not.

Fix (Tier 2, own PR `claude/trail-ratchet-leg-guard`): the leg's own synced `trades.stop_loss` is a floor (`floor_blocks`). `tests/test_order_monitor_leg_stop_ratchet.py` — 2 of 3 tests fail without the fix and pass with it; the third is the negative control.

## 5. Follow-ups
* Exact count of ignored crossings: replay each closed package's candles through the live monitor (needs candle history; not in this lane's budget). Filed as the row's note.
* The ETH `bybit_1` stale venue-snapshot row (§2): check whether that package closed, and whether `venue_protection_snapshot` should expire rows of closed packages.
