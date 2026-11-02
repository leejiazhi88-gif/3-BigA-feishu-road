"""Restore stock-specific manual font colors and keep every row at 29px."""
import json
from pathlib import Path
from business_composition import feishu_client as feishu
import refresh_all_20261102 as run

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'work/refresh-all-20261102'

def main():
    t=feishu.get_token()
    styles=json.loads((WORK/'preserved_font_styles.json').read_text())
    for i in range(0,len(styles),30):
        feishu.api(feishu.BASE+'/styles_batch_update',t,'PUT',{'data':styles[i:i+30]})
    result=feishu.api(feishu.BASE+'/dimension_range',t,'PUT',{
        'dimension':{'sheetId':run.worker.TARGET,'majorDimension':'ROWS','startIndex':1,'endIndex':500},
        'dimensionProperties':{'fixedSize':29}})
    after=feishu.read_range(t,run.worker.sheet_range(json.loads((WORK/'payload.json').read_text())['valueRange']['values'][0]))
    expected=json.loads((WORK/'payload.json').read_text())['valueRange']['values']
    width=len(expected[0]);errors=[]
    assert len(after)==len(expected)
    for r,(a,b) in enumerate(zip(expected,after),1):
        for c,(x,y) in enumerate(zip(a+['']*(width-len(a)),b+['']*(width-len(b))),1):
            if not run.worker.equivalent(x,y):errors.append((r,c))
    assert not errors,errors[:10]
    assert feishu.condition_formats(t,run.worker.TARGET)==json.loads((WORK/'cf_before.json').read_text())
    (WORK/'finalized.json').write_text(json.dumps({'height_px':29,'rows':500,'height_response':result,'manual_font_cells':sum(len(x['ranges']) for x in styles),'readback_errors':0,'conditional_formats_preserved':True},indent=2)+'\n')
    print('Final styles and 29px row height applied; complete values readback passed')

if __name__=='__main__':main()
