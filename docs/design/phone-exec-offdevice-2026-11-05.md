# Running the Breakout executor off the operator's phone — viability and design spec (2026-11-05)

> **Doc status:** `live` · category `architecture` · last verified `2026-11-05` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)
>
> **Lane PHONE-EXEC-OFFDEVICE** (dispatched by Manager Session 2026-11-04b). Tier-1, docs only. **Nothing here is built, and no live executor, account or credential was touched.**
>
> **Gates this adds or changes: none.** This is a viability memo with a go/no-go for the operator. Any later build is its own row and its own decision.

**Operator request (2026-11-05 ~06:55Z, verbatim in substance):** *"add a work item this week to check the viability of finding a way to run the executor not directly on my phone, like maybe a digital twin of the phone so that it has the same device ID and same IP address and everything, but doesn't do it on my phone ... at least like a design spec, and then we can decide if it's worth building."*

## 0. Verdict up front

1. **A "digital twin with the same device ID" is the wrong target.** The venue never sees our device ID (§ 1). What the venue can see is the **IP, a browser fingerprint, and a logged-in session**. Copying a hardware identity onto an emulator would be identity spoofing, adds risk and buys nothing. **Do not do it** (§ 2.5).
2. **The legitimate version is a second, honest Android device at the operator's home** on the home network, with its own identity, logging in the way the phone does today. That is allowed by everything we could read, subject to the Breakout questions in § 2.1.
3. **Recommendation: GO on a small spike** (a spare phone, or a redroid container on an always-on home box). **NO-GO on cloud Android and on headless-browser replacement** (§ 3). Details and the questions only the operator can answer: § 4.
4. **Two findings outside this request:** the executor serves **one** venue, not three (§ 1.1), and Tradeify's published text says running a bot across multiple firms is against its policy (§ 2.2). The second needs the operator.

## 1. How the executor works today

Sources read: `tools/phone-executor/` (Kotlin app + `assets/exec.js`), `docs/integrations/breakout-phone-executor-DESIGN.md`, `config/prop_platforms.yaml`, `config/accounts.yaml`, checklist rows PHONE-EXEC-DESIGN, PHONE-EXEC-1B, PHONE-KEEPALIVE, PHONE-AUTOLOGIN, PHONE-AUTOLOGIN-2, PHONE-BG, PROP-EXEC.

### 1.1 Which venues the phone serves (correcting the dispatch)

The dispatch named three venues. **Only `breakout_2` runs on the phone** (`config/prop_platforms.yaml::phone_accounts.breakout_2`, `platform: breakout_phone`, `terminal_url: https://trade.breakoutprop.com/`). Measured from `config/prop_platforms.yaml`:

| account | executor | runs on |
|---|---|---|
| `breakout_2` | `breakout_phone` (Android WebView app "JTA Executor") | the operator's phone |
| `tradeify_1` | `platform: dxtrade` (headless-browser adapter) | the live VM |
| `velotrade_1` | `platform: dxtrade_api` (REST) | the live VM |

So the off-device question is a **Breakout-only** question. Tradeify and Velotrade are in § 2 for completeness, because the same operator, strategies and home network are involved.

Why the phone exists at all: the VM's egress is **blocked by Cloudflare** for `trade.breakoutprop.com` (HTTP 403, `server=cloudflare`; the ASN-block reading, error 1005, is INFERRED not measured: design § 7.9). The phone, on a consumer network with a stock WebView, is the only path that has been measured to work.

### 1.2 What the executor depends on

| dependency | what it is | who/what holds it |
|---|---|---|
| **App identity ("device ID")** | A 256-bit token minted by the app. Only its SHA-256 fingerprint ("Share ID") is committed (`config/prop_phone_devices.yaml`), pinned to one account. | **Our server only.** It is a pairing token for `/api/bot/prop/phone/*`. **It is never sent to Breakout.** |
| **WebView session** | Stock Android WebView, stock user agent (carries the `wv` marker), no stealth/spoofing/challenge-solving (design header + § 7.11). Cookies/localStorage live in the app's WebView profile. | The phone |
| **Login** | Email-based login with a number-match step. Automatic re-login (PHONE-AUTOLOGIN-2/3) reads the login mail from a **dedicated Gmail inbox over IMAP** (`Mail.kt`, app password in app Setup). No SMS/authenticator in the path. Row state: **landed_unproven**. | App + the dedicated inbox |
| **IP** | Whatever network the phone is on. Not pinned: Wi-Fi at home or mobile data, and it changes when the phone moves. | Phone/network |
| **Cloudflare/Turnstile classification** | A genuine consumer-network WebView passes; the datacenter VM does not. | Venue's edge |
| **Keepalive** | Foreground service, 60 s watchdog, AlarmManager chain, boot receiver, battery-optimisation exemption, "Display over other apps" (`Liveness.kt`, `KeepAlive.kt`, manifest). Heartbeat reported to `/api/bot/prop/status`; stale-heartbeat alert is hourly-carrier (~70 min latency). | App + Android settings |
| **Background operation** | A backgrounded WebView does not run JS, so the app brings itself to the front to claim and fill, then minimises (PHONE-BG, observed). | App + overlay permission |

