# Phone executor (breakout_2): action coverage and the self-diagnosis loop

> **Doc status:** `live` · category `instruction` · last verified `2026-11-11` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)
> Row: `PHONE-SELF-DIAGNOSE` (absorbs `PHONE-SCREENSHOTS`). Code: `tools/phone-executor/` (Kotlin app, `assets/exec.js`).

**Gates this adds or changes:** none. FLAG_SECURE gets narrower, so the operator can screenshot more screens. The new
read route is read-only. No trade path decision reads any field this adds.

Operator, 2026-11-11, verbatim: *"me being able to take screenshots and the app being able to A, do all the actions
without limitations and B, take screenshots of everything that it's doing so that it can send it back to a lane so that
the lane can understand what's going on... we need to close this loop"*.

## 1. How a lane diagnoses the app without asking the operator

| What you need | Where | Auth |
|---|---|---|
| What the app is doing right now: state, versions, FLAG_SECURE, capture count and last error, remote exec.js result | `GET /api/bot/prop/status?account_id=breakout_2` → `phone_heartbeat.state` (`secure`, `exec_js`, `exec_src`, `js_refresh`, `captures`, `capture_err`) | bot tier (no diag token) |
| What it did, step by step, and whether each step's screenshot is a real page | `GET /api/bot/prop/phone_steps?account_id=breakout_2&limit=5` (or `&run_id=`) → `runs[].steps_detail[]` with `step`, `ok`, `note`, `image`, `image_blank`, `img_why` | bot tier. **New in this PR.** |
| The screenshot itself, and the sanitized DOM it was taken with | `GET /api/diag/phone_capture_file?account_id=breakout_2&run_id=<run>&name=<image or .dom.json>` | diag token |
| Recent app events (submitted, mismatch, positions_miss, ...) | `phone_events` on `/prop/status` | bot tier |

`image_blank` is `true` when the frame is uniform (an off-screen WebView draw that rendered nothing) and `false` for a
real page. It is `null` when the image was not checked, and `image_check.read_state` then says why (`pillow_unavailable`,
`undecodable`, `no_image`). The app's own measure (`device_img_std`, taken BEFORE the redaction boxes are painted) wins
over the server's measure. The server sees an image that is already redacted. `img_why` says why a step has no image:
`credential_screen`, `no_snapshot` or `draw_failed:<err>`.

Every flow already captures each step (`Capture.step`, PHONE-EXEC-OBSERVABLE-1018): entry, cancel and close (flow
`cancel`), amend, drill, positions/closed misses, anomaly, and a periodic capture. The image is drawn off-screen from
the app's own WebView and redacted on the device (account ids, balances and P&L painted black). The only screens never
imaged are credential screens. Measured 2026-11-11T21:11Z (heartbeat, app `1b.361`): `captures: 332` posted since the
app started. The latest run, `cancel-prop-manual-c54b2229aa1c-c1-20261111T210600Z`, has 1 step, 1 image and 1 DOM
(77,836 bytes). **Not yet established: whether those images are real or blank.** Reading one needs the diag token,
which answers 401 until the operator resets `DIAG_READ_TOKEN`. The `image_blank` field above answers this on the bot
tier once this PR is deployed.

## 2. Coverage: every venue action the executor needs

Sources: the public bot routes `/api/bot/prop/{status,tickets,fills}` read 2026-11-11 ~21:15Z. The population is the
breakout_2 rows inside the routes' newest-200 windows: 53 breakout_2 fills since 2026-10-12, and the ticket
`phone_trail` amend statuses. **Broker layout change: 2026-11-07** (bottom nav plus a Trade view,
exec.js `2026-11-07.1`…`.5`). Results from before that date prove the action on the OLD layout only.

