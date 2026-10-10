from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import json, time, threading, sys, os
import pandas as pd
import tushare as ts
SCRIPT_DIR=Path(__file__).resolve().parent
ROOT=Path(os.environ.get('BUSINESS_COMPOSITION_WORKDIR',SCRIPT_DIR.parents[1]/'work'/'business-composition-all-20261008'))
rows=json.loads((ROOT/'before.json').read_text())['values']
entries=[{'row':i,'code':r[3],'name':r[0]} for i,r in enumerate(rows[1:],2) if r and r[0]]
raw=ROOT/'raw';raw.mkdir(exist_ok=True)
lock=threading.Lock(); next_call=[0.0]
def pace():
 with lock:
  now=time.monotonic();wait=max(0,next_call[0]-now);next_call[0]=max(now,next_call[0])+.35
 if wait:time.sleep(wait)
def run(job):
 e,kind=job;p=raw/f"{e['code'].replace('.','_')}_{kind}.json"
 if p.exists():return {'code':e['code'],'kind':kind,'cached':True}
 pro=ts.pro_api()
 if kind in ('P','I'):
  api='fina_mainbz';params=dict(ts_code=e['code'],type=kind,start_date='20250630',end_date='20260630',fields='ts_code,end_date,bz_item,bz_code,bz_sales,bz_profit,bz_cost,curr_type,update_flag')
 else:
  api='income';params=dict(ts_code=e['code'],start_date='20250101',end_date='20261008',fields='ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,total_revenue,revenue,oper_cost,operate_profit,n_income,n_income_attr_p,int_income,int_exp,n_commis_income,comm_income,invest_income,prem_earned,prem_income,update_flag')
 for attempt in range(3):
  try:
   pace();df=getattr(pro,api)(**params)
   if len(df)>=100 and api=='fina_mainbz':
    pieces=[]
    for period in ['20250630','20251231','20260630']:
     pp={k:v for k,v in params.items() if k not in ['start_date','end_date']};pp['period']=period
     pace();piece=getattr(pro,api)(**pp);assert len(piece)<150,(e['code'],kind,period,'truncated');pieces.append(piece)
    df=pd.concat(pieces,ignore_index=True)
   if api=='income':
    assert len(df)<500
    df=df[df.end_date.astype(str).isin(['20250630','20251231','20260630'])]
   data=json.loads(df.to_json(orient='records',force_ascii=False))
   p.write_text(json.dumps({'api':api,'params':params,'fetched_at':time.strftime('%Y-%m-%dT%H:%M:%S%z'),'rows':data},ensure_ascii=False,indent=2,allow_nan=False))
   return {'code':e['code'],'kind':kind,'n':len(data)}
  except Exception as ex:
   if attempt==2:return {'code':e['code'],'kind':kind,'error':str(ex)}
   time.sleep(2*(attempt+1))
jobs=[(e,k) for e in entries for k in ('P','I','income')];done=[]
with ThreadPoolExecutor(max_workers=3) as pool:
 for n,f in enumerate(as_completed([pool.submit(run,x) for x in jobs]),1):
  result=f.result();done.append(result)
  if result.get('error') or n%20==0: print(json.dumps({'progress':n,'total':len(jobs),'latest':result},ensure_ascii=False),flush=True)
(ROOT/'fetch_log.json').write_text(json.dumps(done,ensure_ascii=False,indent=2))
print(json.dumps({'done':len(done),'errors':[x for x in done if x.get('error')]},ensure_ascii=False),flush=True)
