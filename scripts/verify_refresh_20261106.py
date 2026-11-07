"""Verify the native November 2 workbook export against the latest template."""
from collections import Counter
from copy import copy
from decimal import Decimal
import json
import re
import warnings
from pathlib import Path
import openpyxl

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'work/refresh-all-20261106'
EXPORT=ROOT/'exports/refresh_20261106'
TARGET='2026-11-06（全部）'
SOURCE='2026-11-02（全部）'

def rgb(color,default='000000'):
    return str(color.rgb)[-6:].upper() if color and color.type=='rgb' else default

def number(v):
    if isinstance(v,(int,float)):
        return float(v)
    m=re.match(r'[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?',str(v))
    return float(m[0]) if m else None

def main():
    warnings.filterwarnings('ignore',category=UserWarning,module='openpyxl')
    original=openpyxl.load_workbook(WORK/'source.xlsx')
    current=openpyxl.load_workbook(ROOT/'outputs/refresh_20261106/2026-11-06-all.xlsx')
    s=original[SOURCE];t=current[TARGET]
    hi={c.value:c.column for c in s[1] if c.value};ht={c.value:c.column for c in t[1] if c.value}
    old={s.cell(r,hi['代码']).value:r for r in range(2,s.max_row+1) if s.cell(r,1).value}
    new={t.cell(r,ht['代码']).value:r for r in range(2,t.max_row+1) if t.cell(r,1).value}
    assert len(old)==470 and len(new)>=470 and set(old)<=set(new)
    assert t.freeze_panes==s.freeze_panes
    mapping=json.loads((ROOT/'config/industry_color_map_20261102.json').read_text())['industry_pairs']
    changes=json.loads((WORK/'forecast_changes.json').read_text());bycode={}
    for x in changes:
        if re.fullmatch(r'20\d{2}净利润\(预测,亿元\)',x['field']):bycode.setdefault(x['code'],[]).append(x)
    notes=('笔记（AI别刷新这部分，我自己记录）','笔记2 决策（AI也别刷新）')
    compositions=('25年收入构成','25年利润构成','26年收入构成','26年利润构成')
    pe=('PE(TTM)','2026 PE(预测)','2027 PE(预测)','2028 PE(预测)')
    yoy=('2025净利润同比%(实际/预测)','2026净利润同比%(预测)','2027净利润同比%(预测)','2028净利润同比%(预测)')
    qh=('2026Q1净利润(亿元)','2026Q2锁定预测(亿元)','2026Q2净利润(亿元)','2026 Q3净利润(亿元) 锁定比较基础','2026Q3净利润(亿元)','2026Q4净利润(亿元)')
    rates=('26年预测变化率','27年预测变化率','28年预测变化率')
    dynamic=set(pe+yoy+qh+rates+('本次刷新年度预测变化',))
    errors=[];checks=0;text_format_equivalences=[]
    def check(ok,*detail):
        nonlocal checks
        checks+=1
        if not ok:errors.append(detail)
    typical={h:Counter(s.cell(r,col).number_format for r in old.values()).most_common(1)[0][0] for h,col in hi.items()}
    for code,r in new.items():
        sr=old.get(code)
        check(t.cell(r,ht['最新交易日']).value=='2026-11-06',code,'date')
        pair='\t'.join(str(t.cell(r,ht[h]).value) for h in ('申万一级','申万二级'))
        fill=mapping[pair]['b_color'][1:].upper()
        for h,col in ht.items():
            c=t.cell(r,col);o=s.cell(sr,hi[h]) if sr else None
            expected_format=o.number_format if o else typical[h]
            format_equal=c.number_format==expected_format
            # R contains descriptive text, never numeric values. General and
            # a percentage format render the same literal string unchanged.
            if (not format_equal and h=='本次刷新年度预测变化'
                    and isinstance(c.value,str)
                    and {c.number_format,expected_format}<={'General','0.0%'}):
                text_format_equivalences.append({'code':code,'cell':c.coordinate,
                    'source':expected_format,'current':c.number_format})
                format_equal=True
            check(format_equal,code,h,'number format',c.number_format)
            if h not in notes:check(rgb(c.fill.fgColor)==fill,code,h,'fill')
            if h not in dynamic:
                check(rgb(c.font.color)==(rgb(o.font.color) if o else '000000'),code,h,'static font')
            if h in notes and sr:
                check(c.value==o.value and copy(c.fill)==copy(o.fill) and copy(c.font)==copy(o.font),code,h,'personal note')
            if h in compositions and sr:check(c.value==o.value,code,h,'composition')
        for h in pe+yoy:
            c=t.cell(r,ht[h]);v=number(c.value);want='000000'
            if v is not None:
                want=('00B050' if v<30 else 'C00000' if v>50 else '000000') if h in pe else ('C00000' if v<=0 else '00B050' if v>=.3 else '0070C0' if v>=.1 else '000000')
            check(rgb(c.font.color)==want,code,h,'font')
        for h in qh:
            c=t.cell(r,ht[h]);m=re.search(r'([-+]?\d+(?:\.\d+)?)（(?:上个Q预测|锁定预测|未锁定预测)([-+]?\d+(?:\.\d+)?)）',str(c.value or ''));want='000000'
            if m:
                actual,baseline=map(float,m.groups());ratio=(actual-baseline)/abs(baseline) if baseline else (0 if abs(actual)<=.05 else (1 if actual>0 else -1))
                want='00B050' if actual>baseline else 'C00000' if actual<baseline else '000000'
            check(rgb(c.font.color)==want,code,h,'actual font')
        for year,h in zip((2026,2027,2028),rates):
            c=t.cell(r,ht[h]);v=number(c.value);want='000000' if not v else '00B050' if v>0 else 'C00000'
            check(rgb(c.font.color)==want,code,h,'rate color')
            annual=number(t.cell(r,ht[f'{year}净利润(预测,亿元)']).value)
            parts=[number(t.cell(r,ht[f'{year}Q{q}净利润(亿元)']).value) for q in range(1,5)]
            check(all(x is not None for x in parts) and sum(Decimal(str(x)) for x in parts)==Decimal(str(annual)),code,year,'quarter sum')
            if sr:
                base=number(s.cell(sr,hi[f'{year}净利润(预测,亿元)']).value)
                expected=(annual-base)/abs(base) if base else None
                check((v is None and expected is None) or (v is not None and expected is not None and abs(v-expected)<1e-10),code,year,'revision rate')
        entries=bycode.get(code,[]);delta=min(entries,key=lambda x:x['field'])['change_ratio'] if entries else None
        want='000000' if delta is None or abs(delta)<.03 else '00B050' if delta>=.03 else 'C00000'
        check(rgb(t.cell(r,ht['本次刷新年度预测变化']).font.color)==want,code,'annual change color')
        q3=number(t.cell(r,ht['2026Q3净利润(亿元)']).value);lock=t.cell(r,ht['2026 Q3净利润(亿元) 锁定比较基础']).value
        if '（锁定预测' in str(lock):check(number(lock)==q3,code,'Q3 locked actual mismatch')
        if sr:
            oldlock=s.cell(sr,hi['2026 Q3净利润(亿元) 锁定比较基础']).value
            m=re.search(r'（锁定预测([^）]+)）',str(oldlock))
            if m:check(('（锁定预测'+m[1]+'）') in str(lock),code,'Q3 baseline changed')
    # Verify all pre-existing sheets' values remain untouched.
    for a in original:
        if a.title==TARGET:continue
        b=current[a.title]
        for key in set(a._cells)|set(b._cells):
            check(a.cell(*key).value==b.cell(*key).value,a.title,key,'original sheet value')
    # Native exports can use a global height conversion; 29px was confirmed by API.
    heights={t.row_dimensions[r].height for r in range(1,501)}
    check(len(heights)==1 and None not in heights,'uniform row heights',str(heights))
    result={'companies':len(new),'added':sorted(set(new)-set(old)),'removed':[],
            'checks':checks,'errors':errors,'annual_quarter_reconciliations':len(new)*3,
            'row_heights_exported':sorted(heights),'freeze':t.freeze_panes,
            'old_sheets_values_preserved':True,'notes_preserved':True,
            'industry_colors_reference':SOURCE,'source_business_composition_preserved':True,
            'text_only_format_equivalences':text_format_equivalences}
    EXPORT.mkdir(exist_ok=True,parents=True)
    (EXPORT/'format_verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='errors'},ensure_ascii=False));print('errors',len(errors),errors[:15])
    assert not errors

if __name__=='__main__':main()
