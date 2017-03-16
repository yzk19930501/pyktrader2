#-*- coding:utf-8 -*-
import Tkinter as tk
import re
import datetime
import math

vtype_func_map = {'int':int, 'float':float, 'str': str, 'bool':bool }

def keepdigit(x, p=5):
    out = x
    if isinstance(x, float):
        if x >= 10**p:
            out = int(x)
        elif x>=1:
            n = p + 1 - len(str(int(x)))
            out = int(x*(10**n)+0.5)/float(10**n)
        elif math.isnan(x):
            out = 0
        else:
            out = int(x*10**p+0.5)/1.0/10**p
    return out

def get_type_var(vtype):
    if vtype == 'int':
        v=tk.IntVar()
    elif vtype == 'float':
        v=tk.DoubleVar()
    else:
        v=tk.StringVar()
    return v

def type2str(val, vtype):
    ret = val
    if vtype == 'bool':
        ret = '1' if val else '0'
    elif 'list' in vtype:
        ret = ','.join([str(r) for r in val])
    elif vtype == 'date':
        ret = val.strftime('%Y%m%d')
    elif vtype == 'datetime':
        ret = val.strftime('%Y%m%d')
    else:
        ret = str(val)
    return ret

def str2type(val, vtype):
    ret = val
    if vtype == 'str':
        return ret
    elif vtype == 'bool':
        ret = True if int(float(val))>0 else False
    elif 'list' in vtype:
        key = 'float'
        if len(vtype) > 4:
            key = vtype[:-4]
        func = vtype_func_map[key]
        ret = [func(s) for s in val.split(',')]
    elif vtype == 'date':
        ret = datetime.datetime.strptime(val,'%y%m%d').date()
    elif vtype == 'datetime':
        ret = datetime.datetime.strptime(val,'%y%m%d %H:%M:%S')
    else:
        func = vtype_func_map[vtype]
        ret = func(float(val))
    return ret

def field2variable(name):
    return '_'.join(re.findall('[A-Z][^A-Z]*', name)).lower()

def variable2field(var):
    return ''.join([s.capitalize() for s in var.split('_')])
