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

PLOT_DIR = os.path.join("plots", "ks")


def plot_path(name):
    os.makedirs(PLOT_DIR, exist_ok=True)
    return os.path.join(PLOT_DIR, name)

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


def plot_reversal(ks, boot):
    # 이 차트의 유일한 임무: "부품은 OpenFHE가 빠른데 완제품은 느리다"를 한눈에 보이기.
    # 형태 선택 — 단위가 다른 두 측정(단건 ms vs 부트스트래핑 s)을 한 축에 놓아야 하므로
    # 이중 축(금지)이 아니라 *공통 기준으로 정규화*한다: Lattigo = 1.0.
    # 그러면 1.0선을 기준으로 OpenFHE 막대가 아래(빠름)→위(느림)로 넘어가는 것이 곧 역전이다.
    if boot is None:
        sys.exit("[plot] 부트스트래핑 CSV가 없어 역전 차트를 그릴 수 없다 — --boot 확인")

    # (조건, 지표) -> (lattigo_us, openfhe_us)
    data = {}
    for cond in ("mt", "1core"):
        row = {}
        r = {lib: ks[(ks["cond"] == cond) & (ks["library"] == lib) & (ks["op"] == "rot1")]
             for lib in LIB_ORDER}
        b = {lib: boot[(boot["cond"] == cond) & (boot["library"] == lib)] for lib in LIB_ORDER}
        if any(d.empty for d in r.values()) or any(d.empty for d in b.values()):
            sys.exit(f"[plot] {cond} 조건의 rot1 또는 bootstrap 데이터가 없다")
        row["single key-switch\n(rot1)"] = {lib: r[lib].iloc[0]["mean_us"] for lib in LIB_ORDER}
        row["full bootstrap"] = {lib: b[lib].iloc[0]["mean_us"] for lib in LIB_ORDER}
        data[cond] = row

    fig, axes = plt.subplots(1, 2, figsize=(15, 7.5), sharey=True)
    # 코어 제한 메커니즘이 라이브러리마다 다르므로 제목에 병기한다
    # (OMP_NUM_THREADS는 Go에 무효 — Lattigo는 GOMAXPROCS를 쓴다).
    titles = {"mt": "4 cores\n(OMP_NUM_THREADS=4 / GOMAXPROCS=4)",
              "1core": "1 core\n(OMP_NUM_THREADS=1 / GOMAXPROCS=1)"}

    for ax, cond in zip(axes, ("mt", "1core")):
        metrics = list(data[cond].keys())
        x = range(len(metrics))
        width = 0.34
        for i, lib in enumerate(LIB_ORDER):
            # Lattigo를 1.0으로 정규화 → Lattigo 막대는 항상 1.0, OpenFHE는 배수.
            vals = [data[cond][m][lib] / data[cond][m]["lattigo"] for m in metrics]
            offset = (i - 0.5) * width
            ax.bar([xi + offset for xi in x], vals, width * 0.94,  # 0.94: 인접 막대 사이 여백
                   color=LIB_COLOR[lib], label=lib,
                   edgecolor="white", linewidth=1.6, zorder=3)
            for xi, v in zip(x, vals):
                # 1.0 미만 막대는 라벨을 막대 *안쪽*에 흰 글씨로. 바깥에 두면 1.0 기준선과
                # 겹쳐 선이 글자를 가로지른다.
                if v < 1.0:
                    ax.annotate(f"{v:.2f}x", (xi + offset, v), textcoords="offset points",
                                xytext=(0, -10), ha="center", va="top",
                                fontsize=17, fontweight="bold", color="white", zorder=5)
                else:
                    ax.annotate(f"{v:.2f}x", (xi + offset, v), textcoords="offset points",
                                xytext=(0, 7), ha="center", va="bottom",
                                fontsize=17, fontweight="bold", color="#222222", zorder=5)

        # 기준선 1.0 = Lattigo. 이 선을 넘느냐가 이야기의 전부다.
        ax.axhline(1.0, color="#555555", linestyle="--", linewidth=1.8, zorder=2)
        ax.set_xticks(list(x))
        ax.set_xticklabels(metrics)
        ax.set_title(titles[cond], pad=12, fontsize=16, linespacing=1.4)
        ax.grid(True, axis="y", color="0.9", linewidth=0.8, zorder=0)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)

    axes[0].set_ylabel("latency relative to Lattigo  (Lattigo = 1.0)")
    ymax = max(v[lib] / v["lattigo"] for c in data.values() for v in c.values() for lib in LIB_ORDER)
    axes[0].set_ylim(0, ymax * 1.42)  # 상단 여백: 값 라벨 + 범례 note 자리

    # 1.0선의 의미를 한 번만 명시. 막대·값라벨과 겹치지 않도록 좌상단 빈 영역에 둔다
    # (1.0선 근처는 Lattigo 막대와 "1.00x" 라벨이 차지해 충돌한다).
    axes[0].text(0.03, 0.955,
                 "above dashed line  =  OpenFHE slower\nbelow dashed line  =  OpenFHE faster",
                 transform=axes[0].transAxes, fontsize=14.5, color="#444444",
                 va="top", ha="left", linespacing=1.5,
                 bbox=dict(boxstyle="round,pad=0.5", facecolor="white",
                           edgecolor="#cccccc", linewidth=1.0))

    handles = [plt.Rectangle((0, 0), 1, 1, facecolor=LIB_COLOR[l], edgecolor="white", label=l)
               for l in LIB_ORDER]
    # 범례는 제목 아래·패널 위의 빈 띠에 가로로. 제목과 겹치지 않게 y를 분리한다.
    fig.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, 0.915),
               ncol=2, frameon=False, handlelength=1.6, columnspacing=2.2)
    fig.suptitle("The component is faster, the product is slower — OpenFHE vs Lattigo",
                 fontsize=22, y=0.975)
    fig.text(0.5, 0.055,
             "Same circuit (levelBudget {4,3}, 32768 slots) → both libraries perform "
             "the same number of key-switches.    rot1: reps=30,  bootstrap: reps=10.",
             ha="center", fontsize=14.5, color="#444444")
    fig.text(0.5, 0.017,
             "So the gap is not per-operation speed — it is what each library saves "
             "between operations (hoisting / lazy reduction).",
             ha="center", fontsize=14.5, color="#444444")
    fig.tight_layout(rect=[0, 0.09, 1, 0.895])
    out = plot_path("plot_ks_reversal.png")
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"[plot] {out}")


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

    plot_reversal(ks, boot)

    ks.to_csv(args.out, index=False)
    print(f"\n[merged] {args.out}  ({len(ks)} rows)")


if __name__ == "__main__":
    main()
