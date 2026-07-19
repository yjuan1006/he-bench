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

import matplotlib
matplotlib.use("Agg")  # 헤드리스: 파일로만 저장
import matplotlib.pyplot as plt
import pandas as pd

# 발표용 — aggregate.py보다 한 단계 더 키움.
plt.rcParams.update({
    "axes.titlesize": 20, "axes.labelsize": 18,
    "xtick.labelsize": 17, "ytick.labelsize": 16,
    "legend.fontsize": 17, "figure.titlesize": 23,
})

# aggregate.py와 동일한 Okabe-Ito 팔레트 (엔티티=색, 순위 아님).
# validate_palette 6검사 통과: CVD adjacent ΔE=21.9 / normal ΔE=31.2 / contrast >= 3:1.
# 차트 텍스트는 영문 — 이 환경에 한글 폰트가 없어 한글은 두부박스로 렌더된다.
LIB_COLOR = {"lattigo": "#0072B2", "openfhe": "#D55E00"}
LIB_ORDER = ["lattigo", "openfhe"]

PLOT_DIR = os.path.join("plots", "boot")


def plot_path(name):
    os.makedirs(PLOT_DIR, exist_ok=True)
    return os.path.join(PLOT_DIR, name)

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


def _pick(df, lib, cond, op):
    """(라이브러리, 스레드조건, op) 한 행. 없으면 None."""
    sub = df[(df["library"] == lib) & (df["op"] == op)
             & (df["source"].str.contains(cond, regex=False))]
    return None if sub.empty else sub.iloc[0]


def plot_boot_summary(df):
    # 4조건 막대, 초 단위, 에러바 = 표준편차.
    # 정밀도는 *절대* 같은 축에 넣지 않는다 — 단위가 다른 두 측정을 한 축에 놓으면
    # 두 스케일의 정렬이 임의라 없는 상관을 만들어낸다(이중 축 금지와 같은 이유).
    # 대신 막대 위 텍스트 라벨로만 병기한다.
    fig, ax = plt.subplots(figsize=(11, 7.5))
    conds = ["mt", "1core"]
    cond_label = {"mt": "4 cores", "1core": "1 core"}
    x = range(len(conds))
    width = 0.36
    ymax = 0.0

    for i, lib in enumerate(LIB_ORDER):
        means, errs, precs = [], [], []
        for c in conds:
            b = _pick(df, lib, c, "bootstrap")
            p = _pick(df, lib, c, "precision_bits")
            if b is None:
                sys.exit(f"[plot] {lib}/{c} bootstrap 행이 없다")
            means.append(b["mean_us"] / 1e6)
            errs.append(b["std_us"] / 1e6)
            precs.append(None if p is None else p["mean_us"])
        offset = (i - 0.5) * width
        ax.bar([xi + offset for xi in x], means, width * 0.94,
               yerr=errs, capsize=5, error_kw={"elinewidth": 1.4, "alpha": 0.75},
               color=LIB_COLOR[lib], label=lib, edgecolor="white", linewidth=1.6, zorder=3)
        for xi, m, e, pr in zip(x, means, errs, precs):
            ax.annotate(f"{m:.1f} s", (xi + offset, m + e), textcoords="offset points",
                        xytext=(0, 7), ha="center", va="bottom",
                        fontsize=18, fontweight="bold", color="#222222", zorder=5)
            if pr is not None:
                # 정밀도는 축이 아니라 라벨. 단위(bit)를 반드시 붙여 초와 혼동되지 않게 한다.
                ax.annotate(f"{pr:.1f} bit", (xi + offset, m + e), textcoords="offset points",
                            xytext=(0, 30), ha="center", va="bottom",
                            fontsize=14.5, color="#666666", zorder=5)
            ymax = max(ymax, m + e)

    ax.set_xticks(list(x))
    ax.set_xticklabels([cond_label[c] for c in conds])
    ax.set_ylabel("bootstrap latency (seconds)")
    ax.set_ylim(0, ymax * 1.30)
    ax.grid(True, axis="y", color="0.9", linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(title="library", loc="upper left", frameon=False)

    fig.suptitle("CKKS bootstrapping latency — preset boot16 (logN 16, 32768 slots)",
                 fontsize=21, y=0.975)
    fig.text(0.5, 0.072,
             "Error bars: sample std (n-1), reps=10.  "
             "Gray label = mean precision, not plotted on the axis.",
             ha="center", fontsize=14.5, color="#444444")
    # 이전 캡션은 "(scale 2^45 vs 2^59)"를 나란히 적어 스케일이 정밀도 격차의 원인인 것처럼
    # 읽혔다. 실제로는 인과가 반대다 — 스케일이 *더 큰* OpenFHE가 정밀도는 더 낮다.
    fig.text(0.5, 0.040,
             "Precision differs by ~17 bits — this is not a scale-factor effect:",
             ha="center", fontsize=14.5, color="#444444")
    fig.text(0.5, 0.008,
             "OpenFHE uses the larger scale (2^59 vs 2^45) yet is the less precise one.",
             ha="center", fontsize=14.5, color="#444444")
    fig.tight_layout(rect=[0, 0.105, 1, 0.94])
    out = plot_path("plot_boot_summary.png")
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"[plot] {out}")


