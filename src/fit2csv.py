#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
fit2csv.py — 用 Garmin 官方 FIT Python SDK 批量把 .fit 转成 CSV。

设计要点
--------
一个 FIT 文件里混装了多种「消息类型」(message type)：活动文件里有
record / lap / session；日常监测(wellness)文件里有 monitoring /
monitoring_hr / stress_level / sleep_level / respiration_rate / hrv 等。
它们字段完全不同，塞进同一张 CSV 只会得到一堆 NaN。

所以默认行为是 **按消息类型汇总**：
    out/record.csv          ← 所有 fit 文件的 record 消息拼在一起
    out/monitoring.csv
    out/stress_level.csv
    ...
每张表都带 source_file 列，便于回溯到原始文件。

用法
----
    python fit2csv.py <输入目录或文件> -o <输出目录>
    python fit2csv.py IN -o OUT --per-file          # 每个 fit 单独出一套 CSV
    python fit2csv.py IN -o OUT --only monitoring,monitoring_hr
    python fit2csv.py IN -o OUT --jobs 8            # 多进程
"""
from __future__ import annotations

import argparse
import csv
import sys
import traceback
from collections import OrderedDict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, datetime
from zoneinfo import ZoneInfo
from pathlib import Path

from garmin_fit_sdk import (Decoder, Stream, convert_datetime_to_timestamp,
                            convert_timestamp_to_datetime)

# ---------------------------------------------------------------- 解码单个文件

# read() 的解码选项。全开 = 拿到人类可读的值（带单位缩放、枚举转字符串、
# 时间戳转 datetime），这是做科研分析想要的形态。
DECODE_OPTIONS = dict(
    apply_scale_and_offset=True,     # 应用 Profile 里的 scale/offset，比如心率距离单位
    convert_datetimes_to_dates=True, # FIT Epoch(1989-12-31起) → datetime
    convert_types_to_strings=True,   # 枚举整数 → 'running' 这类字符串
    enable_crc_check=True,           # 校验 CRC，能发现截断/损坏的文件
    expand_sub_fields=True,          # 展开子字段
    expand_components=True,          # 展开压缩打包的分量字段（如 compressed_speed_distance）
    merge_heart_rates=True,          # 把独立 hr 消息合并进 record（仅活动文件有意义）
)


def resolve_timestamp_16(rows: list[dict]) -> int:
    """还原 monitoring 消息的 16 位压缩时间戳，返回补齐的行数。

    Garmin 的日常监测文件为了压体积，只在少数消息上写完整的 timestamp，
    后面跟着一串只带 timestamp_16 的消息——它是上一个完整时间戳抹掉高 16 位
    再加上时间增量。不还原会丢掉仅有压缩时间戳的有效心率记录。

    官方还原算法（FIT SDK / Garmin 论坛一致）：
        ts += (timestamp_16 - (ts & 0xFFFF)) & 0xFFFF
    这一步同时处理了 16 位回绕。ts 必须逐条累积推进，不能只用最近一个完整值。

    补出来的行会打上 timestamp_from_16=True，方便回头审计哪些时间是推算的。
    """
    last = None          # 当前累积的 FIT Epoch 秒
    filled = 0
    for row in rows:
        ts = row.get("timestamp")
        if ts is not None:
            last = ts if isinstance(ts, (int, float)) else convert_datetime_to_timestamp(ts)
            last = int(last)
            row["timestamp_from_16"] = False
            continue
        t16 = row.get("timestamp_16")
        if t16 is None or last is None:
            continue
        last = last + ((int(t16) - (last & 0xFFFF)) & 0xFFFF)
        row["timestamp"] = convert_timestamp_to_datetime(last)
        row["timestamp_from_16"] = True
        filled += 1
    return filled


def flatten(value):
    """把 list/tuple 值压成一个字符串，其余原样返回。"""
    if isinstance(value, (list, tuple)):
        return "|".join("" if v is None else str(v) for v in value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    return value


def decode_one(path: Path, subject: str = "",
               tz=None) -> tuple[str, dict[str, list[dict]], list[str]]:
    """解码一个 fit 文件，返回 (文件名, {消息类型: [行, ...]}, 错误信息列表)。

    subject: 被试编号。目录树扫描时取 --subject，否则取输入目录下第一层目录名，
    写进每行的 subject_id 列——多被试汇总分析时这一列是必须的。
    """
    notes: list[str] = []
    try:
        stream = Stream.from_file(str(path))
        decoder = Decoder(stream)

        if not decoder.is_fit():
            return path.name, {}, [f"{path.name}: 不是 FIT 文件（头部签名不符）"]
        intact = decoder.check_integrity()
        if not intact:
            # 不直接放弃：Garmin 设备偶尔写出 CRC 不全但数据可用的文件
            notes.append(f"{path.name}: 完整性校验未通过，跳过 CRC 继续解析")

        # ★ 关键：is_fit()/check_integrity() 会把流指针读到末尾，
        #   不 reset 就直接 read()，会静默返回 0 条消息（无报错，极易踩坑）。
        stream.reset()

        opts = dict(DECODE_OPTIONS)
        if not intact:
            opts["enable_crc_check"] = False
        messages, errors = decoder.read(**opts)
        for e in errors:
            notes.append(f"{path.name}: 解码告警 {e!r}")
    except Exception:
        return path.name, {}, [f"{path.name}: 解码失败\n{traceback.format_exc()}"]

    tables: dict[str, list[dict]] = {}
    for key, rows in messages.items():
        if not rows:
            continue
        # 已知消息的 key 形如 'record_mesgs'；SDK 没有 Profile 定义的未知消息
        # 会直接用整数消息号做 key，这里统一成 'unknown_<号>'
        name = str(key)
        name = name[:-6] if name.endswith("_mesgs") else name
        if name.isdigit():
            name = f"unknown_{name}"

        # 展平之前先还原 16 位压缩时间戳（monitoring 类消息必需）
        if any("timestamp_16" in r for r in rows):
            n = resolve_timestamp_16(rows)
            if n:
                notes.append(f"INFO {path.name}: {name} 由 timestamp_16 补出 {n} 条时间戳")

        out_rows = []
        for row in rows:
            r = OrderedDict()
            if subject:
                r["subject_id"] = subject
            r["source_file"] = path.name
            # FIT 里的时间一律是 UTC。加一列当地时间和当地日期，
            # 否则按 UTC 分日会把北京时间的一天切错 8 小时。
            if tz is not None:
                t = row.get("timestamp") or row.get("stress_level_time")
                if isinstance(t, datetime):
                    lt = t.astimezone(tz)
                    r["local_time"] = lt.isoformat()
                    r["local_date"] = lt.date().isoformat()
            for k, v in row.items():
                r[str(k)] = flatten(v)
            out_rows.append(r)
        tables[name] = out_rows
    return path.name, tables, notes


# ---------------------------------------------------------------- CSV 写出

def write_csv(rows: list[dict], out_path: Path) -> int:
    """写 CSV。列 = 所有行字段的并集，按首次出现顺序排列（source_file 永远第一列）。"""
    columns: list[str] = []
    seen = set()
    for row in rows:
        for k in row:
            if k not in seen:
                seen.add(k)
                columns.append(k)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig：Excel 双击打开中文/时间列不乱码
    with out_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return len(rows)


# ---------------------------------------------------------------- 主流程

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="批量把 Garmin .fit 转成 CSV（官方 SDK）")
    ap.add_argument("input", help="fit 文件，或包含 fit 文件的目录")
    ap.add_argument("-o", "--out", default="csv_out", help="输出目录（默认 csv_out）")
    ap.add_argument("--per-file", action="store_true",
                    help="每个 fit 文件单独建子目录出 CSV，而不是跨文件汇总")
    ap.add_argument("--only", default="",
                    help="只导出这些消息类型，逗号分隔，如 monitoring,monitoring_hr,stress_level")
    ap.add_argument("--subject", default="",
                    help="手动指定 subject_id（按被试分文件夹时用，如 --subject SAMPLE_001）；"
                         "不填则取输入目录下第一层子目录名")
    ap.add_argument("--jobs", type=int, default=1, help="并行进程数（默认 1）")
    ap.add_argument("--tz", default="Asia/Shanghai",
                    help="当地时区，用于生成 local_time / local_date 列（默认北京时间）；"
                         "传 --tz \"\" 可关闭")
    args = ap.parse_args(argv)

    src = Path(args.input)
    if src.is_dir():
        files = sorted(p for p in src.rglob("*") if p.suffix.lower() == ".fit")
    else:
        files = [src]
    if not files:
        print(f"在 {src} 下没找到 .fit 文件", file=sys.stderr)
        return 1

    def subject_of(p: Path) -> str:
        """优先用 --subject；否则输入是目录时，用相对路径的第一层目录名当被试编号。"""
        if args.subject:
            return args.subject
        if not src.is_dir():
            return ""
        parts = p.relative_to(src).parts
        return parts[0] if len(parts) > 1 else ""

    tz = ZoneInfo(args.tz) if args.tz else None

    keep = {s.strip() for s in args.only.split(",") if s.strip()}
    out_dir = Path(args.out)
    print(f"找到 {len(files)} 个 fit 文件 → {out_dir}")

    merged: dict[str, list[dict]] = {}
    all_notes: list[str] = []
    ok = 0

    def handle(name, tables, notes):
        nonlocal ok
        all_notes.extend(notes)
        if not tables:
            return
        ok += 1
        for mesg, rows in tables.items():
            if keep and mesg not in keep:
                continue
            if args.per_file:
                write_csv(rows, out_dir / Path(name).stem / f"{mesg}.csv")
            else:
                merged.setdefault(mesg, []).extend(rows)

    if args.jobs > 1:
        with ProcessPoolExecutor(max_workers=args.jobs) as ex:
            futs = {ex.submit(decode_one, p, subject_of(p), tz): p for p in files}
            for fut in as_completed(futs):
                handle(*fut.result())
    else:
        for p in files:
            handle(*decode_one(p, subject_of(p), tz))

    if not args.per_file:
        for mesg, rows in sorted(merged.items()):
            n = write_csv(rows, out_dir / f"{mesg}.csv")
            print(f"  {mesg + '.csv':<32} {n:>8} 行")

    print(f"\n成功解码 {ok}/{len(files)} 个文件")
    # INFO 开头的是转换说明（比如补了多少条时间戳），不是错误，分开写两个文件。
    # 用 utf-8-sig，否则 Windows 的记事本 / Get-Content 打开是乱码。
    infos = [n for n in all_notes if n.startswith("INFO ")]
    errs = [n for n in all_notes if not n.startswith("INFO ")]
    out_dir.mkdir(parents=True, exist_ok=True)
    if infos:
        (out_dir / "_notes.log").write_text("\n".join(infos), encoding="utf-8-sig")
        print(f"{len(infos)} 条转换说明写入 {out_dir / '_notes.log'}")
    if errs:
        (out_dir / "_errors.log").write_text("\n".join(errs), encoding="utf-8-sig")
        print(f"{len(errs)} 条告警/错误写入 {out_dir / '_errors.log'}")
    return 0 if ok == len(files) else 2


if __name__ == "__main__":
    sys.exit(main())
