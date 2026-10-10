from pathlib import Path
from collections import defaultdict
import json,math,re,os
SCRIPT_DIR=Path(__file__).resolve().parent
ROOT=Path(os.environ.get('BUSINESS_COMPOSITION_WORKDIR',SCRIPT_DIR.parents[1]/'work'/'business-composition-all-20261008'))
SOURCE=json.loads((ROOT/'before.json').read_text())
PERIODS=['20250630','20251231','20260630']
ROWS=[r for r in SOURCE['values'][1:] if r and r[0]]
# The selected-sheet implementation listed its nine financial companies
# explicitly. The all-A-share sheet contains more banks, brokers and insurers,
# so extend the same operating-profit basis by Shenwan industry classification.
FIN={r[3] for r in ROWS if str(r[1]).strip() in {'银行','非银金融'}}
# Use business divisions instead of broad product totals where these are more informative.
REVENUE_KIND={'601138.SH':'I','600183.SH':'I','600905.SH':'I','301018.SZ':'I',**{c:'I' for c in FIN}}
PERIOD_KIND={('600905.SH','20260630'):'P',('600886.SH','20260630'):'I'}
# Coarser interim disclosure cannot replace the annual detailed business breakdown.
COARSE={'301308.SZ','688120.SH','688766.SH','688110.SH','688123.SH','601138.SH','300408.SZ','603386.SH','600900.SH','688385.SH','601899.SH','603501.SH','688808.SH','301018.SZ'}
TOTAL={'产品','行业','合计','总计','主营业务合计'}
ALIAS={
 '688981.SH':{'集成电路晶圆制造代工':'晶圆代工','集成电路晶圆代工':'晶圆代工','其他主营业务':'其他及调整'},
 '300750.SZ':{'电池矿产资源':'材料、回收及矿产','电池材料及回收':'材料、回收及矿产','电池材料及回收、矿产资源':'材料、回收及矿产'},
 '300394.SZ':{'光有源器件':'有源光器件','光无源器件':'无源光器件'},
 '688008.SH':{'津逮服务器平台':'津逮产品'},
 '601600.SH':{'营销板块':'营销','能源板块':'能源','氧化铝板块':'氧化铝','原铝板块':'原铝'},
 '300033.SZ':{'增值电信业务':'增值电信服务','广告及互联网推广服务':'广告及互联网业务推广服务','基金销售及其他业务':'基金销售及其他交易手续费等其他业务'},
 '601318.SH':{'其他业务及合并抵消':'其他业务及合并抵销'},
 '601919.SH':{'公司内各业务部间相互抵销':'分部间抵销'},
 '600028.SH':{'本部及其他':'其他'},
 '300476.SZ':{'主营业务':'PCB制造'},'603228.SH':{'主营业务':'印制电路板'},
 '601628.SH':{'健康险业务':'健康险业务与意外险业务','意外险业务':'健康险业务与意外险业务'},
}

def load(code,kind):return json.loads((ROOT/'raw'/f"{code.replace('.','_')}_{kind}.json").read_text())['rows']
def income(code,p):
 rs=[r for r in load(code,'income') if r['end_date']==p and str(r['report_type']) in ['1','4','5'] and max(str(r.get('ann_date')or''),str(r.get('f_ann_date')or''))<='20261008']
 # Prefer the most recently published consolidated report, not parent or single-quarter reports.
 rs.sort(key=lambda r:(r.get('f_ann_date')or r.get('ann_date')or'',str(r.get('update_flag')or'')),reverse=True)
 return rs[0] if rs else {}
def num(v):return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
def val(r,metric):
 v=r.get('bz_sales' if metric=='revenue' else 'bz_profit')
 if metric=='profit' and not num(v) and num(r.get('bz_sales')) and num(r.get('bz_cost')):v=r['bz_sales']-r['bz_cost']
 return v if num(v) else None

