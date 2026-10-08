# -*- coding: utf-8 -*-
"""从本地缓存的Connect睡眠JSON生成夜间摘要及分期表。睡眠按醒来日归属；分期来源是服务器结果，不能由仅有awake/unmeasurable的FIT消息推断。项目有效性规则是质控标记，不等同于医疗判断。联网下载统一由download.py负责。"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import warnings
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")

# sleepLevels 里 activityLevel 的含义（已用每晚各分期总时长与 dailySleepDTO 对账验证）。
# -1表示无法测量；新设备需核对各分期合计与摘要的一致性。
STAGE = {-1: "unmeasurable", 0: "deep", 1: "light", 2: "rem", 3: "awake"}






def fit_unmeasurable_pct(sleep_csv: Path, start, end):
    """同一睡眠时段里，FIT 的 sleep_level 被标成 unmeasurable 的分钟占比。
    正常夜晚接近 0（睡着时根本没记录）；设备出状况的夜晚会整段都是 unmeasurable。"""
    if not hasattr(fit_unmeasurable_pct, "cache"):
        if not sleep_csv.exists():
            fit_unmeasurable_pct.cache = None
        else:
            d = pd.read_csv(sleep_csv, low_memory=False, usecols=["local_time", "sleep_level"])
            d["lt"] = (pd.to_datetime(d["local_time"], format="mixed")
                         .dt.tz_convert("Asia/Shanghai").dt.tz_localize(None).dt.floor("min"))
            fit_unmeasurable_pct.cache = set(d.loc[d["sleep_level"] == "unmeasurable", "lt"])
    um = fit_unmeasurable_pct.cache
    if um is None:
        return None
    # 服务器的起止时间不一定落在整分钟上，先对齐，否则一个也匹配不上
    mins = pd.date_range(start.floor("min"), end.floor("min"), freq="min", inclusive="left")
    return round(100 * sum(m in um for m in mins) / max(len(mins), 1), 1)


def build(sid: str, sleep_dir: Path, fit_sleep_csv: Path, tz: str):
    nights, stages, mismatch = [], [], []
    for f in sorted((sleep_dir / "json").glob("*.json")):
        s = json.loads(f.read_text(encoding="utf-8"))
        t = s.get("dailySleepDTO") or {}
        wake = t.get("calendarDate") or f.stem
        mn = lambda k: None if t.get(k) is None else round(t[k] / 60)
        row = {"subject_id": sid, "wake_date": wake}
        if not t.get("sleepStartTimestampLocal"):
            row.update({"valid": False, "flag": "服务器无睡眠记录"})
            nights.append(row)
            continue
        # *Local 时间戳是「把当地时间当 UTC 编码」的毫秒数，直接解析即得北京时间
        st = pd.to_datetime(t["sleepStartTimestampLocal"], unit="ms")
        en = pd.to_datetime(t["sleepEndTimestampLocal"], unit="ms")
        vals = lambda k: [x.get("value") for x in (s.get(k) or []) if isinstance(x.get("value"), (int, float))]
        stress = [v for v in vals("sleepStress") if v >= 0]
        hr = vals("sleepHeartRate")
        row.update({
            "sleep_start": st.strftime("%Y-%m-%d %H:%M"), "sleep_end": en.strftime("%Y-%m-%d %H:%M"),
            "sleep_min": mn("sleepTimeSeconds"), "deep_min": mn("deepSleepSeconds"),
            "light_min": mn("lightSleepSeconds"), "rem_min": mn("remSleepSeconds"),
            "awake_min": mn("awakeSleepSeconds"), "unmeasurable_min": mn("unmeasurableSleepSeconds"),
            "nap_min": mn("napTimeSeconds"),
            "sleep_hr_mean": round(sum(hr) / len(hr), 1) if hr else None,
            "resting_hr": s.get("restingHeartRate"),
            "sleep_stress_mean": round(sum(stress) / len(stress), 1) if stress else None,
            "body_battery_change": s.get("bodyBatteryChange"),
            "spo2_mean": t.get("averageSpO2Value"), "spo2_min": t.get("lowestSpO2Value"),
            "confirmation": t.get("sleepWindowConfirmationType"),
            "fit_unmeasurable_pct": fit_unmeasurable_pct(fit_sleep_csv, st, en),
        })
        # 分期明细 + 对账
        seg_sum = {k: 0.0 for k in STAGE.values()}
        for x in s.get("sleepLevels") or []:
            a = pd.to_datetime(x["startGMT"], utc=True).tz_convert(tz).tz_localize(None)
            b = pd.to_datetime(x["endGMT"], utc=True).tz_convert(tz).tz_localize(None)
            lv = x.get("activityLevel")
            stg = STAGE.get(int(lv), f"level_{lv}") if lv is not None else "level_missing"
            m = (b - a).total_seconds() / 60
            seg_sum[stg] = seg_sum.get(stg, 0) + m
            stages.append({"subject_id": sid, "wake_date": wake, "start": a.strftime("%Y-%m-%d %H:%M"),
                           "end": b.strftime("%Y-%m-%d %H:%M"), "minutes": round(m), "stage": stg})
        for k in ("deep", "light", "rem", "unmeasurable"):
            dto = row[f"{k}_min"] or 0
            if abs(seg_sum[k] - dto) > 2:
                mismatch.append(f"{wake} {k}: 分段合计 {seg_sum[k]:.0f} ≠ 汇总 {dto}")
        # 疑点：REM 为 0 却睡了 3 小时以上（设备支持 REM），或 FIT 在这段时间整段无数据
        flags = []
        if t.get("deviceRemCapable") and (row["rem_min"] or 0) == 0 and (row["sleep_min"] or 0) > 180:
            flags.append("REM为0")
        if (row["fit_unmeasurable_pct"] or 0) > 50:
            flags.append(f"FIT该时段{row['fit_unmeasurable_pct']:.0f}%无数据")
        if row["confirmation"] and not str(row["confirmation"]).startswith("enhanced"):
            flags.append(f"确认方式{row['confirmation']}")
        row["valid"] = not any(f.startswith(("REM", "FIT")) for f in flags)
        row["flag"] = "；".join(flags)
        nights.append(row)

    nights = pd.DataFrame(nights)
    cols = ["subject_id", "wake_date", "valid", "flag"]
    nights = nights[cols + [c for c in nights.columns if c not in cols]]
    nights.to_csv(sleep_dir / "sleep_nightly.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(stages).to_csv(sleep_dir / "sleep_stages.csv", index=False, encoding="utf-8-sig")
    return nights, len(stages), mismatch




