# -*- coding: utf-8 -*-
"""命令行入口：python -m agent_textbook <子命令>"""

import argparse
import os
from collections import Counter

from . import config
from .collect import catalog as cat
from .collect import downloader as dl
from .collect.net import has_credentials, load_token


def _add_filters(p: argparse.ArgumentParser) -> None:
    p.add_argument("--stage", default="", help="学段，默认小学（六三学制）")
    p.add_argument("--subject", default="", help="学科，逗号分隔（模糊匹配）")
    p.add_argument("--version", default="", help="版本，逗号分隔（模糊匹配）")
    p.add_argument("--grade", default="", help="年级，逗号分隔（模糊匹配）")
    p.add_argument("--preset", default="", choices=sorted(config.VERSION_PRESETS), help="版本预设")
    p.add_argument("--include-teacher", action="store_true", help="包含教师用书")
    p.add_argument("--include-wusi", action="store_true", help="包含五·四学制")


def _select(args) -> list[dict]:
    rows = cat.load_catalog()
    if not rows:
        raise SystemExit("没有目录数据，请先运行：python -m agent_textbook catalog")
    rows = cat.select_rows(
        rows,
        stage=args.stage,
        subject=args.subject,
        version=args.version,
        grade=args.grade,
        preset=args.preset,
        include_teacher=args.include_teacher,
        include_wusi=args.include_wusi,
    )
    if getattr(args, "limit", 0):
        rows = rows[: args.limit]
    return rows


def cmd_catalog(args) -> None:
    rows = cat.fetch_catalog()
    path = cat.save_catalog(rows)
    print(f"共 {len(rows)} 本，已写入 {path}")
    primary = [r for r in rows if cat.is_stage(r, include_wusi=True)]
    print("学段分布：", dict(Counter(cat.classify(r["path"])[0] for r in primary)))


def cmd_list(args) -> None:
    rows = _select(args)
    print(f"命中 {len(rows)} 本")
    for key, n in sorted(Counter(
        (cat.classify(r["path"])[1], cat.classify(r["path"])[2]) for r in rows
    ).items()):
        print(f"  {key[0]} / {key[1]}：{n} 本")


def cmd_fetch(args) -> None:
    load_token(args.token)
    if has_credentials():
        print("已载入登录凭据，请求将使用真实签名")
    rows = _select(args)
    print(f"待处理 {len(rows)} 本")
    records = dl.resolve_all(rows, workers=args.workers, region=args.region)
    if not args.dry_run:
        records = dl.download_all(records, out_dir=args.out, workers=args.workers)
    dl.merge_manifest(records)
    print(f"清单已写入 {config.MANIFEST_FILE}")


def cmd_retry(args) -> None:
    load_token(args.token)
    failed = [r for r in dl.read_manifest() if r.get("status") != "ok" and r.get("url")]
    print(f"重跑失败项 {len(failed)} 条")
    if not failed:
        return
    for r in failed:  # download_all 只处理 pending，失败项需先复位
        r["status"] = "pending"
    records = dl.download_all(failed, out_dir=args.out, workers=args.workers)
    dl.merge_manifest(records)


def cmd_sync(args) -> None:
    n = dl.sync_from_disk(out_dir=args.out)
    print(f"按磁盘回填 {n} 条清单记录")


def cmd_organize(args) -> None:
    moved = dl.organize(out_dir=args.out, region=args.region)
    print(f"搬迁 {moved} 个文件到 <地区>/<学段>/<学科>/<版本>/<年级>/ 布局")


def cmd_status(args) -> None:
    rows = dl.read_manifest()
    stat = Counter(r.get("status") for r in rows)
    size = sum(r.get("size") or 0 for r in rows if r.get("status") == "ok")
    print(f"清单 {len(rows)} 条：{dict(stat)}，已下载 {size / 1024 ** 3:.2f} GB")
    for r in rows:
        if r.get("status") != "ok":
            print(f"  失败：{r.get('subject')}/{r.get('version')}/{r.get('title')} —— {r.get('reason')}")


def main() -> None:
    p = argparse.ArgumentParser(prog="agent-textbook", description="小学生教材 Agent 工程命令行")
    p.add_argument("--out", default=config.BOOKS_DIR, help="教材输出目录")
    p.add_argument("--region", default=config.DEFAULT_REGION, help="地区层目录名，默认浙江杭州")
    p.add_argument("--token", default=config.TOKEN_FILE, help="登录凭据 JSON 路径")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("catalog", help="拉取平台全量书目").set_defaults(func=cmd_catalog)

    sp = sub.add_parser("list", help="按条件筛选书目")
    _add_filters(sp)
    sp.add_argument("--limit", type=int, default=0)
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("fetch", help="解析并下载教材")
    _add_filters(sp)
    sp.add_argument("--limit", type=int, default=0)
    sp.add_argument("--workers", type=int, default=config.DEFAULT_WORKERS)
    sp.add_argument("--dry-run", action="store_true", help="只解析写清单，不下载")
    sp.set_defaults(func=cmd_fetch)

    sp = sub.add_parser("retry", help="重跑清单中失败的条目")
    sp.add_argument("--workers", type=int, default=config.DEFAULT_WORKERS)
    sp.set_defaults(func=cmd_retry)

    sp = sub.add_parser("sync", help="按磁盘已下载文件回填清单状态")
    sp.set_defaults(func=cmd_sync)

    sub.add_parser("organize", help="整理已下载文件到新目录布局").set_defaults(func=cmd_organize)
    sub.add_parser("status", help="查看下载清单状态").set_defaults(func=cmd_status)

    args = p.parse_args()
    os.makedirs(args.out, exist_ok=True)
    args.func(args)


if __name__ == "__main__":
    main()
