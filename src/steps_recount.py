# -*- coding: utf-8 -*-
"""按归属日及活动类型重算步数，供官方总步数核查。先合并同一时刻的累计值，再累加正增量。针对已核对的walking/running消息使用steps = cycles × 2；其他设备应核对SDK单位和活动类型。计数器重置可造成误差，正式总步数使用Connect日值。"""
import argparse
from pathlib import Path

import pandas as pd


def recount(series: pd.Series) -> float:
    """累计计数器 → 真实总量，容忍中途归零。"""
    s = series.dropna()
    if s.empty:
        return 0.0
    diffs = s.diff()
    diffs.iloc[0] = s.iloc[0]
    return float(diffs[diffs > 0].sum())


def main() -> int:
    ap = argparse.ArgumentParser(description="按 activity_type 分别重算日步数")
    ap.add_argument("csv_dir", help="fit2csv.py 的输出目录")
    ap.add_argument("-o", "--out", default="daily_steps.csv")
    args = ap.parse_args()

    d = pd.read_csv(Path(args.csv_dir) / "monitoring.csv", low_memory=False)
    subject = d["subject_id"].dropna().iloc[0] if "subject_id" in d and d["subject_id"].notna().any() else ""
    d["lt"] = pd.to_datetime(d["local_time"], format="mixed", utc=False)
    d = d.dropna(subset=["lt"]).sort_values("lt")
    d["day"] = (d["lt"] - pd.Timedelta(seconds=1)).dt.date

    # 相邻两天的导出包有重叠，同一时刻的同一条累计值会在多个 fit 里各出现一次。
    # 不先去重，重叠段会被当成「又涨了一轮」，总量能虚高一两倍。
    d = (d.groupby(["day", "activity_type", "lt"], dropna=False)
           [["cycles", "distance", "active_calories"]]
           .max().reset_index().sort_values("lt"))
    d["lt"] = pd.to_datetime(d["lt"], format="mixed")

    rows = []
    for (day, act), g in d.groupby(["day", "activity_type"], dropna=False):
        cyc = recount(g["cycles"])
        if cyc <= 0:
            continue
        rows.append({"local_date": day, "activity_type": act,
                     "cycles": cyc, "steps": cyc * 2,
                     "distance_m": recount(g["distance"]),
                     "active_calories": recount(g["active_calories"]),
                     "resets": int((g["cycles"].dropna().diff() < 0).sum())})
    per = pd.DataFrame(rows)
    if per.empty:
        pd.DataFrame(columns=["subject_id", "local_date", "steps_recount", "steps_walking", "steps_running"]).to_csv(args.out,index=False,encoding="utf-8-sig")
        return 0

    wide = per.pivot_table(index="local_date", columns="activity_type",
                           values="steps", aggfunc="sum").add_prefix("steps_")
    tot = per.groupby("local_date").agg(
        steps=("steps", "sum"), cycles=("cycles", "sum"),
        distance_m=("distance_m", "sum"),
        active_calories=("active_calories", "sum"),
        resets=("resets", "sum"))
    # 午夜 rollup 口径：当地 00:00:00 那条上写的当日总量，按 activity_type 求和。
    # 两种口径：rollup = 零点那条上的当日总量；recount = 分段累加。
    # 两种FIT核查口径均可能受计数器异常影响，不能保证构成官方值的上下界。
    # 正式总步数使用Connect日值，分项步数保留重算来源。
    roll = d[(d["lt"].dt.hour == 0) & (d["lt"].dt.minute == 0)
             & (d["lt"].dt.second == 0)]
    roll_sum = (roll.groupby(["day", "activity_type"])["cycles"].max()
                    .groupby("day").sum() * 2).rename("steps_rollup")

    out = tot.join(wide).join(roll_sum).round(1)
    out = out.rename(columns={"steps": "steps_recount"})
    order = ["steps_recount", "steps_rollup", "resets", "cycles",
             "distance_m", "active_calories"]
    out = out[[c for c in order if c in out] +
              [c for c in out.columns if c not in order]]
    if subject:
        out.insert(0, "subject_id", subject)

    out.to_csv(args.out, encoding="utf-8-sig")
    print(out.to_string())
    print(f"\n{len(out)} 行 → {args.out}")
    print("resets > 0 的日子计数器出过状况，两种口径都可能错，日步数请以download.py下载的官方值为准。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
