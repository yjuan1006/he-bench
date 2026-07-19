#!/usr/bin/env python3
# aggregate_boot.py — 부트스트래핑 벤치 CSV 집계 (8-op용 aggregate.py와 분리)
#
# 분리한 이유: 단위와 의미가 근본적으로 다르다.
#   - precision_bits 행은 μs가 아니라 *비트*를 담는다 (mean_us=평균, std_us=최악 슬롯)
#   - 레벨 표현이 in_level/out_level 이고 8-op의 level 스윕이 없다
#   - preset이 boot16 계열이라 8-op의 PRESET_ORDER/ALL_OPS/TIERS 전제가 성립하지 않는다
#
# 입력: results_boot2_*.csv (본 결과 4건) + *_sparse_robustness.csv (대조군 2건)
# 출력: results_boot_combined.csv + 콘솔 요약표
import argparse
import os
import sys

import pandas as pd

# 본 결과. 인용은 여기서만 한다.
MAIN_CSVS = [
    "results_boot2_lattigo_mt.csv",
    "results_boot2_lattigo_1core.csv",
    "results_boot2_openfhe_mt.csv",
    "results_boot2_openfhe_1core.csv",
]
# 대조군. 비밀키 분포가 본 결과와 다르므로 절대 섞지 않는다.
ROBUSTNESS_CSVS = [
    "results_boot_lattigo_sparse_robustness.csv",
    "results_boot_openfhe_sparse_robustness.csv",
]

REQUIRED_COLS = ["library", "preset", "in_level", "out_level", "op", "mean_us", "std_us"]
TIME_OPS = ["bootstrap", "btp_setup", "btp_keygen", "us_per_level"]


def read_boot_csv(path):
    # comment='#': 대조군 CSV 상단의 주석 2줄을 헤더로 오인하지 않게 한다.
    df = pd.read_csv(path, comment="#")
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        sys.exit(f"[schema] {path}: 필수 컬럼 없음 {missing} — 부트스트래핑 CSV가 아니다. "
                 f"8-op은 aggregate.py, key-switch 단건은 aggregate_ks.py를 쓸 것.")
    df["source"] = os.path.basename(path)
    return df


def load(paths, label):
    frames = []
    for p in paths:
        if not os.path.exists(p):
            print(f"[note] {p} 없음 — 건너뜀")
            continue
        frames.append(read_boot_csv(p))
    if not frames:
        return None
    df = pd.concat(frames, ignore_index=True)
    df["group"] = label
    return df


def fmt_time(us):
    # μs → 초. 부트스트래핑은 초 단위라 μs로 보면 자릿수만 늘어난다.
    return f"{us / 1e6:8.3f}"


def summary(df, title):
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")

    # 시간 지표: 초 단위 mean ± std
    piv = df[df["op"].isin(TIME_OPS)].pivot_table(
        index="source", columns="op", values="mean_us", observed=True)
    piv = piv.reindex(columns=[o for o in TIME_OPS if o in piv.columns])
    print("\n-- 시간 지표 (초) --")
    print(piv.map(lambda v: "—" if pd.isna(v) else f"{v / 1e6:.3f}").to_string())

    # bootstrap 표준편차는 따로 (변동성 확인용)
    bs = df[df["op"] == "bootstrap"]
    if not bs.empty:
        print("\n-- bootstrap 상세 --")
        for _, r in bs.iterrows():
            print(f"  {r['source']:<46} {r['mean_us'] / 1e6:7.3f} s "
                  f"± {r['std_us'] / 1e6:.3f}  (reps={int(r['reps'])})")

    # 정밀도: 비트. 시간과 절대 같은 표에 넣지 않는다.
    prec = df[df["op"] == "precision_bits"]
    if not prec.empty:
        print("\n-- 정밀도 (비트 — μs 아님) --")
        for _, r in prec.iterrows():
            print(f"  {r['source']:<46} 평균 {r['mean_us']:6.2f} 비트 / "
                  f"최악 {r['std_us']:6.2f} 비트")

    # 작업량·환경 지표
    meta_cols = [c for c in ["limbs_q", "limbs_p", "thread_mechanism", "in_level", "out_level"]
                 if c in df.columns]
    if meta_cols:
        print("\n-- 파라미터/환경 --")
        meta = df.groupby("source", observed=True)[meta_cols].first()
        print(meta.to_string())


def compare(df):
    # 같은 스레드 조건끼리 라이브러리 비율. 정밀도를 반드시 함께 출력한다 —
    # 지연시간만 보면 낮은 정밀도로 얻은 이득이 감춰진다.
    print(f"\n{'=' * 78}\nLattigo vs OpenFHE (같은 스레드 조건끼리)\n{'=' * 78}")
    bs = df[df["op"] == "bootstrap"]
    pr = df[df["op"] == "precision_bits"].set_index(["library", "thread_mechanism"]) \
        if "thread_mechanism" in df.columns else None

    for cond, mech in [("mt", "4"), ("1core", "1")]:
        rows = {}
        for lib in ("lattigo", "openfhe"):
            sub = bs[(bs["library"] == lib) & (bs["source"].str.contains(cond, regex=False))]
            if not sub.empty:
                rows[lib] = sub.iloc[0]
        if len(rows) != 2:
            continue
        lat, ofh = rows["lattigo"], rows["openfhe"]
        ratio = ofh["mean_us"] / lat["mean_us"]
        print(f"\n-- {cond} --")
        print(f"  lattigo {lat['mean_us'] / 1e6:7.3f} s   openfhe {ofh['mean_us'] / 1e6:7.3f} s"
              f"   → OpenFHE가 {ratio:.2f}배 느림")
        # 정밀도 동반 출력
        pl = df[(df["library"] == "lattigo") & (df["op"] == "precision_bits")
                & (df["source"].str.contains(cond, regex=False))]
        po = df[(df["library"] == "openfhe") & (df["op"] == "precision_bits")
                & (df["source"].str.contains(cond, regex=False))]
        if not pl.empty and not po.empty:
            gap = pl.iloc[0]["mean_us"] - po.iloc[0]["mean_us"]
            print(f"  정밀도  lattigo {pl.iloc[0]['mean_us']:.2f} 비트   "
                  f"openfhe {po.iloc[0]['mean_us']:.2f} 비트   → 격차 {gap:.2f} 비트")
            print(f"  ⚠ 동일 정밀도 지점의 비교가 아니다. 지연시간만 인용하지 말 것.")


def main():
    ap = argparse.ArgumentParser(description="부트스트래핑 벤치 CSV 집계")
    ap.add_argument("--main", nargs="+", default=MAIN_CSVS)
    ap.add_argument("--robustness", nargs="+", default=ROBUSTNESS_CSVS)
    ap.add_argument("--out", default="results_boot_combined.csv")
    args = ap.parse_args()

    main_df = load(args.main, "main")
    if main_df is None:
        sys.exit("본 결과 CSV가 하나도 없다 — 벤치를 먼저 실행할 것")
    summary(main_df, "본 결과 — 조밀키 boot16 (인용은 여기서)")
    compare(main_df)

    rc_df = load(args.robustness, "robustness")
    if rc_df is not None:
        summary(rc_df, "대조군 — 희소키 (본 결과와 섞지 말 것)")

    # 병합 저장. group 컬럼으로 본 결과/대조군을 구분해 둔다.
    allf = [d for d in (main_df, rc_df) if d is not None]
    out = pd.concat(allf, ignore_index=True)
    out.to_csv(args.out, index=False)
    print(f"\n[merged] {args.out}  ({len(out)} rows, group 컬럼으로 main/robustness 구분)")


if __name__ == "__main__":
    main()
