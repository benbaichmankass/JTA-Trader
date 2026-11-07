# Phone executor — anomaly: diagnose first, then fix

> **Doc status:** `live` · category `instruction` · last verified `2026-11-07` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)

**Gates this adds or changes:** none. This is a diagnosis-and-fix procedure; nothing halts, nothing new blocks a trade (the app keeps retrying).

The mechanism names a **symptom, never a cause** (operator, 2026-11-07). It serves any executor bug: a UI change is only one possible cause. First worked example: § 7 (breakout_2, 2026-11-06/07).

## 1. The trigger

The phone reports every failed expectation as an event: `terminal_miss`, `positions_miss` (state prefixes `closed_` / `amend_` / `sheet_` / `open_` for the other views), `refusal`, `mismatch`, `error`, `login_failed`, `bg_ticket_fallback`, `loop_restarted`. The server (`src/prop/phone_executor.py::record_anomaly`) records each as **expected vs seen** and deduplicates by a **signature** = step + what was seen (the page shape hash `shape:<8 hex>` that `exec.js controls()` sends on an unknown page; otherwise the digit-masked state + headers).

When a **new signature** appears and the last `account_status` is older than `ANOMALY_STALE_H` (2 h, or never posted), the VM raises **ONE** alert: kind `phone_executor_anomaly`, channel `system`, priority `high`, `dedup_key phone_executor_anomaly:<account>:<signature>`; at most one per account per 6 h. It is in `GET /api/bot/alerts?kind=phone_executor_anomaly` and reaches the manager via the ops-flags PR (`alerts_ledger.wakes_manager`). Manager: dispatch a Sonnet diagnose-and-fix lane pointed here and at the capture.

## 2. The capture (public, digit-masked, no PII)

`GET https://ict-bot.duckdns.org/api/bot/prop/status?account_id=<id>` -> `phone_anomalies.anomalies.<signature>`:
`step`, `kind`, **`expected`** (what the app looked for), **`seen`** (`reason`, `controls`, `headers`, `cells`: the sanitised structure it found instead), `context` (the last 10 phone events, `app_version`, `exec_js`, `exec_src`, `last_state`), `count`, `first_seen`, `last_seen`, `alerted_at`. Also: `phone_diag` / `phone_positions_diag` (latest dumps), `phone_events`, `phone_heartbeat.state`, `phone_captures_last` (+ `GET /api/diag/phone_capture*`, when the step-capture POST works; open at 2026-11-07: heartbeat `capture_err post:* 400`).

Structure-dump line codes (`controls` after the `shape:` line): `vp` viewport and counts · `B` clickable in the bottom 30 % (left to right) · `b` plain bottom-band leaf · `F` fixed/sticky bar (`:kN` clickables inside) · `L` landmark · `T` top-band buttons · `P` pointer-cursor leaf that is not a button · `I` icon-only button (aria-label/title). Each: `tag/role:text:a=aria:y<top%>x<left%>w<width%>`.

## 3. DIAGNOSE FIRST — competing causes, tested against the capture

Write the list into the checklist row before touching code, and say which the evidence supports and which it rules out:

| Cause | What the capture would show | How to test |
|---|---|---|
| UI / layout change at the broker | `seen` has a new shape: different nav / labels; the old markers absent; page otherwise healthy and logged in | compare `controls` with the labels in `exec.js` (`terminal()`, `TAB_LABEL`, `ORDER_RE`) |
| Login / 2FA / session expiry | `last_state` login/other, password or "check your e-mail" words, `login_failed` events | `phone_events` timeline, heartbeat `relogin_*` counters |
| Broker popup / maintenance / challenge | a dialog or "maintenance" / "just a moment" text, `L:` dialog landmark, challenge state | `seen` text, `phone_events` |
| Our own regression | the miss began right after an exec.js or APK version change; the old shape still matches the old markers | `context.exec_js` / `app_version` vs the first miss time; `git log` on exec.js / Kotlin |
| Network / VM | events missing, heartbeat gaps, not a miss; `phone_heartbeat.at` old | `GET /api/diag/*` health, heartbeat timeline |
| App crash / OS kill | `app_started` with `activity_missing`, `loop_restarted`, `restarts_24h` rising | heartbeat state |

Only then fix. **A layout adaptation is one possible fix among several, not the default.** If the capture cannot discriminate the causes, the fix is to **extend the capture** (`exec.js outline()`, or the event payload) and wait one more cycle, not to guess.

## 4. Fixing

