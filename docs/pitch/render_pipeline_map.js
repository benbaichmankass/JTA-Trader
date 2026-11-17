// Renders docs/pitch/pipeline_map.png from the mermaid source in docs/reference/trading-pipeline-map.md
// (section "## The flow"), VERBATIM, so the deck shows the same map as the Work tab.
// Usage: npm install mermaid@11.4.1 (anywhere), then
//   MERMAID_JS=<path>/node_modules/mermaid/dist/mermaid.min.js node docs/pitch/render_pipeline_map.js
const {chromium} = require('playwright');
const fs = require('fs');
const path = require('path');
const root = path.join(__dirname, '..', '..');
const md = fs.readFileSync(path.join(root, 'docs/reference/trading-pipeline-map.md'), 'utf8');
const flow = md.split('## The flow')[1];
const src = flow.split('```mermaid')[1].split('```')[0].trim();
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({viewport: {width: 1400, height: 2400}, deviceScaleFactor: 2});
  await p.setContent('<html><body style="margin:0;background:#F7F6F2"><div id="m"></div></body></html>');
  await p.addScriptTag({path: process.env.MERMAID_JS});
  await p.evaluate(async (s) => {
    mermaid.initialize({startOnLoad: false, theme: 'neutral', flowchart: {htmlLabels: true, useMaxWidth: false}});
    const {svg} = await mermaid.render('g', s);
    document.getElementById('m').innerHTML = svg;
  }, src);
  await (await p.$('#m svg')).screenshot({path: path.join(__dirname, 'pipeline_map.png')});
  await b.close();
})();
