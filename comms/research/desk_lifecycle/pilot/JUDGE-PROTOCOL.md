# Desk in-trade management -- judging protocol (packet only; no tools, no repo, no web)

You are the in-trade manager of an OPEN trade. Each packet is one trade at one checkpoint. Decide the action that
maximises the trade's expected net R from here to its close, NET OF COSTS. You see only the packet.

The packet: `trade` = side, entry / stop / target (prices rebased to 100 at the current close), the same levels in R
from entry (`stop_r`, `tp_r`; 1 R = the initial risk), `now_r` (current price in R), `mfe_r` / `mae_r` (best / worst so
far), `bars_held`, `bars_left_to_time_stop` (the trade closes at market at the time stop), `partial_taken`,
`atr_now_px`, `cost_r_if_closed_now` (the round-trip cost in R a close now realises; costs are already counted in
every outcome). `bars_ohlc` = the last closed 1h bars [t, open, high, low, close], t = 0 is now. The asset and the
date are hidden on purpose; do not guess them.

Actions (closed enum; one per packet):
  hold                          keep both brackets as they are
  tighten_sl   level_r = x      move the stop to x R from entry: above the current stop_r, at least 0.10 R below now_r
  widen_sl     level_r = x      move the stop to x R: below the current stop_r, not below -2.0 R
  move_tp      level_r = y      move the target to y R: at least 0.10 R beyond now_r, at most 10 R
  partial_close                 close 50 % at the next bar's open (once per trade)
  close                         close all at the next bar's open
A moved level applies from the next bar. Both brackets always exist; nothing removes one. An invalid level is
treated as hold. Holding is a decision, not a default: choose it when it is your best estimate.

Answer with ONLY JSON lines, one per packet, in the order given, nothing else:
{"packet_id": "LC-...", "action": "hold|tighten_sl|widen_sl|move_tp|partial_close|close", "level_r": <number, only for tighten_sl/widen_sl/move_tp>, "confidence": <0..1>, "reason": "<= 20 words"}
