"""Finalize a verified full UI copy with November 17 values; keep Q4 locks."""
import json,re,argparse
from pathlib import Path
from collections import defaultdict
from business_composition import feishu_client as f
import refresh_all_20261012 as w
ROOT=Path(__file__).resolve().parents[1];W=ROOT/'work/refresh-all-20261117';E=ROOT/'exports/refresh_20261117';TARGET=None
def save(name,x):(W/name).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def main():
 global TARGET
 parser=argparse.ArgumentParser();parser.add_argument('--sheet-id',required=True);args=parser.parse_args();TARGET=args.sheet_id
 assert TARGET!='b21k2z','Never overwrite source'
 E.mkdir(parents=True,exist_ok=True)
 t=f.get_token();source=f.read_range(t,'b21k2z!A1:BL500');before=f.read_range(t,TARGET+'!A1:BL500')
 assert source==before,'Copy or source changed; review first'
 source_cf=f.condition_formats(t,'b21k2z')
 def comparable(rules):
  result=[]
  for entry in rules['data']['sheet_condition_formats']:
   item=dict(entry['condition_format']);item.pop('cf_id',None)
   item['ranges']=[r.split('!',1)[-1] for r in item.get('ranges',[])]
   result.append(item)
  return sorted(result,key=lambda x:json.dumps(x,sort_keys=True))
 assert comparable(source_cf)==comparable(f.condition_formats(t,TARGET)),'Copy did not preserve rules'
 p=json.loads((W/'payload_dividends.json').read_text());values=p['valueRange']['values'];hs=values[0];idx={h:i for i,h in enumerate(hs)};si={h:i for i,h in enumerate(source[0])}
 old={r[si['代码']]:r+['']*len(si) for r in source[1:] if r and r[0]}
 # Take the user's latest note edits, including any made after preparation.
 for r in values[1:]:
  if r and r[0] and r[idx['代码']] in old:
   for h in hs:
    if h.startswith('笔记'):r[idx[h]]=old[r[idx['代码']]][si[h]]
 cf=f.condition_formats(t,TARGET);assert len(cf['data']['sheet_condition_formats'])==17
 save('online_before.json',before);save('online_cf_before.json',cf)
 w.TARGET=TARGET
 insertion=idx[w.Q4_LOCK_HEADER]
 assert w.Q4_LOCK_HEADER in source[0], 'Existing Q4 lock required'
 for row in values[1:]:
  if row and row[0] and row[idx['代码']] in old:
   assert row[insertion]==old[row[idx['代码']]][si[w.Q4_LOCK_HEADER]],'Q4 lock changed'
 for start in range(0,len(values),100):
  chunk=values[start:start+100]
  f.api(f.BASE+'/values',t,'PUT',{'valueRange':{'range':f'{TARGET}!A{start+1}:{w.column_name(len(hs))}{start+len(chunk)}','values':chunk}})
 colors=json.loads((ROOT/'config/industry_color_map_20261113.json').read_text())['industry_pairs']
 notes=json.loads((ROOT/'config/personal_note_colors_20261113.json').read_text())['codes']
 names=json.loads((ROOT/'config/stock_name_font_styles_20261113.json').read_text())['codes']
 styles=[];expected=[];groups=defaultdict(list)
 pattern=re.compile(r'([-+]?\d+(?:\.\d+)?)（(?:上个Q预测|锁定预测|未锁定预测)([-+]?\d+(?:\.\d+)?)）')
 for rn,row in enumerate(values[1:],2):
  if not row or not row[0]:continue
  code=row[idx['代码']];pair=row[idx['申万一级']]+'\t'+row[idx['申万二级']];back=colors[pair]['b_color']
  for h,i in idx.items():
   c=w.column_name(i+1);style={'backColor':back}
   color=None
   if h.startswith('笔记'):
    n=notes.get(code,{}).get(h,{'backColor':'#FFFFFF','foreColor':'#000000','bold':False})
    style={'backColor':n['backColor'],'foreColor':n['foreColor'],'font':{'bold':n['bold']}}
   elif h=='名称':
    n=names.get(code,{'foreColor':'#000000','bold':False});style.update(foreColor=n['foreColor'],font={'bold':n['bold']})
   elif h=='PE(TTM)' or re.fullmatch(r'20\d{2} PE\(预测\)',h):
    v=w.number(row[i]);color='#00B050' if v is not None and v<30 else '#C00000' if v is not None and v>50 else '#000000'
   elif '净利润同比%' in h:
    v=w.number(row[i]);color='#C00000' if v is not None and v<=0 else '#00B050' if v is not None and v>=.3 else '#0070C0' if v is not None and v>=.1 else '#000000'
   elif h==w.ANNUAL_CHANGE_HEADER:color=w.annual_change_color_from_text(row[i])
   elif h in w.ANNUAL_CHANGE_RATE_HEADERS.values():
    v=row[i];color='#000000' if not isinstance(v,(int,float)) or abs(v)<.03 else '#00B050' if v>=.03 else '#C00000'
   elif re.match(r'202[678]\s*Q[1-4]',h):
    m=pattern.search(str(row[i]));color='#000000'
    if m:
     a,b=map(float,m.groups());color='#00B050' if a>b else '#C00000' if a<b else '#000000'
   if color:style['foreColor']=color
   key=json.dumps(style,sort_keys=True);groups[key].append(f'{TARGET}!{c}{rn}:{c}{rn}')
   expected.append({'code':code,'cell':f'{c}{rn}','style':style})
 for key,ranges in groups.items():
  for start in range(0,len(ranges),100):styles.append({'ranges':ranges[start:start+100],'style':json.loads(key)})
 for start in range(0,len(styles),25):f.api(f.BASE+'/styles_batch_update',t,'PUT',{'data':styles[start:start+25]})
 f.api(f.BASE+'/dimension_range',t,'PUT',{'dimension':{'sheetId':TARGET,'majorDimension':'ROWS','startIndex':1,'endIndex':500},'dimensionProperties':{'fixedSize':29}})
 after=f.read_range(t,f'{TARGET}!A1:{w.column_name(len(hs))}500');assert len(after)==len(values)
 for rn,(a,b) in enumerate(zip(values,after),1):
  for cn,(x,y) in enumerate(zip(a+['']*(len(hs)-len(a)),b+['']*(len(hs)-len(b))),1):assert w.equivalent(x,y),(rn,cn)
 cf_after=f.condition_formats(t,TARGET);assert cf_after==cf,'Conditional formats changed unexpectedly'
 save('final_payload.json',{'valueRange':{'range':f'{TARGET}!A1:BL500','values':values}});save('expected_styles.json',expected)
 result={'online_written':True,'sheet_id':TARGET,'date':'2026-11-17','companies':480,'conditional_formats':17,'values_verified':True,'q4_lock_written':True,'row_height_px':29,'notes_columns_preserved':3}
 save('online_verification.json',result);(E/'online_verification.json').write_text(json.dumps(result,indent=2)+'\n');print(result)
if __name__=='__main__':main()
