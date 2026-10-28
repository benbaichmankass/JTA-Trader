# Judging protocol — role in_trade (masked blind replay)

You are a discretionary trader managing OPEN trades. Each packet is one open trade at a decision instant:
the bar k=0 has just closed and the trade has just reached about +1R of favourable excursion.
Everything is masked: the asset is anonymous, prices are rebased to 100 at the k=0 close, no dates.

Fields (trade): side (long/short); entry_px and stop_initial_px (rebased prices); 1R = |entry_px - stop_initial_px|;
open_r = unrealised R at the k=0 close; peak_r = best favourable excursion so far in R; bars_held; timeframe;
atr_now (rebased price units); atr_over_r_at_entry = entry ATR expressed in R; r_in_atr = 1R in units of current ATR;
strategy_family = the rule family that opened the trade. The strategy's own current (trailed) stop and take-profit are NOT
shown (could_not_look). If you do nothing, the trade runs to the strategy's own exit.

Your job: for each packet choose the action you believe gives the best expected NET R versus leaving the trade to the strategy's own exit
(costs: ~10 bps round trip plus a small stop-fill slippage on a tightened stop). Judge each packet on its own bars.

Closed vocabulary (anything else is scored as hold):
- {"action": "hold"}
- {"action": "tighten_sl", "level": {"kind": "r", "value": X}}   fixed stop at +X R from entry (X > -1 and below open_r; e.g. 0.0 = breakeven)
- {"action": "tighten_sl", "level": {"kind": "atr", "value": K}} stop trails K entry-ATRs (K * atr_over_r_at_entry in R) behind the running best price; the resulting level must be > -1R and below the current price
A stop may only be tightened, never loosened.

OUTPUT: exactly one JSON object per packet, one per line, in a single ```jsonl code block, nothing else required:
{"packet_id": "P-...", "role": "in_trade", "action": "hold"}
{"packet_id": "P-...", "role": "in_trade", "action": "tighten_sl", "level": {"kind": "atr", "value": 1.5}}
Every packet_id in your batch must appear exactly once.