| Action | Status | Last proof on the device | Blocker / next step |
|---|---|---|---|
| **Submit entry with bracket (SL+TP)** | ✅ proven on the new layout | 2026-11-11T20:04:54Z `prop-manual-c54b2229aa1c`: "placed Buy 0.51 ETHUSD lim 2077.57 (seen in open orders)". The operator confirmed by hand at ~21:20Z that the ETH long is open. | Confirming the submit is still flaky: `prop-manual-de7e925668af` (SOL), 20:08:07Z "submitted but not found in Open orders/Positions after 3 reads". The venue "Order submitted" toast confirmer (#24333) is in the installed build. The confirm read depends on the Positions/Open orders reads below. |
| **Read positions** | ❌ broken since the layout change | Last venue Positions read: 2026-11-02T04:37Z (`phone_reconcile`, "venue Positions read overrides the inferred fill"). Every read since 2026-11-07 posts `no_table`: 7 `positions_miss` events between 17:14Z and 20:39Z today. Since then fills are INFERRED from candles. | Fix #24887 (exec.js `2026-11-11.1`: the region labelled Positions counts as the panel) is **merged**. Its signing run 43096668117 has been **queued since 20:32Z** behind the Actions backlog. Until it signs, the VM serves nothing: heartbeat `js_refresh: signature_mismatch`, meaning the tree is at 11-11.1 but the signature is for the older version. **No APK needed.** It loads within 30 min of the signature landing. Proof: `phone_heartbeat.state.exec_js == "2026-11-11.1"`, `exec_src == "remote"`, and `positions_state` other than `no_table`. #24887 covers only the empty (flat) view. A NON-empty Positions table on the new layout is unproven. |
| **Read open orders** | ⚠️ partial | 2026-11-11T20:04Z: c54b "seen in open orders" (positive). 20:08Z: de7e not found after 3 reads (negative, cause unknown). | The capture of the de7e confirm steps answers this (`/prop/phone_steps`, run `entry-prop-manual-de7e925668af-*`). |
| **Read closed orders / history (exit price)** | ❌ never proven | Every phone-reconciled close since 2026-10-16 is `closed_unpriced`: 10 of the 10 `phone_reconcile` closes in the window. `account_status.closed_orders_state: "not_read"` today. | No reader for the closed-orders view on the new layout. The exit price is never read from the venue on either layout. Building one needs a real Closed-orders DOM capture (diag token), then an exec.js reader (remote, **no APK**). Filed on the row. |
| **Read balance / equity** | ✅ equity proven, balance not | 2026-11-11T21:06Z `account_status` equity 4896.11 `MEASURED` (label `portfolio`). `balance`, `realized_today` and `unrealized` are null. | Day P&L shows `day_pnl_state: unreported`. A balance/realized reader needs the account panel DOM (exec.js, **no APK**). |
| **Amend SL** | ⚠️ proven on the old layout only | 4 `amended` results: 2026-10-21T02:01Z, 10-21T18:08Z, 10-22T17:10Z, 10-30T02:00Z. Since the layout change: 1 `no_position` (11-09T12:00Z, a false flat while the positions read was broken). 2 `mismatch` results (10-18, 10-25) and 1 `refused` (10-15) are also in the window. | Unproven on the new layout. It runs through the position sheet, which needs a positions read first, so it waits on #24887. Rehearsal drill: `POST /phone/drill` (needs the screen). |
| **Amend TP** | ❌ never proven | `amend_kind` is `sl` on all 11 amend records in the window. No TP amend was ever issued. | The code path exists (`executeAmendSheet`, `live_review_apply` `move_tp`) but has never run on the device. It needs one rehearsal drill on a test position (MD-EXEC-DEV-TEST-TRADES) once positions read again. |
| **Cancel resting entry** | ⚠️ unproven | Channel added 2026-11-09 (#24469, in the installed APK `1b.361`). First observed run: 2026-11-11T21:06Z, `cancel-prop-manual-c54b2229aa1c-c1` (1 step, image present). Its `cancel_result` is not visible on the bot tier. | Read the run on `/prop/phone_steps`. Note: c54b had already FILLED (operator), so `not_found` is the expected result here. That does not prove cancel. |
| **Close position** | ❌ never proven | `executeClose` (#24469) has never been observed. Every close in the window was an SL, a max-hold inferred close or an operator hand close (5 `prop_report_close_action` rows). | It runs through the position sheet, so it waits on #24887. Proof needs one drill close on a test position (`drillCloseTest` already exists). |
| **Operator screenshot of the terminal** | ⚠️ unproven by the operator | Heartbeat 2026-11-11T21:11Z: `secure: false`, so screenshots are currently allowed. But on the installed build, any page that did not read `logged_in` (a new layout reading "other", a half-loaded view) turns FLAG_SECURE back on. | Fixed in this PR's Kotlin: FLAG_SECURE follows `Capture.credentialScreen` (off the trade host, a password or e-mail field, a code step, a challenge) and nothing else. **Needs the APK** (bundle below). |

### What is limited and why (summary)

1. **The 2026-11-07 broker layout change** broke the reads (positions, closed orders). Every sheet action (amend SL/TP,
   close) and the submit confirm depend on those reads. #24887 is the first piece, waiting only for its signature run.
2. **Two actions have never run on the device at all:** TP amend and close. They need one rehearsal drill each, on a
   test position, after the positions read works.
3. **Exit price and balance were never read.** These need readers built from a real DOM capture. That is exec.js work
   (remote, no APK) but needs the diag token to read the capture.

## 3. What still needs an APK install: ONE bundle

Everything in exec.js ships remotely (signed, `phone-exec-js-sign.yml`, loads within 30 min, no reinstall). The ONE APK
built from `main` after this PR merges carries every Kotlin change below. These are all the Kotlin changes waiting on
`main`, because the installed `1b.361` already has #24469 (cancel/close) and #24333 (venue toast):

| Kotlin change | PR | Why it needs the APK |
|---|---|---|
| FLAG_SECURE on credential screens only (deliverable 1) | this PR | `Window.setFlags` is native |
| Device-side blank measure per image (`img_std`) + `img_why` on every step | this PR | the bitmap is drawn natively (`Capture.bitmap`) |

The operator's one physical step: install the APK from the `phone-executor-apk` run on the merge commit. Nothing else is
bundled, and no other APK is planned. Verify after install: heartbeat `app_version` is newer than `1b.361`, the
operator screenshots the terminal, and `/prop/phone_steps` shows `device_img_std` on new steps.

## 4. Not verified in this session (and how to close each)

- **Real vs blank capture images.** Diag answers 401 (`missing_token`), so no image was read. Closes with the first
  `/prop/phone_steps` read after deploy. `image_check` needs Pillow on the VM; if Pillow is absent the read says
  `pillow_unavailable`, and `device_img_std` closes it after the APK.
- **The operator screenshot.** Closes with the operator's report after the APK.
- **#24887 on the device.** Closes with heartbeat `exec_js 2026-11-11.1` / `exec_src remote` after signing run
  43096668117 completes (the operator chose to wait for the queue, not to cancel runs).
