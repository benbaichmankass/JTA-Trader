# gitleaks baseline — what it accepts and why

> **Doc status:** `live` · category `evidence` · last verified `2026-11-16` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)

`.gitleaks-baseline.json` (repo root) is the accepted-findings list read by
`.github/workflows/gitleaks-history-weekly.yml`. With it, the weekly full-history
scan fails only on **NEW** findings. It is a **redacted gitleaks report**: every
`Secret` is `REDACTED` and every `Match` carries the marker. It cannot be edited
to "trust" a value, only to accept a finding by its `Fingerprint`
(`commit:file:rule:line`).

## What was measured (2026-09-29)

- **Population:** a fresh full `git clone` of `main` + all 1,501 remote branches
  (12,301 commits), gitleaks 8.24.3, default rules, `--redact=100`.
- **352 findings = 350 `generic-api-key` + 2 `telegram-bot-api-token`.** This equals
  the count the first CI dispatch reported (run 36584026733), so the local view
  and CI's view agree.
- **Classification was by value shape and key name, values never printed.** 0 of
  the 350 generic hits carry a vendor-token prefix; 1 of 352 contains a
  placeholder word. This is a shape judgement, not a rotation of anything.

| class | rows | what it is |
|---|---:|---|
| registry_key ids | 295 | `registry_key` values (`pending-…`) in the archived `SESSIONS.json` register and two work-object yamls |
| prose fragment | 23 | 18 junk `.merge_file_*` files committed at `eb3c64a98`, plus 5 rows in `health-review-backlog.json` (a hyphenated phrase, not a credential) |
| test constants / env names | 18 | synthetic values in tests (`abc…`, `0123…` signing-key constants) and env-var **names** (`VELOTRADE_…`) |
| env-var names / ids / other | 10 | env-var names in `config/accounts.yaml`, the M5 consumer scripts, pending-pings, the operator notebook, a gas ticker code |
| REPLACE_ME placeholders | 2 | `config/master-secrets.template.yaml` template values |
| **KNOWN-REVOKED** | 4 | named below |

Sum check: 295 + 23 + 18 + 10 + 2 + 4 = **352**.

## Known-revoked entries (named, deliberately baselined)

These are real credential-shaped values that were committed. The operator stated
**"Revoked"** on 2026-09-29 at 13:50Z (decision JC-SA-04). They stay in the
baseline so the weekly run is green, and are listed here **by name** so they are
never mistaken for false positives:

| rule | file | commit | line |
|---|---|---|---:|
| `telegram-bot-api-token` | `.env` | `2c7818524a78` | 1 |
| `telegram-bot-api-token` | `bybit_config.py` | `9ea895023d47` | 1 |
| `generic-api-key` | `test_bybit_keys.py` (testnet key) | `67f307e0a408` | 5 |
| `generic-api-key` | `test_bybit_keys.py` (testnet secret) | `67f307e0a408` | 6 |

`tests/test_gitleaks_baseline.py` fails if any of these four is missing from the
baseline or from this table.

## Proof that a NEW key still fails (2026-09-29, scratch clone, never pushed)

| scan | result |
|---|---|
| full history, baseline applied | **0** new findings |
| same, plus one commit planting a random synthetic `ghp_`-shaped string and a random `api_key = "…"` in `FAKE_PLANTED_NOT_A_CREDENTIAL.txt` | **2** new findings (`github-pat`, `generic-api-key`), exit code 1 |

The planted strings are random alphanumerics generated for the test, not
credentials.

## Known limitation

The baseline includes each finding's public commit `Message` (gitleaks compares
it; blanking it made all 352 findings reappear as new). For 14 registry-id rows the
matched string also appears in that public commit message. None of the 14 is a
known-revoked row.

## Regenerating

```
git clone <repo> && cd <repo>
gitleaks detect --source . --redact=100 --no-banner --log-level error --exit-code 0 \
  --report-format json --report-path .gitleaks-baseline.json
```

Re-baselining accepts everything currently found, so do it only after reading the
new rows (`scripts/ops/gitleaks_summarize.py` prints rule / file / commit / line).

## 2026-11-16 refresh (SEC-GITLEAKS-BASELINE-1116)

**Why.** `gitleaks-history-weekly` was red every Monday from 2026-11-02 (runs 7, 8, 9; run 43878123590 on 2026-11-16 had
**387** findings the 2026-09-29 baseline did not cover). The job itself was healthy; the research pipeline writes new
machine-made result files every day and the default `generic-api-key` rule matches them.

**What the 387 were (population: the full run log, every line read; rule / path / commit / line only, no value).**

| class | rows | what it is |
|---:|---:|---|
| research artifacts | 384 | `comms/research/RQ-*/{verdict,measurement}.json` (367), `research/results/RQ-*.jsonl` (16), `comms/research/broad_paths/bp2-*/manifest.json` (1): `*_sha256` content hashes (e.g. `trade_key_sha256`) and ids, matched on the key NAME ("key") plus entropy |
| other | 3 | `config/prop_phone_devices.yaml:18` (`token_sha256`, a hash digest of a device token, not the token), `tests/test_prop_platform_dxtrade_api.py:23` (a test constant), `docs/claude/work/checklist/E61.json:14` (prose in a checklist note) |

All 387 are rule `generic-api-key`; **0** came from a vendor rule. Classification is by rule id and key shape, values never
printed. No live credential; nothing was rotated.

**Two changes, both tight.**

1. **`.gitleaks.toml`** (read automatically from the scan root): an allowlist for rule `generic-api-key` ONLY, paths
   `^comms/research/` and `^research/results/` ONLY (manager approval 2026-11-16). Every vendor rule (github-pat, aws,
   telegram-bot-api-token, private-key, ...) still scans those paths, and `generic-api-key` still scans everything else.
   `tests/test_gitleaks_baseline.py` pins the scope (one rule, two paths, no regex or commit exemptions) and, when a
   gitleaks binary is present, plants a synthetic `ghp_`-shaped token under `comms/research/` and proves it is still caught
   (and a planted generic key outside the research paths).
2. **`.gitleaks-baseline.json`**: the 352 original entries are kept byte for byte (the four known-revoked rows above are
   unchanged) and **7** fingerprints are appended after a full-history scan of `main` with the new config (gitleaks 8.24.3,
   sha256-verified, `--redact=100`): the 3 "other" rows above, plus 4 test/workflow strings that this scan reports with a
   fingerprint the old file does not hold: `.github/workflows/vm-net-diag.yml:99` (the RFC 6455 sample `Sec-WebSocket-Key`),
   `tests/test_validation.py:23` and `tests/test_vwap_strategy.py:1028` (a Telegram-token-SHAPED string the test itself labels
   `fake, shape-valid`), `tests/test_api_reporting.py:25` (`key=...` in a test string). These four were not in the CI log's
   printed list; why CI matched them to the old file and the local scan did not is NOT established (UNVERIFIED), so they are
   baselined here rather than assumed.

**Check.** The same scan with `.gitleaks.toml` and the new baseline applied reports **0** new findings (see the PR).
The next scheduled run (Mondays 05:17Z) is the real test.
