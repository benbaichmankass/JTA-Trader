import json,sys
from datetime import datetime
def load(p,name):
    out=[]
    for l in open(p):
        r=json.loads(l); r['leg']=name
        r['et']=datetime.fromisoformat(r['entry_time']); r['xt']=datetime.fromisoformat(r['exit_time'])
        out.append(r)
    return out
P=load('comms/strategy_evidence/runs/2026-10-07/trend_donchian_eth_prop__trades.jsonl','trend_donchian_eth_prop')
A=load('comms/strategy_evidence/runs/2026-10-12-1095d/trend_donchian_eth_4h__trades.jsonl','trend_donchian_eth_4h')
lo=datetime.fromisoformat('2025-10-07 00:00:00+00:00'); hi=datetime.fromisoformat('2026-10-07 19:13:55+00:00')
A=[r for r in A if lo<=r['et']<=hi]; P=[r for r in P if lo<=r['et']<=hi]
days=(hi-lo).total_seconds()/86400
def single_slot(trades):
    # live election: same-tick ties -> higher confidence, then name (no backtest term)
    trades=sorted(trades,key=lambda r:(r['et'],-r.get('confidence',0),r['leg']))
    taken=[];busy_until=None
    for r in trades:
        if busy_until is not None and r['et']<busy_until: continue
        taken.append(r); busy_until=r['xt']
    return taken
def stats(tr):
    n=len(tr); net=sum(r['net_r'] for r in tr)
    pos_days=sum((r['xt']-r['et']).total_seconds() for r in tr)/86400
    eq=0;pk=0;dd=0
    for r in sorted(tr,key=lambda r:r['xt']):
        eq+=r['net_r'];pk=max(pk,eq);dd=max(dd,pk-eq)
    return dict(n=n,net_r=round(net,4),net_r_per_capital_day=round(net/days,5),net_r_per_position_day=round(net/pos_days,4) if pos_days else None,days_in_position=round(pos_days,1),max_dd_r=round(dd,4),by_leg={l:sum(1 for r in tr if r['leg']==l) for l in sorted({r['leg'] for r in tr})})
a=single_slot(A); b=single_slot(P); c=single_slot(A+P)
res=dict(window=[lo.isoformat(),hi.isoformat()],window_days=round(days,2),
 raw_overlap_check=dict(eth_4h_ledger_n_in_window=len(A),eth_prop_ledger_n_in_window=len(P),eth_4h_self_overlaps_removed=len(A)-len(a),eth_prop_self_overlaps_removed=len(P)-len(b)),
 arm_a_eth_4h_alone=stats(a),arm_b_eth_prop_alone=stats(b),arm_c_both_one_slot=stats(c))
print(json.dumps(res,indent=1))
# priority variants: same-tick ties only
from collections import Counter
same=Counter(r['et'] for r in A)&Counter(r['et'] for r in P)
print('same_entry_tick_collisions',sum(same.values()))
def slot_pri(first):
    tr=sorted(A+P,key=lambda r:(r['et'],0 if r['leg']==first else 1))
    t=[];b=None
    for r in tr:
        if b is not None and r['et']<b: continue
        t.append(r);b=r['xt']
    return stats(t)
for f in ('trend_donchian_eth_prop','trend_donchian_eth_4h'): print(f,'first on ties:',slot_pri(f)['net_r'])
# opposite-direction blocked entries in arm c