### 1.3 What the operator still does by hand today

Install each APK build; grant "Allow restricted settings", "Display over other apps", battery exemption; keep the phone charged, on, and not killed by the OS; reopen the app after it dies (it did on 2026-10-13: heartbeat gap ~15:14Z to 18:48Z); paste the inbox app password in Setup; and **not use the phone in a way that fights the app's bring-to-front** (the operator's own aspiration, PHONE-AUTOLOGIN note 2026-10-10: run as backgrounded as possible).

### 1.4 How reliable is it? (MEASURED, with population)

PHONE-KEEPALIVE row, read-only API at 2026-11-01T14:25Z: `app_version 1b.311`, `fgs_running`, `battery_exempt` true, **`restarts_24h = 3`**, `last_restart_reason = activity_missing(service_tick)`, `bg_runs 5 / bg_ok 5`. The API returns only the newest ~40 events, so a 48 h gap audit has **not** been done and the row's observation is NOT MET. PHONE-EXEC-1B is `landed_unproven`: the first live ticket's `phone_result` (confirm dialog, order on venue, SL/TP on venue) is **absent** on the newest non-test breakout_2 tickets (2026-10-28/29). So the baseline is working but not yet proven, and "harden the phone" is a real, ongoing cost.

## 2. Venue rules — the question that decides whether this is allowed

**Method and limits.** Public pages only, read 2026-11-05 unless dated otherwise. The binding contracts (Terms of Use, Evaluation Agreement, Program Rules) for Breakout are **unread**: every `breakoutprop.com` host answers a Cloudflare challenge to our tooling, and we do not try to defeat it. Tradeify and Velotrade fetches below were summarised by a fetch tool; quotes are as returned and should be re-read by a human before anything is relied on. "Not stated" means not stated **in the pages read**, never "permitted".

### 2.1 Breakout (the only venue the phone serves)

Source: `https://intercom.help/breakoutprop/en/` FAQ, 108 articles crawled 2026-10-08 (full verbatim record: [`breakout-terms-read-2026-10-08.md`](../integrations/breakout-terms-read-2026-10-08.md)). Evaluation prohibited-practices article `https://intercom.help/breakoutprop/en/articles/11644090-what-trading-practices-are-prohibited-during-the-breakout-evaluation`:

> *"Sharing account access, or trading multiple accounts from the same household, device, or IP address"*

- **VPS/remote devices:** not stated in the FAQ. (The third-party survey at `https://velotrade.com/reports/algo-trading-rules` lists Breakout's hosted-servers position as "Not stated" and third-party bots as "Restricted"; that is a competitor's summary, not Breakout's text.)
- **Automation:** FAQ is silent on bots/UI automation; the operator accepted the automation risk on 2026-10-05 (pipeline `PI-20261005-9HEP9LYP-0003`, killed).
- **Device/IP consistency:** the only rule is the clause above. It prohibits **multiple accounts** on one household/device/IP, in the **evaluation** list; the funded list omits it. `breakout_2` is `account_state: evaluation`. It does **not** require that one account always uses one device or IP.
- **Account sharing:** prohibited ("Sharing account access"). A second device of ours, run by us, with the operator's own login, is not sharing in the ordinary sense, but the agreements are unread.
- **Consequence for this idea:** a home twin does not create "multiple accounts on one device/IP" **as long as breakout_2 is the only Breakout account active from that household** (`breakout_1` is breached/retired, `retired: true`). Buying a second Breakout account later would put two accounts on one household, with or without a twin: that is already the live risk and is independent of this design.
- **Spoofing:** the FAQ has no clause on device fingerprints. Copying a device identity to make the venue believe a different machine is the original would be deception of the venue's (and Cloudflare's) checks. Nothing we read allows it, and our own design principle forbids it ("stock WebView user agent and no stealth, spoofing or challenge-solving", design header). **Treat as forbidden by us, whatever the text says.**
- **Unclear → question for Breakout in writing** (a first-party answer beats any inference): *"I hold one Breakout evaluation. I run my own software on a dedicated Android device on my home network, logged in with my own credentials. May I replace that device with another dedicated Android device or an emulator on the same home network? Is any device, IP or fingerprint continuity required for one account, and is a changed device treated as account sharing?"*

