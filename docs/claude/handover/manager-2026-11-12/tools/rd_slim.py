# usage: python3 rd/slim.py <rd_registry.json>  -> writes rd/rpN.json chunks for collection "rdreg"
import json,sys,glob,os
d=json.load(open(sys.argv[1])); here=os.path.dirname(os.path.abspath(__file__))
def t(s,n):
    s='' if s is None else str(s); return s if len(s)<=n else s[:n-1]+'…'
I=[]
for i in d['ideas']:
    lr=i.get('latest_result') or {}; ev=i.get('stage0_evidence') or {}
    I.append({"id":i['id'],"name":t(i.get('name'),160),"track":i['track'],"kind":i.get('kind'),
      "prog":t(','.join(i['programme']) if isinstance(i.get('programme'),list) else i.get('programme'),40),
      "stage":i['stage'],"why":t(i.get('stage_reason'),260),"next":t(i.get('next_step'),260),"c":i.get('counts'),
      "lr":({"u":lr.get('unit'),"v":lr.get('verdict'),"d":(lr.get('date') or '')[:10],"n":lr.get('n'),"t":t(lr.get('title'),200)} if lr else None),
      "books":i.get('books'),"last":(i.get('last_activity') or '')[:16] or None,"link":next(iter((i.get('links') or {}).values()),None),
      "open":(i.get('open_units') or [])[:4],
      "ev":({"r":ev.get('expectancy_r_oos'),"n":ev.get('n_trades_oos'),"f":f"{ev.get('folds_positive')}/{ev.get('folds')}"} if ev.get('coverage_state')=='measured' else None)})
out={"generated_at":d['generated_at'],"stages":d['stages'],"summary":{k:d['summary'][k] for k in ('ideas','per_track','per_stage_per_track')},
     "changed":d['summary']['changed_last_7d'],"rules":d['stage_rules'],"ideas":I}
s=json.dumps(out); n=170000; ch=[s[i:i+n] for i in range(0,len(s),n)]
for f in glob.glob(os.path.join(here,'rp*.json')): os.remove(f)
for k,c in enumerate(ch): json.dump({"gen":d['generated_at'],"seq":k,"total":len(ch),"chunk":c},open(os.path.join(here,f'rp{k}.json'),'w'))
print(len(s),len(ch))
