"""PPI pre-event read (PPI-EVENT-DESK-20261113). Hourly bars committed under comms/research; surprises from Bigdata.com economic calendar.
Measures per symbol: (1) |reaction| event vs same-hour baseline, (2) Spearman IC surprise->reaction, (3) continuation trade entered 1h after release, net of an ESTIMATED round-trip cost."""
import json
import sys
import glob
import math
import pandas as pd
import numpy as np
from scipy.stats import spearmanr
import os
R=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))+'/'
EV=[e for e in json.load(open(sys.argv[1]))['events'] if e.get('core_mom') is not None]
SYMS={'GLD':'RQ-20261018-ef5d-01','GDX':'RQ-20261018-ef5d-01','IAUM':'RQ-20261018-ef5d-01','SLV':'RQ-20261018-ef5d-01','TLT':'RQ-20261018-ef5d-01',
 'QQQ':'RQ-20261018-ef5d-01','SPY':'RQ-20261018-ef5d-01','USO':'RQ-20261018-ef5d-01','MGC':'RQ-20261018-ef5d-01','MHG':'RQ-20261018-ef5d-01',
 'BTCUSDT':'RQ-20261022-326f-10','ETHUSDT':'RQ-20261026-f679-02','SOLUSDT':'RQ-20261026-f679-02','XRPUSDT':'RQ-20261026-f679-02','ADAUSDT':'RQ-20261022-4b82-01'}
COST_BPS={'GLD':3,'GDX':4,'IAUM':4,'SLV':4,'TLT':3,'QQQ':2,'SPY':2,'USO':4,'MGC':4,'MHG':6,'BTCUSDT':12,'ETHUSDT':12,'SOLUSDT':14,'XRPUSDT':14,'ADAUSDT':14}  # ESTIMATED round trip incl. spread
def load(s):
    f=glob.glob(f"{R}comms/research/{SYMS[s]}/*/data/{s}_60.csv")[0]
    d=pd.read_csv(f); d['ts']=pd.to_datetime(d['timestamp'],utc=True); return d.set_index('ts').sort_index()
out={}
for s in SYMS:
    d=load(s); c=d['close']; o=d['open']; idx=d.index
    lo,hi=idx[0],idx[-1]; rows=[]
    for e in EV:
        t=pd.Timestamp(e['t']).floor('h')
        if t<lo or t>hi: continue
        # first bar whose START >= t (ETF: first RTH bar after a pre-market release)
        j=idx.searchsorted(t)
        if j>=len(idx) or j==0: continue
        pre=c.iloc[j-1]; r_react=c.iloc[j]/pre-1         # prior close -> close of first post-release bar
        k4=min(j+4,len(idx)-1); k24=idx.searchsorted(idx[j]+pd.Timedelta(hours=24)); k24=min(k24,len(idx)-1)
        r_cont4=c.iloc[k4]/c.iloc[j]-1; r_cont24=c.iloc[k24]/c.iloc[j]-1
        rows.append(dict(t=str(t),s_core=e['core_mom'],s_hl=e['hl_mom'],s_yoy=e['core_yoy'],react=r_react,cont4=r_cont4,cont24=r_cont24,gap_h=(idx[j]-t).total_seconds()/3600))
    if len(rows)<8: continue
    df=pd.DataFrame(rows)
    # baseline: same first-bar-after-hour measure on non-event weekdays, using the same clock hours as the events
    evdays={pd.Timestamp(r['t']).date() for r in rows}; hours={pd.Timestamp(r['t']).hour for r in rows}
    base=[]
    for day in sorted({x.date() for x in idx}):
        if day in evdays or pd.Timestamp(day).weekday()>4: continue
        for h in hours:
            t=pd.Timestamp(day).tz_localize('UTC')+pd.Timedelta(hours=h); j=idx.searchsorted(t)
            if 0<j<len(idx) and idx[j].date()==day: base.append(abs(c.iloc[j]/c.iloc[j-1]-1)); break
    b=np.median(base) if base else float('nan')
    def ic(x, y):
        return spearmanr(x,y).correlation
    n=len(df); cost=COST_BPS[s]/1e4
    res=dict(n=n,abs_react_med_bps=round(df.react.abs().median()*1e4,1),base_med_bps=round(b*1e4,1),vol_ratio=round(df.react.abs().median()/b,2) if b else None,
             ic_core_react=round(ic(df.s_core,df.react),2),ic_hl_react=round(ic(df.s_hl,df.react),2),ic_yoy_react=round(ic(df.s_yoy,df.react),2),
             ic_core_cont4=round(ic(df.s_core,df.cont4),2),ic_core_cont24=round(ic(df.s_core,df.cont24),2))
    # continuation trade: side = sign of measured reaction (follow the first-hour move), enter at close of bar j; net of cost
    for H in ('cont4','cont24'):
        pnl=np.sign(df.react)*df[H]-cost
        res[f'follow_{H}_mean_bps']=round(pnl.mean()*1e4,1); res[f'follow_{H}_t']=round(pnl.mean()/(pnl.std(ddof=1)/math.sqrt(n)),2); res[f'follow_{H}_hit']=round((pnl>0).mean(),2)
        fade=-np.sign(df.react)*df[H]-cost
        res[f'fade_{H}_mean_bps']=round(fade.mean()*1e4,1); res[f'fade_{H}_t']=round(fade.mean()/(fade.std(ddof=1)/math.sqrt(n)),2)
    # surprise-signed trade (needs a nonzero core surprise)
    nz=df[df.s_core!=0]
    for H in ('cont4','cont24'):
        p=np.sign(nz.s_core)*nz[H]
        res[f'surp_{H}_gross_bps_n']=(round(p.mean()*1e4,1),len(nz))
    res['first_bar_gap_h_med']=float(df.gap_h.median())
    out[s]=res
json.dump(out,open(sys.argv[2],'w'),indent=1)
cols=['n','abs_react_med_bps','base_med_bps','vol_ratio','ic_core_react','ic_hl_react','ic_yoy_react','ic_core_cont4','ic_core_cont24','follow_cont4_mean_bps','follow_cont4_t','fade_cont4_mean_bps','fade_cont4_t','follow_cont24_mean_bps','follow_cont24_t','fade_cont24_mean_bps','fade_cont24_t']
print(pd.DataFrame(out).T[cols].to_string())