### 2.2 Tradeify (`tradeify_1`; VM-executed today, relevant only if the idea ever widened)

Source: `https://intercom.help/tradeify/en/articles/10468318-guidelines-for-traders` (fetched 2026-11-05):

- Bots allowed if you own them: *"no one else has access to or is using it."*
- *"We scan to ensure there are no similar orders on other accounts."* and *"We will also require a live video of you enabling the code on your own PC."*
- *"using it across multiple firms is against Tradeify's policy."*
- Personal bots allowed, not high-frequency; it reserves the right to request documentation if risk measures flag an account.
- **VPS/VPN/remote desktop, multiple IPs/devices/locations: not stated on this page.** Our 2026-09-30 note (`docs/research/tradeify-portfolio-feasibility-2026-09-30.md` line 51) records "VPN/VPS allowed; Tradeify may request verification if multiple IPs access it" without a URL; **I could not re-find it on the page just read**, so treat that as UNVERIFIED.
- ⚠️ **Flag for the operator, outside this request:** the "across multiple firms" and "similar orders on other accounts" lines read as applying to **our setup today** (the same strategies run on Breakout, Tradeify and Velotrade). The fetch tool's summary did not make clear whether the lines apply to evaluations or funded accounts only. Needs the operator to read the page and decide whether to ask Tradeify. It does not depend on this design.

### 2.3 Velotrade (`velotrade_1`; REST from the VM today)

