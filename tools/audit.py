# -*- coding: utf-8 -*-
"""交付前自查：数据完整度、课本顺序、正文是否真挂上了。"""
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "src")
from agent_textbook.site import goals          # 册次顺序得用它，字符串排序是错的

P = "pages/data/%s.json"


def _unum(s):
    d = "".join(ch for ch in str(s or "") if ch.isdigit())
    return int(d) if d else 0


def load(k):
    return json.load(open(P % k, encoding="utf-8"))


m, c, e = load("math"), load("chinese"), load("english")

print("== 规模 ==")
print("数学：单元 %d（带正文 %d）· 知识点 %d · 结构图 %d · 应用题 %d · 生活题 %d"
      % (len(m["units"]), sum(1 for u in m["units"] if u.get("text")),
         sum(len(u.get("points") or []) for u in m["units"]),
         sum(1 for u in m["units"] if u.get("map")),
         len(m["problems"]), len(m.get("life", []))))
print("语文：课文 %d · 段落 %d · 要素 %d · 字词 %d · 骨架 %d · 古诗文 %d"
      % (len(c["texts"]), sum(len(t.get("paras") or []) for t in c["texts"]),
         len(c["elements"]), sum(len(v) for v in c["words"].values()),
         len(c["structures"]), len(c["pieces"])))
print("英语：词汇 %d · 句型 %d · 拼读 %d · 语篇 %d · 对话 %d · 项目 %d · 常用表达 %d"
      % (len(e["vocab"]), len(e["grammar"]), len(e["phonics"]), len(e["passages"]),
         len(e["dialogues"]), len(e["projects"]), len(e["exprs"])))


def ordered(rows, key):
    keys = [key(r) for r in rows]
    return keys == sorted(keys)


print("\n== 课本顺序（应为 True）==")
# key_of 给出册次顺序；字符串排序会错（"三" 的码位小于 "二"）
print("数学单元 册→单元：",
      ordered(m["units"], lambda u: (goals.key_of(u["grade"], u["term"]),
                                     _unum(u["unit_no"]))))
print("语文课文 册→单元→课：",
      ordered(c["texts"], lambda t: (goals.key_of(t["grade"], t["term"]),
                                     _unum(t["unit_no"]), t["no"])))
print("英语词汇 册→Unit：",
      ordered(e["vocab"], lambda v: (goals.key_of(v["grade"], v["term"]),
                                     _unum(v["unit"]))))
print("英语语篇 册→Unit：",
      ordered(e["passages"], lambda v: (goals.key_of(v["grade"], v["term"]),
                                        _unum(v["unit"]))))

print("\n== 正文挂载 ==")
tm = sum(len(u.get("text") or []) for u in m["units"])
print("数学单元正文行数合计：", tm, "（样例前 2 行：",
      (m["units"][0].get("text") or [""])[:2], "）")
print("带生活场景的数学单元：",
      sum(1 for u in m["units"] if u.get("life")), "/", len(m["units"]))
print("没匹配上生活场景的单元：",
      [u["title"] for u in m["units"] if not u.get("life")])
print("英语语篇空正文：",
      sum(1 for p in e["passages"] if not (p.get("text") or "").strip()))

print("\n== 抽查：一年级上册 ==")
for u in m["units"]:
    if u["grade"] == "一年级" and u["term"] == "上册":
        print("  数学", u["unit_no"], u["title"], "| 生活：",
              (u.get("life") or [{}])[0].get("where", "—"))
for t in c["texts"]:
    if t["grade"] == "一年级" and t["term"] == "上册":
        print("  语文 第%s单元 第%s课 %s（%d 段）"
              % (t["unit_no"], t["no"], t["title"], len(t.get("paras") or [])))