`exec.js` levers: `terminal()` (what is a ready terminal; keep it strict so no ticket is claimed on an order form that cannot be found), `TAB_LABEL` / `TAB_ALIAS` / `tabText()`, `clickTab`, `tabChips`, `ORDER_RE` / `openTicket`, `accountPanel`, `outline()`. Test: `node tools/phone-executor/test/exec_check.js` (add a case with the captured shape) and `exec_fixtures_check.js`; server: `tests/test_phone_executor.py`. Bump `var EXEC_VERSION`. Tier 2 (prop order path): landing hold, merge-slot claim, wake the manager with the green head sha. **Never place, amend or cancel an order to test.**

## 5. Ship path

- **`exec.js` only (the normal case):** merge to `main` -> `phone-exec-js-sign` signs it -> the phone fetches and verifies it (every 30 min, or on restart) -> heartbeat `exec_js` shows the new version, `exec_src: remote`. No APK.
- **APK + operator install** only when Kotlin must change (call sites in `MainActivity.kt`, `FLAG_SECURE` handling, `Api.kt` payloads, a native masked screenshot). Build with workflow `phone-executor-apk`; the operator installs it (physical): open the APK artifact on the phone, install over the app, reopen once so it logs in. State exactly that in the report.

## 6. Verification

1. A **fresh** `account_status` (`status_freshness` not `stale`, `reported_at` newer than the merge) with `positions_state` read.
2. Heartbeat `exec_js` = the new version; the signature's `count` stops rising.
3. The **first live ticket after that is the mechanics check** (one small trade, OPERATING-PLAN § 2). The lane does not place it.
4. Write the outcome on the checklist row (`scripts/ops/work.py note`): the causes considered, the one confirmed, and whether the capture was enough (if not, what was added to it).

## 7. Worked example — breakout_2, 2026-11-06/07

Symptom: `terminal_miss "tabs=4 inputs=0 probe=false"` every minute from 2026-11-06T04:42Z; `account_status` stale 28 h. Capture (`phone_diag` 08:44Z): controls `Trade, Portfolio . USD, Turbo Eval, ETH x, Market chart, Order book, Depth chart, Favorites, Markets, Activity, Open and trigger orders, Open positions, Position P&L, One-click trading …` and none of the old `Order form` / `Positions` / `Open orders`. Causes: login ruled out (heartbeat `last: logged_in`, the page shows the trading UI); regression ruled out for the start time (exec_js `2026-11-01.1` read fine until 11-06); maintenance popup ruled out (no dialog landmark); **UI change supported** (operator confirmed: navigation moved to the bottom). Fix: `exec.js 2026-11-07.1` (structure dump + `Open positions` / `Open and trigger orders` chip aliases), then the bottom-navigation path from the captured shape. PR #24033; row `PHONE-POSITIONS-READ-CONTEXT`.

**Capture (2026-11-07 14:55Z, signature `eaa42405`, shape `a5b22a08`, app 1b.339):** `<nav>` (aria "Trading navigation") with three bottom buttons Markets / Trade / Activity (y 92 %); header `Trade` + `Portfolio <value> USD` + `Turbo Eval`; `<main>` tablist Market chart / Order book / Depth chart; chips `Open positions` / `Open and trigger orders`; no `Order form`, no Buy/Sell submit. **Diagnosis** (causes tested against it): UI change CONFIRMED (new nav + new chip labels, old markers absent); login ruled out (`last: logged_in`); popup/maintenance ruled out (no dialog landmark); own regression ruled out (the miss began 2026-11-06T04:42Z with exec_js `2026-11-01.1`, not at a version change); network ruled out (heartbeats continuous); crash ruled out (`restarts_24h` 1). **Fix `2026-11-07.2`:** `terminal()` reads the new layout (`newRead` = bottom Trade button + both chips) and taps Trade once per 20 s when the chips are missing (Markets/Activity view); the old path is the fallback. **Order path fenced:** the order form of the new layout was NOT in the capture, so `symbolStep` clicks nothing and `openTicket` finds no order control (a ticket is refused at once, fail-closed) until a lane measures the real form and sets `ORDER_PATH_VERIFIED_ON_NEW_LAYOUT`. Closed orders (probably under Activity) is not read yet. Not established: the `FLAG_SECURE` question (`secure=True` was reported with `fg=False`, the `onCreate` default, so it says nothing about the foreground).

**Follow-up `2026-11-07.3` (same day):** after `.2` loaded, the background read still ended `bg_last logged_in+busy` and posted NO miss. By the code (`readAccount`): "busy" is `terminal()` returning null, not ready, or a ticket form open; a miss is posted only when `terminal()` answers `ready:false`; the `form:` suffix was absent. The only state that is both busy and silent is a null `terminal()` (a page-side error, or a result lost to a navigation), and `.2` was the first version to tap the bottom Trade button from inside `terminal()`. `.3`: the tap never happens on a page younger than 25 s, runs in a `setTimeout` AFTER `terminal()` has returned, and `terminal()` can no longer throw (an error comes back as `err`). The dump now carries a `term:` line (`term:r<ready> n<newLayout> v<newRead> k:<kick> [e:<err>] a<page age s>`) so the next silent failure explains itself. Whether that was the cause is NOT yet established: it is the inference from the code; the next background job on `.3` settles it.

