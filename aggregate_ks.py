#!/usr/bin/env python3
# aggregate_ks.py — key-switch 단건 벤치 CSV 집계 (8-op용 aggregate.py와 분리)
#
# 분리한 이유: preset이 boot16-ks라 8-op의 PRESET_ORDER 전제가 성립하지 않고,
# 레벨 스윕 없이 최상위 레벨 1점만 측정하므로 TIERS 기반 레벨 그래프가 의미 없다.
# (op 이름과 maxLevel/level 컬럼은 8-op과 같아 육안 식별이 어렵다 — 그래서 더 분리가 필요하다.)
#
# 목적: 부트스트래핑 격차가 *단건 key-switch 성능* 차이인지 *조합 최적화* 차이인지 구분.
#   단건 비용비 ≈ 부트스트래핑 비용비  → 단건 성능 차이
#   단건은 비슷/역전인데 부트스트래핑만 벌어짐 → 조합 최적화(hoisting/lazy reduction) 차이
#
# 입력: results_ks_*.csv 4건 (+ 비교용 부트스트래핑 시간은 --boot로 선택 공급)
# 출력: results_ks_combined.csv + 콘솔 요약표
import argparse
import os
import sys

import pandas as pd

KS_CSVS = [
    "results_ks_lattigo_mt.csv",
    "results_ks_lattigo_1core.csv",
    "results_ks_openfhe_mt.csv",
    "results_ks_openfhe_1core.csv",
]
BOOT_CSVS = [
    "results_boot2_lattigo_mt.csv",
    "results_boot2_lattigo_1core.csv",
    "results_boot2_openfhe_mt.csv",
    "results_boot2_openfhe_1core.csv",
]

REQUIRED_COLS = ["library", "preset", "level", "op", "mean_us", "std_us"]
# rot1이 순수 key-switch 지표로 가장 깨끗하다 — rescale이 개입하지 않는다.
# mul 계열은 FLEXIBLEAUTO에서 자동 rescale을 포함하므로 비교에서 주의가 필요하다.
OPS = ["rot1", "relin", "mul_cc_rlk", "mul_cc"]


def read_ks_csv(path):
    df = pd.read_csv(path, comment="#")
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        sys.exit(f"[schema] {path}: 필수 컬럼 없음 {missing} — key-switch CSV가 아니다.")
    bad = sorted(set(df["preset"].astype(str)) - {"boot16-ks"})
    if bad:
        sys.exit(f"[schema] {path}: preset이 boot16-ks가 아니다 {bad} — "
                 f"8-op은 aggregate.py, 부트스트래핑은 aggregate_boot.py를 쓸 것.")
    df["source"] = os.path.basename(path)
    df["cond"] = "1core" if "1core" in os.path.basename(path) else "mt"
    return df


def load(paths, reader):
    frames = []
    for p in paths:
        if not os.path.exists(p):
            print(f"[note] {p} 없음 — 건너뜀")
            continue
        frames.append(reader(p))
    return pd.concat(frames, ignore_index=True) if frames else None


def read_boot_csv(path):
    df = pd.read_csv(path, comment="#")
    df = df[df["op"] == "bootstrap"].copy()
    df["cond"] = "1core" if "1core" in os.path.basename(path) else "mt"
    return df


def main():
    ap = argparse.ArgumentParser(description="key-switch 단건 벤치 CSV 집계")
    ap.add_argument("--ks", nargs="+", default=KS_CSVS)
    ap.add_argument("--boot", nargs="+", default=BOOT_CSVS,
                    help="부트스트래핑 CSV (등가 환산용, 없으면 단건 표만 출력)")
    ap.add_argument("--out", default="results_ks_combined.csv")
    args = ap.parse_args()

    ks = load(args.ks, read_ks_csv)
    if ks is None:
        sys.exit("key-switch CSV가 하나도 없다 — 벤치를 먼저 실행할 것")

    meta = ks.groupby("source", observed=True)[
        [c for c in ["limbs_q", "limbs_p", "thread_mechanism", "maxLevel"] if c in ks.columns]
    ].first()
    print(f"\n{'=' * 78}\nkey-switch 단건 (logN 16 / boot16 체인, 최상위 레벨)\n{'=' * 78}")
    print(meta.to_string())

    print("\n-- 단건 비용 (ms) --")
    print(f"{'조건':<8}{'op':<13}{'Lattigo':>11}{'OpenFHE':>11}{'비율(O/L)':>12}")
    for cond in ("mt", "1core"):
        for op in OPS:
            l = ks[(ks["cond"] == cond) & (ks["library"] == "lattigo") & (ks["op"] == op)]
            o = ks[(ks["cond"] == cond) & (ks["library"] == "openfhe") & (ks["op"] == op)]
            if l.empty or o.empty:
                continue
            lv, ov = l.iloc[0]["mean_us"] / 1000, o.iloc[0]["mean_us"] / 1000
            print(f"{cond:<8}{op:<13}{lv:>11.1f}{ov:>11.1f}{ov / lv:>12.3f}")
        print()

    # 등가 환산: 부트스트래핑 1회 = rot1 몇 회분인가.
    # 회로가 요구하는 key-switch 횟수는 양쪽이 같으므로, 이 값의 차이가 곧 조합 최적화 차이다.
    boot = load(args.boot, read_boot_csv)
    if boot is not None:
        print(f"{'=' * 78}\n부트스트래핑 1회 = rot1 몇 회분인가 (조합 최적화 지표)\n{'=' * 78}")
        print(f"{'조건':<8}{'Lattigo':>12}{'OpenFHE':>12}{'비율':>10}   해석")
        for cond in ("mt", "1core"):
            res = {}
            for lib in ("lattigo", "openfhe"):
                b = boot[(boot["cond"] == cond) & (boot["library"] == lib)]
                r = ks[(ks["cond"] == cond) & (ks["library"] == lib) & (ks["op"] == "rot1")]
                if b.empty or r.empty:
                    continue
                res[lib] = b.iloc[0]["mean_us"] / r.iloc[0]["mean_us"]
            if len(res) != 2:
                continue
            ratio = res["openfhe"] / res["lattigo"]
            note = "조합 최적화 차이" if ratio > 1.2 else "단건 성능 차이"
            print(f"{cond:<8}{res['lattigo']:>12.1f}{res['openfhe']:>12.1f}{ratio:>10.2f}   {note}")
        print("\n  회로가 요구하는 key-switch 횟수는 양쪽이 동일하다(같은 levelBudget·슬롯 수).")
        print("  따라서 이 등가 횟수의 차이 = 연산 사이에서 절약되는 양의 차이")
        print("  (hoisting: 분해 단계 공유 / lazy reduction: 중간 모듈러 축약 생략).")

    ks.to_csv(args.out, index=False)
    print(f"\n[merged] {args.out}  ({len(ks)} rows)")


if __name__ == "__main__":
    main()
