"""Read-only native export verification after the full-copy refresh."""
import json,warnings,sys
from pathlib import Path
from copy import copy
from collections import Counter
import openpyxl
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from forecast_quality_sheet import validate_row
W=ROOT/'work/refresh-all-20261113';E=ROOT/'exports/refresh_20261113'
def rgb(c):return '#'+str(c.rgb)[-6:].upper() if c and c.type=='rgb' else '#000000'
def main():
 warnings.filterwarnings('ignore')
 original=openpyxl.load_workbook(W/'source.xlsx');current=openpyxl.load_workbook(ROOT/'outputs/refresh_20261113/2026-11-13-all.xlsx');t=current['2026-11-13'];s=original['2026-11-06（新）'];h={c.value:c.column for c in t[1] if c.value};sh={c.value:c.column for c in s[1] if c.value}
 old={s.cell(r,sh['代码']).value:r for r in range(2,501) if s.cell(r,1).value};errors=[];formats=[];font_differences=[]
 def check(ok,*x):
  if not ok:errors.append(x)
 for item in json.loads((W/'expected_styles.json').read_text()):
  c=t[item['cell']];st=item['style']
  check(rgb(c.fill.fgColor)==st['backColor'],item['cell'],'fill')
  if 'foreColor' in st:check(rgb(c.font.color)==st['foreColor'],item['cell'],'font color')
  if 'font' in st:check(bool(c.font.b)==st['font']['bold'],item['cell'],'bold')
 typical={k:Counter(s.cell(r,col).number_format for r in old.values()).most_common(1)[0][0] for k,col in sh.items()}
 for r in range(2,480):
  code=t.cell(r,h['代码']).value;sr=old.get(code)
  row=[t.cell(r,c).value for c in range(1,len(h)+1)];validate_row(row,{k:v-1 for k,v in h.items()})
  check(t.cell(r,h['2026Q4锁定预测(亿元)']).value==t.cell(r,h['2026Q4净利润(亿元)']).value,code,'lock')
  for k,c in h.items():
   cell=t.cell(r,c)
   if k.startswith('笔记') and sr:
    source=s.cell(sr,sh[k]);check(cell.value==source.value and copy(cell.fill)==copy(source.fill),code,k,'note value/fill')
    a=copy(cell.font);b=copy(source.font)
    if a.name!=b.name or a.scheme!=b.scheme:
     font_differences.append({'code':code,'cell':cell.coordinate,'source_font':b.name,'current_font':a.name})
     a.name=b.name;a.scheme=b.scheme
    check(a==b,code,k,'note font properties')
   if k not in sh:continue
   expected=s.cell(sr,sh[k]).number_format if sr else typical[k]
   if cell.number_format!=expected:
    formats.append({'code':code,'cell':cell.coordinate,'header':k,'expected':expected,'actual':cell.number_format,'numeric':isinstance(cell.value,(int,float))})
 # Original source and other sheets retain their values (source title renamed by user).
 for a in original:
  name='2026-11-06' if a.title=='2026-11-06（新）' else a.title
  if name not in current.sheetnames:continue
  b=current[name]
  for row in a:
   for c in row:check(c.value==b.cell(c.row,c.column).value,name,c.coordinate,'old value')
 result={'companies':478,'errors':errors,'format_differences':formats,'font_family_differences':font_differences,'annual_quarter_reconciliations':1434,'row_heights':sorted({t.row_dimensions[r].height for r in range(1,501)}),'conditional_format_ranges':len(t.conditional_formatting)}
 (E/'final_format_verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False));assert not errors
if __name__=='__main__':main()
