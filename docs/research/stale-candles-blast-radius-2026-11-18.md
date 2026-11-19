# Stale trainer candles: blast radius by research unit (2026-11-18)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane `AM-OPS-2`, item `PI-20261118-MANAYJZO-0002`

Gates this adds or changes: none. Read-only list; changes no result, grade or config.

**Cause.** The trainer's `data/` candles were extended only for SOL/XRP/ETH 15m (daily timer). Every other feed stopped at its last manual batch (2026-06-18 to 2026-07-10 for candles, 2026-05-24 to 06-20 for funding).

**Population (read from `research/queue/RQ-*.yaml`, `run.workflow`):** 141 units read trainer `data/`: 100 on `m20-exit-lever-sweep.yml` (copies the leg's frames from trainer `data/` by scp) and 41 on `research-script-run-trainer.yml`. Other research workflows (`research-script-run`, `research-harness-dispatch`, `e35-bracket-sweep`) were not traced here and are NOT in this list.

**Declared window vs effective end.** No m20 unit declares a data window: it reads the whole file, so the effective end is the file's last bar at run time. The 41 script units record no `data_last_bar` (only `donchian_depth_retest.py` does), so their effective end is not recoverable from the record; they are listed unmapped.

**Table column "feeds:last bar"** is the trainer file's last bar BEFORE the 2026-11-18 refresh, measured earlier this session. The leg to file mapping is by leg name (symbol token, and timeframe: 2h/4h legs resample 15m, 1h legs read 1h, 5m/15m/1d read their own grain). It is a heuristic, not read from each run. `fresh` means the 15m SOL/XRP/ETH file the daily timer refreshes; I did NOT establish from which date the timer was running, so a result from before that date on such a feed may also be stale.

**Result:** of 100 m20 units, 60 map to a stale feed and have a result row (their `generated_at` is up to ~5 months after the file's last bar), 28 map only to the daily-refreshed 15m feeds, 10 could not be mapped by name (listed as `unmapped`), and the remainder have no result row. A stale-end result does not mean the verdict is wrong; it means the sample ends months before its generation date and needs a re-run to be current. Re-running is a queue decision, not made here.

| unit | kind | status | result generated | legs / script | feeds:last bar | read |
|---|---|---|---|---|---|---|
| RQ-20260922-003 | m20 | done | 2026-09-26 | trend_donchian_eth_prop | ETH_15m:fresh | fresh-feed (daily-refreshed 15m) |
| RQ-20260922-004 | m20 | done | 2026-09-26 | xrp_pullback_2h | XRP_15m:fresh | fresh-feed (daily-refreshed 15m) |
| RQ-20260928-006 | m20 | done | 2026-09-28 | trend_donchian_eth_4h,tlt_pullback_1d,gdx_pullback_1d,qld_tr | ADA_15m:2026-06-18; ETH_15m:fresh; GDX_1d:2026-07-10; QLD_1d:2026-07-10; QQQ_1h:2026-06-18; SPY_1h:2026-06-18; TLT_1d:2026-06-18 | STALE-END |
| RQ-20260928-007 | m20 | done | 2026-09-28 | ada_pullback_2h,eth_pullback_2h,ict_scalp_5m,ict_scalp_avax_ | ADA_15m:2026-06-18; AVAX_5m:2026-06-18; BTC_15m:2026-07-10; ETH_15m:fresh; SOL_15m:fresh; SOL_5m:2026-06-18; TLT_1h:2026-06-18; XRP_15m:fresh; XRP_5m:2026-06-18; None_15m:None | unmapped |
| RQ-20260928-019 | m20 | queued | 2026-10-29 | ada_pullback_2h | ADA_15m:2026-06-18 | STALE-END |
| RQ-20260928-020 | m20 | retired | 2026-09-29 | eth_pullback_2h | ETH_15m:fresh | fresh-feed (daily-refreshed 15m) |
| RQ-20260928-021 | m20 | queued | 2026-10-29 | gdx_pullback_1d | GDX_1d:2026-07-10 | STALE-END |
| RQ-20260928-022 | m20 | queued | 2026-10-29 | gld_pullback_1d | GLD_1d:2026-07-07 | STALE-END |
| RQ-20260929-006 | m20 | retired | 2026-09-30 | gld_pullback_1h | GLD_1h:2026-06-18 | STALE-END |
| RQ-20260929-007 | m20 | queued | 2026-11-13 | iaum_pullback_1d | IAUM_1d:2026-07-07 | STALE-END |
| RQ-20260929-008 | m20 | retired | 2026-09-30 | ict_scalp_eth_15m | ETH_15m:fresh | fresh-feed (daily-refreshed 15m) |
| RQ-20260929-009 | m20 | retired | 2026-10-30 | ict_scalp_mgc_15m | None_15m:None | unmapped |
| RQ-20260929-010 | m20 | retired | 2026-10-01 | ict_scalp_sol_15m | SOL_15m:fresh | fresh-feed (daily-refreshed 15m) |
| RQ-20261002-002 | m20 | retired | 2026-10-03 | ict_scalp_xrp_15m | XRP_15m:fresh | fresh-feed (daily-refreshed 15m) |
| RQ-20261003-002 | m20 | retired | 2026-10-03 | ict_scalp_xrp_5m | XRP_5m:2026-06-18 | STALE-END |
| RQ-20261003-004 | m20 | queued | 2026-11-02 | ief_pullback_1d | IEF_1d:2026-06-18 | STALE-END |
| RQ-20261003-007 | m20 | queued | 2026-11-03 | iwm_trend_long_1d | IWM_1d:2026-07-07 | STALE-END |
| RQ-20261003-008 | m20 | queued | 2026-11-13 | mes_trend_long_1d | MES_1d:2026-07-10 | STALE-END |
| RQ-20261004-656 | m20 | queued | 2026-11-04 | mgc_pullback_1d | MGC_1d:2026-07-10 | STALE-END |
| RQ-20261004-657 | m20 | queued | 2026-11-04 | mhg_pullback_1d | MHG_1d:2026-07-10 | STALE-END |
| RQ-20261004-658 | m20 | queued | 2026-11-13 | qld_trend_long_1d | QLD_1d:2026-07-10 | STALE-END |
| RQ-20261004-659 | m20 | retired | 2026-10-06 | qqq_pullback_1h | QQQ_1h:2026-06-18 | STALE-END |
| RQ-20261004-753 | m20 | done | 2026-10-04 | trend_donchian_xrp_4h | XRP_15m:fresh | fresh-feed (daily-refreshed 15m) |
| RQ-20261004-754 | m20 | done | 2026-10-04 | trend_donchian_xrp_4h | XRP_15m:fresh | fresh-feed (daily-refreshed 15m) |
| RQ-20261004-767 | m20 | done | 2026-10-04 | fvg_range_15m | BTC_15m:2026-07-10 | STALE-END |
| RQ-20261004-768 | m20 | done | 2026-10-04 | ict_scalp_sol_5m | SOL_5m:2026-06-18 | STALE-END |
| RQ-20261004-769 | m20 | done | 2026-10-04 | ict_scalp_avax_5m | AVAX_5m:2026-06-18 | STALE-END |
| RQ-20261004-770 | m20 | done | 2026-10-04 | ict_scalp_5m | BTC_15m:2026-07-10 | STALE-END |
| RQ-20261004-771 | m20 | done | 2026-10-04 | squeeze_breakout_4h | BTC_15m:2026-07-10 | STALE-END |
| RQ-20261004-772 | m20 | done | 2026-10-04 | spy_trend_long_1d | SPY_1d:2026-07-07 | STALE-END |
| RQ-20261004-773 | m20 | done | 2026-10-04 | qld_trend_long_1d | QLD_1d:2026-07-10 | STALE-END |
| RQ-20261004-774 | m20 | done | 2026-10-04 | scha_trend_long_1d | SCHA_1d:2026-07-07 | STALE-END |
| RQ-20261005-005 | m20 | retired | 2026-10-06 | mgc_pullback_1d | MGC_1d:2026-07-10 | STALE-END |
| RQ-20261005-006 | m20 | retired | 2026-10-06 | mhg_pullback_1d | MHG_1d:2026-07-10 | STALE-END |
| RQ-20261005-007 | m20 | retired | 2026-10-07 | qld_trend_long_1d | QLD_1d:2026-07-10 | STALE-END |
| RQ-20261005-008 | m20 | retired | 2026-10-07 | qqq_pullback_1h | QQQ_1h:2026-06-18 | STALE-END |
| RQ-20261005-009 | m20 | queued | 2026-11-06 | qqq_trend_long_1d | QQQ_1d:2026-06-18 | STALE-END |
| RQ-20261005-014 | m20 | queued | 2026-11-07 | scha_trend_long_1d | SCHA_1d:2026-07-07 | STALE-END |
| RQ-20261005-015 | m20 | queued | 2026-11-07 | slv_pullback_1d | SLV_1d:2026-06-18 | STALE-END |
| RQ-20261005-813 | m20 | queued | 2026-11-07 | splg_trend_long_1d | SPLG_1d:2026-07-02 | STALE-END |
| RQ-20261005-814 | m20 | queued | 2026-11-07 | spy_trend_long_1d | SPY_1d:2026-07-07 | STALE-END |
| RQ-20261005-815 | m20 | queued | 2026-11-08 | tlt_pullback_1d | TLT_1d:2026-06-18 | STALE-END |
| RQ-20261006-001 | m20 | queued | 2026-11-08 | tqqq_trend_long_1d | TQQQ_1d:2026-07-10 | STALE-END |
| RQ-20261006-003 | m20 | queued | 2026-11-08 | trend_donchian_eth_4h | ETH_15m:fresh | fresh-feed (daily-refreshed 15m) |
| RQ-20261007-001 | m20 | done | 2026-10-08 | trend_donchian_eth_4h,trend_donchian_xrp_4h,xrp_pullback_2h, | ADA_15m:2026-06-18; ETH_15m:fresh; XRP_15m:fresh | STALE-END |
| RQ-20261007-002 | m20 | done | 2026-10-08 | trend_donchian_eth_prop,trend_donchian_sol_prop | ETH_15m:fresh; SOL_15m:fresh | fresh-feed (daily-refreshed 15m) |
| RQ-20261007-003 | m20 | done | 2026-10-08 | trend_donchian,trend_donchian_sol,trend_donchian_eth,gld_pul | ADA_15m:2026-06-18; BTC_15m:2026-07-10; ETH_15m:fresh; GDX_1d:2026-07-10; GLD_1d:2026-07-07; GLD_1h:2026-06-18; IAUM_1d:2026-07-07; IEF_1d:2026-06-18; IWM_1d:2026-07-07; MES_1d:2026-07-10; MGC_1d:2026-07-10; MHG_1d:2026-07-10; QLD_1d:2026-07-10; QQQ_1d:2026-06-18; QQQ_1h:2026-06-18; SCHA_1d:2026-07-07; SLV_1d:2026-06-18; SOL_15m:fresh; SPLG_1d:2026-07-02; SPY_1d:2026-07-07; SPY_1h:2026-06-18; TLT_1d:2026-06-18; TLT_1h:2026-06-18; TQQQ_1d:2026-07-10; USO_1h:2026-06-18; XRP_15m:fresh | STALE-END |
| RQ-20261007-024 | m20 | retired | 2026-10-08 | ief_pullback_1d | IEF_1d:2026-06-18 | STALE-END |
| RQ-20261007-040 | m20 | done | 2026-10-08 | ada_pullback_2h | ADA_15m:2026-06-18 | STALE-END |
| RQ-20261007-041 | m20 | done | 2026-10-08 | xrp_pullback_2h,trend_donchian_eth_4h,trend_donchian_xrp_4h | ETH_15m:fresh; XRP_15m:fresh | fresh-feed (daily-refreshed 15m) |
| RQ-20261007-042 | m20 | done | 2026-10-08 | trend_donchian_eth_4h,trend_donchian_xrp_4h,xrp_pullback_2h, | ADA_15m:2026-06-18; ETH_15m:fresh; SOL_15m:fresh; XRP_15m:fresh | STALE-END |
| RQ-20261007-043 | m20 | done | 2026-10-08 | trend_donchian_eth_4h,trend_donchian_xrp_4h,xrp_pullback_2h, | ADA_15m:2026-06-18; ETH_15m:fresh; SOL_15m:fresh; XRP_15m:fresh | STALE-END |
| RQ-20261007-904 | m20 | done | 2026-10-08 | trend_donchian_xrp_4h | XRP_15m:fresh | fresh-feed (daily-refreshed 15m) |
| RQ-20261009-002 | m20 | queued | 2026-11-09 | trend_donchian_eth_prop | ETH_15m:fresh | fresh-feed (daily-refreshed 15m) |
| RQ-20261009-004 | m20 | queued | 2026-11-09 | trend_donchian_sol_prop | SOL_15m:fresh | fresh-feed (daily-refreshed 15m) |
| RQ-20261009-005 | m20 | queued | 2026-11-09 | trend_donchian_xrp_4h | XRP_15m:fresh | fresh-feed (daily-refreshed 15m) |
| RQ-20261009-903 | script | done | 2026-10-13 | scripts/research/pm_surprise_eval.py | — | per-script (no data_last_bar recorded) |
| RQ-20261010-002 | m20 | retired | 2026-10-10 | trend_donchian_sol_prop | SOL_15m:fresh | fresh-feed (daily-refreshed 15m) |
| RQ-20261010-003 | m20 | retired | 2026-10-10 | trend_donchian_xrp_4h | XRP_15m:fresh | fresh-feed (daily-refreshed 15m) |
| RQ-20261010-005 | m20 | queued | 2026-11-09 | xrp_pullback_2h | XRP_15m:fresh | fresh-feed (daily-refreshed 15m) |
| RQ-20261011-0ac8-01 | script | done | 2026-10-11 | scripts/research/ml_bakeoff.py | — | per-script (no data_last_bar recorded) |
| RQ-20261011-9da8-01 | script | done | 2026-10-24 | scripts/research/ml_bakeoff.py | — | per-script (no data_last_bar recorded) |
| RQ-20261012-75b2-16 | script | done | 2026-10-12 | scripts/research/ml_bakeoff.py | — | per-script (no data_last_bar recorded) |
| RQ-20261012-75b2-17 | script | done | 2026-10-13 | scripts/research/ml_bakeoff.py | — | per-script (no data_last_bar recorded) |
| RQ-20261012-75b2-18 | script | done | 2026-10-13 | scripts/research/ml_bakeoff.py | — | per-script (no data_last_bar recorded) |
| RQ-20261012-75b2-19 | script | done | 2026-10-14 | scripts/research/ml_bakeoff.py | — | per-script (no data_last_bar recorded) |
| RQ-20261012-75b2-20 | script | done | 2026-10-16 | scripts/research/ml_bakeoff.py | — | per-script (no data_last_bar recorded) |
| RQ-20261012-75b2-21 | script | done | 2026-10-16 | scripts/research/ml_bakeoff.py | — | per-script (no data_last_bar recorded) |
| RQ-20261012-75b2-22 | script | done | 2026-10-13 | scripts/research/ml_bakeoff.py | — | per-script (no data_last_bar recorded) |
| RQ-20261012-75b2-23 | script | done | 2026-10-13 | scripts/research/ml_bakeoff.py | — | per-script (no data_last_bar recorded) |
| RQ-20261012-75b2-24 | script | done | 2026-10-13 | scripts/research/ml_bakeoff.py | — | per-script (no data_last_bar recorded) |
| RQ-20261012-75b2-25 | script | done | 2026-10-13 | scripts/research/ml_bakeoff.py | — | per-script (no data_last_bar recorded) |
| RQ-20261012-75b2-26 | script | done | 2026-10-13 | scripts/research/ml_bakeoff.py | — | per-script (no data_last_bar recorded) |
| RQ-20261012-75b2-27 | script | done | 2026-10-13 | scripts/research/ml_bakeoff.py | — | per-script (no data_last_bar recorded) |
| RQ-20261012-904 | script | done | 2026-10-12 | scripts/research/wepe_g3_ledger.py | — | per-script (no data_last_bar recorded) |
| RQ-20261013-a793-01 | script | done | 2026-10-14 | scripts/research/ml_bakeoff.py | — | per-script (no data_last_bar recorded) |
| RQ-20261013-a793-02 | script | done | 2026-10-14 | scripts/research/ml_bakeoff.py | — | per-script (no data_last_bar recorded) |
| RQ-20261013-a793-03 | script | done | 2026-10-14 | scripts/research/ml_bakeoff.py | — | per-script (no data_last_bar recorded) |
| RQ-20261014-9807-03 | m20 | done | 2026-10-14 | xrp_pullback_2h,ada_pullback_2h,trend_donchian_xrp_4h | ADA_15m:2026-06-18; XRP_15m:fresh | STALE-END |
| RQ-20261016-d37f-01 | m20 | done | 2026-10-16 | ada_pullback_2h | ADA_15m:2026-06-18 | STALE-END |
| RQ-20261016-d37f-02 | m20 | done | 2026-10-16 | gdx_pullback_1d | GDX_1d:2026-07-10 | STALE-END |
| RQ-20261016-d37f-03 | m20 | done | 2026-10-16 | gld_pullback_1d | GLD_1d:2026-07-07 | STALE-END |
| RQ-20261016-d37f-04 | m20 | done | 2026-11-13 | iwm_trend_long_1d | IWM_1d:2026-07-07 | STALE-END |
| RQ-20261016-d37f-05 | m20 | done | 2026-10-16 | qqq_trend_long_1d | QQQ_1d:2026-06-18 | STALE-END |
| RQ-20261016-d37f-06 | m20 | done | 2026-10-16 | scha_trend_long_1d | SCHA_1d:2026-07-07 | STALE-END |
| RQ-20261016-d37f-07 | m20 | done | 2026-10-17 | slv_pullback_1d | SLV_1d:2026-06-18 | STALE-END |
| RQ-20261016-d37f-08 | m20 | done | 2026-10-17 | splg_trend_long_1d | SPLG_1d:2026-07-02 | STALE-END |
| RQ-20261016-d37f-09 | m20 | done | 2026-10-17 | spy_trend_long_1d | SPY_1d:2026-07-07 | STALE-END |
| RQ-20261016-d37f-10 | m20 | done | 2026-10-17 | trend_donchian_eth_4h | ETH_15m:fresh | fresh-feed (daily-refreshed 15m) |
| RQ-20261016-d37f-11 | m20 | done | 2026-10-17 | trend_donchian_eth_prop | ETH_15m:fresh | fresh-feed (daily-refreshed 15m) |
| RQ-20261016-d37f-12 | m20 | done | 2026-10-17 | trend_donchian_sol_prop | SOL_15m:fresh | fresh-feed (daily-refreshed 15m) |
| RQ-20261016-d37f-13 | m20 | done | 2026-11-13 | trend_donchian_xrp_4h | XRP_15m:fresh | fresh-feed (daily-refreshed 15m) |
| RQ-20261018-ff8f-02 | script | done | 2026-10-18 | scripts/research/ml_bakeoff.py | — | per-script (no data_last_bar recorded) |
| RQ-20261018-ff8f-04 | script | done | 2026-10-22 | scripts/research/ml_bakeoff.py | — | per-script (no data_last_bar recorded) |
| RQ-20261022-38be-01 | script | done | 2026-10-23 | scripts/research/ml_bakeoff.py | — | per-script (no data_last_bar recorded) |
| RQ-20261022-4a3b-01 | script | retired | 2026-10-22 | scripts/research/ml_bakeoff.py | — | per-script (no data_last_bar recorded) |
| RQ-20261022-c0d1-01 | script | done | 2026-10-22 | scripts/research/ml_bakeoff.py | — | per-script (no data_last_bar recorded) |
| RQ-20261022-c0d2-01 | script | done | 2026-10-23 | scripts/research/ml_bakeoff.py | — | per-script (no data_last_bar recorded) |
| RQ-20261022-c0d3-01 | script | done | 2026-10-23 | scripts/research/ml_bakeoff.py | — | per-script (no data_last_bar recorded) |
| RQ-20261024-004 | m20 | queued | — | trend_donchian_xrp_adx25 | XRP_15m:fresh | fresh-feed (daily-refreshed 15m) |
| RQ-20261029-013 | m20 | queued | 2026-10-29 | avax_pullback_2h | AVAX_15m:2026-06-18 | STALE-END |
| RQ-20261029-014 | m20 | retired | — | claude_desk | None_15m:None | unmapped |
| RQ-20261029-015 | m20 | queued | 2026-10-30 | eth_pullback_prop_2h | ETH_15m:fresh | fresh-feed (daily-refreshed 15m) |
| RQ-20261030-002 | m20 | retired | — | fade_breakout_4h | BTC_15m:2026-07-10 | stale feed, no result row |
| RQ-20261030-009 | m20 | queued | 2026-10-30 | fvg_range_15m | BTC_15m:2026-07-10 | STALE-END |
| RQ-20261030-013 | m20 | queued | 2026-10-30 | htf_pullback_trend_2h | None_15m:None | unmapped |
| RQ-20261030-016 | m20 | queued | 2026-10-30 | ict_scalp_5m | BTC_15m:2026-07-10 | STALE-END |
| RQ-20261030-019 | m20 | queued | 2026-10-30 | ict_scalp_avax_5m | AVAX_5m:2026-06-18 | STALE-END |
| RQ-20261030-022 | m20 | queued | 2026-10-30 | ict_scalp_sol_5m | SOL_5m:2026-06-18 | STALE-END |
| RQ-20261030-027 | m20 | queued | 2026-10-30 | mgc_trend_1h | MGC_1h:2026-06-18 | STALE-END |
| RQ-20261030-028 | m20 | queued | 2026-10-30 | slv_trend_1h | SLV_1h:None | unmapped |
| RQ-20261030-034 | m20 | queued | 2026-10-30 | sol_pullback_2h | SOL_15m:fresh | fresh-feed (daily-refreshed 15m) |
| RQ-20261030-035 | m20 | queued | 2026-10-31 | squeeze_breakout_4h | BTC_15m:2026-07-10 | STALE-END |
| RQ-20261030-040 | m20 | queued | 2026-10-31 | trend_donchian | BTC_15m:2026-07-10 | STALE-END |
| RQ-20261030-041 | m20 | queued | 2026-10-31 | trend_donchian_1h | None_1h:None | unmapped |
| RQ-20261031-004 | m20 | queued | 2026-10-31 | trend_donchian_ada_4h | ADA_15m:2026-06-18 | STALE-END |
| RQ-20261031-005 | m20 | queued | 2026-10-31 | trend_donchian_avax_4h | AVAX_15m:2026-06-18 | STALE-END |
| RQ-20261031-006 | m20 | queued | 2026-10-31 | trend_donchian_eth | ETH_15m:fresh | fresh-feed (daily-refreshed 15m) |
| RQ-20261031-007 | m20 | queued | 2026-10-31 | trend_donchian_sol | SOL_15m:fresh | fresh-feed (daily-refreshed 15m) |
| RQ-20261031-014 | m20 | retired | — | e4_oi_shock_1h | None_1h:None | unmapped |
| RQ-20261031-015 | m20 | queued | 2026-10-31 | trend_donchian_sol_4h | SOL_15m:fresh | fresh-feed (daily-refreshed 15m) |
| RQ-20261031-018 | m20 | retired | — | turtle_soup | BTC_15m:2026-07-10 | stale feed, no result row |
| RQ-20261031-019 | m20 | queued | 2026-10-31 | uso_trend_1h | USO_1h:2026-06-18 | STALE-END |
| RQ-20261105-001 | m20 | retired | — | ml_entry | None_15m:None | unmapped |
| RQ-20261105-002 | m20 | retired | — | ml_entry_v2 | None_15m:None | unmapped |
| RQ-20261106-003 | m20 | retired | — | ml_entry_eq | None_15m:None | unmapped |
| RQ-20261112-09d2-05 | script | queued | 2026-11-13 | scripts/research/tradeify_futures_fit.py | — | per-script (no data_last_bar recorded) |
| RQ-20261112-0bc8-02 | script | done | 2026-11-13 | scripts/research/volcomp_exit_head_bakeoff.py | — | per-script (no data_last_bar recorded) |
| RQ-20261113-4654-02 | script | done | 2026-11-13 | scripts/research/ml_bakeoff.py | — | per-script (no data_last_bar recorded) |
| RQ-20261113-b819-01 | script | done | 2026-11-13 |  | — | per-script (no data_last_bar recorded) |
| RQ-20261116-089f-01 | script | done | 2026-11-16 | scripts/research/cj4_blind_validation.py | — | per-script (no data_last_bar recorded) |
| RQ-20261116-d5a7-06 | script | done | 2026-11-16 | scripts/research/volcomp_exit_head_bakeoff.py | — | per-script (no data_last_bar recorded) |
| RQ-20261116-d5a7-07 | script | done | 2026-11-16 | scripts/research/volcomp_exit_head_bakeoff.py | — | per-script (no data_last_bar recorded) |
| RQ-20261117-aadc-01 | script | done | 2026-11-18 |  | — | per-script (no data_last_bar recorded) |
| RQ-20261117-aadc-04 | script | done | 2026-11-17 | scripts/research/exit_head_label_bakeoff.py | — | per-script (no data_last_bar recorded) |
| RQ-20261117-aadc-08 | script | done | 2026-11-17 |  | — | per-script (no data_last_bar recorded) |
| RQ-20261117-aadc-11 | script | done | 2026-11-17 | scripts/research/exit_head_label_bakeoff.py | — | per-script (no data_last_bar recorded) |
| RQ-20261117-aadc-12 | script | done | 2026-11-17 | scripts/research/exit_head_label_bakeoff.py | — | per-script (no data_last_bar recorded) |
| RQ-20261118-04a5-01 | script | queued | 2026-11-18 | scripts/research/donchian_depth_retest.py | — | per-script (no data_last_bar recorded) |
| RQ-20261118-aadc-13 | script | queued | 2026-11-18 | scripts/research/exit_head_label_bakeoff.py | — | per-script (no data_last_bar recorded) |
| RQ-20261118-aadc-14 | script | queued | 2026-11-18 | scripts/research/d10_basset_baseline.py | — | per-script (no data_last_bar recorded) |
## Correction and additions (2026-11-19, AM-OPS-7, row `TRAINER-1D-STALE-ROSTERED`)

Measured 2026-11-19 with trainer-vm-diag 44470111874 and a read-only audit of about 210 artifacts. That audit covered 175 research units, 4 Stage-0 records, 13 evidence-run files and about 20 derived records.

- **Correction: the m20 rows do record a window.** The paragraph above says no m20 unit declares a data window. Each m20 result row does carry an OOS `span`, and it confirms the effective end. Examples:
  - `RQ-20261016-d37f-06` (SCHA): span ends 2026-06-12; run 2026-10-16.
  - `RQ-20260928-021` (GDX): ends 2026-06-17; run 2026-10-29.
  - `RQ-20261016-d37f-08` (SPLG): ends 2026-04-14.
  - `RQ-20261031-019` (USO 1h): ends 2026-06-03.
- **Missed: three USO 1h Tradeify units.** `RQ-20261015-24ca-05`, `RQ-20261015-ca42-01` and `RQ-20261016-e2db-02` read trainer `data/USO_1h.csv` through `routing.needs_trainer_resident_data: true` with `run.commands` and no `run.workflow`, so the workflow-keyed count above missed them. All three FAIL, and their samples end at 2026-06-03 (2026-03-20 for the squeeze unit). The Tradeify USOIL non-adoption (05-prop programme, `TRADEIFY-INSTR-SPECS`) cites them.
- **Missed: derived records.**
  - `docs/research/exit-refinement-coverage.json`: 8 cells cite affected runs and now carry `stale_basis`. They include the GDX vol_trail and USO trail_geometry cells marked `passed_unshipped`. A `conditions_verdicts` caveat has been added.
  - `docs/research/alpaca-roster-phase2-capital-efficiency-2026-08-29.md` (m20 run 33248507062).
  - The GDX row of `docs/research/m20-exit-head-rounds.jsonl`.
- **Missed: decisions citing affected results.**
  - `PI-20261101-RXABACKP-0002`: the SCHA `vt_hot90_t2` promotion step. It is on HARD HOLD until re-run `RQ-20261119-a7f1-01` lands.
  - `PI-20260929-YGGMZWK7-0002`: the GDX `vt_hot90_t2` kill, now marked stale-basis.
- **Root cause of the 1d freeze, refined.** GDX, SCHA, USO, DBC, DBA and UNG were never in the lake's daily build. SPLG was renamed SPYM, so the lake built SPYM while the trainer file is `SPLG_1d.csv`. `report_data_freshness.py` printed `stale: true` to a journal nobody read. Fix and alert: #27214.
- **Not affected:**
  - The four Stage-0 records (GDX, SCHA, SPLG, USO), which fetch their own bars.
  - All 13 evidence-run backtests.
  - Every ML manifest.
  - DBC, DBA and UNG consumers.
  - No real-money leg rests on these files: all four legs are rostered on `alpaca_paper` only.
- **Re-run units filed, each blocked on data freshness (never on a date):**
  - `RQ-20261119-a7f1-01` (SCHA), `-02` (GDX), `-03` (USO 1h m20).
  - `-04`, `-05`, `-06` (the USOIL units; they need `USO_1h` current, which #27214 does not cover).
- **Still UNKNOWN:** `RQ-20260928-006`, `RQ-20261007-003` and `RQ-20261004-774` record no span. Their corpus rows are on branch `claude/m20-sweep-corpus`.
