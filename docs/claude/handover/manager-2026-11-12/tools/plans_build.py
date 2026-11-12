# Builds the Plans tab data: ML dev plan (docs/plans/ml-dev-plan.yaml if present on main, else ml-plan-items.yaml)
# joined to live work-store state, plus the frontier sub-queue (work items FRONTIER-Q-*).
import json, subprocess, urllib.request, yaml, os, sys
here=os.path.dirname(os.path.abspath(__file__)); repo='/home/user/JTA-Trader'
subprocess.run(['git','-C',repo,'fetch','-q','origin','main'],check=False)
def show(p):
    r=subprocess.run(['git','-C',repo,'show','origin/main:'+p],capture_output=True,text=True); return r.stdout if r.returncode==0 else None
src='docs/plans/ml-dev-plan.yaml'; txt=show(src)
if not txt: src='docs/plans/ml-plan-items.yaml'; txt=show(src)
plan=yaml.safe_load(txt)
items=[]; off=0
while True:
    d=json.load(urllib.request.urlopen(f"https://ict-bot.duckdns.org/api/bot/work/items?limit=1000&offset={off}",timeout=60))
    xs=d.get('items') if isinstance(d,dict) else d
    items+=xs
    if len(xs)<1000: break
    off+=1000
W={x.get('id'):x for x in items}
def tail(x,n=360):
    s=(x or {}).get('note') or (x or {}).get('notes') or ''
    if isinstance(s,list): s=' '.join(str(i) for i in s[-2:])
    s=str(s); return s[-n:]
P=[]
for it in plan.get('items') or plan.get('lines') or []:
    ref=it.get('ref'); w=W.get(ref)
    P.append({"id":it.get('id'),"track":it.get('track'),"family":it.get('family'),"title":it.get('title'),"plan_state":it.get('state'),
      "ref":ref,"ref_state":(w or {}).get('state') if w else ("unit" if str(ref or '').startswith('RQ-') else None),
      "close":(it.get('close') or '')[:600],"steps":it.get('steps') or it.get('iterations'),"next":it.get('next'),"owner":it.get('owner'),
      "updated":(w or {}).get('updated_at'),"tier":it.get('tier')})
F=[]
for k,x in W.items():
    if str(k).startswith('FRONTIER-Q-'):
        F.append({"id":k,"title":x.get('title'),"state":x.get('state'),"owner":x.get('owner'),"updated":x.get('updated_at'),"note":tail(x)})
F.sort(key=lambda r:r.get('updated') or '',reverse=True)
import datetime
out={"generated_at":datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ'),"plan_source":src,"plan_updated":plan.get('updated'),"plan":P,"frontier":F,
     "tracks":{"S":"AI-trader spine","R":"Regime / when to trade","X":"Exit and take-profit heads","P":"Serve parity and producers","D":"Data, labels, hygiene","N":"New ideas / information classes","F":"Frontier"}}
s=json.dumps(out); json.dump({"json":s},open(os.path.join(here,'plans_doc.json'),'w'))
print(len(s),len(P),len(F),src)
