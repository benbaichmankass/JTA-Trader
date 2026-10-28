# Desk in-trade management -- WALK protocol (v2; one judge walks whole trades; no lookahead)

You manage OPEN trades from fill to close. You will be given trade tokens and exactly ONE command:

  python3 scripts/research/desk_lifecycle_driver.py walk --out <DIR> --candles-dir <C> --trade <T> [--decision '<JSON>']

Run it WITHOUT --decision to get the trade's next check-in packet. Answer that packet by running it again WITH
--decision '<one JSON object>'; it records your answer and prints the NEXT check-in, or {"closed": true} when the trade
is over. Then go to the next token. Running any other command, reading any file, or using any other tool voids your
work (it is audited mechanically). Do not compute with code; judge each packet yourself.

A packet: `why_now` = what triggered this check-in ("clock" = the regular check-in; r+1.0 = price first closed beyond
+1 R; atr_up / atr_down = volatility regime change; mom_with / mom_against = short-term momentum flipped with / against
the trade; break_*_with / *_against = a close beyond the prior 12-bar high / low). `trade` = side; entry (= 100) / stop /
target prices; the same in R from entry (1 R = the initial risk); now_r; mfe_r / mae_r; bars held; bars left to the time
stop (the trade closes at market there); partial_taken; actions_so_far; atr_now_px; cost_r_if_closed_now (every
outcome is net of costs). `new_bars` = closed 1h bars [t since fill, open, high, low, close]: the first packet shows
the last 48, later ones only the bars since your previous check-in. Asset and date are hidden; do not guess them.

Decide what maximises the trade's expected net R from here to its close. Holding is a decision, not a default.
  hold | tighten_sl level_r=x (above the current stop_r, >= 0.10 R below now_r) | widen_sl level_r=x (below the
  current stop_r, not below -2.0 R) | move_tp level_r=y (>= 0.10 R beyond now_r, <= 10 R) | partial_close (50 %, once) |
  close (all, at the next bar's open). A moved level applies from the next bar. Both brackets always exist.
Decision JSON: {"packet_id": "<from the packet>", "action": "...", "level_r": <number, only for tighten_sl / widen_sl /
move_tp>, "confidence": <0..1>, "reason": "<= 15 words"}
When every token is closed, reply with one line per token: <token> closed <number of check-ins answered>.
