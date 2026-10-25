# Real-page fixtures for exec.js (PHONE-EXEC-OBSERVABLE-1018, piece 3)

Every `<name>.html` here is a Breakout terminal page **as the phone saw it**, rebuilt from a DOM snapshot the
app captured (`__ex.snapshot`, redacted on the device, scrubbed on the server, stored 7 days) with **every number
replaced**. `exec_fixtures_check.js` serves each one on the trade host, injects the bundled `exec.js` and runs the
assertions in `<name>.spec.json`. CI runs it on every push (`phone-executor-apk.yml`, job `check`), so a fix to a
reader or a target is proven against the real page shape instead of guessed per APK.

## Adding one from a capture

```
# 1. pick the run and step (manager / operator, DIAG token): GET /api/diag/phone_captures?account_id=breakout_2
#    then GET /api/diag/phone_capture?account_id=breakout_2&run_id=<run>
# 2. fetch the DOM snapshot of the step: GET /api/diag/phone_capture_file?account_id=breakout_2&run_id=<run>&name=NNN-<step>.dom.json
python3 -I tools/phone-executor/test/fixture_from_capture.py <that file> --name breakout-positions-sheet \
    --note "what the page shows / which miss it reproduces" --source "<run>/NNN-<step>"
# 3. write breakout-positions-sheet.spec.json: {"checks": [{"call": "__ex.positionsRead()", "expect": {...}, "note": "..."}]}
#    expect = partial deep match (objects recurse, arrays compare whole, "re:<regex>" for strings, "any")
NODE_PATH=<playwright node_modules> node tools/phone-executor/test/exec_fixtures_check.js
```

What goes in: the `.html`, `.meta.json` and `.spec.json`. **Never the raw capture** (it is not in the repo by
decision: captures live on the VM only, 7-day TTL). The generator replaces every digit run (same length and
leading digit, seeded by the value, so one value maps to one replacement across the page); ids and money were
already masked on the device. Check the HTML comment and `meta.json` before committing a fixture built from a
page you did not look at.

A fixture is static: it proves **reads and targets** (what `positionsRead` parses, which cell `sheetTarget`
picks, whether a point is covered, what the sheet / modal readers return). Whether a tap OPENS something is the
rehearsal drill's job on the phone (`phone-drill` system-action).

`sample-positions-sheet-synthetic` is built from `exec_check.js`'s synthetic sheet page, not from a phone
capture: it proves the tooling end to end and is replaced by the first real one.

## Fixtures

| fixture | source | what it proves |
|---|---|---|
| `sample-positions-sheet-synthetic` | `exec_check.js`'s synthetic sheet page | the tooling end to end (replaced by real ones); built BEFORE the geometry fix below and left as is — it carries no geometry check, and its exact build recipe (which synthetic variant, which tabs shown) was not recorded, so rebuild it from a recorded recipe or retire it before asserting a point on it |
| `breakout-sheet-tpsl-stop-row` | breakout_2, app 1b.300, 2026-10-18 14:32Z, amend #a8 step `003-stop_row` | the REAL [1 TP / 1 SL] rows carry the trigger (USD) **and** the quantity (ETH) as separate bare numbers; `sheetOrders` reads the trigger by the quote unit (exec.js ≥ 2026-10-18.4; ≤ .3 returned null here and the app reported `human_moved`) and the row's Edit control is the one pencil; the pencil is `span[tabindex] > button "Edit order"` and `sheetEditStopTarget` resolves it to the BUTTON with a touch point inside its rect (exec.js ≥ 2026-10-18.5; drill 1 clicked the wrapper span and opened nothing) |

| `breakout-modal-edit-stop-loss` | breakout_2, app 1b.300 + exec.js .5, 2026-10-18 19:00Z, drill 2 step `010-modal_open` | the REAL "Edit Stop loss" modal: the ONE Trigger input is the PRICE field (`name=protectionStopLossPrice`, text, unit USD); the "Stop loss Entry distance" slider (`input type=range` in `div.ds-slider`) is seen (`sliders: 1`) and never a target — `modalSetTrigger` types only into the price input and the slider's value is untouched (exec.js ≥ 2026-10-18.6); no sheet root while the modal is up (`sheetOrders` → `no_sheet`), which is why drill 2 read null after Cancel |

**Geometry (fixed 2026-10-18):** every rendered node is `position:absolute`, so a node's `left/top` are relative to
its rendered PARENT (the containing block), not the viewport; the tool subtracts the parent's rect. Fixtures built
before that fix placed nested nodes at accumulated offsets (the Stop row's Edit button at 1383,4926 instead of
335,392), which no read-only spec noticed and the first point-in-rect assertion did. Rebuild any fixture from its
capture with the current tool before adding a geometry check to it.
