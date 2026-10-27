#!/usr/bin/env python3
"""把最新的 data.json 内联进 index.html（替换 window.__DATA__）"""
import json, re

data = json.load(open('app_1.0/src/data.json'))
js = 'window.__DATA__ = ' + json.dumps(data, ensure_ascii=False) + ';'

html = open('app_1.0/src/index.html').read()

# 用正则替换 window.__DATA__ = {...}; 整段
pattern = r'window\.__DATA__ = \{.*?\};'
new_html, n = re.subn(pattern, js, html, count=1, flags=re.DOTALL)

if n == 0:
    print('❌ 未找到 window.__DATA__ 内联数据段，检查格式')
else:
    open('app_1.0/src/index.html','w').write(new_html)
    print(f'✅ 已替换内联数据（替换 {n} 处），文件大小 {len(new_html)} 字节')
    # 验证
    check = open('app_1.0/src/index.html').read()
    assert '23642675' in check, '总资产2364.3万未写入'
    assert '688.09' in check, '累计收益688.09%未写入'
    print('✅ 验证通过：2364.3万总资产、688.09%收益均已就位')