def raw_view(code,p,kind,metric):
 rs=[dict(r) for r in load(code,kind) if r['end_date']==p]
 # Deduplicate the same item and currency using the update marker.
 unique={}
 for r in sorted(rs,key=lambda r:str(r.get('update_flag')or'')):
  unique[(r['bz_item'],r.get('curr_type'))]=r
 rs=list(unique.values());currencies={r.get('curr_type') for r in rs}
 assert len(currencies)<=1,(code,p,kind,currencies)
 total_rows=[r for r in rs if r['bz_item'] in TOTAL]
 denominator=next((val(r,metric) for r in total_rows if val(r,metric) is not None),None)
 detail={r['bz_item']:r for r in rs if r['bz_item'] not in TOTAL}
 # These companies consolidate a finance subsidiary. Describe operating-business
 # revenue and gross profit consistently, excluding separate interest income.
 inc=income(code,p)
 if code in {'600519.SH','000333.SZ','000651.SZ'}:
  detail.pop('合计特别调整',None)
  denominator=inc.get('revenue') if metric=='revenue' else inc['revenue']-inc['oper_cost']
  if code=='600519.SH' and p=='20260630' and '其他业务' in detail:
   interest=inc['total_revenue']-inc['revenue']
   detail['其他业务']['bz_sales']-=interest
   if num(detail['其他业务'].get('bz_profit')):detail['其他业务']['bz_profit']-=interest
 if code=='688808.SH' and p=='20251231':detail.pop('主营业务',None)
 if code=='002230.SZ' and p=='20250630':
  detail={k.replace('智慧城市-','智慧城市：').replace('开放平台及消费者业务-','开放平台及消费者业务：'):r for k,r in detail.items()}
 if code=='002236.SZ' and p=='20260630' and kind=='P':
  detail.pop('智慧物联产品及方案：软件业务',None)
  sales=inc['revenue']-sum(r['bz_sales'] for r in detail.values())
  cost=inc['oper_cost']-sum(r['bz_cost'] for r in detail.values())
  detail['智慧物联产品及方案（差额）']={'bz_sales':sales,'bz_profit':sales-cost,'bz_cost':cost}

 # A few feeds expose a subtotal without hierarchy punctuation.
 if code=='688521.SH' and p=='20260630' and kind=='P':
  for k in ['芯片定制解决方案服务','半导体IP授权服务']:detail.pop(k,None)
  # In this feed "其他" repeats "其他业务".
  if '其他' in detail and '其他业务' in detail and val(detail['其他'],metric)==val(detail['其他业务'],metric):detail.pop('其他')
 # Keep either a parent or its children, never both.
 for parent in sorted(list(detail),key=len):
  if parent not in detail:continue
  children=[k for k in detail if k.startswith(parent+'：')]
  if not children:continue
  leaves=[k for k in children if not any(x.startswith(k+'：') for x in children)]
  pv=val(detail[parent],metric);vs=[val(detail[k],metric) for k in leaves]
  if pv is not None and all(v is not None for v in vs) and math.isclose(sum(vs),pv,rel_tol=1e-5,abs_tol=10000):
   detail.pop(parent)
   for k in children:
    if k not in leaves:detail.pop(k,None)
  else:
   for k in children:detail.pop(k,None)
 # Some reports repeat the same leaf once with a division prefix and once
 # without it, for example "基石业务：高端铝箔" and "高端铝箔".
 for name in list(detail):
  if '：' not in name or name not in detail:continue
  leaf=name.rsplit('：',1)[1]
  if leaf in detail and val(detail[name],metric)==val(detail[leaf],metric):
   detail.pop(leaf)
 items={k:val(r,metric) for k,r in detail.items()}
 known={k:v for k,v in items.items() if v is not None}
 missing=[k for k,v in items.items() if v is None]
 inc=income(code,p)
 if denominator is None:
  if metric=='revenue':denominator=inc.get('total_revenue') or inc.get('revenue')
  elif code in FIN:denominator=inc.get('operate_profit')
  elif num(inc.get('revenue')) and num(inc.get('oper_cost')):denominator=inc['revenue']-inc['oper_cost']
 if not num(denominator) or abs(denominator)<1e-8:return None
 if not known:return None
 # Never mix USD with CNY totals from a separate income statement.
 if currencies and currencies!={'CNY'} and not total_rows:
  if missing:return None
  denominator=sum(known.values())
 # Remove an unmarked subtotal when the remaining disclosed leaves reconcile
 # exactly to the denominator. This catches feeds that publish "主营业务" next
 # to all of its children without hierarchy punctuation.
 tolerance=max(10000,abs(denominator)*1e-5)
 for name,value in sorted(list(known.items()),key=lambda x:abs(x[1]),reverse=True):
  if abs((sum(known.values())-value)-denominator)<=tolerance:
   known.pop(name)
   break
 # If data are only a tiny unreconciled slice, leave them for manual review.
 residual=denominator-sum(known.values())
 issues=[]
 if abs(residual)>max(10000,abs(denominator)*1e-5):
  label='未单列业务合计（差额）' if missing else '未拆分及合并调整（差额）'
  known[label]=residual
  if abs(residual/denominator)>.02:issues.append(f'residual={residual/denominator:.1%}; missing={missing}')
 return {'kind':kind,'period':p,'metric':metric,'total':denominator,'items':known,'missing':missing,'issues':issues,'currency':next(iter(currencies),'CNY'),'profit_basis':'营业利润' if code in FIN else '毛利'}

