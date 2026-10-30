"""Check public Eastmoney broker reports for missing/stale or anomalous forecasts.

Only explicit three-year attributable-net-profit sentences with year labels and
units are parsed. EPS, revenue, search snippets, and user posts are not estimates.
"""
import concurrent.futures
from datetime import datetime, timedelta
import html
import json
from pathlib import Path
import re
import requests

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'work/forecast-quality-20261030'
DEST = WORK / 'external'


def parse(text):
    text=re.sub(r'\s+', '',text)
    # Explicitly forbid unlabelled values and prior-forecast parentheticals.
    pattern=(r'(?:预计|预测)[^。；]{0,100}?(?:2026[-—~～至/、]2028|2026[/、]2027[/、]2028|26[-—~～至/]28)年'
             r'[^。；]{0,70}?归母净利润(?:分别)?(?:为|达到|有望达到|约为|实现)?'
             r'([-+]?\d+(?:\.\d+)?)[/、，]([-+]?\d+(?:\.\d+)?)[/、，]([-+]?\d+(?:\.\d+)?)'
             r'(亿元|百万元)')
    matches=list(re.finditer(pattern,text))
    values=[]
    for m in matches:
        unit=1 if m[4]=='亿元' else .01
        values.append(([float(m[i])*unit for i in (1,2,3)],m[0]))
    if not values or any(v[0]!=values[0][0] for v in values):return None
    return values[0]


def fetch(item, asof='20261029', dest=DEST):
    dest.mkdir(parents=True,exist_ok=True)
    begin=(datetime.strptime(asof,'%Y%m%d')-timedelta(days=90)).strftime('%Y%m%d')
    code=item['code'];path=dest/(code.replace('.','_')+'.json')
    if path.exists():return json.loads(path.read_text())
    out=dict(item,checked_at=datetime.now().isoformat(),reports=[],records=[],status='ok')
    try:
        entries=[]
        for page in range(1,11):
            res=requests.get('https://reportapi.eastmoney.com/report/list',params={
                'code':code[:6],'pageSize':100,'pageNo':page,'beginTime':datetime.strptime(begin,'%Y%m%d').strftime('%Y-%m-%d'),
                'endTime':datetime.strptime(asof,'%Y%m%d').strftime('%Y-%m-%d'),'qType':0},timeout=25)
            res.raise_for_status();obj=res.json()
            if 'data' not in obj:raise ValueError('No data key')
            entries.extend(obj['data'])
            if page>=int(obj.get('TotalPage',1)):break
        else:raise ValueError('Pagination incomplete')
        seen=set()
        for r in sorted(entries,key=lambda x:x['publishDate'],reverse=True):
            if r.get('stockCode')!=code[:6]:continue
            date=r['publishDate'][:10].replace('-','')
            if not begin<=date<=asof:continue
            org=r['orgSName']
            if org in seen:continue
            seen.add(org)
            url='https://data.eastmoney.com/report/info/'+r['infoCode']+'.html'
            page=requests.get(url,timeout=25);page.raise_for_status()
            text=html.unescape(re.sub('<[^>]+>',' ',page.text))
            prediction=parse(text)
            evidence={'date':date,'org':org,'title':r['title'],'url':url,
                      'parsed':bool(prediction),'excerpt':prediction[1] if prediction else ''}
            out['reports'].append(evidence)
            if prediction:
                for year,value in zip((2026,2027,2028),prediction[0]):
                    out['records'].append({'ts_code':code,'report_date':date,'org_name':org,
                        'quarter':f'{year}Q4','np':value*10000,'report_title':r['title'],
                        'source':'东方财富研报原文','url':url})
        out['list_rows']=len(entries)
    except Exception as exc:
        out['status']='failed';out['error']=str(exc)[:300]
    path.write_text(json.dumps(out,ensure_ascii=False,indent=2))
    return out


if __name__=='__main__':
    items=json.loads((WORK/'external_candidates.json').read_text());result=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for r in pool.map(fetch,items):
            result.append(r)
            if len(result)%10==0 or len(result)==len(items):
                print(f'external check {len(result)}/{len(items)}',flush=True)
    (WORK/'external_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print('reports',sum(len(x['reports']) for x in result),'parsed',sum(len(x['records'])//3 for x in result),
          'failed',sum(x['status']!='ok' for x in result))