**Correction `2026-11-07.4` (from the app's own capture, evidence not inference):** the first stored captures (`anomaly-terminal_miss-20261107T185724Z`, `periodic-terminal-20261107T185725Z`, app 1b.345, exec_js `.3`) show the background engine's page opens on the **Markets** view: path `/app/account/ACCT/trade/eth-usd`, `<nav aria-label="Trading navigation">` with Markets / Trade / Activity at y 751, tablist Market chart / Order book / Depth chart / Favorites, a chart iframe, and **no `Open positions` / `Open and trigger orders` chips in the document**. The dump's `term:r0 n1 v0 k:young a23` says: new layout recognised, read surface not found, tap held back as "young" at page age 23 s. `.3`'s 25 s gate was longer than the whole background read window (~23 s), so the Trade tap never fired; **`.3` over-corrected**, and the "null `terminal()`" explanation for the `.2` silence above is NOT supported (`.3` reports `err` empty). The likelier `.2` story, unproven: the immediate tap opened a Trade view that made `ticketOpen` true (busy, and no miss is posted while a ticket form is open). `.4`: the gate is 4 s (`KICK_AFTER_MS`) and the `term:` line ends with `t<ticketOpen>`. What the Trade view contains (chips? an order form?) is read from the next periodic capture, taken after the read loop.

## 7b. Screenshots the app takes itself (PHONE-SELF-SCREENSHOTS, operator 2026-11-07)

The app draws its OWN WebView to an off-screen bitmap (no system screenshot, nothing on screen), paints black boxes over every masked value, and POSTs it with a sanitised DOM snapshot to `POST /api/bot/prop/phone/capture` (stored on the VM only, 7-day TTL, never in git). **The only gate is "is this a credential screen"** (`Capture.credentialScreen`: off the trade host, a password / e-mail field, a code step, a challenge). `FLAG_SECURE` (system screenshots / recents) and "the terminal reads ready" do **not** gate it, and no image is taken without its redaction list (the snapshot of the same page).

When it captures: **(a)** on every `terminal_miss`, foreground and background, flow `anomaly` step `terminal_miss`, once per new page shape (`shape:<hash>`) then at most every 30 min; **(b)** every 10 min while the terminal is open, flow `periodic` step `view` (one run holds 60 steps); **(c)** at each step of the existing flows (`entry`, `amend`, `drill`, `positions`, `closed`).

**How a lane reads them** (diag tier; `scripts/ops/diag_fetch.sh` carries the credential):
1. List: `bash scripts/ops/diag_fetch.sh "/api/diag/phone_captures?account_id=breakout_2&limit=20"` -> `runs[]` (`run_id`, `flow`, `steps`, `failed`, `images`, `first_at`, `app_version`). `phone_captures_last` on `/api/bot/prop/status` names the newest run.
2. One run: `bash scripts/ops/diag_fetch.sh "/api/diag/phone_capture?account_id=breakout_2&run_id=<run_id>"` -> `steps[]` with the `image` and `dom` file names.
3. A file: `GET /api/diag/phone_capture_file?account_id=breakout_2&run_id=<run_id>&name=<NNN-step>.jpg` (image) or `.dom.json` (the sanitised DOM tree). The image route is binary: fetch it with the same credential and open it with the Read tool.
Never copy a capture image into git or a PR (public repo): describe what it shows.

**The 400 that blocked every upload (root cause, MEASURED 2026-11-07):** the app posts flow `closed` after every unclean Closed-orders read, but the server's `FLOWS` tuple lacked it, so each one answered 400 `flow must be one of ...`; the heartbeat showed `capture_err post:* 400` (`http` is scrubbed to `*`). 17 runs were stored in total, flows `positions` 9 / `amend` 5 / `entry` 3, none `closed`, the newest 2026-11-05 22:17Z. Fixed by adding `closed`, `anomaly`, `periodic` to `FLOWS`; `tests/test_phone_captures.py::test_the_apps_flow_names_are_all_known_to_the_server` fails if the app ever posts a flow the server refuses.

## 8. Known limits

- Images are redacted on the device by exec.js's mask list (account ids, balances, equity, P&L): a value the masker does not know is NOT hidden, so check an image before quoting it. The operator's own system screenshots are a different path (`FLAG_SECURE`, on until a tick reads `logged_in`, `MainActivity.setSecure`); the app's own captures do not depend on it.
- Expectation failures the page script cannot see (a Kotlin exception) arrive only as `error` events with a short reason.
- `ready` stays strict by design: after an unrecognised page the app reads nothing until a lane adapts it, which is what the alert is for.