def plot_boot_density(main_df, rc_df):
    # 조밀/희소 2x2. 희소는 *대조군*이며 파라미터 세트 전체가 다르다는 경고가 필수다.
    if rc_df is None:
        print("[note] 대조군 CSV가 없어 density 차트를 건너뜀")
        return
    fig, ax = plt.subplots(figsize=(12, 7.8))
    groups = ["dense (main)", "sparse (control)"]
    x = range(len(groups))
    width = 0.36
    ymax = 0.0

    for i, lib in enumerate(LIB_ORDER):
        means, precs = [], []
        for src_df, cond in ((main_df, "mt"), (rc_df, "sparse")):
            b = _pick(src_df, lib, cond, "bootstrap")
            p = _pick(src_df, lib, cond, "precision_bits")
            if b is None:
                sys.exit(f"[plot] {lib} {cond} bootstrap 행이 없다")
            means.append(b["mean_us"] / 1e6)
            precs.append(None if p is None else p["mean_us"])
        offset = (i - 0.5) * width
        ax.bar([xi + offset for xi in x], means, width * 0.94,
               color=LIB_COLOR[lib], label=lib, edgecolor="white", linewidth=1.6, zorder=3)
        for xi, m, pr in zip(x, means, precs):
            ax.annotate(f"{m:.1f} s", (xi + offset, m), textcoords="offset points",
                        xytext=(0, 7), ha="center", va="bottom",
                        fontsize=18, fontweight="bold", color="#222222", zorder=5)
            if pr is not None:
                ax.annotate(f"{pr:.1f} bit", (xi + offset, m), textcoords="offset points",
                            xytext=(0, 30), ha="center", va="bottom",
                            fontsize=14.5, color="#666666", zorder=5)
            ymax = max(ymax, m)

    ax.set_xticks(list(x))
    ax.set_xticklabels(groups)
    ax.set_ylabel("bootstrap latency (seconds)")
    ax.set_ylim(0, ymax * 1.22)
    ax.grid(True, axis="y", color="0.9", linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(title="library", loc="upper left", frameon=False)

    fig.suptitle("Secret-key density: main result vs control group", fontsize=21, y=0.985)
    # 필수 경고: 희소 쪽은 비밀키 분포만 바뀐 것이 아니다.
    # 축 *바깥* 배너로 둔다 — 축 안에 두면 범례·값라벨과 충돌한다.
    fig.text(0.5, 0.905,
             "CAUTION — the two sparse bars are NOT a single-variable change.\n"
             "Lattigo sparse swaps the whole preset (N16QP1546H192H32: scale 2^40, depth 15);\n"
             "OpenFHE sparse changes only SecretKeyDist.",
             ha="center", va="top", fontsize=13, color="#7a3b00", linespacing=1.6,
             bbox=dict(boxstyle="round,pad=0.55", facecolor="#fff4e8",
                       edgecolor="#D55E00", linewidth=1.4))
    fig.text(0.5, 0.072, "Gray label = mean precision (bits), not plotted on the axis.",
             ha="center", fontsize=14.5, color="#444444")
    # 이전 캡션("faster AND more precise")은 Lattigo에 대해 거짓이었다 — 차트에 찍힌
    # 29.7 → 27.3 bit와 정면으로 모순. 정밀도는 두 라이브러리에서 반대 방향으로 움직인다.
    fig.text(0.5, 0.040,
             "Sparse is faster for both, but precision moves in opposite directions "
             "(OpenFHE +6.4 bit, Lattigo -2.4 bit).",
             ha="center", fontsize=14.5, color="#444444")
    fig.text(0.5, 0.008, "The cost is the security assumption.",
             ha="center", fontsize=14.5, color="#444444")
    fig.tight_layout(rect=[0, 0.105, 1, 0.815])
    out = plot_path("plot_boot_density.png")
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"[plot] {out}")


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

    plot_boot_summary(main_df)
    plot_boot_density(main_df, rc_df)

    # 병합 저장. group 컬럼으로 본 결과/대조군을 구분해 둔다.
    allf = [d for d in (main_df, rc_df) if d is not None]
    out = pd.concat(allf, ignore_index=True)
    out.to_csv(args.out, index=False)
    print(f"\n[merged] {args.out}  ({len(out)} rows, group 컬럼으로 main/robustness 구분)")


if __name__ == "__main__":
    main()
