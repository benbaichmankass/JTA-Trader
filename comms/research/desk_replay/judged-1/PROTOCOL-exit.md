# Judging protocol — role exit (masked blind replay)

You are a discretionary trader deciding whether to EXIT open trades. Each packet is one open trade at a decision instant:
the bar k=0 has just closed and the trade has just reached about +1R of favourable excursion.
Everything is masked: the asset is anonymous, prices are rebased to 100 at the k=0 close, no dates.

Fields (trade): side (long/short); entry_px and stop_initial_px (rebased prices); 1R = |entry_px - stop_initial_px|;
open_r = unrealised R at the k=0 close; peak_r = best favourable excursion so far in R; bars_held; timeframe;
atr_now (rebased price units); atr_over_r_at_entry = entry ATR expressed in R; r_in_atr = 1R in units of current ATR;
strategy_family = the rule family that opened the trade. The strategy's own current (trailed) stop and take-profit are NOT
shown (could_not_look). If you hold, the trade runs to the strategy's own exit.

Your job: for each packet choose the action you believe gives the best expected NET R versus holding to the strategy's own exit.
A close or partial_close fills at the NEXT bar's open (not the k=0 close), paying ~10 bps round trip plus slippage.

Closed vocabulary (anything else is scored as hold):
- {"action": "hold"}
- {"action": "close"}           exit 100% at the next bar's open
- {"action": "partial_close"}   exit 50% at the next bar's open, the rest runs to the strategy's own exit

OUTPUT: exactly one JSON object per packet, one per line, in a single ```jsonl code block, nothing else required:
{"packet_id": "P-...", "role": "exit", "action": "hold"}
Every packet_id in your batch must appear exactly once.
