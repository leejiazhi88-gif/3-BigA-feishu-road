#!/usr/bin/env python3
"""Copy through Chrome's visible Feishu menu, then verify through the API.

Requires the user-authorized Chrome Apple Events JavaScript setting.
Uses no cookies, browser internals or undocumented Feishu endpoints.
"""
import argparse,json,subprocess,time
from business_composition import feishu_client as f

def js(tab_id,code,window_id):
    script='''on run argv
set targetId to (item 1 of argv) as integer
set windowId to (item 2 of argv) as integer
set codeText to item 3 of argv
tell application "Google Chrome"
 tell tab id targetId of window id windowId
  return execute javascript codeText
 end tell
end tell
end run'''
    return subprocess.run(['osascript','-e',script,str(tab_id),str(window_id),code],check=True,text=True,capture_output=True,timeout=30).stdout.strip()

def normalized(rules):
    items=[]
    for r in rules['data']['sheet_condition_formats']:
        c=dict(r['condition_format']);c.pop('cf_id',None)
        c['ranges']=[x.split('!',1)[-1] for x in c['ranges']];items.append(c)
    return sorted(items,key=lambda x:json.dumps(x,sort_keys=True))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tab-id',type=int,required=True);p.add_argument('--window-id',type=int,required=True)
    p.add_argument('--source-id',required=True);p.add_argument('--title',required=True)
    a=p.parse_args();token=f.get_token()
    def evaluate(code):return js(a.tab_id,code,a.window_id)
    def sheets():return f.api(f'sheets/v3/spreadsheets/{f.SPREADSHEET}/sheets/query',token)['data']['sheets']
    before=sheets();assert not any(s['title']==a.title for s in before),'Target already exists; inspect instead of recopying'
    source=next(s for s in before if s['sheet_id']==a.source_id)
    url=evaluate('location.href')
    assert url.startswith('https://my.feishu.cn/wiki/DlRmwrJOgiWIVhkWZtsc6h0Bnnd?') and 'sheet='+a.source_id in url,url
    title=json.dumps(source['title'],ensure_ascii=False)
    found=evaluate(f'JSON.stringify(Array.from(document.querySelectorAll("[data-e2e=tab-sheet-item]")).filter(e=>e.textContent==={title}).map(e=>e.textContent))')
    assert json.loads(found)==[source['title']],'Source tab not unambiguous in visible DOM'
    rules=f.condition_formats(token,a.source_id);assert normalized(rules),'Source has no conditional formats'
    evaluate(f'Array.from(document.querySelectorAll("[data-e2e=tab-sheet-item]")).find(e=>e.textContent==={title}).dispatchEvent(new MouseEvent("contextmenu",{{bubbles:true,button:2}}));"opened"')
    for _ in range(20):
        if evaluate('JSON.stringify(!!document.querySelector("[data-e2e=tab-sheet-copy]"))')=='true':break
        time.sleep(.25)
    else:raise RuntimeError('Copy menu did not appear')
    evaluate('document.querySelector("[data-e2e=tab-sheet-copy]").click();"copied"')
    ids={s['sheet_id'] for s in before}
    for _ in range(30):
        new=[s for s in sheets() if s['sheet_id'] not in ids]
        if new:break
        time.sleep(1)
    assert len(new)==1,'Cannot uniquely identify new sheet'
    dest=new[0]['sheet_id']
    assert normalized(f.condition_formats(token,dest))==normalized(rules),'Copied rules differ'
    meta=f.metadata(token,dest)
    assert meta['grid_properties']==source['grid_properties'],'Copied grid differs'
    # Full UI copy must preserve all original values before preparation/write.
    import refresh_all_20261012 as worker
    end=worker.column_name(source['grid_properties']['column_count'])+str(source['grid_properties']['row_count'])
    assert f.read_range(token,f'{a.source_id}!A1:{end}')==f.read_range(token,f'{dest}!A1:{end}'),'Copy values differ'
    f.api(f.BASE+'/sheets_batch_update',token,'POST',{'requests':[{'updateSheet':{'properties':{'sheetId':dest,'title':a.title}}}]})
    print(json.dumps({'sheet_id':dest,'title':a.title,'source':a.source_id,'copied_by':'visible UI','conditional_formats':len(normalized(rules)),'values_verified':True},ensure_ascii=False))
if __name__=='__main__':main()
