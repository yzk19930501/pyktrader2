# -*- coding: utf-8 -*-
'''
optstrat.py
Created on Feb 03, 2015
@author: Harvey
'''
import json
import os
import csv
import pyktlib
import mysqlaccess
import trade
import instrument
import pandas as pd
import data_handler as dh
from eventType import *
from eventEngine import Event
from misc import *

class OptionStrategy(object):
    common_params = {'name': 'opt_m', 'products':{'m1705': {201705: [2800, 2850, 2900, 2950, 3000]}, \
                                                  'm1709': {201709: [2800, 2850, 2900, 2950, 3000]}}, \                     
                     'pos_scaler': 1.0, 'daily_close_buffer': 3, 'exec_class': 'ExecAlgo1DFixT', \
                     'is_disabled': True,}
    def __init__(self, config, agent = None):
        self.load_config(config)
        self.underliers = self.products.keys()                
        self.option_map = self.get_option_map(self.products)
        self.option_insts = self.option_map.values()
        self.instIDs = self.underliers + self.option_insts        
        self.underlying = [None] * len(self.instIDs)
        self.expiry_map = {}        
        self.risk_table = pd.DataFrame(0, index = self.instIDs(), 
                                          columns = ['product', 'underlying', 'cont_mth', 'otype', 'strike', \
                                                     'multiple', 'df', 'margin_long', 'margin_short', \
                                                     'pos_long', 'pos_short', 'out_long', 'out_short', 'under_price',\
                                                     'pv', 'delta', 'gamma', 'vega', 'theta', \
                                                     'ppos', 'ppv', 'pdelta', 'pgamma', 'pvega', 'ptheta'])
        self.risk_table['underlying'] = self.risk_table.index
        self.risk_table['df'] = 1.0
        self.group_risk = None
        self.agent = agent
        self.folder = ''
        self.submitted_pos = dict([(inst, []) for inst in self.instIDs])
        self.proxy_flag = {'delta': False, 'gamma': True, 'vega': True, 'theta': True} 
        self.hedge_config = {'order_type': OPT_LIMIT_ORDER, 'num_tick': 1}

    def load_config(self, config):
        d = self.__dict__
        for key in self.common_params:
            d[key] = config.get(key, self.common_params[key])

    def save_config(self):
        config = {}
        d = self.__dict__
        for key in self.common_params:
            config[key] = d[key]
        config['assets'] = []
        fname = self.folder + 'config.json'
        with open(fname, 'w') as ofile:
            json.dump(config, ofile)

    def save_state(self):
        filename = self.folder + 'strat_status.csv'
        self.on_log('save state for strat = %s' % self.name, level = logging.DEBUG)
        out_df = self.risk_table(['pos_long', 'pos_short', 'out_long', 'out_short'])
        out_df.to_csv(filename)
            
    def load_state(self):
        self.on_log('load state for strat = %s' % self.name, level = logging.DEBUG)
        filename = self.folder + 'strat_status.csv'
        out_df = pd.read_csv(filename)
        self.risk_table.update(out_df)
    
    def dep_instIDs(self):
        return self.instIDs

    def set_agent(self, agent):
        self.agent = agent
        self.folder = self.agent.folder + self.name + '_'
        self.underlying = [self.agent.instruments[instID] for instID in self.instIDs]   
        for inst in self.underlying:
            if inst.ptype == instrument.ProductType.Option:
               if (inst.underlying, inst.cont_mth) not in self.expiry_map:
                   self.expiry_map[(inst.underlying, inst.cont_mth)] = inst.expiry
        for key in ['product', 'cont_mth', 'multiple']:
            self.risk_table[key] = [ getattr(inst, key) for inst in self.underlying ]         
        idx = len(self.underliers)
        for key in ['underlying', 'otype', 'strike', 'pv', 'delta', 'gamma', 'vega', 'theta']:
            self.risk_table[key][idx:] = [ getattr(inst, key) for inst in self.underlying[idx:] ]
        for under, inst in zip(self.underliers, self.underlying[:idx]):
            self.risk_table[self.risk_table['underlying'] == under]['under_price'] = inst.mid_price
        self.register_func_freq()
        self.register_bar_freq()

    def register_func_freq(self):
        pass

    def register_bar_freq(self):
        pass

    def on_log(self, text, level = logging.INFO):
        event = Event(type=EVENT_LOG)
        event.dict['data'] = text
        event.dict['owner'] = "strategy_" + self.name
        event.dict['level'] = level
        self.agent.eventEngine.put(event)
        
    def initialize(self):
        self.load_state()
        idx = len(self.underliers)
        for key in ['pv', 'delta', 'gamma', 'vega', 'theta']:
            self.risk_table[key][idx:] = [getattr(inst, key) for inst in self.underlying[idx:]]
        self.update_pos_greeks()
        self.update_margin()
    
    def update_margin(self):
        for key in ['margin_long', 'margin_short']:
            self.risk_table[key] = [ inst.calc_margin_amount(ORDER_BUY, price) for inst, price in zip(self.underlying, self.risk_table['under_price'])]

    def update_pos_greeks(self):
        '''update position greeks according to current positions'''
        keys = ['pv', 'delta', 'gamma', 'vega', 'theta']
        self.risk_table['ppos'] = self.risk_table['pos_long'] - self.risk_table['pos_short']
        for key in keys:
            pos_key = 'p' + key
            self.risk_table[pos_key] = self.risk_table[key] * self.risk_table['ppos'] * self.risk_table['multiple']
        group_keys = ['underlying', 'cont_mth', 'ppv', 'pdelta', 'pgamma','pvega','ptheta']
        self.group_risk = self.risk_table[group_keys].groupby(['underlying', 'cont_mth']).sum()

    def risk_agg(self, risk_list):
        risks = [ r for r in list(self.risk_table) if str(r) in risk_list]
        risk_df = self.risk_table[risks]
        return risk_df.to_dict('index')

    def submit_trade(self, xtrade):
        book = xtrade.book
        exec_algo = eval(self.exec_class)(xtrade, **self.exec_args[book])
        xtrade.set_algo(exec_algo)
        self.submitted_trades[book].append(xtrade)
        self.agent.submit_trade(xtrade)

    def add_submitted_pos(self, xtrade):
        book = xtrade.book
        if book in self.submitted_pos:
            for trade in self.submitted_pos[book]:
                if trade.id == xtrade.id:
                    return False
        self.submitted_pos[book].append(xtrade)
        return True

    def day_finalize(self):
        self.logger.info('strat %s is finalizing the day - update trade unit, save state' % self.name)
        self.update_pos_greeks()
        self.update_margin()
        self.save_state()

    def get_option_map(self, products):
        option_map = {}
        for under in products:
            for cont_mth in products[under]:
                for strike in products[under][cont_mth]:
                    for otype in ['C', 'P']:
                        key = (str(under), cont_mth, otype, strike)
                        instID = under
                        exch = inst2exch(instID)
                        if instID[:2] == "IF":
                            instID = instID.replace('IF', 'IO')
                        if exch == 'CZCE':
                            instID = instID + otype + str(strike)
                        else:
                            instID = instID + '-' + otype + '-' + str(strike)
                        option_map[key] = instID
        return option_map

    def run_tick(self, ctick):
        if self.is_disabled: return

    def run_min(self, inst, freq):
        if self.is_disabled: return
    
    def delta_hedger(self):
        tot_deltas = self.group_risk.pdelta.sum()
        cum_vol = 0
        if (self.spot_model == False) and (self.proxy_flag['delta']== False):
            for idx, inst in enumerate(self.underliers):
                if idx == self.main_cont: 
                    continue
                multiple = self.risk_table.get_value(inst, 'multiple')
                cont_mth = self.risk_table.get_value(inst, 'cont_mth')
                pdelta = self.group_risk[cont_mth, 'delta'] 
                volume = int( - pdelta/multiple + 0.5)
                cum_vol += volume
                if volume!=0:
                    curr_price = self.agent.instruments[inst].price
                    buysell = 1 if volume > 0 else -1
                    valid_time = self.agent.tick_id + 600
                    xtrade = trade.XTrade( [inst], [volume], [self.hedge_config['order_type']], curr_price*buysell, [self.hedge_config['num_tick']], \
                                               valid_time, self.name, self.agent.name)
                    self.submitted_pos[inst].append(xtrade)
                    self.agent.submit_trade(xtrade)
        inst = self.underliers[self.main_cont]
        multiple = self.option_map[inst, 'multiple']
        tot_deltas += cum_vol
        volume = int( tot_deltas/multiple + 0.5)
        if volume!=0:
            curr_price = self.agent.instruments[inst].price
            buysell = 1 if volume > 0 else -1
            etrade = trade.XTrade( [inst], [volume], [self.hedge_config['order_type']], curr_price*buysell, [self.hedge_config['num_tick']], \
                                valid_time, self.name, self.agent.name)
            self.submitted_pos[inst].append(etrade)
            self.agent.submit_trade(etrade)
        
