// Page-side check for tools/phone-executor/app/src/main/assets/exec.js against a SYNTHETIC ticket built to the
// shape read on Breakout's terminal (design § 7.9: Market/Limit/Trigger tabs, Buy/Sell tabs, "Limit price" and
// "Quantity" inputs, a TP/SL checkbox revealing fields, a separate "Long (buy) ..." submit disabled until a
// quantity is entered). It proves the helpers' mechanics, NOT Breakout's real labels (the dry run measures those).
const { chromium } = require("playwright");
const fs = require("fs");
const src = fs.readFileSync("tools/phone-executor/app/src/main/assets/exec.js", "utf8");
const page = `<!doctype html><html><body>
<button>Positions</button><button>Open orders</button><button>Order</button>
<h2>ETHUSD</h2>
<form id=f>
 <div role=tablist><button type=button role=tab aria-selected=false>Market</button><button type=button role=tab aria-selected=true>Limit</button><button type=button role=tab aria-selected=false>Trigger</button></div>
 <div role=tablist><button type=button role=tab aria-selected=true>Buy</button><button type=button role=tab aria-selected=false>Sell</button></div>
 <label for=lp>Limit price</label><input id=lp type=text inputmode=numeric>
 <label for=q>Quantity</label><input id=q type=text inputmode=numeric>
 <div role=alert>Quantity ETH available to trade 1.23</div>
 <label><input type=checkbox id=cb> TP/SL</label>
 <div id=tpsl style="display:none"><label for=tp>Take profit price</label><input id=tp type=text><label for=tpp>Take profit %</label><input id=tpp type=text>
 <label for=sl>Stop loss price</label><input id=sl type=text><label for=slp>Stop loss %</label><input id=slp type=text></div>
 <button type=submit id=sub disabled>Long (buy) ETHUSD</button>
</form>
<script>
document.querySelectorAll('[role=tab]').forEach(function(b){b.onclick=function(){b.parentElement.querySelectorAll('[role=tab]').forEach(function(x){x.setAttribute('aria-selected','false')});b.setAttribute('aria-selected','true');
 if(b.textContent==='Sell')document.getElementById('sub').textContent='Short (sell) ETHUSD'; if(b.textContent==='Buy')document.getElementById('sub').textContent='Long (buy) ETHUSD';}});
document.getElementById('cb').onchange=function(){document.getElementById('tpsl').style.display=this.checked?'block':'none'};
document.getElementById('q').addEventListener('input',function(){document.getElementById('sub').disabled=!this.value});
document.getElementById('f').onsubmit=function(e){e.preventDefault();window.__submitted=(window.__submitted||0)+1};
</script></body></html>`;
function eq(a, b, m) { if (JSON.stringify(a) !== JSON.stringify(b)) { console.error("FAIL", m, JSON.stringify(a), "!=", JSON.stringify(b)); process.exit(1); } console.log("ok", m); }
(async () => {
  const b = await chromium.launch(); const p = await b.newPage();
  await p.setContent(page); await p.addScriptTag({ content: src });
  const r = (code) => p.evaluate(code);
  eq(await r("__ex.state().ticketOpen"), true, "ticket open");
  eq(await r("__ex.tab('Sell')"), "clicked", "sell tab");
  eq(await r("__ex.tabSelected('Sell')"), true, "sell selected");
  eq(await r("/short/i.test(__ex.ticket().submit.text)"), true, "submit label follows side");
  await r("__ex.tab('Buy')");
  let tk = await r("__ex.ticket()");
  const k = (re) => tk.inputs.filter((i) => new RegExp(re, "i").test(i.label)).map((i) => i.k);
  eq(k("limit price").length, 1, "one limit price field");
  eq(await r(`__ex.setInput(${k("limit price")[0]}, '2500.10')`), "2500.10", "price read back");
  eq(await r("__ex.ticket().submit.disabled"), true, "submit disabled before qty");
  eq(await r(`__ex.setInput(${k("quantity")[0]}, '0.01')`), "0.01", "qty read back");
  eq(await r("__ex.ticket().submit.disabled"), false, "submit enabled after qty (input event registered)");
  eq(await r("__ex.setTpsl(true)"), "ok", "tp/sl ticked");
  tk = await r("__ex.ticket()");
  eq(tk.tpsl, true, "tpsl read back on");
  eq(k("take ?profit").length, 2, "two TP fields (price + %): app must prefer 'price'");
  eq(k("take ?profit.*price|price.*take ?profit").length, 1, "one TP price field");
  eq(/ETH/.test(JSON.stringify(tk.alerts)), true, "quantity unit alert names the base asset");
  eq(await r("window.__submitted || 0"), 0, "nothing submitted by the fill path");
  eq(await r("__ex.loginNumber()"), "", "no login number on the ticket page");
  // LANDING STATES on a routed trade.breakoutprop.com origin (fix 2026-10-05 ~20:20Z): the logged-in landing has
  // no tabs and no exact "Positions" button, and must still read as logged in, never as "other".
  const p2 = await b.newPage();
  const pages = {
    "/en/account/A1/trade": "<div><span>Trade</span><div role=button>Portfolio</div><div>Open orders</div><div>Positions</div><canvas></canvas></div>",
    "/en/account/A1/overview": "<div><span>Portfolio</span><div>Positions</div><p>Balance</p></div>",
    "/en/account/A1/trade-ready": "<div><button>Order</button><div role=tablist><button role=tab>Buy</button><button role=tab>Sell</button></div></div>",
    "/": "<div><h1>Your accounts</h1><a href='/en/account/A1/trade'>Turbo 5K</a></div>",
    "/two": "<div><a href='/en/account/A1/trade'>One</a><a href='/en/account/B2/trade'>Two</a></div>",
    "/en/account/A2/trade": "<div><div role=tablist><button role=tab>Positions</button><button role=tab>Open orders</button><button role=tab>History</button></div><span>Buy</span> 85,225 <span>Sell</span> 85,220</div>",
    "/en/account/A3/trade": "<div><span>Buy</span> <span>Sell</span></div>",
    "/login": "<form><input type=email><button>Continue</button></form>",
  };
  await p2.route("https://trade.breakoutprop.com/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    route.fulfill({ status: 200, contentType: "text/html", body: "<!doctype html><html><body>" + (pages[path] || "<p>?</p>") + "</body></html>" });
  });
  const st = async (path) => { await p2.goto("https://trade.breakoutprop.com" + path); await p2.addScriptTag({ content: src }); return p2.evaluate("__ex.state()"); };
  let s1 = await st("/en/account/A1/trade");
  eq([s1.loggedIn, s1.onAccount], [true, true], "landing inside an account reads logged in (no tabs, no exact button)");
  s1 = await st("/");
  eq([s1.loggedIn, s1.onAccount, s1.accountLinkCount, s1.singleAccountLink], [true, false, 1, "https://trade.breakoutprop.com/en/account/A1/trade"], "account list with ONE account: logged in, single link");
  s1 = await st("/two");
  eq([s1.loggedIn, s1.accountLinkCount, s1.singleAccountLink], [true, 2, ""], "two accounts: no single link (app waits for a human tap)");
  s1 = await st("/en/account/A1/overview");
  eq(s1.loggedIn, true, "account overview reads logged in");
  eq(await p2.evaluate("__ex.terminal().ready"), false, "account overview is NOT the terminal (the 05:21Z claim page): no claim");
  eq(await p2.evaluate("__ex.terminalHref()"), "https://trade.breakoutprop.com/en/account/A1/trade", "terminal URL derived from the current account path");
  await st("/en/account/A1/trade-ready");
  eq(await p2.evaluate("__ex.terminal().ready"), true, "terminal with Order control + Buy/Sell tabs is ready");
  // TERMINAL WITH THE TICKET CLOSED (fix 06:17Z, "terminal did not load" on the real terminal): no Order control,
  // no Buy/Sell tabs, but the 1a probe classifier (trade host, /trade path, buy+sell markers, tabs>=3) says ready.
  await st("/en/account/A2/trade");
  eq(await p2.evaluate("[__ex.terminal().ready, __ex.terminal().probe, __ex.terminal().orderControl]"), [true, true, false], "terminal with the ticket closed is ready via the probe classifier");
  eq(await p2.evaluate("__ex.controls()"), ["Positions", "Open orders", "History"], "controls(): the page's control texts for the miss event");
  await st("/en/account/A3/trade");
  eq(await p2.evaluate("__ex.terminal().ready"), false, "buy/sell words alone (no tabs, no inputs) are not the terminal");
  s1 = await st("/login");
  eq([s1.loggedIn, s1.email], [false, true], "login form is never logged in");
  // LABEL-BASED FIELDS (fix 2026-10-05 ~22:40Z): price and quantity are set and read back BY LABEL, never by index,
  // and the two labels must resolve to two different inputs with their own values.
  const p3 = await b.newPage(); await p3.setContent(page); await p3.addScriptTag({ content: src });
  const r3 = (code) => p3.evaluate(code);
  let sp = await r3("__ex.setByLabel('limit price', '', '2500.10')");
  eq([sp.n, sp.label, sp.value], [1, "Limit price", "2500.10"], "price set by label");
  let sq = await r3("__ex.setByLabel('quantity', '', '0.01')");
  eq([sq.n, sq.label, sq.value], [1, "Quantity", "0.01"], "quantity set by label");
  eq(sp.k !== sq.k, true, "price and quantity are different inputs");
  eq(await r3("__ex.readByLabel('limit price', '').value"), "2500.10", "price read back by label is still the price, not the quantity");
  eq(await r3("__ex.readByLabel('quantity', '').value"), "0.01", "quantity read back by label");
  eq(await r3("__ex.readByLabel('nosuchlabel', '').n"), 0, "missing label: n=0, nothing set");
  await r3("__ex.setTpsl(true)");
  let amb = await r3("__ex.setByLabel('take ?profit', '', '1')");
  eq([amb.n, amb.labels], [2, ["Take profit price", "Take profit %"]], "ambiguous label: n=2 with the labels, nothing set");
  eq(await r3("__ex.readByLabel('take ?profit', '').value === undefined"), true, "ambiguous label returns no value");
  eq((await r3("__ex.setByLabel('take ?profit', 'price', '2600')")).value, "2600", "prefer narrows TP to the price field");
  eq(await r3("__ex.readByLabel('take ?profit', '%').value"), "", "TP % field untouched");
  eq(await r3("__ex.ticket().symbol"), "ETHUSD", "ticket() reports the asset on the submit label");
  eq(await r3("window.__submitted || 0"), 0, "label-based fill submits nothing");

  // INSTRUMENT SELECTION (fix 2026-10-05 ~22:40Z): the terminal starts on BTC and the ticket is ETH. The executor
  // must select ETH (through whichever route the page offers) or refuse with a named reason; it never submits.
  // Fixture A: a symbol strip of buttons (the exact-text route).
  const strip = (cur) => `<!doctype html><html><body>
<div id=strip><button>BTCUSD</button><button>ETHUSD</button><button>SOLUSD</button></div>
<button>Order</button><h2 id=h>${cur}</h2>
<form id=f><div role=tablist><button type=button role=tab aria-selected=true>Market</button><button type=button role=tab aria-selected=false>Limit</button></div>
<div role=tablist><button type=button role=tab aria-selected=true>Buy</button><button type=button role=tab aria-selected=false>Sell</button></div>
<label for=lp>Limit price</label><input id=lp type=text value="85,778.8"><label for=q>Quantity</label><input id=q type=text value="85,778.8">
<div role=alert>Quantity exceeds available to trade</div>
<button type=submit id=sub>Long (buy) ${cur.replace('USD','')}</button></form>
<script>document.querySelectorAll('#strip button').forEach(function(b){b.onclick=function(){var s=b.textContent;document.getElementById('h').textContent=s;document.getElementById('sub').textContent='Long (buy) '+s.replace('USD','');}});
document.getElementById('f').onsubmit=function(e){e.preventDefault();window.__submitted=(window.__submitted||0)+1};</script></body></html>`;
  // symbolStep() refuses ("bad_host") off breakoutprop.com, so these fixtures are served on the trade host.
  const onHost = async (html) => { const pg = await b.newPage(); await pg.route("https://trade.breakoutprop.com/**", (route) => route.fulfill({ status: 200, contentType: "text/html", body: html }));
    await pg.goto("https://trade.breakoutprop.com/en/account/A1/trade"); await pg.addScriptTag({ content: src }); return pg; };
  const pA = await onHost(strip("BTCUSD"));
  const rA = (code) => pA.evaluate(code);
  eq(await r3("__ex.symbolStep('ETHUSD')"), "bad_host", "symbol routes refuse off breakoutprop.com");
  eq(await rA("__ex.symbolOnTicket()"), "BTC", "ticket starts on BTC (the 2026-10-05 22:20Z dump)");
  eq(await rA("__ex.symbolStep('ETHUSD')"), "clicked_symbol", "strip: exact-text ETHUSD button clicked");
  eq(await rA("__ex.symbolOnTicket()"), "ETH", "strip: submit label now names ETH");
  eq(await rA("__ex.symbolStep('ETHUSD')"), "done", "strip: second step reports done");
  eq(await rA("__ex.symbolStep('Market')"), "not_a_symbol", "a word that is not a symbol clicks nothing (Market tab is not a symbol control)");
  eq(await rA("__ex.tabSelected('Market')"), true, "Market tab untouched by the symbol routes");
  eq(await rA("window.__submitted || 0"), 0, "strip: nothing submitted");
  // Fixture B: a current-symbol picker (BTC/USD) that opens a search box; results are rows that START with the symbol.
  const picker = `<!doctype html><html><body>
<button id=cur aria-haspopup=listbox>BTC/USD</button><div id=pk style="display:none"><input id=s placeholder="Search symbol"><ul id=res></ul></div>
<form id=f><label for=lp>Limit price</label><input id=lp type=text><label for=q>Quantity</label><input id=q type=text>
<button type=submit id=sub>Long (buy) BTC</button></form>
<script>var ALL=['BTCUSD Bitcoin','ETHUSD Ethereum','ETHUSDT Ethereum Tether','SOLUSD Solana'];
document.getElementById('cur').onclick=function(){document.getElementById('pk').style.display='block'};
document.getElementById('s').addEventListener('input',function(){var v=this.value.toUpperCase();var u=document.getElementById('res');u.innerHTML='';ALL.filter(function(a){return a.indexOf(v)===0}).forEach(function(a){var li=document.createElement('li');li.textContent=a;li.onclick=function(){var sym=a.split(' ')[0];document.getElementById('cur').textContent=sym.slice(0,3)+'/'+sym.slice(3);document.getElementById('sub').textContent='Long (buy) '+sym.replace(/USDT?$/,'');document.getElementById('pk').style.display='none'};u.appendChild(li)})});
document.getElementById('f').onsubmit=function(e){e.preventDefault();window.__submitted=(window.__submitted||0)+1};</script></body></html>`;
  const pB = await onHost(picker);
  const rB = (code) => pB.evaluate(code);
  eq(await rB("__ex.symbolOnTicket()"), "BTC", "picker: ticket starts on BTC");
  eq(await rB("__ex.symbolStep('ETHUSD')"), "opened_picker", "picker: current-symbol control opened");
  eq(await rB("__ex.symbolStep('ETHUSD')"), "typed_search", "picker: symbol typed into the search box");
  eq(await rB("__ex.symbolStep('ETHUSD')"), "ambiguous", "picker: ETHUSD and ETHUSDT both start with ETHUSD and neither is exact-only -> refuse, click nothing");
  eq(await rB("__ex.symbolOnTicket()"), "BTC", "picker: ambiguous result changed nothing");
  await rB("ALL.splice(2,1); document.getElementById('s').dispatchEvent(new Event('input'))");
  eq(await rB("__ex.symbolStep('ETHUSD')"), "clicked_result", "picker: with one result left, its row (starts with the symbol) is clicked");
  eq(await rB("__ex.symbolOnTicket()"), "ETH", "picker: submit label now names ETH");
  eq(await rB("window.__submitted || 0"), 0, "picker: nothing submitted");
  // Fixture C: no symbol control at all -> "none", so the app refuses with the route in the reason.
  const pC = await onHost(strip("BTCUSD").replace(/<div id=strip>.*?<\/div>/, ""));
  eq(await pC.evaluate("__ex.symbolStep('ETHUSD')"), "none", "no selector: none (app refuses 'symbol ETH not on the submit label')");
  eq(await pC.evaluate("__ex.symbolOnTicket()"), "BTC", "no selector: ticket unchanged");
  // Fixture D (fix 06:24Z, am-2 "symbol route: none"): a watchlist whose rows are plain divs with the symbol in a
  // leaf span and the click handler on the row. Route 1b clicks the ONE exact leaf; the read-back verifies.
  const wl = strip("BTCUSD").replace(/<div id=strip>.*?<\/div>/, "<div id=wl><div class=r data-s=BTCUSD><span>BTCUSD</span><span>85,225.0</span></div><div class=r data-s=ETHUSD><span>ETHUSD</span><span>2,612.4</span></div></div>")
    .replace("document.querySelectorAll('#strip button').forEach(function(b){b.onclick=function(){var s=b.textContent;", "document.querySelectorAll('#wl .r').forEach(function(b){b.onclick=function(){var s=b.getAttribute('data-s');");
  const pD = await onHost(wl);
  eq(await pD.evaluate("__ex.symbolStep('ETHUSD')"), "clicked_label", "watchlist: exact leaf label clicked, row handler fires");
  eq(await pD.evaluate("__ex.symbolOnTicket()"), "ETH", "watchlist: submit label now names ETH");
  eq(await pD.evaluate("__ex.symbolStep('ETHUSD')"), "done", "watchlist: then done");
  const cands = await pD.evaluate("__ex.symbolCandidates().map(function(c){return c.text})");
  eq(cands.includes("BTCUSD") && cands.includes("ETHUSD") && !cands.some(function (c) { return /\d/.test(c); }), true, "symbolCandidates lists the watchlist symbols, digits masked");
  eq(await pD.evaluate("Array.isArray(__ex.ticket().symbolCandidates)"), true, "refusal dump carries symbolCandidates");
  eq(await pD.evaluate("window.__submitted || 0"), 0, "watchlist: nothing submitted");
  // Fixture E (MEASURED 2026-10-06 08:58Z terminal_miss): the real PANEL-layout terminal with the order form CLOSED:
  // no tabs, no inputs, no buy/sell text; an "Order form" toggle, Positions / Open orders panels, an open-instrument
  // chip "BTC x" and a watchlist of "<BASE> <signed %>" buttons. Opening the form shows the usual ticket.
  const panel = `<!doctype html><html><body>
<button>Trade</button><button id=chip>BTC x</button><button>Market chart</button><button id=of>Order form</button>
<button>Open orders</button><button>Positions</button><button>Order book</button>
<div id=wl><button data-s=BTC>BTC -1.2%</button><button data-s=ETH>ETH -0.5%</button><button data-s=SOL>SOL +2.0%</button></div>
<div id=panel></div>
<script>var cur='BTC';
function form(){return '<form id=f><div role=tablist><button type=button role=tab aria-selected=false>Market</button><button type=button role=tab aria-selected=true>Limit</button></div><div role=tablist><button type=button role=tab aria-selected=true>Buy</button><button type=button role=tab aria-selected=false>Sell</button></div><label for=lp>Limit price</label><input id=lp type=text value=1><label for=q>Quantity</label><input id=q type=text value=0><button type=button id=qu aria-label=\"Toggle quantity unit\">USD</button><div id=tps>TP/SL</div><div id=tpbox></div><button type=submit id=sub>Long (buy) '+cur+'</button></form>';}
document.getElementById('of').onclick=function(){document.getElementById('panel').innerHTML=form();document.getElementById('qu').onclick=function(){this.textContent=this.textContent==='USD'?cur:'USD';};document.getElementById('tps').onclick=function(){document.getElementById('tpbox').innerHTML='<label for=tp>Take profit price</label><input id=tp type=text><label for=sl>Stop loss price</label><input id=sl type=text>';};document.getElementById('f').onsubmit=function(e){e.preventDefault();window.__submitted=(window.__submitted||0)+1};};
document.querySelectorAll('#wl button').forEach(function(b){b.onclick=function(){cur=b.getAttribute('data-s');document.getElementById('chip').textContent=cur+' x';var sb=document.getElementById('sub');if(sb)sb.textContent='Long (buy) '+cur;};});
</script></body></html>`;
  const pE = await onHost(panel);
  const rE = (code) => pE.evaluate(code);
  eq(await rE("[__ex.terminal().ready, __ex.terminal().panels, __ex.terminal().tabs, __ex.terminal().inputs]"), [true, true, 0, 0], "panel terminal, form closed: ready via panels (the 08:58Z miss)");
  eq(await rE("__ex.symbolShown()"), "BTC", "panel: shown symbol read from the one 'BTC x' chip");
  eq(await rE("__ex.symbolStep('ETHUSD')"), "clicked_watch", "panel: the ONE 'ETH -0.5%' watchlist button clicked");
  eq(await rE("__ex.symbolStep('ETHUSD')"), "done", "panel: chip now 'ETH x' -> done");
  eq(await rE("__ex.openTicket()"), "clicked", "panel: 'Order form' opens the ticket");
  eq(await rE("__ex.symbolOnTicket()"), "ETH", "panel: submit label names ETH");
  // QUANTITY UNIT + TP/SL (MEASURED am-3 09:16Z): "Toggle quantity unit" button reads USD; "TP/SL" control hides the TP/SL inputs.
  eq(await rE("__ex.qtyUnit()"), "USD", "panel: quantity unit toggle reads USD");
  eq(await rE("__ex.toggleQtyUnit()"), "clicked", "panel: unit toggled once");
  eq(await rE("__ex.qtyUnit()"), "ETH", "panel: quantity unit now ETH");
  eq(await rE("__ex.readByLabel('take ?profit|\\btp\\b','price').n"), 0, "panel: TP field hidden before the TP/SL control");
  eq(await rE("__ex.openTpsl(0)"), "expanded", "panel: TP/SL control clicked");
  eq(await rE("__ex.openTpsl()"), "ok", "panel: TP/SL now open");
  eq(await rE("[__ex.readByLabel('take ?profit|\\btp\\b','price').n, __ex.readByLabel('stop ?loss|\\bsl\\b','price').n]"), [1, 1], "panel: TP and SL fields unique by label");
  eq(await rE("window.__submitted || 0"), 0, "panel: nothing submitted");
  // Fixture F (MEASURED am-4 09:48Z): TP/SL checkbox already CHECKED, section still collapsed behind a "TP/SL" header.
  const tpF = `<!doctype html><html><body><form id=f><div role=tablist><button type=button role=tab aria-selected=true>Buy</button></div>
<label for=lp>Limit price</label><input id=lp type=text><label><input type=checkbox id=cb checked>TP/SL</label>
<div id=hdr aria-expanded=false>TP/SL</div><div id=box></div><button type=submit>Long (buy) ETH</button></form>
<script>document.getElementById('hdr').onclick=function(){document.getElementById('box').innerHTML='<label for=tp>Take profit price</label><input id=tp type=text><label for=sl>Stop loss price</label><input id=sl type=text>';};
document.getElementById('cb').onclick=function(){window.__cbClicks=(window.__cbClicks||0)+1};</script></body></html>`;
  const pF = await onHost(tpF);
  eq(await pF.evaluate("__ex.openTpsl(0)"), "expanded", "checked box + collapsed section: header expanded, box untouched");
  eq(await pF.evaluate("[__ex.openTpsl(), document.getElementById('cb').checked, window.__cbClicks || 0]"), ["ok", true, 0], "then ok; checkbox never toggled off");
  // Fixture G: the "TP/SL" text is a plain span; the handler sits on a text-less role=switch beside it.
  const tpG = `<!doctype html><html><body><form id=f><label for=lp>Limit price</label><input id=lp type=text>
<div><span id=txt>TP/SL</span><button type=button role=switch id=sw aria-checked=false></button></div><div id=box></div>
<button type=submit>Long (buy) ETH</button></form>
<script>document.getElementById('sw').onclick=function(){this.setAttribute('aria-checked','true');document.getElementById('box').innerHTML='<label for=tp>Take profit price</label><input id=tp type=text><label for=sl>Stop loss price</label><input id=sl type=text>';};</script></body></html>`;
  const pG = await onHost(tpG);
  eq(await pG.evaluate("__ex.openTpsl(0)"), "expanded", "switch layout: text clicked first (no effect)");
  eq(await pG.evaluate("__ex.openTpsl(1)"), "switched", "switch layout: the text-less switch beside it is clicked");
  eq(await pG.evaluate("__ex.openTpsl(2)"), "ok", "switch layout: TP/SL inputs now shown");
  eq(await pG.evaluate("__ex.tpslArea()[0].node.text"), "TP/SL", "tpslArea dump names the TP/SL element");
  // POSITION AMEND (PROP-TRAIL-PHONE): SYNTHETIC Positions table + edit dialog. Proves the helpers' mechanics, NOT
  // Breakout's real edit UI (never captured): unique row, never a close control, dialog fields by label, one save.
  const posH = (cols, rowBtns, extraRow) => `<!doctype html><html><body><button>Positions</button><button>Open orders</button>
<table><thead><tr>${cols.map((c) => "<th>" + c + "</th>").join("")}</tr></thead><tbody>
<tr id=r1><td>ETHUSD</td><td>Buy</td><td>0.50</td><td>2,500.00</td>${cols.includes("SL") ? "<td id=csl>2,450.00</td><td id=ctp>2,800.00</td>" : ""}<td>${rowBtns}</td></tr>${extraRow || ""}
</tbody></table><div id=dl></div>
<script>window.__closed=0;window.__saved=0;
document.querySelectorAll('[data-close]').forEach(function(x){x.onclick=function(){window.__closed++}});
document.querySelectorAll('[data-edit]').forEach(function(x){x.onclick=function(){
 var sl=(document.getElementById('csl')||{}).textContent||window.__sl||'2450.00', tp=(document.getElementById('ctp')||{}).textContent||window.__tp||'2800.00';
 document.getElementById('dl').innerHTML='<div role=dialog><h3>Edit position</h3><label for=dsl>Stop loss price</label><input id=dsl type=text value="'+sl.replace(/,/g,'')+'"><label for=dslp>Stop loss %</label><input id=dslp type=text><label for=dtp>Take profit price</label><input id=dtp type=text value="'+tp.replace(/,/g,'')+'"><button id=sv>Save</button><button id=cx>Cancel</button><button>Close position</button></div>';
 document.getElementById('sv').onclick=function(){window.__saved++;var a=document.getElementById('dsl').value,b2=document.getElementById('dtp').value;if(document.getElementById('csl')){document.getElementById('csl').textContent=a;document.getElementById('ctp').textContent=b2}else{window.__sl=a;window.__tp=b2}document.getElementById('dl').innerHTML=''};
 document.getElementById('cx').onclick=function(){document.getElementById('dl').innerHTML=''};}});
</script></body></html>`;
  const COLS = ["Symbol", "Side", "Qty", "Entry", "SL", "TP", ""];
  const pP = await onHost(posH(COLS, "<button data-edit aria-label='Edit'>✎</button><button data-close>Close</button>"));
  const rP = (c) => pP.evaluate(c);
  let pi = await rP("__ex.posInfo('ETHUSD','long|buy')");
  eq([pi.n, pi.sl, pi.tp], [1, "2,450.00", "2,800.00"], "amend: one ETH long row, SL/TP columns read");
  eq((await rP("__ex.posInfo('ETHUSD','short|sell')")).n, 0, "amend: no short row");
  eq(await rP("__ex.posEdit('ETHUSD','long|buy')"), "clicked", "amend: the row's ONE edit control clicked");
  eq(await rP("window.__closed"), 0, "amend: close control never clicked");
  eq((await rP("__ex.editDialog()")).n, 1, "amend: one dialog");
  eq((await rP("__ex.dlgRead('stop ?loss|\\bsl\\b','')")).n, 2, "amend: SL label ambiguous (price + %) without prefer");
  eq((await rP("__ex.dlgRead('stop ?loss|\\bsl\\b','price')")).value, "2450.00", "amend: dialog SL read by label");
  eq((await rP("__ex.dlgSet('stop ?loss|\\bsl\\b','price','2530.00')")).value, "2530.00", "amend: dialog SL typed + read back");
  eq((await rP("__ex.dlgRead('take ?profit|\\btp\\b','price')")).value, "2800.00", "amend: kept TP unchanged");
  eq(await rP("__ex.dlgCancel()"), "clicked", "amend (dry): cancelled, not saved");
  eq([await rP("window.__saved"), (await rP("__ex.editDialog()")).n, (await rP("__ex.posInfo('ETHUSD','long|buy')")).sl], [0, 0, "2,450.00"], "amend (dry): nothing saved, row unchanged");
  await rP("__ex.posEdit('ETHUSD','long|buy')");
  await rP("__ex.dlgSet('stop ?loss|\\bsl\\b','price','2530.00')");
  eq(await rP("__ex.dlgSave()"), "clicked", "amend (live): the ONE save button (never 'Close position')");
  eq([await rP("window.__saved"), await rP("window.__closed"), (await rP("__ex.posInfo('ETHUSD','long|buy')")).sl], [1, 0, "2530.00"], "amend (live): saved, row read back with the new SL");
  // no SL/TP columns: the read-back re-opens the dialog; a row with only a close control has no edit route
  const pQ = await onHost(posH(["Symbol", "Side", "Qty", "Entry", ""], "<button data-edit title='Modify TP/SL'></button><button data-close>Close</button>"));
  eq([(await pQ.evaluate("__ex.posInfo('ETHUSD','long|buy')")).sl, await pQ.evaluate("__ex.posEdit('ETHUSD','long|buy')")], [null, "clicked"], "amend: no SL column -> null; edit found by title");
  const pR = await onHost(posH(["Symbol", "Side", "Qty", "Entry", ""], "<button data-close>Close</button><button data-close aria-label='Close position'>x</button>"));
  eq([await pR.evaluate("__ex.posEdit('ETHUSD','long|buy')"), await pR.evaluate("window.__closed")], ["no_edit", 0], "amend: only close controls -> no_edit, nothing clicked");
  const pS = await onHost(posH(COLS, "<button data-edit>Edit</button>", "<tr><td>ETHUSD</td><td>Buy</td><td>0.10</td><td>2,400</td><td>2,300</td><td>2,900</td><td><button data-edit>Edit</button></td></tr>"));
  eq(await pS.evaluate("__ex.posEdit('ETHUSD','long|buy')"), "rows_2", "amend: two ETH long rows -> refused, nothing clicked");
  eq(await pS.evaluate("__ex.dlgSave()"), "none", "amend: no dialog -> no save");

  // ACCOUNT PANEL READ (PHONE-BALANCE-READ): label-anchored, one distinct number or null.
  const acctA = `<!doctype html><html><body><button>Positions</button><button>Open orders</button>
<button id=pf>Portfolio 98,123.45 USD</button><button>Turbo Eval 1</button><div><span>Balance</span><span>97,000.10</span></div><div>Equity: 98,123.45</div></body></html>`;
  const acctpA = await onHost(acctA);
  eq(await acctpA.evaluate("__ex.accountPanel()"), {balance: 97000.1, equity: 98123.45, portfolio: 98123.45, unrealized: null, n: {balance: 1, equity: 1, portfolio: 1, unrealized: 0}}, "account panel: balance/equity/portfolio read by label");
  const acctpB = await onHost(`<!doctype html><html><body><button>Portfolio 10,000.00 USD</button><button>Turbo Eval 5</button></body></html>`);
  eq(await acctpB.evaluate("__ex.accountPanel()"), {balance: null, equity: null, portfolio: 10000, unrealized: null, n: {balance: 0, equity: 0, portfolio: 1, unrealized: 0}}, "account panel: only Portfolio shown -> balance/equity absent (null), portfolio read");
  const acctpC = await onHost(`<!doctype html><html><body><button>Portfolio 1.00 USD</button><span>Portfolio 2.00 USD</span><button>Balance</button></body></html>`);
  eq(await acctpC.evaluate("__ex.accountPanel()"), {balance: null, equity: null, portfolio: null, unrealized: null, n: {balance: 0, equity: 0, portfolio: 2, unrealized: 0}}, "account panel: two different values or no value -> null, never guessed");
  eq(await acctpC.evaluate("window.__submitted || 0"), 0, "account panel: read-only");

  // Fixture H (SOL-PICKER, MEASURED 2026-10-06 dry-fill dumps): the real "Select market" chip (div role=button,
  // aria-label "Select market", text "ETH 20x"), watchlist buttons WITH a price ("SOL 150.23 -1.23%"), the ticket open on
  // ETH. The list the chip opens is UNMEASURED: H = a role=dialog of plain div rows (handler on the row, symbol in a
  // leaf span, a "SOLV" decoy); I = the same rows with NO popup role, SOL first (found as "appeared after the click");
  // J = the chip opens nothing -> watchlist fallback; K = two SOL rows -> ambiguous, nothing picked, watchlist fallback.
  const market = (mode) => `<!doctype html><html><body>
<div role=button id=chip aria-label="Select market">ETH 20x</div><button>Order form</button><button>Open orders</button><button>Positions</button>
<div id=wl><button data-s=BTC>BTC 62,410.5 -1.20%</button><button data-s=ETH>ETH 2,612.40 -0.50%</button><button data-s=SOL>SOL 150.23 -1.23%</button></div>
<div id=list></div>
<form id=f><div role=tablist><button type=button role=tab aria-selected=false>Market</button><button type=button role=tab aria-selected=true>Limit</button></div>
<div role=tablist><button type=button role=tab aria-selected=true>Buy</button><button type=button role=tab aria-selected=false>Sell</button></div>
<label for=lp>Limit price</label><input id=lp type=text><label for=q>Quantity</label><input id=q type=text>
<button type=button aria-label="Toggle quantity unit">USD</button><button type=submit id=sub>Long (buy) ETH</button></form>
<script>var MODE='${mode}';var LEV={BTC:50,ETH:20,SOL:10,SOLV:5,XRP:5};
function pick(s){document.getElementById('chip').textContent=s+' '+LEV[s]+'x';document.getElementById('sub').textContent='Long (buy) '+s;close();}
function close(){document.getElementById('list').innerHTML='';}
function row(s,name){var d=document.createElement('div');d.className='r';d.innerHTML='<span>'+s+'</span><span>'+name+'</span>';d.onclick=function(){window.__picks=(window.__picks||0)+1;pick(s.split(/[-\/]/)[0])};return d;}
document.getElementById('chip').onclick=function(){if(MODE==='J')return;var l=document.getElementById('list');var box=l;
 if(MODE!=='I'){box=document.createElement('div');box.setAttribute('role','dialog');l.appendChild(box);}
 var rs=MODE==='I'?[['SOL','Solana'],['BTC','Bitcoin'],['ETH','Ethereum']]:[['BTC','Bitcoin'],['ETH','Ethereum'],['SOLV','Solv'],['SOL','Solana'],['XRP','Ripple']];
 if(MODE==='K')rs.push(['SOL-PERP','Solana perp']);
 rs.forEach(function(r){box.appendChild(row(r[0],r[1]))});};
document.addEventListener('keydown',function(e){if(e.key==='Escape')close();});
document.querySelectorAll('#wl button').forEach(function(b){b.onclick=function(){window.__wl=(window.__wl||0)+1;pick(b.getAttribute('data-s'));};});
document.getElementById('f').onsubmit=function(e){e.preventDefault();window.__submitted=(window.__submitted||0)+1};</script></body></html>`;
  for (const [mode, route] of [["H", ["opened_market", "picked_market"]], ["I", ["opened_market", "picked_market"]],
    ["J", ["opened_market", "market_no_row", "clicked_watch"]], ["K", ["opened_market", "market_ambiguous", "clicked_watch"]]]) {
    const pM = await onHost(market(mode)); const rM = (code) => pM.evaluate(code);
    eq([await rM("__ex.marketShown()"), await rM("__ex.symbolShown()")], ["ETH", "ETH"], `market ${mode}: chip 'ETH 20x' read as ETH, ticket on ETH`);
    eq(await rM("__ex.symbolReset()"), "ok", `market ${mode}: picker state reset per ticket`);
    const got = []; for (let i = 0; i < route.length; i++) got.push(await rM("__ex.symbolStep('SOLUSD')"));
    eq(got, route, `market ${mode}: route ${route.join(">")}`);
    eq(await rM("__ex.symbolStep('SOLUSD')"), "done", `market ${mode}: then done`);
    eq([await rM("__ex.symbolOnTicket()"), await rM("__ex.marketShown()")], ["SOL", "SOL"], `market ${mode}: submit label AND chip name SOL`);
    eq([await rM("window.__picks || 0"), await rM("window.__wl || 0")], mode === "J" || mode === "K" ? [0, 1] : [1, 0], `market ${mode}: exactly one selection click (${mode === "J" || mode === "K" ? "watchlist" : "picker row"})`);
    eq(await rM("window.__submitted || 0"), 0, `market ${mode}: nothing submitted`);
    eq(await rM("[__ex.symbolStep('ETHUSD'), __ex.symbolStep('ETHUSD')]"), ["opened_market", mode === "J" ? "market_no_row" : "picked_market"], `market ${mode}: and back to ETH from SOL`);
  }
  // SERVER READ-BACK (PHONE-GO-TOKEN, design 3.4): the app builds the read-back from these page reads (MainActivity.kt
  // readBack: SELECTED tabs, the submit label + disabled state, the TP/SL box, the by-label values) and hashes
  // "key=value" lines in READBACK_FIELDS order (== src/prop/phone_executor.py). Mirrors the app; proves the page reads
  // it depends on, and that any change to the form between verify and click changes the hash (no click).
  const crypto = require("crypto");
  const FIELDS = ["ticket_id", "symbol", "side", "order_type", "price", "qty", "qty_unit", "tp", "sl", "submit_label", "submit_disabled", "tpsl"];
  await r("__ex.setByLabel('take ?profit', 'price', '2600.00')"); await r("__ex.setByLabel('stop ?loss', 'price', '2450.00')");
  const readBack = async () => {
    const tk = await r("__ex.ticket()");
    const sel = (re) => { const h = tk.tabs.filter((x) => x.selected && re.test(x.text.trim())); return h.length === 1 ? h[0].text.trim() : ""; };
    const val = async (re, pref) => ((await r(`__ex.readByLabel(${JSON.stringify(re)}, ${JSON.stringify(pref)})`)).value || "").trim();
    return {ticket_id: "t1", symbol: tk.symbol.trim(), side: sel(/^(buy|sell)$/i), order_type: sel(/^(market|limit|trigger|stop)$/i),
      price: await val("limit price", "limit price"), qty: await val("quantity", "quantity"), qty_unit: "ETH",
      tp: await val("take ?profit|\\btp\\b", "price"), sl: await val("stop ?loss|\\bsl\\b", "price"),
      submit_label: tk.submit.text.trim(), submit_disabled: String(tk.submit.disabled), tpsl: tk.tpsl === null ? "" : String(tk.tpsl)};
  };
  const hash = (rb) => crypto.createHash("sha256").update(FIELDS.map((k) => k + "=" + String(rb[k]).trim()).join("\n")).digest("hex");
  const rb1 = await readBack();
  eq([rb1.symbol, rb1.side, rb1.order_type, rb1.price, rb1.qty, rb1.tp, rb1.sl, rb1.submit_label, rb1.submit_disabled, rb1.tpsl],
    ["ETHUSD", "Buy", "Limit", "2500.10", "0.01", "2600.00", "2450.00", "Long (buy) ETHUSD", "false", "true"], "read-back: what the page shows");
  eq(hash(await readBack()), hash(rb1), "re-read of an unchanged form hashes the same (go allowed)");
  await r("__ex.setByLabel('quantity', '', '0.02')");
  eq(hash(await readBack()) === hash(rb1), false, "a changed quantity changes the hash (no click)");
  await r("__ex.setByLabel('quantity', '', '0.01')"); await r("__ex.tab('Sell')");
  const rbS = await readBack();
  eq([rbS.side, /short/i.test(rbS.submit_label), hash(rbS) === hash(rb1)], ["Sell", true, false], "a flipped side changes side, label and hash");
  await r("__ex.tab('Buy')");
  eq(await r("window.__submitted || 0"), 0, "nothing submitted by the read-back path");

  // LOGIN LINEUP (PHONE-AUTOLOGIN-2, operator 2026-10-10: "choose the correct 2 digit number from a line up of 3").
  // Synthetic shapes, not Breakout's real page: the mechanics of reading the choices and tapping exactly one.
  const lp = await b.newPage();
  await lp.route("https://app.breakoutprop.com/**", (route) => route.fulfill({ status: 200, contentType: "text/html", body:
    "<!doctype html><html><body>" + ({
      "/lineup": "<p>Check your email and select the matching number</p><div style='font-size:12px'>Step 2</div>" +
        "<div id=c><button style='font-size:32px' onclick='window.__picked=\"a\"'><span>47</span></button>" +
        "<button style='font-size:32px' onclick='window.__picked=\"b\"'><span>12</span></button>" +
        "<button style='font-size:32px' onclick='window.__picked=\"c\"'><span>83</span></button></div>",
      "/single": "<p>Check your email and tap the number</p><h1 style='font-size:48px'>47</h1><p style='font-size:10px'>Expires in 10</p>",
      "/dup": "<p>select the number</p><button>47</button><button>47</button><button>12</button>",
      "/box": "<p>select the number</p><div style='cursor:pointer' onclick='window.__picked=\"box\"'><span>47</span><span>12</span><span>83</span></div>",
    }[new URL(route.request().url()).pathname] || "") + "</body></html>" }));
  const lg = async (path) => { await lp.goto("https://app.breakoutprop.com" + path); await lp.addScriptTag({ content: src }); };
  await lg("/lineup");
  let ch = await lp.evaluate("__ex.loginChoices()");
  eq([ch.n, ch.top.sort(), ch.btn.sort()], [3, ["12", "47", "83"], ["12", "47", "83"]], "lineup: three tappable choices at the top size");
  eq(await lp.evaluate("__ex.state().codeWait"), true, "lineup page reads as the code step");
  eq(await lp.evaluate("__ex.loginNumber()"), "", "lineup: no SINGLE number (the 12:30Z/12:40Z failure shape)");
  eq(await lp.evaluate("__ex.loginPick('12')"), "clicked", "lineup: the matching choice is tapped");
  eq(await lp.evaluate("window.__picked"), "b", "lineup: exactly the matching control was tapped");
  eq(await lp.evaluate("__ex.loginPick('99')"), "none", "lineup: a number not on the page taps nothing");
  await lg("/single");
  ch = await lp.evaluate("__ex.loginChoices()");
  eq([ch.top, ch.btn], [["47"], []], "single-number page: one top number, no tappable lineup");
  eq(await lp.evaluate("__ex.loginNumber()"), "47", "single-number page: loginNumber still reads it");
  await lg("/dup");
  eq(await lp.evaluate("__ex.loginPick('47')"), "ambiguous", "two controls with the same number: nothing tapped");
  await lg("/box");
  eq(await lp.evaluate("__ex.loginChoices().btn"), [], "one clickable box holding all three numbers is not a lineup control");

  // PHONE-AUTOLOGIN-3 (live 2026-10-10 13:52Z/13:56Z: page_n=0 for 90 s on portal.breakoutprop.com). One synthetic
  // page per hypothesis; each must now be READ (or, for (c), described) instead of reading as zero.
  const lp3 = await b.newPage();
  await lp3.route("https://portal.breakoutprop.com/**", (route) => route.fulfill({ status: 200, contentType: "text/html; charset=utf-8", body:
    "<!doctype html><html><body>" + ({
      // (b) numbers with an icon child, split digit spans, zero-width characters
      "/icons": "<p>Select the matching number</p>" +
        "<button onclick='window.__picked=\"a\"'>47<svg width=8 height=8></svg></button>" +
        "<button onclick='window.__picked=\"b\"'><span>1</span><span>2</span></button>" +
        "<button onclick='window.__picked=\"c\"'>​83​</button>",
      // (b) radios whose number is only in value / aria-label, with a separate text label
      "/radios": "<p>Choose the number from your email</p>" +
        "<label><input type=radio name=n value=47 onclick='window.__picked=\"a\"'><span>47</span></label>" +
        "<label><input type=radio name=n value=12 onclick='window.__picked=\"b\"'><span>12</span></label>" +
        "<label><input type=radio name=n value=83 onclick='window.__picked=\"c\"'><span>83</span></label>",
      "/aria": "<p>select</p><div role=button aria-label=47 style='width:20px;height:20px' onclick='window.__picked=\"a\"'></div>" +
        "<div role=button aria-label=12 style='width:20px;height:20px' onclick='window.__picked=\"b\"'></div>" +
        "<div role=button aria-label=83 style='width:20px;height:20px' onclick='window.__picked=\"c\"'></div>",
      // (b) a shadow root and a same-origin iframe
      "/shadow": "<p>Select the number</p><x-pick id=h></x-pick><script>var r=document.getElementById('h').attachShadow({mode:'open'});" +
        "r.innerHTML='<button onclick=\"window.__picked=1\">47</button><button onclick=\"window.__picked=2\">12</button><button onclick=\"window.__picked=3\">83</button>';</script>",
      "/frame": "<p>Select the number</p><iframe src='/inner' style='width:300px;height:200px'></iframe>",
      "/inner": "<button onclick='parent.__picked=\"f\"'>47</button><button onclick='parent.__picked=\"g\"'>12</button><button>83</button>",
      // (c) the page only says "check your email": nothing numeric to read, the structure must say so
      "/check": "<h1>Check your email</h1><p>We sent a sign-in link to b***@example.com. It expires in 15 minutes.</p>" +
        "<a href='https://portal.breakoutprop.com/help/42'>Need help?</a><button>Resend email</button>",
      // (a) an email form whose FIRST matching button is a social login; the real submit is in the form
      "/email": "<button onclick='window.__social=1'>Continue with Google</button><form id=f onsubmit='event.preventDefault()'>" +
        "<input type=email><button type=submit onclick='window.__sent=1'>Continue</button></form>",
      // (a) a form with NO button: only Enter submits it
      "/enter": "<form id=f onsubmit='event.preventDefault();window.__sent=1'><input type=email></form>",
    }[new URL(route.request().url()).pathname] || "") + "</body></html>" }));
  const lg3 = async (path) => { await lp3.goto("https://portal.breakoutprop.com" + path); await lp3.waitForTimeout(150); await lp3.addScriptTag({ content: src }); };
  for (const [path, want, pick] of [["/icons", ["12", "47", "83"], "b"], ["/radios", ["12", "47", "83"], "b"], ["/aria", ["12", "47", "83"], "b"],
    ["/shadow", ["12", "47", "83"], 2]]) {
    await lg3(path);
    ch = await lp3.evaluate("__ex.loginChoices()");
    eq(ch.btn.sort(), want, `${path}: three tappable choices read`);
    eq(await lp3.evaluate("__ex.loginPick('12')"), "clicked", `${path}: the one matching choice tapped`);
    eq(await lp3.evaluate("window.__picked"), pick, `${path}: exactly that control`);
  }
  await lg3("/frame");
  eq((await lp3.evaluate("__ex.loginChoices()")).btn.sort(), ["12", "47", "83"], "/frame: choices read inside a same-origin iframe");
  eq(await lp3.evaluate("__ex.loginPick('47')"), "clicked", "/frame: tapped inside the iframe");
  eq(await lp3.evaluate("window.__picked"), "f", "/frame: exactly that control");
  let pr = await lp3.evaluate("__ex.loginProbe()");
  eq([pr.frames, pr.frames_xo], [1, 0], "/frame: probe counts one readable iframe");
  await lg3("/check");
  eq((await lp3.evaluate("__ex.loginChoices()")).n, 0, "/check: nothing numeric on a check-your-email page");
  pr = await lp3.evaluate("__ex.loginProbe()");
  eq([pr.phrases.includes("check_email"), pr.phrases.includes("we_sent"), pr.cands], [true, true, 0], "/check: probe names the shape");
  eq(/\d|@|example|http/.test(JSON.stringify(pr.texts)), false, "/check: probe texts carry no digit, email or link");
  eq(pr.texts.includes("Check your email"), true, "/check: heading text kept (scrubbed)");
  eq(pr.numtok > 0 && typeof pr.sig === "string", true, "/check: numeric tokens COUNTED, sig present");
  await lg3("/email");
  const sig0 = (await lp3.evaluate("__ex.loginProbe()")).sig;
  eq(await lp3.evaluate("__ex.loginEmail('a@b.co')"), "clicked", "/email: submitted");
  eq(await lp3.evaluate("[window.__social || 0, window.__sent || 0]"), [0, 1], "/email: the form's Continue, never the social button");
  eq((await lp3.evaluate("__ex.loginSubmitInfo()")).where, "form", "/email: submit info says form");
  await lp3.evaluate("document.body.insertAdjacentHTML('beforeend', '<p>Check your email</p>')");
  eq((await lp3.evaluate("__ex.loginProbe()")).sig !== sig0, true, "/email: sig changes when the page advances");
  await lg3("/enter");
  eq(await lp3.evaluate("__ex.loginEmail('a@b.co')"), "submitted", "/enter: no button -> form submitted");
  eq(await lp3.evaluate("__ex.loginEnter()"), "enter+submit", "/enter: Enter path available");
  eq(await lp3.evaluate("window.__sent"), 1, "/enter: form submitted");
  // regression: the original lineup still reads exactly as before under the broadened reader
  await lg("/lineup");
  eq((await lp.evaluate("__ex.loginChoices()")).n, 3, "lineup: still exactly three candidates");
  // POSITIONS + CLOSED ORDERS READ (PROP-TRACKING, 2026-10-12). SYNTHETIC tables in the shape the 2026-10-12 operator
  // screenshot described ("ETH 5x ... uPnL +31.27 USD"); they prove the mapping and the fail-closed states, NOT
  // Breakout's real headers (the first live read measures those; a miss posts the masked headers).
  const posTable = (tab, rows, extra) => `<!doctype html><html><head><meta charset=utf-8></head><body><div role=tablist><button role=tab>${tab}</button><button role=tab>Open orders</button><button role=tab>Closed orders</button></div>
<div id=wrap><table><thead><tr><th>Symbol</th><th>Size</th><th>Entry price</th><th>Mark price</th><th>Liq. price</th><th>Unrealized PnL</th><th>TP/SL</th></tr></thead>
<tbody>${rows}</tbody></table>${extra || ""}</div></body></html>`;
  const ROWS2 = "<tr><td>ETH 5x Long</td><td>1.1758 ETH</td><td>2,527.80</td><td>2,554.40</td><td>2,100.00</td><td>+31.27 USD (1.05%)</td><td>2655.4 / 2506.5</td></tr>" +
    "<tr><td>SOL 5x Long</td><td>17.26 SOL</td><td>111.16</td><td>112.30</td><td>90.10</td><td>+19.67 USD</td><td>-</td></tr>";
  const qP = await onHost(posTable("Positions (2)", ROWS2));
  let qpr2 = await qP.evaluate("__ex.positionsRead()");
  eq(qpr2.state, "read", "positions: two rows read");
  eq(qpr2.rows.map((r) => [r.symbol, r.side, r.qty, r.entry, r.mark, r.upnl]),
    [["ETH", "long", 1.1758, 2527.8, 2554.4, 31.27], ["SOL", "long", 17.26, 111.16, 112.3, 19.67]], "positions: symbol/side/qty/entry/mark/uPnL mapped by header");
  eq(qpr2.count, 2, "positions: the tab's own count read");
  eq(Object.keys(qpr2.rows[0]).includes("liq"), false, "positions: liquidation price not read as anything");
  const qP2 = await onHost(posTable("Positions (3)", ROWS2));
  eq((await qP2.evaluate("__ex.positionsRead()")).state, "count_mismatch", "positions: tab count 3 vs 2 rows -> not read");
  const qP3 = await onHost(posTable("Positions", "", ""));
  eq((await qP3.evaluate("__ex.positionsRead()")).state, "empty_unconfirmed", "positions: header with no rows and no empty text is NOT flat");
  const qP4 = await onHost(posTable("Positions", "<tr><td colspan=7>No open positions</td></tr>"));
  let e4 = await qP4.evaluate("__ex.positionsRead()");
  eq([e4.state, e4.rows], ["read", []], "positions: explicit 'No open positions' row reads as flat");
  const qP5 = await onHost(posTable("Positions", "<tr><td>ETH</td><td>1.17</td><td>2527.8</td><td>2554</td><td>2100</td><td>31</td><td>-</td></tr>"));
  eq((await qP5.evaluate("__ex.positionsRead()")).state, "unparsed", "positions: a row with no readable side is unparsed, never guessed");
  const qP6 = await onHost(`<!doctype html><html><body><div role=tablist><button role=tab>Positions</button></div><div class=card>ETH 5x uPnL +31.27</div></body></html>`);
  let e6 = await qP6.evaluate("__ex.positionsRead()");
  eq([e6.state, e6.controls.includes("Positions")], ["no_table", true], "positions: card layout (no table) -> no_table with the masked controls dump");
  eq(/31/.test(JSON.stringify(e6)), false, "positions miss dump carries no value");
  const qP7 = await onHost(posTable("Positions", "<tr><td>ETHUSD</td><td>-1.5</td><td>2600</td><td>2550</td><td>3000</td><td>−75.00</td><td>-</td></tr>", "<p>x</p>"));
  let e7 = await qP7.evaluate("__ex.positionsRead()");
  eq([e7.state, e7.rows[0].side, e7.rows[0].qty, e7.rows[0].upnl], ["read", "short", 1.5, -75], "positions: signed size gives the side; unicode minus uPnL");
  // REVIEW OF #17745 (blocking 1): "no positions" text ANYWHERE on the page is not a flat read; only the tab's own
  // count of 0 or the ONE visible tab panel saying so.
  const qF1 = await onHost(`<!doctype html><html><body><div role=tablist><button role=tab>Positions</button></div><p>You have no positions in your watchlist alerts</p></body></html>`);
  eq((await qF1.evaluate("__ex.positionsRead()")).state, "no_table", "flat refused: page-wide 'no positions' text is not the Positions panel");
  const qF2 = await onHost(`<!doctype html><html><body><div role=tablist><button role=tab>Positions (0)</button></div><p>whatever</p></body></html>`);
  let f2 = await qF2.evaluate("__ex.positionsRead()");
  eq([f2.state, f2.rows], ["read", []], "flat accepted: the tab's own count is 0");
  const qF3 = await onHost(`<!doctype html><html><body><div role=tablist><button role=tab>Positions</button></div><div role=tabpanel>No open positions</div></body></html>`);
  eq((await qF3.evaluate("__ex.positionsRead()")).state, "read", "flat accepted: the one visible tab panel says no positions");
  // REVIEW OF #17745 (blocking 2): more rows than the cap are refused, never truncated (a dropped row would read as closed)
  const many = Array.from({length: 16}, (_, i) => `<tr><td>ETH Long</td><td>${i + 1}</td><td>2500</td><td>2501</td><td>2000</td><td>1</td><td>-</td></tr>`).join("");
  const qF4 = await onHost(posTable("Positions", many));
  let f4 = await qF4.evaluate("__ex.positionsRead()");
  eq([f4.state, f4.n_rows, f4.rows], ["too_many_rows", 16, undefined], "16 positions -> too_many_rows, nothing sent");
  // DIV GRID (PHONE-POSITIONS-DIV, 2026-10-12): the LIVE Positions view has no <table>: header labels Market | UP&L |
  // Side | Value | Opening price | Current price | TP / SL | Net P&L (read from the first live diag), no size column.
  // SYNTHETIC rows in that shape; the empty state "Start trading with leverage" appears while flat.
  const gridRow = (m, up, side, val, op, cur, tpsl, net) => `<div class=r><div>${m}</div><div>${up}</div><div>${side}</div><div>${val}</div><div>${op}</div><div>${cur}</div><div>${tpsl}</div><div>${net}</div></div>`;
  const gridPage = (tab, body, aside) => `<!doctype html><html><head><meta charset=utf-8></head><body>
<div id=top><span>Trade</span><div>Portfolio 4,947.72 USD</div></div>
<div id=side><div><button>Market</button><button>Limit</button></div><div>Side</div><div>Value</div>${aside || ""}</div>
<div id=bottom><div id=tabs><button>Open orders</button><button>${tab}</button><button>Portfolio</button><button>Closed orders</button><button>Trades</button></div>
<div id=panel><div id=hdr><div>Market</div><div>UP&amp;L</div><div>Side</div><div>Value</div><div>Opening price</div><div>Current price</div><div>TP / SL</div><div>Net P&amp;L</div></div>${body}</div></div></body></html>`;
  const G2 = gridRow("ETHUSD 5x", "+31.27 USD", "Long", "3,003.30 USD", "2,527.80", "2,554.40", "2655.4 / 2506.5", "+30.10 USD") +
    gridRow("SOLUSD 5x", "-4.50 USD", "Short", "1,921.00 USD", "111.16", "112.30", "-", "-5.60 USD");
  const gP = await onHost(gridPage("Positions", G2));
  let g2 = await gP.evaluate("__ex.positionsRead()");
  eq([g2.state, g2.layout, g2.n_rows], ["read", "div_grid", 2], "div grid: two positions read");
  eq(g2.rows.map((r) => [r.symbol, r.side, r.entry, r.mark, r.upnl, r.value]),
    [["ETHUSD", "long", 2527.8, 2554.4, 31.27, 3003.3], ["SOLUSD", "short", 111.16, 112.3, -4.5, 1921]], "div grid: mapped by header label (UP&L is upnl)");
  eq(g2.rows.map((r) => r.netpnl), [30.1, -5.6], "div grid: Net P&L kept apart from upnl");
  eq(g2.rows.map((r) => [r.qty, r.qty_src]), [[1.17573598, "value/mark"], [17.10596616, "value/mark"]], "div grid: qty derived from Value / Current price, labelled");
  const gP1 = await onHost(gridPage("Positions", gridRow("ETHUSD", "+1.00 USD", "Long", "2,554.40 USD", "2,527.80", "2,554.40", "-", "+0.50 USD")));
  let g1 = await gP1.evaluate("__ex.positionsRead()");
  eq([g1.state, g1.rows.length, g1.rows[0].side], ["read", 1, "long"], "div grid: one position read");
  const gE = await onHost(gridPage("Positions", "<div class=empty><svg></svg><p>Start trading with leverage</p><button>Trade</button></div>"));
  let ge = await gE.evaluate("__ex.positionsRead()");
  eq([ge.state, ge.rows], ["read", []], "div grid: empty-state INSIDE the Positions panel is flat");
  const gE2 = await onHost(gridPage("Positions", "", "<p>Start trading with leverage</p>"));
  eq((await gE2.evaluate("__ex.positionsRead()")).state, "empty_unconfirmed", "div grid: empty-state text elsewhere on the page is NOT flat");
  const gO = await onHost(gridPage("Positions", gridRow("ETHUSD 5x", "+31.27 USD", "Long", "3,003.30 USD", "2,527.80", "2,554.40", "-", "+30.10 USD"), "<p>Start trading with leverage</p>"));
  let go = await gO.evaluate("__ex.positionsRead()");
  eq([go.state, go.rows.length, go.rows[0].symbol], ["read", 1, "ETHUSD"], "div grid: 1 open position + 'Start trading' text elsewhere reads the position, not flat");
  const gO2 = await onHost(gridPage("Positions", gridRow("ETHUSD 5x", "+31.27 USD", "Long", "3,003.30 USD", "2,527.80", "2,554.40", "-", "+30.10 USD") + "<p>Start trading with leverage</p>"));
  eq((await gO2.evaluate("__ex.positionsRead()")).rows.length, 1, "div grid: a row present wins over stray empty text inside the panel");
  const gE3 = await onHost(gridPage("Positions", "", ""));
  eq((await gE3.evaluate("__ex.positionsRead()")).state, "empty_unconfirmed", "div grid: header with no rows and no empty text is NOT flat");
  const gE4 = await onHost(gridPage("Positions (0)", ""));
  let ge4 = await gE4.evaluate("__ex.positionsRead()");
  eq([ge4.state, ge4.rows], ["read", []], "div grid: the tab's own count 0 is flat");
  eq((await (await onHost(gridPage("Positions (3)", G2))).evaluate("__ex.positionsRead()")).state, "count_mismatch", "div grid: tab count 3 vs 2 rows -> not read");
  const gMany = Array.from({length: 16}, () => gridRow("ETHUSD", "+1 USD", "Long", "2,554.40 USD", "2,500", "2,554.40", "-", "+1 USD")).join("");
  let gm = await (await onHost(gridPage("Positions", gMany))).evaluate("__ex.positionsRead()");
  eq([gm.state, gm.n_rows, gm.rows], ["too_many_rows", 16, undefined], "div grid: 16 positions -> too_many_rows, nothing sent");
  const gBad = G2 + "<div class=r><div>XRPUSD 5x</div><div>+1 USD</div><div>Long</div><div>500 USD</div></div>";
  let gb = await (await onHost(gridPage("Positions", gBad))).evaluate("__ex.positionsRead()");
  eq(gb.state, "unparsed", "div grid: a row whose cells do not line up with the header is unparsed, never dropped");
  eq(/\d/.test(JSON.stringify(gb.headers)), false, "div grid: miss dump headers carry no digits");
  const gNoSide = await onHost(gridPage("Positions", gridRow("ETHUSD", "+1 USD", "-", "2,554.40 USD", "2,500", "2,554.40", "-", "+1 USD")));
  eq((await gNoSide.evaluate("__ex.positionsRead()")).state, "unparsed", "div grid: no readable side -> unparsed, never guessed");
  const gNoTabs = await onHost(`<!doctype html><html><body><div id=hdr><div>Market</div><div>UP&amp;L</div><div>Side</div><div>Value</div><div>Opening price</div><div>Current price</div></div><p>Start trading with leverage</p></body></html>`);
  eq((await gNoTabs.evaluate("__ex.positionsRead()")).state, "empty_unconfirmed", "div grid: no tab bar to bound the panel -> no flat evidence");
  const closedT = `<!doctype html><html><body><div role=tablist><button role=tab>Positions</button><button role=tab>Closed orders</button></div>
<table><tr><th>Time</th><th>Symbol</th><th>Side</th><th>Type</th><th>Filled</th><th>Avg. price</th><th>Status</th><th>Realized PnL</th></tr>
<tr><td>2026-10-12 12:01:05</td><td>ETH</td><td>Sell</td><td>Take profit</td><td>1.1758</td><td>2,655.40</td><td>Filled</td><td>+150.03</td></tr>
<tr><td>2026-10-11 15:50:48</td><td>ETH</td><td>Buy</td><td>Limit</td><td>1.1758</td><td>2,527.80</td><td>Filled</td><td>-</td></tr></table></body></html>`;
  const qC = await onHost(closedT);
  let qcr = await qC.evaluate("__ex.closedRead()");
  eq(qcr.state, "read", "closed orders read");
  eq([qcr.rows[0].symbol, qcr.rows[0].side, qcr.rows[0].qty, qcr.rows[0].price, qcr.rows[0].type, qcr.rows[0].status, qcr.rows[0].pnl, qcr.rows[0].time],
    ["ETH", "short", 1.1758, 2655.4, "Take profit", "Filled", 150.03, "2026-10-12 12:01:05"], "closed orders: the TP fill row mapped");
  eq(qcr.rows[1].pnl, null, "closed orders: '-' P&L stays null, never 0");
  // ACCOUNT PANEL on the Portfolio tab (PROP-TRACKING): balance + the terminal's own unrealized P&L, signed
  const qA = await onHost(`<!doctype html><html><head><meta charset=utf-8></head><body><button>Portfolio 5,099.14 USD</button><div role=tablist><button role=tab>Portfolio</button></div>
<dl><dt>Balance</dt><dd>5,048.20</dd><dt>Unrealized PnL</dt><dd>\u221212.06</dd></dl></body></html>`);
  let ap = await qA.evaluate("__ex.accountPanel()");
  eq([ap.balance, ap.portfolio, ap.unrealized], [5048.2, 5099.14, -12.06], "account panel: balance, portfolio and signed unrealized read by label");
  await b.close(); console.log("exec_check: all passed");
})().catch((e) => { console.error(e); process.exit(1); });
