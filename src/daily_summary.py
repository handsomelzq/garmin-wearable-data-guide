#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""将SDK解码长表聚合为FIT日级核查表。累计字段按活动类型聚合，午夜记录按前一天归属；瞬时心率按实际本地日期统计。中途重置的计数器需对照Connect日值。厂商未公开字段的映射仅适用于已核对设备，不能当作通用SDK定义。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

# 当日累计、午夜归零、按 activity_type 分开计的字段
CUMULATIVE = ["steps", "cycles", "distance", "active_calories", "active_time"]
# active_time 只算这两类才与官方活动秒数一致（generic 的 active_time 官方不计入）
ACTIVE_TYPES = ["walking", "running"]
# 未公开的当日累计字段：列名 → (输出列名, 换算除数)
HIDDEN_CUM = {"35": ("ascent_m", 1000), "36": ("descent_m", 1000),
              "37": ("moderate_min", 1), "38": ("vigorous_min", 1)}
# 压力分档，与 Connect 官方口径一致（-2 = 活动中）
STRESS_BANDS = {"stress_rest_min": (0, 25), "stress_low_min": (26, 50),
                "stress_medium_min": (51, 75), "stress_high_min": (76, 100)}
KEY = ["subject_id", "local_date"]


def dedup(df: pd.DataFrame) -> pd.DataFrame:
    """按除 source_file 外的全部列去重（同一记录会出现在相邻两天的导出包里）。"""
    cols = [c for c in df.columns if c != "source_file"]
    return df.drop_duplicates(subset=cols, keep="first")


def attribution_date(local_time: pd.Series) -> pd.Series:
    """累计值的归属日：把 00:00:00 整点的记录算回前一天。"""
    t = pd.to_datetime(local_time, errors="coerce", format="mixed", utc=False)
    # 统一成 'YYYY-MM-DD' 字符串，和 CSV 里的 local_date 列同类型，否则 join 对不上
    return (t - pd.Timedelta(seconds=1)).dt.strftime("%Y-%m-%d")


def cumulative_days(mon: pd.DataFrame) -> pd.DataFrame:
    """按类型各取当日最大值再相加，并标出计数器中途归零的日子。"""
    have = [c for c in CUMULATIVE if c in mon.columns]
    cum = mon.dropna(subset=["activity_type"]).dropna(subset=have, how="all").copy()
    cum["attrib_date"] = attribution_date(cum["local_time"])
    per = cum.groupby(["subject_id", "attrib_date", "activity_type"])[have].max()
    day = per.groupby(level=[0, 1]).sum(min_count=1)
    if "active_time" in have:
        act = per[per.index.get_level_values("activity_type").isin(ACTIVE_TYPES)]
        day["active_time"] = act["active_time"].groupby(level=[0, 1]).sum(min_count=1)

    # 计数器中途归零：同一 (日, 类型) 内按时间排序后 cycles 出现下降
    if "cycles" in cum.columns:
        c = cum.dropna(subset=["cycles"]).copy()
        c["t"] = pd.to_datetime(c["local_time"], format="mixed")
        c = (c.groupby(["subject_id", "attrib_date", "activity_type", "t"])["cycles"].max()
               .reset_index().sort_values("t"))
        drop = c.groupby(["subject_id", "attrib_date", "activity_type"])["cycles"].diff() < 0
        day["counter_reset"] = drop.groupby([c["subject_id"], c["attrib_date"]]).any()
        day["counter_reset"] = day["counter_reset"].fillna(False).astype(bool)

    day.index.names = KEY
    return day.round(1)


def hidden_cumulative_days(mon: pd.DataFrame) -> pd.DataFrame | None:
    """未公开的当日累计字段：楼层高度（毫米→米）与强度分钟。"""
    have = [c for c in HIDDEN_CUM if c in mon.columns]
    if not have:
        return None
    h = mon.dropna(subset=have, how="all").copy()
    h["attrib_date"] = attribution_date(h["local_time"])
    day = h.groupby(["subject_id", "attrib_date"])[have].max()
    for src, (name, div) in HIDDEN_CUM.items():
        if src in day:
            day[name] = day.pop(src) / div
    if {"moderate_min", "vigorous_min"} <= set(day.columns):
        # Garmin 的强度分钟口径：高强度按 2 倍计
        day["intensity_min"] = day["moderate_min"].fillna(0) + 2 * day["vigorous_min"].fillna(0)
    day.index.names = KEY
    return day.round(2)


