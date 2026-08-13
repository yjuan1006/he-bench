#!/usr/bin/env python3
"""부트스트래핑 1단계 — 두 라이브러리가 **동시에** 성립하는 (q0, Δ, 잔여L, levelBudget) 영역.

입력  explore/boot_params/boot_grid_{openfhe,lattigo}.csv        (잔여 L 3..14, 지정 격자)
      explore/boot_params/boot_grid_{openfhe,lattigo}_Lext.csv   (잔여 L 15..20, 보충 스윕)
      explore/boot_params/boot_galois_lattigo.csv                (분해깊이별 회전키 개수)
출력  explore/boot_params/boot_feasible.csv   +  boot_feasible.txt (콘솔 사본)

⚠️ **프리셋을 확정하지 않는다.** 이 표는 **2단계에서 실측할 후보 목록**이다.

선정 규칙 (2026-08-11 수정)
--------------------------
§8.5 규칙 7 의 "dnum 최소화"는 8-op 에서 **체인 길이가 고정된 상태**로 P 구성만 고를 때
확립된 규칙이다(근거: key-switch 런타임이 dnum 에 비례). 부트에서는 `levelBudget` 이
체인 길이 자체를 바꾸므로 그 전제가 깨진다 — 실제로 규칙을 그대로 적용하면 OpenFHE 최적이
**전부 `{1,1}`** 으로 몰린다(체인이 짧을수록 digit 이 줄어 dnum 이 작아진다). 그런데 `{1,1}`
은 선형변환을 인수분해 없이 도는 구성이라 회전키가 **383개**로 폭증한다(`{4,4}` 는 33개,
`boot_galois_lattigo.csv`). dnum 규칙이 보지 못하는 축이다.

  → **levelBudget(분해깊이)은 선정 규칙에서 제외한다.** 계산으로 우열을 정할 근거가 없다.
  → dnum/PCount 최소화는 **levelBudget 을 고정한 안에서만** 적용한다.
     OpenFHE : (dnum, logQP_boot) 오름차순
     Lattigo : (dnum, PCount_boot, logQP_boot) 오름차순  ← 규칙 7 의 "동률이면 P 작은 쪽"
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import respath  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTDIR = os.path.join(ROOT, "explore", "boot_params")
BOUND = 1747          # Bossuat et al., ePrint 2024/463, Table 5.2 (λ=128, uniform ternary, N=65536)
LEXT_MAX = 20         # 보충 스윕의 상한. 최대 L 이 여기 걸리면 답이 잘린 것이다
DNUM_CAP = 8          # 2단계 후보의 dnum 상한 — keygen 시간 통제 (§9.5: dnum 15 에서 9분 초과)

KEY = ["q0", "delta", "residual_L", "levelBudget_c2s", "levelBudget_s2c"]

_buf = []


def p(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    _buf.append(s)


def load(base):
    """지정 격자 + 보충 스윕을 합친다. 어느 쪽에서 왔는지 `grid` 열로 남긴다."""
    frames = []
    for name, tag in ((f"boot_grid_{base}.csv", "L3-14"),
                      (f"boot_grid_{base}_Lext.csv", "L15-20")):
        if not respath.exists(name):
            p(f"[경고] {name} 없음 — 그만큼 답이 잘린다")
            continue
        d = pd.read_csv(respath.find(name))
        d["grid"] = tag
        frames.append(d)
    return pd.concat(frames, ignore_index=True)


def main():
    of, la = load("openfhe"), load("lattigo")

    for name, d in (("openfhe", of), ("lattigo", la)):
        ok = d[d.ok == 1]
        if len(ok) and ok.logQP_boot.max() > BOUND:
            sys.exit(f"[모순] {name}: ok=1 인데 logQP_boot {ok.logQP_boot.max()} > {BOUND}")
        p(f"[{name}] 행 {len(d)} / ok=1 {len(ok)} / 잔여L 범위 "
          f"{int(ok.residual_L.min())}~{int(ok.residual_L.max())}")

    gal = pd.read_csv(respath.find("boot_galois_lattigo.csv"))
    galmap = {(int(r.c2s_depth), int(r.s2c_depth)): int(r.galois_total_with_conj)
              for _, r in gal.iterrows()}

    ofok = of[of.ok == 1].copy()
    laok = la[la.ok == 1].copy()

    # levelBudget 을 고정한 **안에서만** dnum/PCount 를 최소화한다.
    ofb = (ofok.sort_values(["dnum", "logQP_boot"])
                .groupby(KEY, as_index=False).first())
    lab = (laok.sort_values(["dnum", "PCount_boot", "logQP_boot"])
                .groupby(KEY, as_index=False).first())

    cols = ["boot_depth", "evalmod_levels", "QCount_boot", "logQ_boot", "PCount_boot", "logP_boot",
            "logQP_boot", "margin_1747", "dnum", "QCount_residual", "logQ_residual",
            "logQP_residual", "grid"]
    m = ofb[KEY + cols].merge(lab[KEY + cols], on=KEY, suffixes=("_of", "_la"))
    m["rotkeys_la"] = [galmap.get((int(a), int(b))) for a, b in
                       zip(m.levelBudget_c2s, m.levelBudget_s2c)]
    m["rotkeys_of"] = pd.NA      # keygen 없이 못 얻는다 (FindBootstrapRotationIndices 가 private)
    m = m.sort_values(KEY).reset_index(drop=True)

    os.makedirs(OUTDIR, exist_ok=True)
    f = os.path.join(OUTDIR, "boot_feasible.csv")
    m.to_csv(f, index=False)
    p(f"\n[feasible] {os.path.relpath(f, ROOT)}  ({len(m)}행 = (q0, Δ, L, levelBudget) 조합)")

    if m.empty:
        p("공통 가능 영역이 비었다.")
        return

    lbs = sorted(set(zip(m.levelBudget_c2s, m.levelBudget_s2c)))
    p(f"공통 levelBudget: {', '.join('{%d,%d}' % (a, b) for a, b in lbs)}")
    ofonly = sorted(set(zip(ofb.levelBudget_c2s, ofb.levelBudget_s2c)) - set(lbs))
    if ofonly:
        p(f"⚠️ OpenFHE 에만 있는 levelBudget: "
          f"{', '.join('{%d,%d}' % (a, b) for a, b in ofonly)} — Lattigo 격자 축(분해깊이 2~4) 밖이라 "
          f"공통 표에서 빠진다. 회전키 비용도 여기서 가장 나쁘다.")

    # ---- (a) levelBudget 별 최대 L ----------------------------------------
    p("\n=== (a) levelBudget 별 양쪽 동시 만족 잔여 L 의 최대 ===")
    p(f"{'levelBudget':>12}{'최대L':>7}{'회전키(LA)':>11}  나오는 (q0, Δ)")
    gmax = 0
    for a, b in lbs:
        g = m[(m.levelBudget_c2s == a) & (m.levelBudget_s2c == b)]
        mx = int(g.residual_L.max())
        gmax = max(gmax, mx)
        where = g[g.residual_L == mx][["q0", "delta"]].drop_duplicates()
        w = ", ".join(f"({int(r.q0)},{int(r.delta)})" for _, r in where.iterrows())
        p(f"{'{%d,%d}' % (a, b):>12}{mx:>7}{galmap.get((a, b), '-'):>11}  {w}")

    p(f"\n전역 최대 잔여 L = **{gmax}**")
    if gmax >= LEXT_MAX:
        p(f"⚠️⚠️ 보충 스윕 상한 {LEXT_MAX} 에 걸렸다 — 답이 잘렸다. 범위를 더 늘릴지 판단 필요.")
    else:
        p(f"보충 스윕 상한 {LEXT_MAX} 에 걸리지 않았다 — 격자 안에서 확정된 값이다.")

    # ---- (b) q0 를 낮추면 L 이 느는가 (levelBudget 고정) --------------------
    for ref in ((3, 3), (4, 4)):
        g = m[(m.levelBudget_c2s == ref[0]) & (m.levelBudget_s2c == ref[1])]
        if g.empty:
            continue
        p(f"\n=== (b) levelBudget {'{%d,%d}' % ref} 고정 — q0 별 Δ 별 최대 L ===")
        piv = g.groupby(["delta", "q0"]).residual_L.max().unstack("q0")
        p(f"{'Δ':>4}" + "".join(f"{'q0=' + str(int(c)):>8}" for c in piv.columns))
        for d, r in piv.iterrows():
            p(f"{int(d):>4}" + "".join(
                f"{(int(r[c]) if pd.notna(r[c]) else '-'):>8}" for c in piv.columns))
        for c in (45, 60):
            if c in piv.columns:
                v = piv[c].dropna()
                p(f"  q0={c}: 가능한 Δ {len(v)}개, 최대 L {int(v.max()) if len(v) else '-'}")

    # ---- (c) 부트 깊이 비대칭 ----------------------------------------------
    p("\n=== (c) levelBudget 별 부트 깊이 — OpenFHE vs Lattigo ===")
    p(f"{'levelBudget':>12}{'OF 깊이':>9}{'LA 깊이':>9}{'차':>5}"
      f"{'OF EvalMod':>12}{'LA EvalMod':>12}{'회전키(LA)':>11}")
    for a, b in lbs:
        g = m[(m.levelBudget_c2s == a) & (m.levelBudget_s2c == b)]
        ofd = sorted(g.boot_depth_of.unique())
        lad = sorted(g.boot_depth_la.unique())
        ofem = sorted(of[of.evalmod_levels.notna()].evalmod_levels.unique())
        laem = sorted(la[la.evalmod_levels.notna()].evalmod_levels.unique())
        p(f"{'{%d,%d}' % (a, b):>12}{int(ofd[0]):>9}{int(lad[0]):>9}"
          f"{int(ofd[0] - lad[0]):>5}{int(ofem[0]):>12}{int(laem[0]):>12}"
          f"{galmap.get((a, b), '-'):>11}")
    p("  → 같은 분해깊이에서 OpenFHE 가 항상 **+1** 이다. approxModDepth 14 vs EvalMod 13 의 차이 하나뿐이다.")

    # ---- 2단계 실측 후보 --------------------------------------------------
    # 조건: 분해깊이 2~4 (회전 비용이 감당되는 구간) · **양쪽 dnum ≤ 8** (keygen 시간 통제,
    # §9.5 의 dnum 15 keygen 9분 초과 이력) · Δ 는 자르지 않는다 (정밀도 곡선을 그려야 한다).
    c = m[(m.dnum_of <= DNUM_CAP) & (m.dnum_la <= DNUM_CAP)].copy()
    c = c.sort_values(["q0", "delta", "levelBudget_c2s", "levelBudget_s2c", "residual_L"])
    ccols = (KEY + ["boot_depth_of", "evalmod_levels_of", "evalmod_levels_la",
                    "logQ_boot_la",
                    "dnum_of", "PCount_boot_of", "logP_boot_of",
                    "logQP_boot_of", "margin_1747_of",
                    "boot_depth_la", "dnum_la", "PCount_boot_la", "logP_boot_la",
                    "logQP_boot_la", "margin_1747_la", "rotkeys_la", "grid_of", "grid_la"])
    fc = os.path.join(OUTDIR, "boot_stage2_candidates.csv")
    c[ccols].to_csv(fc, index=False)
    p(f"\n=== 2단계 실측 후보 (분해깊이 2~4, 양쪽 dnum ≤ {DNUM_CAP}, Δ 전 범위) ===")
    p(f"[후보] {os.path.relpath(fc, ROOT)}  ({len(c)}행 / 전체 {len(m)}행)")
    p(f"  (q0, Δ) {c.groupby(['q0','delta']).ngroups}쌍 · Δ {sorted(c.delta.unique().astype(int).tolist())}")
    p(f"{'q0':>4}{'Δ':>5}{'lb':>7}{'L범위':>9}{'OF dnum':>9}{'LA dnum':>9}"
      f"{'OF logQP':>10}{'LA logQP':>10}{'최소여유':>9}{'회전키LA':>9}")
    for (q, d, a, b), g in c.groupby(["q0", "delta", "levelBudget_c2s", "levelBudget_s2c"]):
        mn = min(g.margin_1747_of.min(), g.margin_1747_la.min())
        p(f"{int(q):>4}{int(d):>5}{'{%d,%d}' % (a, b):>7}"
          f"{f'{int(g.residual_L.min())}~{int(g.residual_L.max())}':>9}"
          f"{f'{int(g.dnum_of.min())}~{int(g.dnum_of.max())}':>9}"
          f"{f'{int(g.dnum_la.min())}~{int(g.dnum_la.max())}':>9}"
          f"{f'{int(g.logQP_boot_of.min())}~{int(g.logQP_boot_of.max())}':>10}"
          f"{f'{int(g.logQP_boot_la.min())}~{int(g.logQP_boot_la.max())}':>10}"
          f"{int(mn):>9}{int(g.rotkeys_la.iloc[0]):>9}")

    with open(os.path.join(OUTDIR, "boot_feasible.txt"), "w") as fh:
        fh.write("\n".join(_buf) + "\n")
    p("\n※ 프리셋 확정은 이 표로 하지 않는다 — 2단계 정밀도 측정이 있어야 한다.")


if __name__ == "__main__":
    main()