def strength(v):
 if not v:return -1
 # Prefer a view with meaningful breakdown and limited aggregate residual.
 normal=[(k,x) for k,x in v['items'].items() if not any(w in k for w in ['差额','抵销','抵消','调整'])]
 covered=sum(abs(x) for k,x in normal)/max(abs(v['total']),1)
 residual=sum(abs(x) for k,x in v['items'].items() if '差额' in k)/max(abs(v['total']),1)
 return min(len(normal),7)+min(covered,1)*3-min(residual,3)*5

def choose(code,p,metric):
 kind=PERIOD_KIND.get((code,p),REVENUE_KIND.get(code,'P'))
 preferred=raw_view(code,p,kind,metric)
 if metric=='profit':
  alternate=raw_view(code,p,'I' if kind=='P' else 'P',metric)
  if code not in {'002236.SZ','002230.SZ'} and strength(alternate)>strength(preferred)+1:preferred=alternate
  # An industry total does not provide a business profit split for telecoms.
  if code in {'600941.SH','601728.SH','600050.SH'} or (code=='688235.SH' and p=='20260630'):return None
 residual=sum(abs(x) for k,x in preferred['items'].items() if '差额' in k)/max(abs(preferred['total']),1) if preferred else 0
 if preferred and residual>.5 and not preferred['missing']:return None
 return preferred

def canon(code,v):
 if not v:return None
 out=defaultdict(float)
 for k,x in v['items'].items():
  name=ALIAS.get(code,{}).get(k,k)
  if name in {'其他','其他业务','其他业务收入','合计特别调整','技术服务及其他收入','技术服务收入及其他收入','未拆分及合并调整（差额）'}:name='其他及调整'
  # Keep unallocated profits visibly unallocated, rather than assigning them to known products.
  out[name]+=x
 return dict(out)

def format_parts(items,total,max_parts=7):
 if abs(total)<1e-8:return '合计接近零，不适合计算占比'
 ordered=sorted(items.items(),key=lambda x:abs(x[1]),reverse=True)
 main=[(k,v) for k,v in ordered if abs(v/total)>=.0005]
 tiny=[(k,v) for k,v in ordered if abs(v/total)<.0005]
 if len(main)>max_parts:
  rest=main[max_parts-1:]+tiny;main=main[:max_parts-1];tiny=rest
 if tiny and abs(sum(v for k,v in tiny)/total)>=.0005:
  main.append(('其余项目合计',sum(v for k,v in tiny)))
 return '；'.join(f'{k} {v/total:.1%}' for k,v in main)

def actual_text(code,v,metric):
 if v is None:
  return '2025实际｜未取得可核验的分业务利润，无法可靠拆分。来源：2025年报主营构成。' if metric=='profit' else '2025实际｜未取得可核验的分业务收入构成。'
 basis='收入' if metric=='revenue' else v['profit_basis']
 note='（非净利润）' if metric=='profit' else ''
 text=f"2025实际·{basis}构成{note}：{format_parts(v['items'],v['total'])}。"
 if v['total']<=0:text+=f"合计{v['total']/1e8:.2f}亿元；负合计占比仅表示损益贡献。"
 if any(x<0 and abs(x/v['total'])>=.0005 for x in v['items'].values()):text+='负项为亏损或合并抵销。'
 if code in {'600519.SH','000333.SZ','000651.SZ'}:text+='营业业务口径，不含财务子公司利息收入。'
 return text

def strip_default_source(text):
 return text.replace('来源：2025年报（Tushare）。','').replace('来源：2025年报主营构成。','')