Sources: `https://velotrade.com/rules` as quoted in `docs/research/velotrade-api-executor-design-2026-10-05.md` § 3 (read 2026-10-05) and `https://velotrade.com/reports/algo-trading-rules` (fetched 2026-11-05, Velotrade's own survey page):

- *"Velotrade permits the use of Expert Advisors (EAs) and other automated trading systems."* and *"Full programmatic API access is available on all accounts ... Connect any execution engine, algo trading system, trading bot, or signal automation directly to your account via the DXtrade REST or WebSocket API."*
- Hosted servers: the survey table lists Velotrade as **"Permitted"**. Its own FAQ heading on running a bot on a VPS had no answer text.
- IP/device, multiple accounts, account sharing: **not stated** on the pages read. Velotrade's blog (`https://velotrade.com/blog/prop-firms-that-allow-eas`, search snippet only, not read in full) says copy trading is allowed only between accounts you own.
- Cross-account hedging is banned (design § 1.3).

### 2.4 Summary table

| venue | VPS / remote device | bots | device/IP consistency | account sharing | verdict for a home-network twin |
|---|---|---|---|---|---|
| Breakout (phone) | not stated (FAQ); agreements unread | FAQ silent; risk accepted by operator | only: no multiple accounts per household/device/IP (evaluation list) | prohibited | **Allowed on the text read, if breakout_2 stays the only Breakout account at that household. Ask Breakout to confirm.** |
| Tradeify | not stated on the page read; older note UNVERIFIED | own bot only | "may request verification if multiple IPs" (UNVERIFIED) | implied no | n/a (not on the phone) |
| Velotrade | survey: "Permitted" | permitted incl. API | not stated | not stated | n/a (not on the phone) |

### 2.5 Where copying an identity would be spoofing

- **Same network (home IP), second honest device, own login:** legitimate use of your own connection.
- **Cloning an Android ID / Build fingerprint / Play Integrity attestation / WebView fingerprint onto an emulator so the venue or Cloudflare cannot tell it from the phone:** spoofing. Forbidden by our own rule, and it is exactly what bot-detection looks for. It also **has no upside**, because the venue is not given our app's device ID (§ 1.2).
- **Residential-proxy egress used to make a datacenter machine look like a home user:** an evasion of the block that exists to stop datacenter clients. Same category. Not recommended even where a vendor sells it.

## 3. Options

Costs are order-of-magnitude estimates (ESTIMATED, not quoted), effort in lane-days of an engineer-session.

### 3.1 Baseline: keep the phone, harden it
- **Feasibility:** already running.
- **Cost / effort:** ~$0 plus the 5-minute stale-heartbeat timer (PHONE-KEEPALIVE open follow-up), ~0.5 day; optionally a dedicated charger and a "do not disturb" profile.
- **Venue sees:** unchanged (phone, whatever network it is on, WebView session).
- **Failure modes:** `restarts_24h=3` on 2026-11-01; Android killing the app; the operator using or carrying the phone (IP changes to mobile data; phone leaves the house); updates; battery.
- **Operator by hand:** installs, settings grants, reopening after a death, inbox app password.

### 3.2 Cheap dedicated spare Android phone at home
- **Feasibility:** high. The app is a plain APK built by CI (`phone-executor-apk.yml`), no root, no special build.
- **Cost / effort:** ~$60-150 for a used handset, a charger on a smart plug; ~1 day (pair a second device, update `config/prop_phone_devices.yaml`, test with the existing `phone-dry-test` action).
- **Venue sees:** a **different device** (new WebView profile, its own cookies) on the **home IP**, which is more stable than a phone that roams. A fresh login (number-match via the inbox) is needed once.
- **Failure modes:** same Android keepalive issues as the baseline, but the phone is never carried or used; home Wi-Fi/ISP outage; dynamic home IP changes at router reboot (venue sees an IP change mid-session, same as today on mobile data); a stuck-device hardware failure.
- **Operator by hand:** one-time install/grants/login, plug it in. Pair it with the Breakout question (§ 2.1) before relying on it.
- **Fit to the request:** best match of "not on my phone, same home IP, nothing spoofed."

### 3.3 Android emulator / redroid container on an always-on home box
- **Feasibility:** medium. redroid needs a Linux host with binder/ashmem kernel modules (not available on many consumer routers/NAS images); Android Studio's emulator needs KVM and a GPU-less software path is slow. A mini-PC or Raspberry Pi 5 class box works for redroid in principle.
- **Cost / effort:** ~$150-350 for a mini-PC (or $0 if the operator has an always-on machine); 3-5 days (host setup, redroid image with WebView, Play-Services-free APK sideload, headless display/automation for the overlay permission, auto-restart, monitoring).
- **Venue sees:** the **home IP for real**, but an emulator's WebView/Build fingerprint, which commonly differs from a phone and can be flagged by Cloudflare/Turnstile or the venue's own checks. **Unknown whether the Breakout terminal accepts it**; we would learn that only on a test. We must not mask the fingerprint (§ 2.5), so if it is challenged, this option simply fails.
- **Failure modes:** bot-detection on emulator fingerprints; the emulator's software WebView is slower; "Display over other apps"/bring-to-front logic (PHONE-BG) behaves differently without a physical screen; home ISP/power; the box needs updates.
- **Operator by hand:** buy/host the box, give SSH access path, one-time login. Effort and risk are higher than 3.2 for the same IP benefit.

### 3.4 Cloud Android instance or VPS (with or without residential egress)
- **Feasibility:** low for this venue. The reason the phone exists is that **datacenter egress is blocked by Cloudflare** for the Breakout terminal (§ 1.1). A cloud Android (Genymotion Cloud, AWS Device Farm, a redroid on a VPS) leaves from a datacenter ASN and is expected to be blocked the same way (INFERRED from the VM result; not tested on a cloud Android).
- **Residential-egress variant:** routing through a residential proxy makes the IP look like a home user while the machine is a datacenter emulator. That is evasion (§ 2.5) and the IP is a different household from the operator's. Not recommended; do not build.
- **Cost / effort:** $20-60/month for cloud Android; a residential proxy extra; 3-5 days.
- **Failure modes:** block; proxy IP rotation breaking session continuity; account-sharing optics ("who is at that IP?").
- **Operator by hand:** same as 3.3 plus the vendor account.

### 3.5 Headless-browser automation in place of the WebView
- **Feasibility:** low-to-medium. It is exactly what the VM executor does for Tradeify (Playwright, `src/prop/platform/dxtrade.py`), and it works there because DXtrade white-labels have no Cloudflare block on the VM. For Breakout it needs a residential/home IP (the VM is blocked) and a real-browser fingerprint (headless Chromium is trivially detectable and a Turnstile target).
- **Cost / effort:** large: `breakout_terminal`-style adapter exists for the OLD terminal; the new terminal's DOM was only ever measured through the WebView, and the 8,600-line `dxtrade.py` shows how DOM-heavy this is. 5-10 days plus a home host for the egress. Not cheaper than 3.2.
- **Venue sees:** a desktop-class headless browser on the home IP; **the highest chance of being challenged**.
- **Failure modes:** bot challenge; DOM drift (the PHONE-* history is mostly DOM drift); login number-match needs the same inbox plumbing.
- **Operator by hand:** the host box and the one-time login.

### 3.6 Comparison

| option | works for Breakout? | venue sees | build effort | monthly cost | spoofing risk | operator by hand |
|---|---|---|---|---|---|---|
| Baseline (harden phone) | yes, today | phone, roaming IP | 0.5 d | ~0 | none | installs, reopen after deaths |
| **Spare phone at home** | very likely | new device, **stable home IP** | ~1 d | ~0 after $60-150 | none | one-time setup |
| redroid at home | uncertain (emulator fingerprint) | emulator, home IP | 3-5 d | ~0 after hardware | none if unmasked; **fails if flagged** | box + setup |
| Cloud Android / VPS | **expected to be blocked** | datacenter IP | 3-5 d | $20-60+ | residential variant = evasion | vendor account |
| Headless browser | unlikely (Cloudflare + fingerprint) | desktop headless | 5-10 d | host box | detection arms race | host + login |

## 4. Recommendation and go/no-go

**Decision: GO for a spike on the spare-phone path (3.2); NO-GO on 3.3-3.5 until that result and the Breakout answer are in.** A redroid spike (3.3) is worth doing only if the operator has a spare always-on Linux box and wants to stop buying handsets.

Rationale: 3.2 removes the real problems (the phone being used, roaming and killed) at the lowest cost and risk, keeps the venue-visible shape (an ordinary Android WebView on a consumer network), and needs no identity copying. The "twin with the same device ID" in the request has nothing to attach to: the venue is never shown our device ID, and cloning a hardware identity would be spoofing.

**Proposed spike (not started; needs the operator's go):**
1. Ask Breakout in writing (§ 2.1 question). Do not wait for the answer to buy the handset; do wait for it before moving live tickets onto the second device.
2. Pair a spare phone as a **second** device pinned to `breakout_2`, in **dry** mode first (`phone-dry-test` action), alongside the current phone; then switch the pin and retire the old device in `config/prop_phone_devices.yaml` (one device per account, so there is no double-claim).
3. Success: a clean `dry_filled` with the app backgrounded, 48 h with no heartbeat gap > 10 min on one build, and the PHONE-EXEC-1B close observation met on a real ticket.

**Questions only the operator can answer:**
1. Is the phone on home Wi-Fi when it executes, or on mobile data? (Decides how much IP stability a home device actually adds. Not measured here.)
2. Do you have a spare Android phone, or an always-on Linux box at home? (Decides 3.2 vs 3.3.)
3. Do you accept the Breakout terms risk on a second device, or do you want to ask Breakout first (§ 2.1) / paste the Evaluation Agreement so a session can quote it?
4. Will `breakout_2` stay the only Breakout account at that household? (Clause A.)
5. Tradeify's *"using it across multiple firms is against Tradeify's policy"* (§ 2.2): do you want to read the page and decide whether to ask Tradeify? Independent of this design.
6. Is a hardware purchase of roughly $60-150 authorised, and is the spike worth its ~1 lane-day?

## 5. Not established

- What identifiers the Breakout terminal or its Cloudflare layer collect from a WebView (canvas, WebGL, Play Integrity, etc.) — nothing in our captures shows it.
- Whether an emulator or a second physical device passes Cloudflare for `trade.breakoutprop.com` — untested.
- Breakout's Evaluation Agreement, Program Rules and Terms of Use (all 403 to our tooling).
- Tradeify's VPS/IP stance (the 2026-09-30 note has no URL); Velotrade's IP/device and multiple-account rules.
- Cost figures in § 3 are ESTIMATED, not quoted.
