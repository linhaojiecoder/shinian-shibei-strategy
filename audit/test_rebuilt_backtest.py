#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import unittest
import rebuilt_backtest as engine


class AccountingTests(unittest.TestCase):
    def test_dividend_receivable_and_payment(self):
        days = ['2020-01-01', '2020-01-02', '2020-01-03', '2020-01-06']
        prices = {code: {day: [1.0, 1.0, 1.0, 1.0, 1000] for day in days} for code in engine.CODES}
        prices['510300']['2020-01-03'] = [.9, .9, .9, .9, 1000]
        prices['510300']['2020-01-06'] = [.9, .9, .9, .9, 1000]
        event = {'record_date':'2020-01-02','ex_date':'2020-01-03','pay_date':'2020-01-06','amount_per_share':.1}
        actions = {('510300','2020-01-03'):[('dividend',event)]}
        indices = {code:[1.0]*len(days) for code in engine.CODES}
        result = engine.simulate(prices,days,actions,indices,fee=0,buy_hold='510300')
        before, ex, paid = result['ledger'][1:]
        self.assertAlmostEqual(ex['receivable'],300000)
        self.assertAlmostEqual(ex['total'],before['total'])
        self.assertAlmostEqual(paid['receivable'],0)
        self.assertAlmostEqual(paid['cash'],300000)
        self.assertAlmostEqual(paid['total'],before['total'])

    def test_split_preserves_value_and_cost(self):
        days = ['2020-01-01', '2020-01-02', '2020-01-03']
        prices = {code: {day: [5.0, 5.0, 5.0, 5.0, 1000] for day in days} for code in engine.CODES}
        prices['513100']['2020-01-03'] = [1.0,1.0,1.0,1.0,1000]
        actions = {('513100','2020-01-03'):[('split',{'ratio':5})]}
        indices = {code:[1.0]*len(days) for code in engine.CODES}
        result = engine.simulate(prices,days,actions,indices,fee=0,buy_hold='513100')
        before, after = result['ledger'][1:]
        self.assertAlmostEqual(before['total'],after['total'])
        self.assertEqual(after['holdings']['513100']['shares'],5*before['holdings']['513100']['shares'])
        self.assertAlmostEqual(after['holdings']['513100']['cost'],before['holdings']['513100']['cost']/5)

    def test_fee_and_cash_limit(self):
        days = ['2020-01-01', '2020-01-02']
        prices = {code:{day:[3.0,3.0,3.0,3.0,1000] for day in days} for code in engine.CODES}
        indices = {code:[1.0,1.0] for code in engine.CODES}
        result = engine.simulate(prices,days,{},indices,fee=.0008,buy_hold='510300')
        order = result['orders'][0]
        holding = result['ledger'][0]['holdings']['510300']
        self.assertEqual(order['shares']%100,0)
        self.assertGreaterEqual(result['ledger'][0]['cash'],0)
        self.assertAlmostEqual(holding['cost'],3.0*1.0008)
        self.assertAlmostEqual(order['cash_change'],-order['shares']*holding['cost'])


if __name__ == '__main__':
    unittest.main()
