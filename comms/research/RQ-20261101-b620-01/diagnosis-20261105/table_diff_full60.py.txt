import sys,json,pandas as pd,numpy as np
from pathlib import Path
sys.path.insert(0,'/home/user/JTA-Trader/scripts/research');sys.path.insert(0,'/home/user/JTA-Trader')
import ml_decision_entry as E, ml_entry_timeframe as T
ce=Path('/tmp/claude-0/diag/E');ct=Path('/tmp/claude-0/diag/T')
sp=T.spec('1h','bar');syms=E.universe();print(len(syms),flush=True)
E.fetch(ce,syms);print('E fetched',flush=True)
import concurrent.futures as cf
with cf.ThreadPoolExecutor(8) as ex: list(ex.map(lambda s:T.fetch_symbol(ct,s,'1h'),syms))
print('T fetched',flush=True)
te=E.build_table(ce,syms);tt=T.build_table(ct,syms,sp)
cut=pd.Timestamp(E.HOLDOUT_START,tz='UTC')-pd.Timedelta(hours=25)
te=te[te.ts<cut];tt=tt[tt.ts<cut]
m=te.merge(tt,on=['symbol','ts'],how='outer',suffixes=('_e','_t'),indicator=True)
out={'rows_E':len(te),'rows_T':len(tt),'only_E':int((m._merge=='left_only').sum()),'only_T':int((m._merge=='right_only').sum())}
oe=m[m._merge=='left_only'];ot=m[m._merge=='right_only']
out['only_E_by_symbol']=oe.symbol.value_counts().head(10).to_dict();out['only_T_by_symbol']=ot.symbol.value_counts().head(10).to_dict()
out['only_E_ts_range']=[str(oe.ts.min()),str(oe.ts.max())] if len(oe) else None;out['only_T_ts_range']=[str(ot.ts.min()),str(ot.ts.max())] if len(ot) else None
b=m[m._merge=='both'];diffs={}
for c in E.FEATURES+['net_long','net_short']:
    a=b[c+'_e'].astype(float);d=b[c+'_t'].astype(float);both=a.notna()&d.notna()
    n=int((np.abs(a[both]-d[both])>1e-5).sum());nm=int((a.isna()!=d.isna()).sum())
    if n or nm: diffs[c]={'n_gt_1e-5':n,'nan_mismatch':nm,'maxabs':float(np.abs(a[both]-d[both]).max())}
out['feature_diffs']=diffs
json.dump(out,open('/tmp/claude-0/diag/full60.json','w'),indent=1,default=str);print(json.dumps(out,indent=1,default=str))