def forecast(code,metric,vs):
 annual=vs['20251231'][metric];half=vs['20260630'][metric]
 if not annual and not half:return {'text':'2026预测｜缺少可核验的分业务利润基础，暂无法可靠预测拆分。','method':'unavailable','items':None}
 if code in COARSE or (not half) or (code=='600036.SH'):
  selected=annual or half;method='2025结构基准' if annual else '2026半年结构基准'
  assumption='假设全年细分占比维持2025年；未取得2026半年可比细分，低置信基准' if annual else '假设下半年占比维持2026上半年'
  items=selected['items'];total=selected['total']
 else:
  selected=half;items=half['items'];total=half['total'];method='2026半年结构基准';assumption='假设下半年占比维持2026上半年'
  # Comparable revenue seasonality, using only strictly positive prior bases.
  rv={p:canon(code,vs[p]['revenue']) for p in PERIODS}
  if all(rv.values()) and len({tuple(sorted(x)) for x in rv.values()})==1 and code not in FIN and code not in {'002475.SZ','300124.SZ','300418.SZ','603259.SH'}:
   ok=True;pred={}
   for name,h26 in rv['20260630'].items():
    h25=rv['20250630'][name];fy=rv['20251231'][name]
    if h25<=0 or fy<h25*.999 or h26<0 or h26/h25>4:ok=False;break
    pred[name]=fy*h26/h25
   if ok and sum(pred.values())>0:
    if metric=='revenue':
     items=pred;total=sum(pred.values());method='半年同比延续';assumption='按各业务上半年收入同比延续至全年，保留2025季节性'
    else:
     profits=canon(code,half)
     if profits and set(profits)==set(pred) and all(0<=profits[k]<=rv['20260630'][k] and rv['20260630'][k]>0 for k in pred):
      items={k:pred[k]*profits[k]/rv['20260630'][k] for k in pred};total=sum(items.values());method='收入外推×半年毛利率';assumption='收入按半年同比外推，毛利率维持2026上半年'
 basis='收入' if metric=='revenue' else selected['profit_basis']
 if selected.get('issues'):assumption+='；含未单列业务差额'
 note='（非净利润）' if metric=='profit' else ''
 text=f"2026预测·{basis}构成{note}：{format_parts(items,total)}。模型：{assumption}；非机构分部预测。"
 if code in {'600519.SH','000333.SZ','000651.SZ'}:text+='营业业务口径，不含财务子公司利息收入。'
 if any(x<0 and abs(x/total)>=.0005 for x in items.values()):text+='负项保留亏损/抵销。'
 return {'text':text,'method':method,'items':items,'total':total,'basis':basis,'assumption':assumption}

def main():
 selected_path=ROOT/'selected_prepared.json'
 if not selected_path.exists():selected_path=SCRIPT_DIR.parents[1]/'config'/'selected_business_composition_20261008.json'
 selected={x['code']:x for x in json.loads(selected_path.read_text())}
 result=[];audit=[]
 for rn,r in enumerate(SOURCE['values'][1:],2):
  if not r or not r[0]:continue
  code=r[3];vs={p:{m:choose(code,p,m) for m in ['revenue','profit']} for p in PERIODS}
  texts=[actual_text(code,vs['20251231'][m],m) for m in ['revenue','profit']]
  preds=[forecast(code,m,vs) for m in ['revenue','profit']];texts += [x['text'] for x in preds]
  # Preserve every reviewed cell from the 3.2 selected-sheet project exactly.
  if code in selected:texts=selected[code]['values']
  texts=[strip_default_source(text) for text in texts]
  result.append({'row':rn,'name':r[0],'code':code,'values':texts,'actual':vs['20251231'],'forecasts':preds})
  audit.append({'row':rn,'name':r[0],'code':code,'views':vs,'forecast_methods':[x['method'] for x in preds]})
 (ROOT/'prepared.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
 (ROOT/'audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2,allow_nan=False))
 (ROOT/'preview.md').write_text('\n\n'.join(f"{x['row']} {x['name']} {x['code']}\n"+'\n'.join(x['values']) for x in result))
 print(json.dumps({'rows':len(result),'methods':{m:sum(m in a['forecast_methods'] for a in audit) for m in sorted({m for a in audit for m in a['forecast_methods']})},'issues':[(a['row'],a['name'],p,m,v['issues']) for a in audit for p in PERIODS for m,v in a['views'][p].items() if v and v['issues']]},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
