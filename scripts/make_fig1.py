#!/usr/bin/env python3
"""make_fig1.py — CISC-W'26 그림 1: 프리셋 A, mul_cc_rlk, 세 라이브러리 레벨-비용 곡선.

**읽기 전용.** explore/v3_summary_timing.csv 만 읽는다(재생성·수정 없음).
평활·보간·이상치 제거 없이 12개 실측점을 그대로 잇는다.

산출:
  figures/fig1_preset_A_mul_cc_rlk.pdf  (벡터, 조판용)
  figures/fig1_preset_A_mul_cc_rlk.png  (300dpi, 미리보기)

캡션(확정, 논문 본문에 들어감 — 그림 안에는 제목을 넣지 않는다):
  [그림 1] 같은 조건, 다른 형태. OpenFHE와 Lattigo는 음영 구간(decomposition 전이)에서
  곡선이 꺾이지만 SEAL은 전 구간에서 매끄럽다. 프리셋 A, mul_cc_rlk, 로그 스케일.
  세 라이브러리의 Q-체인이 동일하므로 가로축의 같은 위치는 같은 잔여 타워 수를 뜻한다.
"""
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.path.join(ROOT, "explore", "v3_summary_timing.csv")
OUTDIR = os.path.join(ROOT, "figures")

# ── 한글 폰트 ────────────────────────────────────────────────────────────
# 서버에 fonts-nanum 을 설치해 사용(2026-09-02). 없으면 영문 레이블로 대체하고 보고한다.
KOFONT_PATH = "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"
USE_KOREAN = os.path.exists(KOFONT_PATH)
if USE_KOREAN:
    fm.fontManager.addfont(KOFONT_PATH)
    KOFONT_NAME = fm.FontProperties(fname=KOFONT_PATH).get_name()
    matplotlib.rcParams["font.family"] = KOFONT_NAME
matplotlib.rcParams["axes.unicode_minus"] = False

LABEL_X = "잔여 레벨 L" if USE_KOREAN else "Remaining level L"
LABEL_Y = ("mul_cc_rlk 지연시간 (μs, 로그 스케일)" if USE_KOREAN
           else "mul_cc_rlk latency (μs, log scale)")

# ── 데이터 ───────────────────────────────────────────────────────────────
d = pd.read_csv(CSV)
sub = d[(d["mode"] == "1t") & (d.preset == "A") & (d.op == "mul_cc_rlk")].copy()
assert len(sub) == 36, f"기대 36행(12레벨x3라이브러리), 실제 {len(sub)}"

LIBS = [
    ("openfhe", "OpenFHE", "-", "o"),
    ("lattigo", "Lattigo", "--", "s"),
    ("seal",    "SEAL",    ":",  "^"),
]

series = {}
for lib, _, _, _ in LIBS:
    g = sub[sub.library == lib].sort_values("level", ascending=False)
    assert list(g.level) == list(range(12, 0, -1)), f"{lib}: 레벨 12..1 전부가 아니다"
    series[lib] = g

# digit 전이 확인 — OpenFHE/Lattigo 동일, 정확히 2곳(L10->L9, L5->L4)
for lib in ("openfhe", "lattigo"):
    seq = list(series[lib].digit.astype(int))
    assert seq == [3, 3, 3, 2, 2, 2, 2, 2, 1, 1, 1, 1], f"{lib} digit 수열 불일치: {seq}"
seal_seq = list(series["seal"].digit.astype(int))
assert seal_seq == list(range(13, 1, -1)), f"seal digit 수열(L+1) 불일치: {seal_seq}"

TRANSITIONS = [(10, 9, "3→2"), (5, 4, "2→1")]  # (레벨 상단, 레벨 하단, 라벨)

# ── 검증 출력: 12x3 값 ───────────────────────────────────────────────────
print("=== 플롯 데이터 (level, OpenFHE, Lattigo, SEAL) ===")
for L in range(12, 0, -1):
    row = [f"{series[lib].set_index('level').loc[L, 'mean_us']:.0f}" for lib, _, _, _ in LIBS]
    print(f"L{L:<3d} " + "  ".join(f"{lib}={v}" for (lib, _, _, _), v in zip(LIBS, row)))

# ── 그림 ─────────────────────────────────────────────────────────────────
plt.rcParams.update({
    "font.size": 8,
    "axes.labelsize": 8,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "legend.fontsize": 7.5,
})

fig, ax = plt.subplots(figsize=(2.85, 2.15))

for lib, label, ls, marker in LIBS:
    g = series[lib]
    ax.plot(g.level, g.mean_us, linestyle=ls, marker=marker, markersize=3.2,
             linewidth=1.1, color="black" if lib == "seal" else None,
             label=label, zorder=3)

# 음영 밴드 — digit 전이 구간(OpenFHE/Lattigo 공통, 2곳뿐)
for hi, lo, lab in TRANSITIONS:
    ax.axvspan(lo, hi, color="grey", alpha=0.18, zorder=1, linewidth=0)
    ax.text((hi + lo) / 2, 1.0, lab, transform=ax.get_xaxis_transform(),
            ha="center", va="bottom", fontsize=6.5, color="dimgrey")

ax.set_yscale("log")
ax.set_xlim(12.5, 0.5)          # 왼쪽 12, 오른쪽 1
ax.set_xticks(range(12, 0, -1))
ax.set_xlabel(LABEL_X)
ax.set_ylabel(LABEL_Y)

# y축: 원 단위(μs) 대신 k 단위로 짧게 표기 — 좁은 폭에서 자리를 아낀다
YTICKS = [5000, 10000, 20000, 50000, 100000]
ax.set_yticks(YTICKS)
ax.yaxis.set_major_formatter(mticker.FuncFormatter(
    lambda v, _: f"{v/1000:g}k" if v >= 1000 else f"{v:g}"))
ax.yaxis.set_minor_locator(mticker.NullLocator())
ax.set_ylim(5000, 110000)

ax.grid(axis="y", which="major", linewidth=0.3, alpha=0.25, zorder=0)
for spine in ("top", "right"):
    ax.spines[spine].set_visible(False)

ax.legend(loc="upper right", frameon=False, handlelength=1.6, handletextpad=0.4,
          labelspacing=0.25, borderaxespad=0.2)

fig.tight_layout(pad=0.15)

os.makedirs(OUTDIR, exist_ok=True)
pdf_path = os.path.join(OUTDIR, "fig1_preset_A_mul_cc_rlk.pdf")
png_path = os.path.join(OUTDIR, "fig1_preset_A_mul_cc_rlk.png")
fig.savefig(pdf_path, bbox_inches="tight")
fig.savefig(png_path, dpi=300, bbox_inches="tight")

print(f"\n[saved] {pdf_path} ({os.path.getsize(pdf_path)} bytes)")
print(f"[saved] {png_path} ({os.path.getsize(png_path)} bytes)")
print(f"[font] Korean font used: {USE_KOREAN} "
      f"({KOFONT_NAME if USE_KOREAN else 'fallback to English labels'})")
