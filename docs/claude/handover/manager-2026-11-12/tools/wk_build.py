import json, re, subprocess, sys, datetime
import os, sys
SP=(sys.argv[1] if len(sys.argv)>1 else os.getcwd()).rstrip("/")+"/"  # output dir (needs a wk/ subdir)
os.makedirs(SP+"wk",exist_ok=True)
REPO=os.environ.get("JTA_REPO","/home/user/JTA-Trader")
wp=open(REPO+"/docs/plans/weekly/2026-11-12/WORKPLAN.md").read().splitlines()
rows=[]; am=None; day=None; sec=None
for ln in wp:
    if ln.startswith("## "):
        sec=ln[3:].strip(); am=None; day=None
    m=re.match(r"### (AM-[A-Z]+)",ln)
    if m: am=m.group(1); continue
    m=re.match(r"\*\*(2026-\d\d-\d\d)\*\*",ln.strip())
    if m: day=m.group(1); continue
    if sec and sec.startswith("3.") and am and ln.startswith("|") and not ln.startswith("|--") and not ln.startswith("| #"):
        c=[x.strip() for x in ln.strip("|").split("|")]
        if len(c)>=4 and c[1] and not c[1].startswith("row"):
            rows.append({"id":c[1],"am":am,"slot":day,"bucket":"surge","n":c[0],"size":c[2],"what":c[3]})
    if sec and sec.startswith("4.") and ln.startswith("**AM-"):
        m=re.match(r"\*\*(AM-[A-Z]+) \(\d+\):\*\* (.*)",ln)
        if m:
            for i,x in enumerate(m.group(2).split(",")):
                rows.append({"id":x.strip(),"am":m.group(1),"slot":"11-17/18","bucket":"throttle","n":str(i+1),"size":"","what":""})
    if sec and sec.startswith("5.") and ln and not ln.startswith("#"):
        for x,a in re.findall(r"([A-Z0-9][A-Z0-9-]+) \((AM-[A-Z]+)\)",ln):
            rows.append({"id":x,"am":a,"slot":"standing","bucket":"standing","n":"","size":"","what":""})
    if sec and sec.startswith("6.") and ln.startswith("| ") and not ln.startswith("| row"):
        c=[x.strip() for x in ln.strip("|").split("|")]
        if len(c)>=3: rows.append({"id":c[0],"am":"AM-"+c[1],"slot":"observe","bucket":"landed_unproven","n":"","size":"","what":"closes when: "+c[2]})
# fetch store
items={}; off=0
while True:
    out=subprocess.run(["curl","-sS","--max-time","60",f"https://ict-bot.duckdns.org/api/bot/work/items?limit=1000&offset={off}"],capture_output=True,text=True).stdout
    d=json.loads(out); it=d.get("items",[])
    for x in it: items[x["id"]]=x
    off+=len(it)
    if not it or off>=d.get("total",0): break
def tail(x):
    n=(x.get("extra") or {}).get("note") or ""
    n=n.strip()
    return n[-420:] if n else ""
seen=set(); out=[]
for r in rows:
    if r["id"] in seen: continue
    seen.add(r["id"]); x=items.get(r["id"])
    if x:
        r.update(state=x.get("state"), title=x.get("title") or "", owner=x.get("owner"), updated_at=x.get("updated_at"),
                 prs=x.get("prs") or [], terminal=x.get("terminal_reason"), note=tail(x))
        if not r["what"]: r["what"]=(x.get("title") or "")[:140]
    else:
        r.update(state="not_in_store")
    out.append(r)
# added since planning (09:05Z) and not in plan
cut="2026-11-12T09:05"
added=[]
for k,x in items.items():
    if k in seen or x.get("kind")!="build": continue
    if (x.get("created_at") or "")>=cut:
        added.append({"id":k,"am":(x.get("owner") or "")[:60],"slot":"added today","bucket":"added","n":"","size":"",
            "what":(x.get("title") or "")[:160],"state":x.get("state"),"owner":x.get("owner"),"updated_at":x.get("updated_at"),"prs":x.get("prs") or [],"note":tail(x)})
added.sort(key=lambda r:r.get("updated_at") or "", reverse=True)
snap={"generated_at":datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ"),"plan":"docs/plans/weekly/2026-11-12/WORKPLAN.md","store_total":len(items),"rows":out,"added":added}
json.dump({"json":json.dumps(snap)},open(SP+"wk/snapshot_doc.json","w"))
from collections import Counter
print(len(out),"plan rows;",len(added),"added; states",Counter(r["state"] for r in out).most_common())
print("bytes",len(json.dumps(snap)))
# chunk for the artifact db (256 KB/doc limit)
s=json.dumps(snap); size=170000
chunks=[s[i:i+size] for i in range(0,len(s),size)]
import os
for f in os.listdir(SP+"wk"):
    if f.startswith("chunk_"): os.remove(SP+"wk/"+f)
for i,c in enumerate(chunks):
    json.dump({"gen":snap["generated_at"],"seq":i,"total":len(chunks),"chunk":c},open(SP+f"wk/chunk_{i}.json","w"))
print("chunks",len(chunks))
