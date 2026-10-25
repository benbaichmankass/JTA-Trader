// REAL-PAGE fixtures for exec.js (PHONE-EXEC-OBSERVABLE-1018, piece 3): every tools/phone-executor/test/fixtures/<name>.html
// (built by fixture_from_capture.py from a phone capture, numbers replaced, redacted on the device) is served on the
// trade host and its <name>.spec.json assertions run against the bundled exec.js. A spec is a list of
//   {"call": "<JS expression using __ex>", "expect": <partial deep match>, "note": "..."}
// where `expect` matches when every key it names equals the result's (nested objects recurse; an array matches an
// array of the same length element by element, each element partially;
// a string "re:<regex>" matches a string result; "any" accepts anything). Static pages prove READS and TARGETS; a
// tap that must OPEN something is the rehearsal drill's job on the phone.
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");
const src = fs.readFileSync("tools/phone-executor/app/src/main/assets/exec.js", "utf8");
const dir = path.join("tools", "phone-executor", "test", "fixtures");

function matches(got, exp) {
  if (exp === "any") return true;
  if (typeof exp === "string" && exp.startsWith("re:")) return typeof got === "string" && new RegExp(exp.slice(3)).test(got);
  if (Array.isArray(exp)) return Array.isArray(got) && got.length === exp.length && exp.every((e, i) => matches(got[i], e));
  if (exp && typeof exp === "object") {
    if (!got || typeof got !== "object") return false;
    return Object.keys(exp).every((k) => matches(got[k], exp[k]));
  }
  return JSON.stringify(got) === JSON.stringify(exp);
}

(async () => {
  const names = fs.existsSync(dir) ? fs.readdirSync(dir).filter((f) => f.endsWith(".html")).map((f) => f.slice(0, -5)).sort() : [];
  if (!names.length) { console.log("exec_fixtures_check: no fixtures under " + dir + " (nothing captured yet); nothing to prove"); return; }
  const b = await chromium.launch();
  let fails = 0, checks = 0;
  for (const name of names) {
    const specPath = path.join(dir, name + ".spec.json");
    if (!fs.existsSync(specPath)) { console.error("FAIL " + name + ": no spec (" + specPath + ")"); fails++; continue; }
    const spec = JSON.parse(fs.readFileSync(specPath, "utf8"));
    const html = fs.readFileSync(path.join(dir, name + ".html"), "utf8");
    const meta = fs.existsSync(path.join(dir, name + ".meta.json")) ? JSON.parse(fs.readFileSync(path.join(dir, name + ".meta.json"), "utf8")) : {};
    const ctx = await b.newContext({ viewport: { width: meta.vw || 390, height: meta.vh || 800 }, deviceScaleFactor: meta.dpr || 1, hasTouch: true, isMobile: true });
    const pg = await ctx.newPage();
    await pg.route("https://trade.breakoutprop.com/**", (r) => r.fulfill({ status: 200, contentType: "text/html", body: html }));
    await pg.goto("https://trade.breakoutprop.com/en/account/ACCT/trade");
    await pg.addScriptTag({ content: src });
    for (const step of spec.checks || spec) {
      checks++;
      let got;
      try { got = await pg.evaluate(step.call); } catch (e) { got = { __error: String(e.message || e).slice(0, 200) }; }
      const ok = matches(got, step.expect);
      console.log((ok ? "ok   " : "FAIL ") + name + ": " + (step.note || step.call) + (ok ? "" : "\n      got " + JSON.stringify(got).slice(0, 600) + "\n      want " + JSON.stringify(step.expect).slice(0, 300)));
      if (!ok) fails++;
    }
    await ctx.close();
  }
  await b.close();
  console.log(`exec_fixtures_check: ${names.length} fixture(s), ${checks} check(s), ${fails} failed`);
  if (fails) process.exit(1);
})().catch((e) => { console.error(e); process.exit(1); });