def stress_extra_days(st: pd.DataFrame) -> pd.DataFrame:
    """每分钟一条的压力表：分档时长、体能电池、佩戴时长。同一分钟只计一次。"""
    tcol = "stress_level_time" if "stress_level_time" in st.columns else "local_time"
    one = st.drop_duplicates(subset=["subject_id", tcol], keep="first")
    v = one["stress_level_value"]
    parts = {name: one[(v >= lo) & (v <= hi)].groupby(KEY).size()
             for name, (lo, hi) in STRESS_BANDS.items()}
    parts["stress_activity_min"] = one[v == -2].groupby(KEY).size()
    out = pd.DataFrame(parts)
    if "3" in one.columns:                                   # 体能电池
        bb = pd.to_numeric(one["3"], errors="coerce")
        out = out.join(bb.groupby([one[k] for k in KEY]).agg(
            bb_mean="mean", bb_min="min", bb_max="max").round(1))
    if "4" in one.columns:                                   # 佩戴状态，1 = 在测
        w = one[pd.to_numeric(one["4"], errors="coerce") == 1].groupby(KEY).size()
        out["wear_min"] = w
        out["wear_pct"] = (out["wear_min"] / 1440 * 100).round(1)
    band_cols = list(STRESS_BANDS) + ["stress_activity_min"] + (["wear_min"] if "wear_min" in out else [])
    out[band_cols] = out[band_cols].fillna(0).astype(int)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="生成日级汇总宽表")
    ap.add_argument("csv_dir", nargs="?", default="data/csv", help="fit2csv 的输出目录")
    ap.add_argument("-o", "--out", default="data/daily_summary.csv", help="输出 CSV")
    args = ap.parse_args(argv)

    base = Path(args.csv_dir)
    if not (base / "monitoring.csv").exists():
        sys.exit(f"{base} 下没有 monitoring.csv，请先跑 fit2csv.py")

    mon = dedup(pd.read_csv(base / "monitoring.csv", low_memory=False))
    if "local_date" not in mon.columns:
        sys.exit("CSV 里没有 local_date 列，请用带 --tz 的 fit2csv.py 重新转换")

    # ---- 瞬时指标：心率，按记录自身的当地日期归组 ----
    hr = mon[mon["heart_rate"].between(30, 254)]          # 0和255无效
    hr = hr.drop_duplicates(["subject_id", "local_time", "heart_rate"])
    hr_day = hr.groupby(KEY)["heart_rate"].agg(
        hr_n="size", hr_mean="mean", hr_min="min", hr_max="max").round(1)

    # ---- 累计指标：归属日 = (当地时间 - 1 秒) 的日期，按类型相加 ----
    cum_day = cumulative_days(mon)
    hid_day = hidden_cumulative_days(mon)

    # ---- 静息心率：每天设备给出的当日静息心率 ----
    rhr_day = None
    p = base / "monitoring_hr_data.csv"
    if p.exists():
        rhr = dedup(pd.read_csv(p, low_memory=False))
        col = ("current_day_resting_heart_rate"
               if "current_day_resting_heart_rate" in rhr.columns else "resting_heart_rate")
        if "local_date" in rhr.columns and col in rhr.columns:
            rhr_day = rhr.groupby(KEY)[col].median().round(1)
            rhr_day.name = "resting_hr"

    # ---- 压力：剔除 -1 / -2 哨兵；另出分档时长、体能电池、佩戴时长 ----
    st_day = st_extra = None
    p = base / "stress_level.csv"
    if p.exists():
        st = dedup(pd.read_csv(p, low_memory=False))
        if "local_date" in st.columns:
            ok = st[st["stress_level_value"].between(0, 100)]
            st_day = ok.groupby(KEY)["stress_level_value"].agg(
                stress_n="size", stress_mean="mean", stress_max="max").round(1)
            # 有效率 = 有效采样 / 总采样，反映佩戴质量
            tot = st.groupby(KEY).size().rename("stress_total")
            st_day = st_day.join(tot, how="outer")
            st_day["stress_n"] = st_day["stress_n"].fillna(0)
            st_day["stress_valid_pct"] = (
                st_day["stress_n"] / st_day["stress_total"] * 100).round(1)
            st_extra = stress_extra_days(st)

    out = hr_day.join(cum_day, how="outer")
    for part in (hid_day, rhr_day, st_day, st_extra):
        if part is not None:
            out = out.join(part, how="outer")

    out = out.sort_index()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out, encoding="utf-8-sig")
    print(out.to_string())
    print(f"\n{len(out)} 行 → {args.out}")
    print("注意：日期区间两端的那一天通常不完整（只覆盖部分小时），分析时建议剔除。")
    if "counter_reset" in out and out["counter_reset"].fillna(False).any():
        bad = out[out["counter_reset"].fillna(False)].index.get_level_values("local_date").tolist()
        print("计数器中途归零的日子（日总量请用官方值）：" + "、".join(bad))
    return 0


if __name__ == "__main__":
    sys.exit(main())