class EquityOptStrat(OptionStrategy):
    def __init__(self, name, underliers, expiries, strikes, agent = None):
        OptionStrategy.__init__(self, name, underliers, expiries, strikes, agent)        
        self.proxy_flag = {'delta': True, 'gamma': True, 'vega': True, 'theta': True}
        self.dividends = [(datetime.date(2015,4,20), 0.0), (datetime.date(2015,11,20), 0.10)]
        
    def get_option_map(self, products):
        option_map = {}
        for under in products:
            for cont_mth in products[under]:
                map = mysqlaccess.get_stockopt_map(under, [cont_mth], products[under][cont_mth])
                option_map.update(map)
        return option_map
    
class IndexFutOptStrat(OptionStrategy):
    def __init__(self, name, underliers, expiries, strikes, agent = None):
        OptionStrategy.__init__(self, name, underliers, expiries, strikes, agent)
        self.proxy_flag = {'delta': True, 'gamma': True, 'vega': True, 'theta': True} 

class CommodOptStrat(OptionStrategy):
    def __init__(self, name, underliers, expiries, strikes, agent = None):
        OptionStrategy.__init__(self, name, underliers, expiries, strikes, agent)
        self.proxy_flag = {'delta': False, 'gamma': False, 'vega': True, 'theta': True} 
        
class OptArbStrat(CommodOptStrat):
    def __init__(self, name, underliers, expiries, strikes, agent = None):
        CommodOptStrat.__init__(self, name, underliers, expiries, strikes, agent)
        self.callspd = dict([(exp, dict([(s, {'upbnd':0.0, 'lowbnd':0.0, 'pos':0.0}) for s in ss])) for exp, ss in zip(expiries, strikes)])
        self.putspd = dict([(exp, dict([(s, {'upbnd':0.0, 'lowbnd':0.0, 'pos':0.0}) for s in ss])) for exp, ss in zip(expiries, strikes)])
        self.bfly = dict([(exp, dict([(s, {'upbnd':0.0, 'lowbnd':0.0, 'pos':0.0}) for s in ss])) for exp, ss in zip(expiries, strikes)])

class OptSubStrat(object):
    def __init__(self, strat):
        self.strat = strat
    
    def tick_run(self, ctick):
        pass
