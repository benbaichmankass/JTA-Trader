# Phone executor — the broker changed its page layout

> **Doc status:** `live` · category `instruction` · last verified `2026-11-07` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)

**Gates this adds or changes:** none. This is a diagnosis-and-fix procedure; nothing halts, nothing new blocks a trade (the app keeps retrying the old and new paths).

Origin: 2026-11-06/07, the broker moved its navigation to the bottom of the screen; the breakout_2 phone executor missed the terminal for 28 h before anyone saw it. Operator, 2026-11-07: *"If we had had this mechanism … the app could handle it itself."* Lane `PHONE-BREAKOUT-NEW-LAYOUT`.

## 1. The trigger

- The phone posts `terminal_miss` ("terminal did not load …", `tabs=N inputs=N probe=…`) every ~minute while it cannot find the terminal. On a page that is **not** a known terminal, `exec.js` `controls()` leads the payload with `shape:<8 hex>` (FNV-1a over the bottom-band buttons, fixed bars and landmarks) followed by 11 control texts and 28 structure lines.
- The server (`src/prop/phone_executor.py::record_layout_shape`) keeps **one record per shape hash** (`prop_phone_layouts_<account>.json`, newest 12), so one new layout is one capture, not one a minute.
- When a hash has not alerted yet **and** the last `account_status` is older than `LAYOUT_STALE_H` (2 h, or never), the VM raises **ONE** alert: kind `phone_layout_changed`, channel `system`, priority `high`, `dedup_key phone_layout_changed:<account>:<hash>`. At most one per account per 6 h. It lands in the alert ledger, so `GET /api/bot/alerts?kind=phone_layout_changed` shows it and the ops-flags PR carries it (`alerts_ledger.wakes_manager`).

## 2. Where the capture lives (all public, digit-masked, no PII)

`GET https://ict-bot.duckdns.org/api/bot/prop/status?account_id=<id>`:
- `phone_layouts.shapes.<hash>`: `first_seen`, `last_seen`, `count`, `alerted_at`, `controls` (the structure dump).
- `phone_diag`: the latest miss (same payload). `phone_events`: the miss timeline. `phone_heartbeat.state`: app/exec_js versions.
- Step captures (`phone_captures_last`, `GET /api/diag/phone_capture*`) when the capture POST works (an open item at 2026-11-07: heartbeat `capture_err post:* 400`).

Line codes in the dump: `vp` viewport and counts · `B` clickable in the bottom 30 % (left to right; the new navigation) · `b` plain bottom-band leaf · `F` fixed/sticky bar (`:kN` clickables inside) · `L` landmark · `T` top-band buttons · `P` pointer-cursor leaf that is not a button · `I` icon-only button (aria-label/title). Each: `tag/role:text:a=aria:y<top%>x<left%>w<width%>`.

## 3. How a lane reads it and adapts `exec.js`

1. Read the alert, then the capture above. Identify: which element is the bottom navigation, which one opens the trading view, where positions / open orders / the order form now are, and what the new labels are.
2. `tools/phone-executor/app/src/main/assets/exec.js`: keep the old path as the fallback and add the new one. The levers: `terminal()` (what counts as a ready terminal; keep it strict so no ticket is claimed on an order form that cannot be found), `TAB_LABEL` / `TAB_ALIAS` / `tabText()` (new chip labels answer to `positions` / `open orders` / `closed orders`), `clickTab`, `tabChips`, `ORDER_RE` / `openTicket` (order form opener), `accountPanel` (balance/portfolio headline). Test with `node tools/phone-executor/test/exec_check.js` (add a case with the captured shape) and `exec_fixtures_check.js`.
3. Bump `var EXEC_VERSION = "YYYY-MM-DD.N";`. Tier 2 (it is the prop order path): landing hold, merge-slot claim, wake the manager with the green head sha. **Never place, amend or cancel an order to test.**

## 4. Ship path

- **`exec.js` only (the normal case):** merge to `main` → `phone-exec-js-sign` signs it → the phone fetches and verifies it (every 30 min, or on restart) → heartbeat `exec_js` shows the new version, `exec_src: remote`. No APK, no operator action.
- **APK + operator install** is needed only when Kotlin must change: the call sites in `MainActivity.kt` (what is read, in which order, `FLAG_SECURE` handling, `Api.kt` payloads), or a native screenshot. Build with workflow `phone-executor-apk`; the operator installs it (a physical action): open the build's APK artifact on the phone, install over the existing app, reopen it once so it logs in. Say exactly that in the report.

## 5. Verification

1. A **fresh** `account_status` on `/api/bot/prop/status` (`status_freshness` not `stale`, `reported_at` newer than the merge) with `positions_state` read.
2. Heartbeat `exec_js` = the new version. The `phone_layouts` record for the old hash stops counting.
3. The **first live ticket after that is the mechanics check** (one small trade, OPERATING-PLAN § 2). The lane does not place it.
4. Write the outcome on the checklist row (`scripts/ops/work.py note`), including whether the dump was enough to fix the layout from (if not, extend `outline()`).

## 6. Known limits

- No native screenshot yet: needs an APK (the WebView blur/mask must happen before upload). The structure dump is the evidence today.
- `ready` stays strict by design: after a layout change the app **reads nothing** until a lane adapts it, which is what the alert is for.
