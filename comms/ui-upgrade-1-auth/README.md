# UI-UPGRADE-1-AUTH — SPA side (step 3), handoff patch

> Row `UI-UPGRADE-1-AUTH`, design `docs/plans/ui-upgrade-1-auth-and-keys-design.md` §2a/§2c.
> **Why a patch and not a PR:** this lane's attempt to attach `benbaichmankass/ict-trader-dashboard`
> with push access (`add_repo`) was denied by the session's permission classifier, so the SPA code
> could not be pushed from here. Apply it from a session that can push to that repo.

`ict-trader-dashboard-ui-upgrade-1-auth.patch` is **new files only** (no edits to existing SPA files,
because that repo's source was not readable from this session and a patch with guessed context lines
would not apply):

| file | what |
|---|---|
| `webapp/src/lib/session.ts` | device-session store (localStorage, memory fallback), `authHeaders()`, `authCall()`, `marketSocketUrl()` (fetches a 60 s single-use ws ticket), 401 → sign-in signal |
| `webapp/src/lib/passkey.ts` | Google Identity Services button → `POST /api/auth/google`; WebAuthn assert / first-device enrol / add-device, base64url ↔ ArrayBuffer |
| `webapp/src/routes/SignIn.svelte` | Google → passkey (or enrolment-code) screen |
| `webapp/src/routes/Devices.svelte` | Admin → Devices: list, revoke one, sign out everywhere else, register a passkey on this device |

```
git apply --check comms/ui-upgrade-1-auth/ict-trader-dashboard-ui-upgrade-1-auth.patch   # run inside the SPA repo
```

## Verified / not verified
- ✅ `git apply --check` passes on an empty repo (new files).
- ✅ `session.ts` and `passkey.ts` type-check clean under `tsc --strict` (TypeScript 5.4, `lib: dom,es2020`).
- ❌ The two `.svelte` files were **not compiled** (no SPA toolchain here) and nothing was run in a browser.
  Written in Svelte-4 syntax (valid under Svelte 5 legacy mode); adjust if the SPA is on runes.
- ❌ The endpoints are tested server-side (`tests/test_web_site_auth.py`) with a software authenticator;
  a real passkey ceremony in a real browser has **not** been observed.

## Integration steps the patch does NOT do (edit existing SPA files)
1. **`webapp/src/lib/api.ts`** (the one fetch call site): `import { authHeaders, configureSession, signalUnauthorized } from './session'`;
   call `configureSession({ apiBase })` once with the same base URL; spread `...authHeaders()` into the
   request headers (keep `auth-bearer.mjs`'s invariant: every request sends the bearer); on a `401`
   call `signalUnauthorized()`. Until `SITE_AUTH_ENFORCE` is on, the bearer is simply ignored by the API.
2. **`App.svelte`**: if `currentToken()` is null render `<SignIn on:signedin={...} />`, else the app;
   subscribe `onUnauthorized(() => token = null)`.
3. **Nav**: add an Admin → Devices entry rendering `Devices.svelte`.
4. **`/ws/market` client**: build the URL with `await marketSocketUrl('symbols=…&interval=…')` on every
   (re)connect — a ticket is single use, so a reconnect needs a fresh one.
5. **CSP** (design §2a.5): the Pages site must allow `script-src https://accounts.google.com/gsi/client`,
   `frame-src https://accounts.google.com/gsi/`, and `connect-src` the API origin (+ `https://accounts.google.com`).
6. **Operator prerequisites** (names only): `GOOGLE_OAUTH_CLIENT_ID` (Web-application client; authorised JS
   origin = the Pages origin) and `WEB_SESSION_PEPPER` set on the web-api; `webauthn` installed on the VM;
   the first enrolment code comes from `python -m src.web.api.enrol_code` on the VM (the Tier-1
   `passkey-enrol-code` system-action that wraps it is not built yet).

## Rollout order (do not skip)
Ship the API (gate OFF) → ship the SPA sign-in → operator signs in once and enrols a passkey →
`PI-20261011-CFUJ7YFR-0001` (24 h consumer check) and `-0002` (service-bearer retrofit) clear →
only then the operator flips `SITE_AUTH_ENFORCE=1` with `set-env`; verify an anonymous `curl` returns 401
and a signed-in one 200. Revert = unset it.
