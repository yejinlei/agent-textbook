# -*- coding: utf-8 -*-
"""可选：用 Manim 把"公式是怎么来的"渲染成动画。

页面里的可视化实验室（app.js）是主力：能拖、能点、离线可用。
Manim 出的是视频，适合"看一遍就懂"的推导——割补、等分拼长方形。

只有装了 manim 才用得着：
    pip install manim
    python -m agent_textbook anim

产物放进 pages/assets/video/；下次生成页面时会自动嵌进数学页
（没渲染过就没有视频，页面也不受影响）。
"""
import glob
import os
import shutil
import subprocess
import sys
import tempfile

# slug → （视频里的场景名、页面上的标题、一句话说明）
VIDEOS = {
    "cut_parallelogram": ("CutParallelogram", "割补：平行四边形 → 长方形",
                          "沿高割一刀，把三角形补到另一边，就是长方形——所以 S＝a×h"),
    "circle_area": ("CircleToRect", "等分：圆 → 近似长方形",
                    "等分 32 份拼起来，长是圆周的一半 πr，宽是 r——所以 S＝πr²"),
    "fraction_bar": ("FractionBar", "分数的意义：整体与部分",
                     "把整体平均分成几份、取其中几份，就是分数"),
}


def _scenes():
    """返回 [(slug, Scene 类)]；没装 manim 就返回空表。"""
    try:
        import manim  # noqa: F401
    except Exception:
        return []

    from manim import (BLUE, YELLOW, Create, DashedLine, FadeIn, MathTex,
                       Polygon, Rectangle, Scene, Sector, Text, Transform,
                       VGroup, Write, np)

    class CutParallelogram(Scene):
        """平行四边形沿高割开，补到另一边变成长方形——S＝ah 是这么来的。"""

        def construct(self):
            a, h, s = 4.0, 2.0, 1.2
            off = np.array([-a / 2 - s / 2, -h / 2, 0])
            A = np.array([0, 0, 0]) + off
            B = np.array([a, 0, 0]) + off
            C = np.array([a + s, h, 0]) + off
            D = np.array([s, h, 0]) + off
            E = np.array([s, 0, 0]) + off        # 高与底边的交点

            para = Polygon(A, B, C, D, color=BLUE, fill_opacity=0.25)
            rest = Polygon(E, B, C, D, color=BLUE, fill_opacity=0.25)
            tri = Polygon(A, E, D, color=YELLOW, fill_opacity=0.6)
            cut = DashedLine(D, E, color="#c0392b")
            label = MathTex("S = a \\times h").to_edge(DOWN)

            self.play(Create(para))
            self.wait(0.4)
            self.play(Create(cut))
            self.wait(0.4)
            self.play(FadeIn(tri), FadeIn(rest))
            self.play(tri.animate.shift(np.array([a, 0, 0])), run_time=2.2)
            self.wait(0.4)
            self.play(Write(label))
            self.wait(1)

    class CircleToRect(Scene):
        """圆等分成 32 份，拼成近似长方形——S＝πr² 是这么来的。"""

        def construct(self):
            import math
            r, n = 1.5, 32
            circle = Sector(radius=r, angle=2 * math.pi, color=BLUE, fill_opacity=0.25)
            sectors = VGroup(*[
                Sector(radius=r, angle=2 * math.pi / n, start_angle=i * 2 * math.pi / n,
                       color=YELLOW if i % 2 == 0 else BLUE, fill_opacity=0.6)
                for i in range(n)
            ])
            w = math.pi * r / (n / 2)
            rects = VGroup()
            for i in range(n):
                col, row = i % (n // 2), i // (n // 2)
                rects.add(Rectangle(
                    width=w * 0.98, height=r / 2 * 0.98,
                    color=YELLOW if i % 2 == 0 else BLUE, fill_opacity=0.6,
                ).move_to([-math.pi * r / 2 + w * (col + 0.5),
                           (0.5 - row) * r / 2, 0]))
            label = MathTex("S = \\pi r \\times r = \\pi r^2").to_edge(DOWN)

            self.play(Create(circle))
            self.wait(0.4)
            self.play(Transform(circle, sectors))
            self.wait(0.4)
            self.play(Transform(sectors, rects), run_time=2.2)
            self.wait(0.4)
            self.play(Write(label))
            self.wait(1)

    class FractionBar(Scene):
        """整体平均分成几份、取其中几份——分数的意义。"""

        def construct(self):
            import math
            n, m, W, H = 4, 3, 6.0, 1.0
            bar = Rectangle(width=W, height=H, color="#2f3437")
            parts = VGroup()
            for i in range(n):
                p = Rectangle(width=W / n * 0.98, height=H * 0.98,
                              color=YELLOW if i < m else "#ffffff", fill_opacity=0.7)
                p.move_to([-W / 2 + W / n * (i + 0.5), 0, 0])
                parts.add(p)
            label = MathTex("\\frac{%d}{%d} = %.2f" % (m, n, m / n)).to_edge(DOWN)

            self.play(Create(bar))
            self.wait(0.3)
            self.play(Create(parts), run_time=1.5)
            self.wait(0.4)
            self.play(Write(label))
            self.wait(1)

    return [(slug, name, {"cut_parallelogram": CutParallelogram,
                          "circle_area": CircleToRect,
                          "fraction_bar": FractionBar}[slug])
            for slug, (name, _, _) in VIDEOS.items()]


def render_all(out_dir: str = None, quality: str = "-ql") -> dict:
    """渲染全部场景到 pages/assets/video/。没装 manim 就如实返回。"""
    from .. import config

    out = out_dir or os.path.join(config.ROOT, "pages")
    vdir = os.path.join(out, "assets", "video")
    ss = _scenes()
    if not ss:
        return {"ok": False, "msg": "未安装 manim（pip install manim 后才可用）",
                "files": []}

    os.makedirs(vdir, exist_ok=True)
    done, failed = [], []
    for slug, scene_name, _cls in ss:
        with tempfile.TemporaryDirectory() as tmp:
            cmd = [sys.executable, "-m", "manim", "render", quality,
                   "--media_dir", tmp, __file__, scene_name]
            try:
                r = subprocess.run(cmd, capture_output=True, text=True)
            except Exception as e:      # pragma: no cover
                failed.append((slug, str(e)[:120]))
                continue
            hits = glob.glob(os.path.join(tmp, "videos", "*", scene_name + ".mp4"))
            if not hits:
                failed.append((slug, (r.stderr or r.stdout or "")[-200:]))
                continue
            dst = os.path.join(vdir, slug + ".mp4")
            shutil.copy(hits[0], dst)
            done.append(dst)
    return {"ok": bool(done), "msg": "渲染 %d 个，失败 %d 个" % (len(done), len(failed)),
            "files": done, "failed": failed}


def video_block(kind: str, out_dir: str) -> str:
    """生成页面里嵌视频的那段 HTML（视频不存在就返回空）。"""
    from .. import config

    out = out_dir or os.path.join(config.ROOT, "pages")
    vdir = os.path.join(out, "assets", "video")
    want = {"all": list(VIDEOS), "num": ["fraction_bar"],
            "geo": ["cut_parallelogram", "circle_area"],
            "problem": ["fraction_bar"]}.get(kind, [])
    has = [s for s in want if os.path.exists(os.path.join(vdir, s + ".mp4"))]
    if not has:
        return ""
    cards = "".join(
        '<div class="card vid"><h3>%s</h3><p class="small">%s</p>'
        '<video controls preload="none" playsinline src="../assets/video/%s.mp4"></video></div>'
        % (VIDEOS[s][1], VIDEOS[s][2], s) for s in has)
    return "<h2>公式动画（Manim）</h2>" + \
        '<p class="lead">看一遍就懂的推导。页面里的可视化实验室可以自己拖，' + \
        "这里是做好的动画。</p>" + cards
