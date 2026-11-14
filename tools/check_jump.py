"""检查 extra.html 跳转逻辑：href → hash 正则 → hubs.extra 键三方一致性"""
import re, json, urllib.parse

def extract(p):
    t = open(p, encoding='utf-8').read()
    i = t.find('window.DATA'); j = t.find('{', i); d = 0
    for k in range(j, len(t)):
        if t[k] == '{': d += 1
        elif t[k] == '}':
            d -= 1
            if d == 0: return json.loads(t[j:k+1])

d = extract('F:/src/agent-textbook/pages/english/index.html')
en_d = d['hubs']
keys = set(en_d['extra'].keys())

print(f'hubs.extra 键共 {len(keys)} 个，示例：{list(keys)[:3]}')

e = extract('F:/src/agent-textbook/pages/english/extra.html')
rs = e['readings']

# 模拟 app.js 中的 unitLink + applyUnitHash
# app.js: '#' + encodeURIComponent(book) + '#U' + uno  （encodeURIComponent 保留 !'()*）
# applyUnitHash: /^#([^#]+)#U(\d+)$/ 然后 decodeURIComponent(m[1])
JS_RE = re.compile(r'^#([^#]+)#U(\d+)$')

def js_encode(s):
    # encodeURIComponent 等价：safe 空串，但不转义 !'()*
    return urllib.parse.quote(s, safe="!" + "'" + "()*")

def js_decode(s):
    return urllib.parse.unquote(s)

matched = missed = 0
sample_miss = []
sample_ok = []
for r in rs:
    for u in (r.get('units') or []):
        book = u.get('book') or ''
        uno = u.get('unit_no') or 0
        href = '#' + js_encode(book) + '#U' + str(uno)
        m = JS_RE.match(href)
        if not m:
            missed += 1; sample_miss.append(('noregex', href)); continue
        decoded = js_decode(m.group(1))
        ck = decoded + '#U' + str(int(m.group(2)))
        if ck in keys:
            matched += 1
            if len(sample_ok) < 3: sample_ok.append((href, ck))
        else:
            missed += 1
            if len(sample_miss) < 5: sample_miss.append((href, ck))

print(f'\n[方向1] extra→index 跳转：matched={matched} missed={missed}')
if sample_ok: print('  样例 OK:', sample_ok)
if sample_miss: print('  样例 MISS:', sample_miss)

# 诊断：打印 keys 和 books 的 utf-8 codepoints 对比
if missed:
    sample_u = list(rs[0].get('units', []))
    if sample_u:
        print(f'\n[诊断] extra.units[0] book: {sample_u[0].get("book")!r}')
        print(f'[诊断] hubs.extra keys[0]:   {list(keys)[0]!r}')
        kb = list(keys)[0].split('#U')[0]
        ub = sample_u[0].get('book') or ''
        print(f'  key book codepoints: {[hex(ord(c)) for c in kb]}')
        print(f'  unit book codepoints: {[hex(ord(c)) for c in ub]}')
        print(f'  equal: {kb == ub}')

# 方向 2: index→extra (hubExtend 反向入口)
# app.js 里 hubExtend 用 unitExtraOf(x) 查 HUBS.extra[(x.book||"")+"#U"+(x.unit_no||0)]
ps = d.get('passages') or []
dlg = d.get('dialogues') or []
all_units = ps + dlg
m2 = m3 = 0
no_extra = set()
for p in all_units:
    k = (p.get('book') or '') + '#U' + str(p.get('unit_no') or 0)
    if k in keys:
        lst = en_d['extra'][k]
        for b in lst:
            if b.get('id'): m2 += 1
    else:
        m3 += 1; no_extra.add(k)

print(f'\n[方向2] index→extra 反向索引：命中键 {m2-m3}（miss 键 {m3}）')
print(f'  无课外书的单元数：{len(no_extra)}')
if no_extra: print(f'  示例无课外书单元：{list(no_extra)[:5]}')

# 检查 extra 键里是否有空标题/空 ID 的书（app.js 中 esc(b.title||"课外阅读") 会兜底）
bad = 0
for k, lst in en_d['extra'].items():
    for b in lst:
        if not b.get('id') or not b.get('title'): bad += 1
print(f'\n  反向索引里空 id/空 title 的记录：{bad}')

# 检查 extra 页 units 数据（app.js 读 b.units）
u_missing = 0
for r in rs:
    ids = r.get('pairs_with_unit') or []
    if ids and not r.get('units'):
        u_missing += 1
print(f'\n  有 pairs_with_unit 但缺 units 的书（会导致 fallback 到裸字符串）：{u_missing}')
