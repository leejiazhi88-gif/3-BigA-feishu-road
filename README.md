# Shenwan L2 Sector Radar

Local research tool for identifying Shenwan 2021 level-2 sectors that are:

- starting to strengthen before they become crowded
- already in a confirmed trend
- hot enough that new entries deserve caution
- losing trend quality after a strong run

## Run

The pipeline reads `TUSHARE_TOKEN` from the environment. If it is missing, it
prompts for the token without echoing it.

```bash
.venv/bin/python scripts/build_sector_radar.py
```

The first run fetches and caches Shenwan daily sector data, current Shenwan L2
members, recent A-share daily rows for breadth, and financial-indicator report
periods under `data/raw/`. Later runs reuse cached history and refresh the
latest requested window.

## Outputs

- `reports/latest.html`: browsable sector radar
- `reports/YYYYMMDD.html`: dated report snapshot
- `exports/sector_scores_latest.csv`: full Shenwan level-2 score table
- `exports/startup_candidates_latest.csv`: sectors that look early or improving
- `exports/risk_warnings_latest.csv`: sectors that look crowded or weakening
- `exports/stage_migrations_latest.csv`: current stage and recent stage changes

## Current Scope

The current scoring model uses:

- Shenwan level-2 index action: relative trend versus the Shenwan A-share
  index, 20/60/120-session return, ranking improvement, turnover attention,
  volatility, and PE/PB temperature where available
- constituent breadth: member stocks above 20/60/120-session averages, positive
  member returns, fresh 60-session highs, and leader-versus-median spread
- financial prosperity summary: current constituent coverage for revenue
  growth, profit growth, profit improvement versus the prior available report
  period, and operating-cash-flow quality

Funding persistence and event/catalyst evidence are the next validation layers.
The report already separates confirmation from refutation so those evidence
sources can be added without hiding the reasoning in a single score.

## Feishu all-stock business composition

The `2026-10-8（全部）` sheet now includes four business-composition columns in
`AX:BA`: 2025 revenue, 2025 profit, 2026 revenue forecast, and 2026 profit
forecast. The result covers 446 companies and is available in
`exports/business_composition/2026-10-08-all.json`.

The calculation follows the reviewed `3.2 飞书筛选器（精选）` method. It uses
Tushare `fina_mainbz` and `income`, removes duplicate parent/child disclosures,
reconciles segment totals, uses gross-profit composition for non-financial
companies and operating-profit composition for banks, brokers, and insurers.
2026 uses comparable half-year growth where reliable and otherwise retains the
latest defensible structure with an explicit assumption in the cell text.
Tushare is the default source and is therefore omitted from cell text; only
non-default sources are labeled explicitly.

Run the four phases below. Raw responses and Feishu snapshots stay under the
ignored `work/` directory. `apply_composition.py` writes only `AX:BA`, verifies
all cells by reading them back, preserves `A:AW`, and checks conditional formats,
filters, and frozen panes.

```bash
.venv/bin/python scripts/business_composition/prepare_source.py
.venv/bin/python scripts/business_composition/fetch_raw.py
.venv/bin/python scripts/business_composition/build_composition.py
.venv/bin/python scripts/business_composition/apply_composition.py
```

## 2026-10-09 all-stock refresh

The `2026-10-12（全部）` copied sheet was refreshed with the latest complete
close from 2026-10-09. Selection is additive: all 446 prior companies remain,
and newly qualifying companies are appended before the full list is resorted
by Shenwan L1 market capitalization, Shenwan L2 market capitalization, and
company market capitalization. A company that later falls below the threshold
is retained.

The refresh preserves personal notes in column B and the Q3 locked comparison
value in column AK by stock code. It refreshes annual actual/consensus profit
and quarterly actual/forecast profit for every company. The change audit in
`exports/refresh_20261009/forecast_changes.csv` records the old value, new
value, and percentage change for every changed forecast. Existing business
composition remains unchanged on daily refreshes; it is recalculated for new
entrants once and otherwise only after interim or annual reports.
Industry row coloring explicitly excludes column B, whose personal-note
background and font colors are preserved independently by stock code.
Column Q records every annual forecast changed by the current refresh in the
form `20XX年（旧值XXX，+X.X%）`; multiple years are separated with a Chinese
semicolon, and a newly available forecast is labeled `新增预测`. Its font is
green for an increase and red for a decrease. When multiple years changed,
the nearest changed year determines the color; a change without an old value
uses black.

```bash
.venv/bin/python scripts/refresh_all_20261012.py prepare
.venv/bin/python scripts/refresh_all_20261012.py apply
```

## 2026-10-13 intraday refresh

The `实时数据（26.10.13 11点30分）` sheet uses the 11:30 intraday snapshot.
Selection remains additive: 451 existing companies were retained and two new
qualifiers were added. Only market fields in `G:Q` are recalculated for
existing companies; `A:F` are preserved by stock code, with identification
fields populated once for new entrants. Intraday market capitalization comes
from the live quote, TTM PE scales the latest Tushare daily PE by the intraday
price, and trailing returns use the intraday price against historical closes.

Industry background colors are keyed by Shenwan L1 and L2 using the most
recent dated all-stock sheet, `2026-10-12（全部）`, as the reference. Column B
keeps its independent personal-note colors. The sheet title includes the quote
timestamp after every refresh.

```bash
.venv/bin/python scripts/refresh_realtime_20261013.py prepare
.venv/bin/python scripts/refresh_realtime_20261013.py apply
```

## 2026-10-16 all-stock refresh

The copied `2026-10-16（全部）` sheet was refreshed with the 2026-10-16 close.
The refresh is additive: all 451 companies from `2026-10-12（全部）` remain, and
`301660.SZ` was added because its market value exceeded CNY 600bn while
`600323.SH` was added as the second-largest company in the Shenwan level-2
environmental-governance group. The final sheet contains 453 companies.

Annual and quarterly profit values were refreshed. The annual forecast audit
contains 143 changes across 60 companies in
`exports/refresh_20261016/forecast_changes.json`; the annual-change column uses
the nearest changed year for the font direction: 29 green, 30 red, and one
black entry with no comparable old value. Personal notes, decision notes, the
Q3 archive, and business-composition columns are preserved. Industry row
colors use `2026-10-12（全部）` as the reference. Returns are formatted as
percentages with one decimal place, and the 13 existing conditional-format
rules remain in place.

## 2026-10-23 all-stock refresh

`2026-10-23（全部）` was copied from the latest dated sheet before its values
were refreshed with the 2026-10-23 close. All 453 existing companies remain
and seven newly qualified companies were added, producing a final list of 460.
The additions are recorded in `exports/refresh_20261023/additions.json`.

Annual and quarterly profits were refreshed together. The complete old value,
new value, and percentage change audit is stored in
`exports/refresh_20261023/forecast_changes.json`. There are 280 annual forecast
changes across 109 companies; the annual-change column is green for 56 nearest
year increases and red for 53 decreases. Both personal-note columns, the Q3
archive, and existing business composition are preserved by stock code.
Industry colors use `2026-10-16（全部）` as the latest reference. Market value,
growth, year-on-year profit, return, and dividend-yield number formats were
verified across all 460 rows, together with the 15 conditional-format rules.
