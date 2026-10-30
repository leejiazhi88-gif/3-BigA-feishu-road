import unittest
from decimal import Decimal
import pandas as pd
from scripts import forecast_quality as f
from scripts.supplement_forecast_reports import parse


def report(org,date,value,year=2026):
    return {'org_name':org,'report_date':date,'np':value*10000,'quarter':f'{year}Q4','report_title':'报告'}


class ForecastQualityTests(unittest.TestCase):
    def test_superseded_broker_does_not_vote_twice(self):
        rows=[report('甲证券','20260801',1),report('甲证券','20261020',100),report('乙证券','20261021',120)]
        s=f.select(f.records(pd.DataFrame(rows),'20261029'),2026,'20261029','20261019')
        self.assertEqual(s['value'],110)
        self.assertEqual(len(s['used']),2)

    def test_ninety_day_boundary_and_no_future_reports(self):
        rows=[report('甲','20260731',3),report('乙','20260730',9),report('丙','20261030',90)]
        s=f.select(f.records(pd.DataFrame(rows),'20261029'),2026,'20261029','20261025')
        self.assertEqual(s['value'],3)
        self.assertEqual(s['status'],'财报后未更新')

    def test_each_year_selects_its_own_available_records(self):
        rows=[report('甲','20261027',10),report('乙','20260801',20,2027)]
        r=f.records(pd.DataFrame(rows),'20261029')
        self.assertEqual(f.select(r,2026,'20261029','20261025')['status'],'机构预测')
        self.assertEqual(f.select(r,2027,'20261029','20261025')['status'],'财报后未更新')
        self.assertIsNone(f.select(r,2028,'20261029','20261025')['value'])

    def test_same_day_conflicting_predictions_are_not_silently_selected(self):
        r=f.records(pd.DataFrame([report('甲','20261027',10),report('甲','20261027',100)]),'20261029')
        self.assertIsNone(f.select(r,2026,'20261029',None)['value'])

    def test_rounding_reconciles_without_adjusting_actuals(self):
        annual,q=f.reconcile(114.742618,{1:33.461854,2:26.709296,3:27.285734},[.25]*4)
        self.assertEqual(q[:3],[33.5,26.7,27.3])
        self.assertEqual(sum(Decimal(str(x)) for x in q),Decimal(str(annual)))

    def test_restatement_uses_latest_consolidated_record(self):
        rows=[dict(end_date='20260630',ann_date=d,f_ann_date=d,report_type=t,n_income_attr_p=v*1e8)
              for d,t,v in [('20260801','1',10),('20261001','1',12),('20261001','2',99)]]
        q,c=f.actuals(pd.DataFrame(rows),'20261029')
        self.assertEqual(c['20260630'],12)
        self.assertNotIn((2026,2),q)  # A cumulative is not a standalone Q2 without Q1.

    def test_demingli_stale_reports_use_model_and_no_blank_quarters(self):
        income=pd.DataFrame([dict(end_date=e,ann_date=d,f_ann_date=d,report_type='1',n_income_attr_p=v*1e8)
            for e,d,v in [('20260331','20260430',33.461854),('20260630','20260828',60.17115),('20260930','20261026',87.456884)]])
        r=pd.DataFrame([report('甲','20260507',143.1)])
        out,need=f.build(r,income,'20261029','半导体')
        self.assertTrue(need)
        self.assertEqual(out[2026]['annual'],114.7)
        for year,x in out.items():
            self.assertTrue(x['status'].startswith('模型估算'))
            self.assertEqual(sum(Decimal(str(v)) for v in x['quarters']),Decimal(str(x['annual'])))

    def test_public_report_parser_requires_explicit_years_and_profit_units(self):
        got=parse('预计2026-2028年归母净利润为-1.5/6.3/17.2亿元。')
        self.assertEqual(got[0],[-1.5,6.3,17.2])
        self.assertIsNone(parse('预计2026-2028年收入为10/20/30亿元。'))
        self.assertIsNone(parse('预计2025-2027年归母净利润为10/20/30亿元。'))

    def test_half_year_cumulative_is_split_and_labelled_estimated(self):
        income=pd.DataFrame([dict(end_date='20260630',ann_date='20260820',f_ann_date='20260820',report_type='1',n_income_attr_p=1.7e8)])
        out,_=f.build(pd.DataFrame(),income,'20261029')
        self.assertEqual(out[2026]['imputed_quarters'],[1,2])
        self.assertEqual(out[2026]['actual_quarters'],[])
        self.assertEqual(out[2026]['annual'],3.4)

    def test_public_and_primary_source_do_not_double_count_same_broker(self):
        rows=[report('国信证券','20261027',10),dict(report('国信证券股份有限公司','20261027',10),source='东方财富研报原文')]
        s=f.select(f.records(pd.DataFrame(rows),'20261029'),2026,'20261029',None)
        self.assertEqual(len(s['used']),1)
        self.assertEqual(s['used'][0]['source'],'Tushare')

    def test_loss_reduction_is_positive_revision(self):
        from scripts.refresh_all_20261012 import percent_change
        self.assertEqual(percent_change(-10,-5),.5)
        self.assertEqual(percent_change(-10,-15),-.5)


if __name__=='__main__':unittest.main()
