#!/usr/bin/env python3
"""level_cost_profile.py — v3 8-op 데이터로 논문 4절 주장 (A)(B)(C)(D)를 판정한다.

**분석 전용.** 새 측정을 돌리지 않고 `explore/v3_summary_*.csv` 만 읽는다(읽기 전용).

판정 대상
  (A) 저레벨 포화 — OpenFHE 는 특수소수 P 를 레벨과 무관하게 고정 운반하므로
      타워가 줄수록 고정비 비중이 커져 "내려도 덜 빨라지는" 구간이 생기는가.
      SEAL 은 60비트 1개뿐이라 그 현상이 없어야 한다.
  (B) SEAL 의 매끄러움 — level↔digit 관계에 계단이 없는가.
      ⚠️ digit 열의 **정의가 라이브러리마다 다르다**(아래 DIGIT_DEF 주석).
  (C) 계단 크기 전수 재산출 — 계단 전이 / 비계단 구간의 g(L) 분포.
  (D) mt 행의 reps 실태 — 단일 실행인가 다중 실행 median 인가.

출력
  analysis/out/level_cost_report.md   주장별 판정 + 근거 표
  analysis/out/g_table.csv            인접 레벨쌍 g(L) 전수
  analysis/out/fit_coeffs.csv         mean_us ≈ a·(L+1)·digit + b 적합 계수
  analysis/out/step_classification.csv  preset×library 의 level↔digit 표 + 전이 표시
  analysis/out/step_ratio_summary.csv   계단/비계단 g(L) 요약
  analysis/out/reps_audit.csv           mode×library reps 분포
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import respath  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "analysis", "out")

# key-switch 를 실제로 수행하는 연산. digit 수가 비용에 직접 들어가는 것은 이 셋뿐이다.
#   rot1        자동사상 후 키스위치 1회
#   relin       size-3 → size-2 키스위치 1회 (단독 계측)
#   mul_cc_rlk  텐서곱 + 키스위치 1회
KS_OPS = ["rot1", "relin", "mul_cc_rlk"]
# 대조군 — 키스위치가 없어 digit 과 무관해야 한다. mul_cc 는 relin 없는 텐서곱,
# rescale 은 모듈러스 드롭이라 둘 다 키스위치를 타지 않는다.
NONKS_OPS = ["add_cc", "add_cp", "mul_cp", "mul_cc", "rescale"]

CV_GATE = 0.05          # 이 값을 넘는 행은 측정 오염 가능성 — 게이트에 걸고 건수를 보고한다
CV_POLLUTED = 0.20      # 비정상 산포. 별도 표기(DVFS/스케줄링 오염 의심)

# ─────────────────────────────────────────────────────────────────────────────
# digit 열의 라이브러리별 정의 (소스 확인 결과 — 2026-08-19)
#   src/presetsearch_openfhe.cpp:216-222
#       parts = min(dnum, ceil((L+1)/perPart)),  dnum=GetNumPartQ(), perPart=GetNumPerPartQ()
#       → OpenFHE 하이브리드 키스위치의 **실제 digit 수**. dnum 에서 포화하는 계단.
#   src/presetsearch_lattigo.go:283-288
#       p = min(dnum, ceil((L+1)/len(P)))
#       → 같은 형태지만 perPart 자리에 **특수소수 개수 len(P)** 를 넣은 재구성값이다.
#         Lattigo 는 digit 수를 노출하는 API 가 없어 하이브리드 규칙을 밖에서 재현했다.
#   src/presetsearch_seal.cpp:169-171
#       digit = L + 1  (무조건)
#       → SEAL 은 특수소수가 항상 1개이고 digit 을 Q 프라임 1개씩 쪼개므로
#         "digit 수 = 해당 레벨의 Q 프라임 수 = level+1". **계산이 아니라 항등식이다.**
# ⚠️ 따라서 세 열은 같은 이름이지만 같은 양이 아니다. 특히 SEAL 의 digit 은
#    데이터에서 관측된 값이 아니라 level 의 재표기이므로, "SEAL 은 계단이 없다"를
#    이 열로 확인하는 것은 **동어반복**이다. 아래 (B) 에서 그대로 보고한다.
DIGIT_DEF = {
    "openfhe": "min(dnum, ceil((L+1)/perPart)) — 런타임 GetNumPartQ/GetNumPerPartQ 기반 (실제 digit 수)",
    "lattigo": "min(dnum, ceil((L+1)/#P)) — API 부재로 하이브리드 규칙을 밖에서 재구성",
    "seal":    "L+1 — 항등식(특수소수 1개, Q 프라임 1개당 digit 1개). 관측값 아님",
}


def pearson(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    if len(x) < 3 or x.std() == 0 or y.std() == 0:
        return np.nan, len(x)
    return float(np.corrcoef(x, y)[0, 1]), len(x)


def spearman(x, y):
    s = pd.DataFrame({"x": x, "y": y}).dropna()
    if len(s) < 3:
        return np.nan, len(s)
    rx, ry = s.x.rank(), s.y.rank()
    if rx.std() == 0 or ry.std() == 0:
        return np.nan, len(s)
    return float(np.corrcoef(rx, ry)[0, 1]), len(s)


def ols_fit(x, y):
    """y = a·x + b 최소제곱. (a, b, R2, n, rmse_rel) 반환."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 3 or np.ptp(x) == 0:
        return np.nan, np.nan, np.nan, len(x), np.nan
    a, b = np.polyfit(x, y, 1)
    pred = a * x + b
    ss_res = float(((y - pred) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan
    rmse_rel = float(np.sqrt(ss_res / len(x)) / y.mean())
    return float(a), float(b), r2, len(x), rmse_rel


def md_table(df, floatfmt="{:.4g}"):
    """pandas → GitHub markdown 표 (tabulate 없이)."""
    d = df.copy()
    for c in d.columns:
        if pd.api.types.is_float_dtype(d[c]):
            d[c] = d[c].map(lambda v: "" if pd.isna(v) else floatfmt.format(v))
        else:
            d[c] = d[c].astype(str)
    cols = list(d.columns)
    lines = ["| " + " | ".join(cols) + " |",
             "|" + "|".join("---" for _ in cols) + "|"]
    for _, r in d.iterrows():
        lines.append("| " + " | ".join(r[c] for c in cols) + " |")
    return "\n".join(lines)


def qsum(s):
    """분포 요약 — 최소/중앙/최대 + 사분위."""
    s = pd.Series(s).dropna()
    if len(s) == 0:
        return dict(n=0, min=np.nan, q25=np.nan, med=np.nan, q75=np.nan, max=np.nan)
    return dict(n=len(s), min=float(s.min()), q25=float(s.quantile(.25)),
                med=float(s.median()), q75=float(s.quantile(.75)), max=float(s.max()))


# ═════════════════════════════════════════════════════════════════════════════
def main():
    rep = []          # 보고서 줄 모음
    def w(*a):
        rep.append(" ".join(str(x) for x in a))

    src = respath.find("v3_summary_timing.csv")
    d = pd.read_csv(src)
    os.makedirs(OUT, exist_ok=True)

    w("# 레벨-비용 프로파일 재분석 — 논문 4절 주장 (A)(B)(C)(D) 사전 검증")
    w("")
    w(f"입력: `{os.path.relpath(src, ROOT)}`  ({len(d)}행 × {d.shape[1]}열, 읽기 전용)")
    w("생성: `analysis/level_cost_profile.py` — 새 측정 없음, 기존 데이터만 사용")
    w("")
    w("---")
    w("")

    # ── 0. 행 수 회계 ────────────────────────────────────────────────────────
    w("## 0. 행 수 회계 (필터 단계별)")
    w("")
    presets = d.groupby("preset")["depth"].first().to_dict()
    libs = sorted(d.library.unique())
    modes = sorted(d["mode"].unique())
    ops = sorted(d.op.unique())
    n_expect = sum(dep * len(libs) * len(modes) * len(ops) for dep in presets.values())
    w(f"- 프리셋 {list(presets.items())} (preset→depth=maxLevel)")
    w(f"- 라이브러리 {libs} · 모드 {modes} · op {len(ops)}종 {ops}")
    w(f"- 기대 행 수 = Σ(depth) × lib3 × mode2 × op8 = {n_expect}  →  실제 **{len(d)}행** "
      f"({'일치' if n_expect == len(d) else '불일치 ⚠️'})")
    w("")

    # 레벨 연속성 확인
    gaps = []
    for k, g in d.groupby(["preset", "mode", "library", "op"]):
        lv = sorted(g.level.unique())
        if lv != list(range(min(lv), max(lv) + 1)):
            gaps.append((k, lv))
        if len(lv) != len(g):
            gaps.append((k, "중복 레벨"))
    w(f"- 레벨 연속성: {len(d.groupby(['preset','mode','library','op']))}개 그룹 전수 확인 → "
      f"결측/중복 **{len(gaps)}건**" + ("" if not gaps else f" ⚠️ {gaps[:5]}"))
    w(f"- 각 프리셋 레벨 범위: " + ", ".join(
        f"{p}=1..{v}" for p, v in sorted(presets.items())))
    w("")

    ks = d[d.op.isin(KS_OPS)]
    nks = d[d.op.isin(NONKS_OPS)]
    w(f"- key-switch 포함 op {KS_OPS} → **{len(ks)}행** "
      f"(= {len(d)} × 3/8 = {len(d)*3//8})")
    w(f"- key-switch 없는 op(대조군) {NONKS_OPS} → **{len(nks)}행**")
    w("")

    # cv 게이트 현황
    w("### cv 게이트 현황 (임계 cv > %.2f)" % CV_GATE)
    w("")
    gate = (d.assign(gated=d.cv > CV_GATE, polluted=d.cv > CV_POLLUTED)
              .groupby(["mode", "library"])
              .agg(n=("cv", "size"), gated=("gated", "sum"), polluted=("polluted", "sum"),
                   cv_med=("cv", "median"), cv_max=("cv", "max")).reset_index())
    gate["gated_pct"] = 100 * gate.gated / gate.n
    w(md_table(gate[["mode", "library", "n", "gated", "gated_pct", "polluted", "cv_med", "cv_max"]]))
    w("")
    w(f"> 게이트에 걸린 행은 **버리지 않고 표시만** 한다. cv > {CV_POLLUTED} 인 행은 "
      "측정 오염(DVFS/스케줄링) 의심으로 `polluted` 로 따로 센다.")
    w("")

    # ── 1. digit 정의 감사 (B-2 선행) ────────────────────────────────────────
    w("---")
    w("")
    w("## 1. ⚠️ `digit` 열의 라이브러리별 정의 감사 (B-2 — 다른 모든 판정의 전제)")
    w("")
    w("`scripts/v3_unify.py` 는 원본 CSV 의 `digits` 문자열(`L12=3;L11=3;…`)을 레벨별로 펼 뿐이고, "
      "그 문자열은 **각 벤치 하네스가 서로 다른 규칙으로** 만든다.")
    w("")
    dd = pd.DataFrame([{"library": k, "digit 정의 (소스 근거)": v} for k, v in DIGIT_DEF.items()])
    w(md_table(dd))
    w("")
    w("근거 위치: `src/presetsearch_openfhe.cpp:216-222` · `src/presetsearch_lattigo.go:283-288` · "
      "`src/presetsearch_seal.cpp:169-171`")
    w("")
    # 실증 확인
    chk = []
    for (p, lib), g in d[d["mode"] == "1t"].groupby(["preset", "library"]):
        t = g.groupby("level")["digit"].first()
        dnum = int(g.dnum.iloc[0]); pc = int(g.PCount.iloc[0])
        ident = bool((t.index + 1 == t.values).all())
        # perPart 추정: OpenFHE 는 GetNumPerPartQ, 여기선 관측 digit 에서 역산
        cand = None
        for per in range(1, 20):
            pred = np.minimum(dnum, np.ceil((t.index.values + 1) / per)).astype(int)
            if (pred == t.values).all():
                cand = per
                break
        chk.append(dict(preset=p, library=lib, dnum=dnum, PCount=pc,
                        digit_eq_level_plus_1=ident,
                        fits_min_dnum_ceil=("perPart=%d" % cand) if cand else "—",
                        digit_min=int(t.min()), digit_max=int(t.max()),
                        distinct=int(t.nunique())))
    chkdf = pd.DataFrame(chk)
    w("실증 확인 (1t; mt 는 동일한 파라미터라 digit 열이 같다):")
    w("")
    w(md_table(chkdf))
    w("")
    w("**결론(B-2):** 세 열은 이름만 같고 같은 양이 아니다. SEAL 열은 `digit = level+1` 이 "
      "항상 참인 **항등식**이며 측정에서 나온 값이 아니다. Lattigo 열은 라이브러리가 "
      "노출하지 않는 값을 밖에서 재구성한 것이므로 **검증되지 않은 추정치**다. "
      "OpenFHE 열만 런타임 API(`GetNumPartQ`/`GetNumPerPartQ`)에서 직접 읽은 실제 digit 수다. "
      "논문에서 세 라이브러리의 digit 을 같은 축에 올려 비교하면 안 된다.")
    w("")

    # ── 2. g(L) 전수 계산 ────────────────────────────────────────────────────
    key = ["preset", "mode", "library", "op"]
    rows = []
    skipped_noncontig = 0
    for k, g in d.groupby(key):
        g = g.sort_values("level")
        m = g.set_index("level")
        for L in sorted(m.index):
            if L + 1 not in m.index:          # 레벨 불연속 → 쌍 제외
                if L + 1 <= m.index.max():
                    skipped_noncontig += 1
                continue
            lo, hi = m.loc[L], m.loc[L + 1]
            rows.append(dict(zip(key, k)) | dict(
                level=L, digit_lo=int(lo.digit), digit_hi=int(hi.digit),
                mean_lo=lo.mean_us, mean_hi=hi.mean_us,
                g=lo.mean_us / hi.mean_us,
                cv_lo=lo.cv, cv_hi=hi.cv, cv_max=max(lo.cv, hi.cv),
                step=int(lo.digit) != int(hi.digit),
                ks=k[3] in KS_OPS,
                logP=int(lo.logP), PCount=int(lo.PCount), dnum=int(lo.dnum),
                logN=int(lo.logN), depth=int(lo.depth)))
    G = pd.DataFrame(rows)
    G["gated"] = G.cv_max > CV_GATE
    G["polluted"] = G.cv_max > CV_POLLUTED
    G.to_csv(os.path.join(OUT, "g_table.csv"), index=False)

    n_pairs_expect = sum((dep - 1) * len(libs) * len(modes) * len(ops) for dep in presets.values())
    w("---")
    w("")
    w("## 2. 한계 이득비 g(L) = mean_us(L) / mean_us(L+1) 전수 계산")
    w("")
    w(f"- 기대 쌍 수 = Σ(depth−1) × 3 × 2 × 8 = **{n_pairs_expect}**  →  실제 **{len(G)}쌍** "
      f"({'일치' if n_pairs_expect == len(G) else '불일치 ⚠️'})")
    w(f"- 레벨 불연속으로 제외한 쌍: **{skipped_noncontig}건**")
    w(f"- cv 게이트(>{CV_GATE}) 통과: **{int((~G.gated).sum())}쌍** / 게이트 걸림 **{int(G.gated.sum())}쌍** "
      f"(그 중 cv>{CV_POLLUTED} 오염 의심 **{int(G.polluted.sum())}쌍**)")
    w(f"- key-switch op 쌍: **{int(G.ks.sum())}** / 대조군 쌍: **{int((~G.ks).sum())}**")
    w("- g < 1 이면 레벨을 내려 빨라진 것, g ≈ 1 이면 **내려도 안 빨라진 것**(포화)")
    w("")
    w("전체 파일: `analysis/out/g_table.csv`")
    w("")

    # ── 3. (A) 저레벨 포화 ───────────────────────────────────────────────────
    w("---")
    w("")
    w("## 3. 주장 (A) — 저레벨 포화가 실제로 존재하는가")
    w("")
    Gk = G[G.ks & ~G.gated].copy()
    w(f"대상: key-switch op × cv 게이트 통과 = **{len(Gk)}쌍** "
      f"(게이트로 제외 {int((G.ks & G.gated).sum())}쌍)")
    w("")

    # 3-1 저레벨 vs 고레벨 g 비교 (1t)
    w("### 3.1 저레벨 3쌍 vs 고레벨 3쌍의 g 비교 (1t)")
    w("")
    w("각 (preset, library, op) 에서 g(1),g(2),g(3) 을 '저레벨', 상위 3쌍을 '고레벨' 로 본다. "
      "포화가 있다면 저레벨 g 가 1.0 에 더 가까워야 한다.")
    w("")
    cmp_rows = []
    for (p, lib, mo), g in Gk.groupby(["preset", "library", "mode"]):
        lv = sorted(g.level.unique())
        if len(lv) < 6:
            lowset, hiset = lv[:max(1, len(lv)//2)], lv[-max(1, len(lv)//2):]
        else:
            lowset, hiset = lv[:3], lv[-3:]
        lo = g[g.level.isin(lowset)].g
        hi = g[g.level.isin(hiset)].g
        cmp_rows.append(dict(preset=p, mode=mo, library=lib,
                             g_low_med=lo.median(), g_high_med=hi.median(),
                             d_low=abs(1 - lo.median()), d_high=abs(1 - hi.median()),
                             n_low=len(lo), n_high=len(hi),
                             low_levels=",".join(f"L{int(v)}" for v in lowset),
                             high_levels=",".join(f"L{int(v)}" for v in hiset)))
    C1 = pd.DataFrame(cmp_rows)
    C1["approaches_1"] = C1.d_low < C1.d_high
    for mo in modes:
        sub = C1[C1["mode"] == mo].sort_values(["preset", "library"])
        w(f"**mode = {mo}**")
        w("")
        w(md_table(sub[["preset", "library", "low_levels", "g_low_med", "high_levels",
                        "g_high_med", "d_low", "d_high", "approaches_1", "n_low", "n_high"]]))
        w("")

    # 3-2 g vs level 추세 (Spearman)
    w("### 3.2 g(L) 의 레벨 추세 — Spearman ρ(level, g)")
    w("")
    w("ρ < 0 이면 **레벨이 낮을수록 g 가 크다** = 저레벨로 갈수록 1.0 에 접근(포화). "
      "OpenFHE/Lattigo 는 digit 계단이 g 를 흔들므로 **비계단 쌍만** 쓴 값을 함께 낸다.")
    w("")
    tr_rows = []
    for (p, mo, lib, op), g in Gk.groupby(["preset", "mode", "library", "op"]):
        r_all, n_all = spearman(g.level, g.g)
        ns = g[~g.step]
        r_ns, n_ns = spearman(ns.level, ns.g)
        tr_rows.append(dict(preset=p, mode=mo, library=lib, op=op,
                            rho_all=r_all, n_all=n_all, rho_nonstep=r_ns, n_nonstep=n_ns))
    T = pd.DataFrame(tr_rows)
    T.to_csv(os.path.join(OUT, "g_trend_spearman.csv"), index=False)
    agg = (T.groupby(["mode", "library"])
             .agg(rho_all_med=("rho_all", "median"),
                  neg_all=("rho_all", lambda s: int((s < 0).sum())),
                  n_all=("rho_all", lambda s: int(s.notna().sum())),
                  rho_ns_med=("rho_nonstep", "median"),
                  neg_ns=("rho_nonstep", lambda s: int((s < 0).sum())),
                  n_ns=("rho_nonstep", lambda s: int(s.notna().sum()))).reset_index())
    w(md_table(agg))
    w("")
    w("(`neg_*` = ρ<0 인 (preset×op) 그룹 수 / `n_*` = ρ 를 계산할 수 있었던 그룹 수)")
    w("")

    # 3-2b 레벨 의존 형태 비교 — 이게 (A)의 물리적 알맹이다
    w("### 3.2b 레벨 의존 형태 비교 — key-switch 비용은 레벨의 몇 차인가")
    w("")
    w("(A)의 물리 주장은 '고정비가 있다'가 아니라 '**OpenFHE 는 P 를 고정 운반해서 "
      "레벨 의존 항이 SEAL 보다 완만하다**'이다. 세 모델을 같은 데이터에 맞춰 R² 로 가른다.")
    w("")
    w("- M1  `mean_us ≈ a·(L+1) + b`         — 타워 수에만 비례 (digit 무시)")
    w("- M2  `mean_us ≈ a·(L+1)·digit + b`   — 지시된 모델")
    w("- M3  `mean_us ≈ a·(L+1)² + b`        — digit 이 레벨과 함께 늘어나는 경우")
    w("")
    mc = []
    for (p_, mo, lib, op), g in d.groupby(["preset", "mode", "library", "op"]):
        gg = g[g.cv <= CV_GATE]
        if len(gg) < 3:
            continue
        L1 = gg.level + 1
        r = dict(preset=p_, mode=mo, library=lib, op=op)
        r["R2_M1"] = ols_fit(L1, gg.mean_us)[2]
        r["R2_M2"] = ols_fit(L1 * gg.digit, gg.mean_us)[2]
        r["R2_M3"] = ols_fit(L1 ** 2, gg.mean_us)[2]
        mc.append(r)
    MC = pd.DataFrame(mc)
    MC.to_csv(os.path.join(OUT, "model_compare.csv"), index=False)
    mck = MC[MC.op.isin(KS_OPS) & (MC["mode"] == "1t")]
    tbl = (mck.groupby("library")[["R2_M1", "R2_M2", "R2_M3"]].median().reset_index())
    tbl["best"] = tbl[["R2_M1", "R2_M2", "R2_M3"]].idxmax(axis=1).str.replace("R2_", "")
    w("**1t · key-switch op · R² 중앙값**")
    w("")
    w(md_table(tbl))
    w("")
    w(md_table(mck.sort_values(["library", "preset", "op"])[
        ["preset", "library", "op", "R2_M1", "R2_M2", "R2_M3"]]))
    w("")

    # 3-3 고정비 적합
    w("### 3.3 고정비 적합 — mean_us ≈ a·(level+1)·digit + b")
    w("")
    fits = []
    for (p, mo, lib, op), g in d.groupby(["preset", "mode", "library", "op"]):
        g = g.sort_values("level")
        gg = g[g.cv <= CV_GATE]
        x = (gg.level + 1) * gg.digit
        a, b, r2, n, rr = ols_fit(x, gg.mean_us)
        maxL = g.level.max()
        y_max = float(g.loc[g.level == maxL, "mean_us"].iloc[0])
        y_min = float(g.loc[g.level == g.level.min(), "mean_us"].iloc[0])
        fits.append(dict(preset=p, mode=mo, library=lib, op=op, ks=op in KS_OPS,
                         a=a, b=b, R2=r2, n_used=n, n_total=len(g),
                         rmse_rel=rr,
                         mean_at_maxL=y_max, mean_at_L1=y_min,
                         b_over_maxL=b / y_max if y_max else np.nan,
                         b_over_L1=b / y_min if y_min else np.nan,
                         b_over_a=b / a if a and np.isfinite(a) and a != 0 else np.nan,
                         logP=int(g.logP.iloc[0]), PCount=int(g.PCount.iloc[0]),
                         dnum=int(g.dnum.iloc[0]), logN=int(g.logN.iloc[0])))
    F = pd.DataFrame(fits)
    F.to_csv(os.path.join(OUT, "fit_coeffs.csv"), index=False)

    Fk = F[F.ks & (F["mode"] == "1t")]
    w("**1t · key-switch op** (전체는 `analysis/out/fit_coeffs.csv`; 적합은 cv 게이트 통과 행만 사용)")
    w("")
    w(md_table(Fk.sort_values(["op", "preset", "library"])[
        ["preset", "library", "op", "n_used", "n_total", "a", "b", "R2", "rmse_rel",
         "mean_at_maxL", "b_over_maxL", "b_over_a"]]))
    w("")
    w("적합 품질 요약 (R²):")
    w("")
    q = (F[F.ks].groupby(["mode", "library"])["R2"]
         .agg(n="size", min="min", med="median", max="max").reset_index())
    w(md_table(q))
    w("")

    # 3-4 b 와 logP/PCount 상관
    w("### 3.4 절편 b 와 logP / PCount 의 상관 (A-5)")
    w("")
    w("⚠️ 프리셋 A~D 는 logP 만 다른 게 아니라 **logN(15/15/14/14)과 depth 도 다르다**. "
      "b 는 μs 절대값이라 logN 이 바뀌면 자릿수가 바뀐다. 따라서 원시 b 상관은 "
      "**logN 교란을 그대로 안고 있는 값**이고, 무차원량 `b/mean(maxL)` 와 "
      "`b/a`(= 고정비를 '(L+1)·digit 단위'로 환산) 를 함께 본다.")
    w("")
    cor_rows = []
    for (mo, lib, op), g in F[F.ks].groupby(["mode", "library", "op"]):
        for tgt in ["b", "b_over_maxL", "b_over_a"]:
            for xcol in ["logP", "PCount"]:
                r, n = pearson(g[xcol], g[tgt])
                cor_rows.append(dict(mode=mo, library=lib, op=op, y=tgt, x=xcol, r=r, n=n))
    CO = pd.DataFrame(cor_rows)
    CO.to_csv(os.path.join(OUT, "b_vs_logP_corr.csv"), index=False)
    piv = (CO[CO["mode"] == "1t"].pivot_table(index=["library", "op"], columns=["y", "x"],
                                              values="r"))
    piv.columns = [f"{a}~{b}" for a, b in piv.columns]
    w("**1t · Pearson r (프리셋 4점, n=4 — 상관계수로서 신뢰구간이 사실상 없다)**")
    w("")
    w(md_table(piv.reset_index()))
    w("")
    w("프리셋별 원자료(1t, rot1):")
    w("")
    w(md_table(F[(F["mode"] == "1t") & (F.op == "rot1")].sort_values(["library", "preset"])[
        ["library", "preset", "logN", "logP", "PCount", "dnum", "a", "b", "R2",
         "b_over_maxL", "b_over_a"]]))
    w("")

    w("**logN 층화 비교 — 교란을 빼고 본 b** (1t · rot1)")
    w("")
    w("logP 상관 r ≈ 0.9 는 logN 이 같이 움직여 만든 값이다. logN 을 고정하면 프리셋이 "
      "2개씩만 남아 상관계수를 쓸 수 없으므로 **방향만** 본다.")
    w("")
    st = []
    for logn, ps in [(15, ["A", "C"]), (14, ["B", "D"])]:
        for lib in libs:
            sub = F[(F["mode"] == "1t") & (F.op == "rot1") & (F.library == lib) &
                    (F.preset.isin(ps))].sort_values("logP")
            if len(sub) != 2:
                continue
            lo, hi = sub.iloc[0], sub.iloc[1]
            st.append(dict(logN=logn, library=lib,
                           preset_lo=f"{lo.preset}(logP{int(lo.logP)},P{int(lo.PCount)})",
                           b_lo=lo.b,
                           preset_hi=f"{hi.preset}(logP{int(hi.logP)},P{int(hi.PCount)})",
                           b_hi=hi.b,
                           b_hi_over_lo=hi.b / lo.b if lo.b else np.nan,
                           logP_hi_over_lo=hi.logP / lo.logP))
    w(md_table(pd.DataFrame(st)))
    w("")
    w("**같은 logN·같은 op 에서 라이브러리 간 b 비교** (1t · rot1) — P 운반량이 다른 것이 "
      "b 에 나타나는가:")
    w("")
    cross = []
    for logn, ps in [(15, ["A", "C"]), (14, ["B", "D"])]:
        for pp in ps:
            sub = F[(F["mode"] == "1t") & (F.op == "rot1") & (F.preset == pp)].set_index("library")
            cross.append(dict(logN=logn, preset=pp,
                              b_openfhe=sub.loc["openfhe", "b"], P_of=int(sub.loc["openfhe", "PCount"]),
                              b_lattigo=sub.loc["lattigo", "b"], P_la=int(sub.loc["lattigo", "PCount"]),
                              b_seal=sub.loc["seal", "b"], P_se=int(sub.loc["seal", "PCount"]),
                              of_over_seal=sub.loc["openfhe", "b"] / sub.loc["seal", "b"],
                              la_over_seal=sub.loc["lattigo", "b"] / sub.loc["seal", "b"]))
    w(md_table(pd.DataFrame(cross)))
    w("")

    # 3-5 포화 '바닥' — 레벨을 끝까지 내렸을 때 얼마나 남는가
    w("### 3.5 포화의 직접 측정 — 레벨을 바닥까지 내렸을 때 남는 비용")
    w("")
    w("g(L) 은 **비**라서 타워 수 기하( (L+1)/(L+2) )에 지배당한다. 고정비의 크기를 직접 보려면 "
      "`mean(L=1)/mean(maxL)`(바닥 비율)과 `b/mean(L=1)`(L=1 에서 고정비가 차지하는 몫)을 본다. "
      "둘 다 클수록 '내려도 안 없어지는 비용'이 크다는 뜻이다.")
    w("")
    fl = []
    for (p_, lib), g in F[(F["mode"] == "1t") & F.ks].groupby(["preset", "library"]):
        fl.append(dict(preset=p_, library=lib, depth=int(d[d.preset == p_].depth.iloc[0]),
                       floor=float((g.mean_at_L1 / g.mean_at_maxL).median()),
                       b_share_at_L1=float(g.b_over_L1.median()),
                       b_share_at_maxL=float(g.b_over_maxL.median())))
    FL = pd.DataFrame(fl)
    FL.to_csv(os.path.join(OUT, "saturation_floor.csv"), index=False)
    w(md_table(FL.sort_values(["preset", "library"])))
    w("")

    # ── 4. (B) SEAL 매끄러움 ────────────────────────────────────────────────
    w("---")
    w("")
    w("## 4. 주장 (B) — SEAL 은 정말 매끄러운가 (계단의 대조군)")
    w("")
    sc = []
    for (p, lib), g in d[d["mode"] == "1t"].groupby(["preset", "library"]):
        t = g.groupby("level")["digit"].first().sort_index(ascending=False)
        lv = list(t.index)
        for i, L in enumerate(lv):
            nxt = t.loc[L - 1] if (L - 1) in t.index else None
            sc.append(dict(preset=p, library=lib, level=int(L), digit=int(t.loc[L]),
                           digit_at_L_minus_1=(int(nxt) if nxt is not None else None),
                           transition_down=(None if nxt is None else int(nxt) != int(t.loc[L]))))
    SC = pd.DataFrame(sc)
    SC.to_csv(os.path.join(OUT, "step_classification.csv"), index=False)

    w("### 4.1 level ↔ digit 표 (1t; mt 동일)")
    w("")
    for p in sorted(presets):
        w(f"**preset {p}** (depth {presets[p]}, logN {int(d[d.preset==p].logN.iloc[0])})")
        w("")
        t = (d[(d.preset == p) & (d["mode"] == "1t")]
             .groupby(["library", "level"])["digit"].first().unstack().sort_index(axis=1, ascending=False))
        t.columns = [f"L{c}" for c in t.columns]
        w(md_table(t.reset_index(), floatfmt="{:.0f}"))
        w("")
    w("digit 전이가 일어나는 레벨(내려가면서 digit 이 바뀌는 지점, 1t):")
    w("")
    tr = (SC[SC.transition_down == True]
          .groupby(["preset", "library"])["level"]
          .agg(lambda s: ",".join(f"L{v}→L{v-1}" for v in sorted(s, reverse=True))).reset_index())
    tr.columns = ["preset", "library", "전이 지점 (L→L-1)"]
    trn = SC[SC.transition_down.notna()].groupby(["preset", "library"]).agg(
        pairs=("transition_down", "size"), steps=("transition_down", "sum")).reset_index()
    tr = tr.merge(trn, on=["preset", "library"], how="right").fillna({"전이 지점 (L→L-1)": "—"})
    tr["step_frac"] = tr.steps / tr.pairs
    w(md_table(tr))
    w("")
    w("**관찰:** SEAL 은 `step_frac = 1.000` — 모든 인접 레벨쌍이 '전이'다. "
      "이는 매끄러움의 증거가 아니라 **`digit = level+1` 정의의 직접 귀결**이다(§1). "
      "SEAL 에서는 '계단 없음' 을 digit 열로 확인할 수 없다 — 확인할 대상 자체가 없다.")
    w("")

    w("### 4.2 g(L) 분포의 단봉/이봉 판정 (1t · key-switch op · cv 게이트 통과)")
    w("")
    w("계단이 있으면 g 분포가 '계단값(작음)' 과 '비계단값(1에 가까움)' 으로 갈라져 이봉이 된다. "
      "여기서는 히스토그램 대신 **분포 요약 + 갭 통계**로 본다 "
      "(정렬한 g 값들의 최대 인접 간격 / 전체 범위 = `gap_ratio`; 클수록 두 덩어리로 갈라졌다는 뜻).")
    w("")
    bi = []
    for (p, lib), g in Gk[Gk["mode"] == "1t"].groupby(["preset", "library"]):
        v = np.sort(g.g.values)
        if len(v) < 4:
            gap, gr = np.nan, np.nan
        else:
            dif = np.diff(v)
            gap = float(dif.max())
            gr = float(gap / (v[-1] - v[0])) if v[-1] > v[0] else np.nan
        s = qsum(g.g)
        bi.append(dict(preset=p, library=lib, n=s["n"], g_min=s["min"], g_med=s["med"],
                       g_max=s["max"], iqr=s["q75"] - s["q25"], max_gap=gap, gap_ratio=gr))
    BI = pd.DataFrame(bi)
    w(md_table(BI.sort_values(["preset", "library"])))
    w("")

    # ── 5. (C) 계단 크기 전수 재산출 ────────────────────────────────────────
    w("---")
    w("")
    w("## 5. 주장 (C) — 계단 크기 전수 재산출")
    w("")
    w(f"분류: 계단 전이 = `digit(L) != digit(L+1)`, 비계단 = 같음. "
      f"cv 게이트(>{CV_GATE}) 통과 쌍만 요약하고, 게이트 걸린 쌍 수를 함께 낸다.")
    w("")
    w("⚠️ **SEAL 은 정의상 모든 쌍이 '계단' 이므로 이 분류가 무의미하다.** "
      "아래 표에서 SEAL 행은 대조가 아니라 참고값이다.")
    w("")

    def step_summary(df, label):
        out = []
        for (p, lib), g in df.groupby(["preset", "library"]):
            for flag, name in [(True, "계단"), (False, "비계단")]:
                sub = g[g.step == flag]
                s = qsum(sub.g)
                out.append(dict(preset=p, library=lib, 부류=name, n=s["n"],
                                g_min=s["min"], g_med=s["med"], g_max=s["max"],
                                gated_excluded=int((df[(df.preset == p) & (df.library == lib) &
                                                       (df.step == flag)].gated).sum()) if False else np.nan))
        return pd.DataFrame(out)

    for mo in ["1t", "mt"]:
        sub_all = G[G.ks & (G["mode"] == mo)]
        sub = sub_all[~sub_all.gated]
        rowsx = []
        for (p, lib), g in sub_all.groupby(["preset", "library"]):
            for flag, name in [(True, "계단"), (False, "비계단")]:
                allf = g[g.step == flag]
                keep = allf[~allf.gated]
                s = qsum(keep.g)
                rowsx.append(dict(preset=p, library=lib, 부류=name,
                                  n=s["n"], gated=int(allf.gated.sum()),
                                  g_min=s["min"], g_med=s["med"], g_max=s["max"]))
        SS = pd.DataFrame(rowsx)
        SS.to_csv(os.path.join(OUT, f"step_ratio_summary_{mo}.csv"), index=False)
        w(f"### 5.{1 if mo=='1t' else 2} mode = {mo} · key-switch op (rot1/relin/mul_cc_rlk)")
        w("")
        w(md_table(SS.sort_values(["library", "preset", "부류"])))
        w("")

    # op 별 상세 (1t, OpenFHE/Lattigo)
    w("### 5.3 op 별 상세 (1t · OpenFHE·Lattigo — 계단 분류가 의미 있는 쌍만)")
    w("")
    rowsx = []
    for (lib, op, flag), g in (Gk[(Gk["mode"] == "1t") & (Gk.library != "seal")]
                               .groupby(["library", "op", "step"])):
        s = qsum(g.g)
        rowsx.append(dict(library=lib, op=op, 부류="계단" if flag else "비계단",
                          n=s["n"], g_min=s["min"], g_med=s["med"], g_max=s["max"]))
    w(md_table(pd.DataFrame(rowsx).sort_values(["library", "op", "부류"])))
    w("")

    # 대조군
    w("### 5.4 대조군 — key-switch 없는 op (digit 과 무관해야 한다)")
    w("")
    Gn = G[~G.ks & ~G.gated]
    rowsx = []
    for (lib, flag), g in Gn[Gn["mode"] == "1t"].groupby(["library", "step"]):
        s = qsum(g.g)
        rowsx.append(dict(library=lib, 부류="계단(digit 전이)" if flag else "비계단",
                          n=s["n"], g_min=s["min"], g_med=s["med"], g_max=s["max"]))
    w(md_table(pd.DataFrame(rowsx).sort_values(["library", "부류"])))
    w("")
    w("op 별 (1t, 전 라이브러리 합산):")
    w("")
    rowsx = []
    for (op, flag), g in Gn[Gn["mode"] == "1t"].groupby(["op", "step"]):
        s = qsum(g.g)
        rowsx.append(dict(op=op, 부류="계단" if flag else "비계단", n=s["n"],
                          g_min=s["min"], g_med=s["med"], g_max=s["max"]))
    w(md_table(pd.DataFrame(rowsx).sort_values(["op", "부류"])))
    w("")

    # 네 프리셋 재현성
    w("### 5.5 네 프리셋 전부에서 재현되는가 (1t · OpenFHE·Lattigo)")
    w("")
    rec = []
    for (p, lib), g in Gk[(Gk["mode"] == "1t") & (Gk.library != "seal")].groupby(["preset", "library"]):
        st, ns = g[g.step].g, g[~g.step].g
        sep = (st.max() < ns.min()) if len(st) and len(ns) else None
        rec.append(dict(preset=p, library=lib, n_step=len(st), n_nonstep=len(ns),
                        step_max=st.max() if len(st) else np.nan,
                        nonstep_min=ns.min() if len(ns) else np.nan,
                        완전분리=("예" if sep else ("아니오" if sep is not None else "판정불가")))) 
    w(md_table(pd.DataFrame(rec).sort_values(["library", "preset"])))
    w("")

    # ── 6. (D) reps 실태 ────────────────────────────────────────────────────
    w("---")
    w("")
    w("## 6. 주장 (D) — mt 데이터의 reps 실태")
    w("")
    ra = d.groupby(["mode", "library"])["reps"].agg(
        n="size", uniq=lambda s: sorted(set(s)), min="min", max="max").reset_index()
    ra.to_csv(os.path.join(OUT, "reps_audit.csv"), index=False)
    w(md_table(ra))
    w("")
    w("`reps` 는 **한 프로세스 안에서의 반복 횟수**(warmup 3 후 30회 평균)이지 "
      "**프로세스 반복 횟수가 아니다.** 두 축을 구분해야 한다.")
    w("")
    w("수집 경로 확인:")
    w("")
    w("- `scripts/run_main_mt.sh:47-53` — 프리셋 A·B·C 의 mt 는 라이브러리마다 "
      "`presetsearch_*` 를 **1회씩만** 실행하고 그 결과를 그대로 병합한다. 반복 런·median 없음.")
    w("- `scripts/run_main_D.sh:43-48,55` — 프리셋 D 도 동일하게 **단일 실행**.")
    w("- `scripts/v3_unify.py` 는 그 단일 실행 CSV 를 그대로 읽어 요약할 뿐, median 을 취하지 않는다.")
    w("- `results/baseline_mt_runs/README.md` 가 같은 사실을 명시한다: "
      "*\"이 값들이 `explore/v3_summary_timing.csv` 의 mt 열(단일 런)을 대체한다 … "
      "B·C·D 의 mt 는 반복 런 자체가 없어 여전히 단일 런이다\"*")
    w("")
    # 반복 런이 있는 유일한 자료로 산포 정량화
    try:
        runs = []
        for i in range(1, 6):
            fn = f"results_v3n15d42L12_off8_timing_mt_run{i}_dku16c.csv"
            if respath.exists(fn):
                r = pd.read_csv(respath.find(fn))
                r["run"] = i
                runs.append(r)
        if runs:
            R = pd.concat(runs, ignore_index=True)
            R = R[(R.ok == 1) & (R.library == "openfhe")]
            sp = (R.groupby(["op", "level"])["mean_us"]
                    .agg(runs="size", mn="min", md="median", mx="max").reset_index())
            sp["spread"] = (sp.mx - sp.mn) / sp.md
            spk = sp[sp.op.isin(KS_OPS)]
            w(f"**런 간 재현성 정량화** — 반복 런이 존재하는 유일한 자료 "
              f"`results/baseline_mt_runs/` (프리셋 A, HEXL-OFF 빌드, OpenFHE {int(sp.runs.max())}런):")
            w("")
            w(md_table(pd.DataFrame([
                dict(대상="key-switch op", n=len(spk),
                     spread_med=spk.spread.median(), spread_q75=spk.spread.quantile(.75),
                     spread_max=spk.spread.max()),
                dict(대상="전체 op", n=len(sp),
                     spread_med=sp.spread.median(), spread_q75=sp.spread.quantile(.75),
                     spread_max=sp.spread.max()),
            ])))
            w("")
            w("(`spread = (max−min)/median`, 같은 (op,level) 을 여러 프로세스 실행에서 잰 값의 산포)")
            w("")
            w("⚠️ 이 자료는 **HEXL-OFF 빌드**라 v3 본측정(`build_openfhe`)과 빌드가 다르다. "
              "절대값 대체용이 아니라 **런 간 산포의 크기**만 인용한다.")
            w("")
    except Exception as e:      # 자료가 없으면 조용히 넘어가지 않고 사실을 남긴다
        w(f"(반복 런 자료 읽기 실패: {e})")
        w("")

    # mt OpenFHE 가 게이트에서 통째로 빠진 사실 — (D) 경고의 실측 뒷받침
    mt_of = G[(G["mode"] == "mt") & (G.library == "openfhe") & G.ks]
    w(f"**요약 CSV 자체에서 관측되는 결과** — mt · OpenFHE · key-switch op 쌍 "
      f"{len(mt_of)}개 중 cv 게이트(>{CV_GATE}) 통과 **{int((~mt_of.gated).sum())}개**. "
      f"즉 이 조합은 cv 기준을 세우는 순간 **분석 가능한 표본이 하나도 남지 않는다** "
      f"(위 §3·§5 의 mt·OpenFHE 칸이 전부 비어 있는 이유). "
      f"행 단위로도 mt·OpenFHE 256행 중 {int((d[(d['mode']=='mt')&(d.library=='openfhe')].cv > CV_POLLUTED).sum())}행이 "
      f"cv>{CV_POLLUTED} 다.")
    w("")

    # ── 7. 정밀도 부수 확인 ─────────────────────────────────────────────────
    w("---")
    w("")
    w("## 7. 부수 확인 — 정밀도의 레벨 의존성 / preset C OpenFHE 예외값")
    w("")
    try:
        P = pd.read_csv(respath.find("v3_summary_precision.csv"))
        pr = (P.groupby(["preset", "mode", "library", "level"])["ks_loss"].mean()
                .reset_index())
        rng = (pr.groupby(["preset", "mode", "library"])["ks_loss"]
                 .agg(n_level="size", mn="min", med="median", mx="max").reset_index())
        rng["range"] = rng.mx - rng.mn
        w("ks_loss( = enc_dec − rot1, 비트) 의 레벨 간 변화폭 (1t):")
        w("")
        w(md_table(rng[rng["mode"] == "1t"].sort_values(["preset", "library"])[
            ["preset", "library", "n_level", "mn", "med", "mx", "range"]]))
        w("")
        cexc = rng[(rng.preset == "C") & (rng.library == "openfhe")]
        w("preset C · OpenFHE 확인 — 예외값의 정체:")
        w("")
        w(md_table(cexc))
        w("")
        cl = (P[(P.preset == "C") & (P.library == "openfhe") & (P["mode"] == "1t")]
              .groupby("level")["ks_loss"].agg(mean="mean", std="std", n="size").reset_index())
        w(md_table(cl.sort_values("level", ascending=False)))
        w("")
        # rep 단위 산포 — OpenFHE 는 전 프리셋에서 크다
        sd = (P[P["mode"] == "1t"].groupby(["preset", "library", "level"])["ks_loss"].std()
                .groupby(["preset", "library"]).median().reset_index()
                .rename(columns={"ks_loss": "rep_std_med"}))
        w("rep 단위 표준편차(레벨별 std 의 중앙값, 1t):")
        w("")
        w(md_table(sd.pivot(index="preset", columns="library", values="rep_std_med").reset_index()))
        w("")
        w("**해석:** preset C · OpenFHE 의 0.81비트는 레벨 전반의 완만한 변화가 아니라 "
          "**L5↔L4 사이의 단일 계단**이다(L10~L5 ≈ 4.09비트, L4~L1 ≈ 3.28비트). "
          "레벨평균의 표준오차는 0.73/√12 ≈ 0.21비트이므로 계단 폭 0.809 는 약 3.8σ — 잡음이 아니다. "
          "다만 digit 전이 지점(OpenFHE C 는 L6→L5)과 **한 레벨 어긋나 있어** "
          "digit 계단으로 바로 귀속시킬 수 없다. 원인 규명은 별도 확인이 필요하다. "
          "또한 OpenFHE 는 **모든 프리셋에서** rep 단위 산포가 Lattigo·SEAL 보다 한 자릿수 크다 "
          "(위 표) — 정밀도 수치를 인용할 때 이 산포를 함께 밝혀야 한다.")
        w("")
    except Exception as e:
        w(f"(정밀도 CSV 처리 실패: {e})")
        w("")

    # ── 8. 판정 ─────────────────────────────────────────────────────────────
    w("---")
    w("")
    w("## 8. 판정")
    w("")
    # 판정에 쓸 숫자 재계산
    verdict_num = {}
    for lib in libs:
        s = C1[(C1["mode"] == "1t") & (C1.library == lib)]
        verdict_num[lib] = dict(
            approach=int(s.approaches_1.sum()), total=len(s),
            d_low=float(s.d_low.median()), d_high=float(s.d_high.median()),
            rho=float(T[(T["mode"] == "1t") & (T.library == lib)].rho_all.median()),
            rho_ns=float(T[(T["mode"] == "1t") & (T.library == lib)].rho_nonstep.median()),
            b_rel=float(F[(F["mode"] == "1t") & F.ks & (F.library == lib)].b_over_maxL.median()),
            r2=float(F[(F["mode"] == "1t") & F.ks & (F.library == lib)].R2.median()),
        )
    V = pd.DataFrame(verdict_num).T.reset_index().rename(columns={"index": "library"})
    w("판정에 쓴 요약 수치 (1t · key-switch op):")
    w("")
    w(md_table(V))
    w("")
    w("- `approach/total` = (preset×… 그룹 중) 저레벨 g 가 고레벨 g 보다 1.0 에 가까운 그룹 수")
    w("- `d_low`/`d_high` = |1 − g| 의 중앙값 (저레벨 / 고레벨)")
    w("- `rho` = Spearman ρ(level, g) 중앙값, `rho_ns` = 비계단 쌍만")
    w("- `b_rel` = b / mean_us(maxLevel), `r2` = 적합 R² 중앙값")
    w("")
    # (A) 판정 보조 — 라이브러리 차이가 저레벨에 몰려 있는가, 전 구간 균일한가
    ratio_rows = []
    for p_ in sorted(presets):
        r = {}
        for lib in libs:
            sub = C1[(C1["mode"] == "1t") & (C1.preset == p_) & (C1.library == lib)]
            if len(sub):
                r[lib] = (float(sub.d_low.iloc[0]), float(sub.d_high.iloc[0]))
        if "openfhe" in r and "seal" in r:
            ratio_rows.append(dict(
                preset=p_,
                g_low_of=float(C1[(C1["mode"]=="1t")&(C1.preset==p_)&(C1.library=="openfhe")].g_low_med.iloc[0]),
                g_low_seal=float(C1[(C1["mode"]=="1t")&(C1.preset==p_)&(C1.library=="seal")].g_low_med.iloc[0]),
                d_low_of_over_seal=r["openfhe"][0] / r["seal"][0],
                d_high_of_over_seal=r["openfhe"][1] / r["seal"][1]))
    RR = pd.DataFrame(ratio_rows)
    w("(A) 보조 — OpenFHE 와 SEAL 의 차이가 **저레벨에 몰려 있는지** 전 구간 균일한지:")
    w("")
    w(md_table(RR))
    w("")
    w("`d_*_of_over_seal` = |1−g| 의 OpenFHE/SEAL 비. 저레벨과 고레벨에서 이 비가 같으면 "
      "라이브러리 차이는 **레벨 구간에 특정되지 않은 전 구간 성질**이다.")
    w("")

    # ── 9. 판정문 (사람이 쓴 결론 — 위 자동 산출 숫자에 근거) ─────────────────
    w("---")
    w("")
    w("## 9. 주장별 판정")
    w("")
    w("> §0~§8 의 표는 스크립트가 자동 산출한 숫자다. 아래 §9 는 그 숫자를 읽고 쓴 **결론**이다.")
    w("")

    w("### (A) 저레벨 포화 — **부분 성립** (지시된 판정 기준으로는 불성립, 물리 기전은 확인)")
    w("")
    w("**지시된 기준으로는 성립하지 않는다.** 기준은 \"OpenFHE 의 g(L) 이 저레벨에서 유의하게 "
      "1.0 에 접근\" 이었으나, 데이터는 **정확히 반대 방향**이다.")
    w("")
    w("- Spearman ρ(level, g) 가 **모든 라이브러리에서 양수**다 (1t 중앙값: OpenFHE 0.55 · "
      "Lattigo 0.50 · SEAL 1.00). ρ<0 인 (preset×op) 그룹은 **36개 중 0개**. "
      "비계단 쌍만 봐도 ρ 중앙값 0.87~0.95 로 더 강하게 양수다.")
    w("- 저레벨 g 는 고레벨 g 보다 **1.0 에서 더 멀다**. 12개 (preset×library) 조합 중 "
      "\"저레벨이 1 에 더 가깝다\" 는 **0개**. (예: A·OpenFHE 저레벨 0.835 / 고레벨 0.925)")
    w("- 이유는 기전이 아니라 기하다. 적합 모델 `a·(L+1)·digit + b` 가 R² 0.99 로 맞는데, "
      "digit 이 1 로 포화한 저레벨 구간에서 g(L) = (a(L+1)+b)/(a(L+2)+b) 이고 이 값은 "
      "L 이 작아질수록 **작아진다**. 즉 레벨을 내릴 때의 **상대 이득은 저레벨에서 오히려 커진다**. "
      "\"내려도 덜 줄어드는 구간\" 은 이 데이터에 없다.")
    w("")
    w("**같은 데이터가 지지하는 것** — 고정비 자체는 실재하고, 라이브러리를 가른다:")
    w("")
    w("- 절편 b 는 같은 logN·같은 op 에서 **OpenFHE 가 SEAL 의 2.28~3.11배**, Lattigo 가 1.53~2.13배다 "
      "(4프리셋 전부, §3.4). PCount 는 OpenFHE 2~5 · Lattigo 2~5 · SEAL 1 이다.")
    w("- 레벨을 바닥까지 내렸을 때 남는 비율 `mean(L=1)/mean(maxL)` 은 **4프리셋 전부에서 "
      "OpenFHE > SEAL** (0.159/0.193/0.244/0.438 대 0.056/0.172/0.076/0.290, §3.5). "
      "OpenFHE 는 레벨을 다 내려도 SEAL 보다 많이 남는다.")
    w("- ⚠️ 단, 이 차이는 **저레벨에 몰려 있지 않다**. |1−g| 의 OpenFHE/SEAL 비가 저레벨과 "
      "고레벨에서 거의 같다(위 표). 라이브러리 차이는 **곡선 전체의 기울기 차이**이지 "
      "특정 레벨 구간의 국소 현상이 아니다.")
    w("")
    w("**논문에 대한 함의:** 4.2절을 \"저레벨에 포화 구간이 존재한다\" 로 쓰면 **데이터에 반한다**. "
      "살릴 수 있는 형태는 \"OpenFHE·Lattigo 는 레벨 무관 고정비(P 운반)가 SEAL 의 2~3배여서 "
      "레벨 하강으로 회수 가능한 비용의 비율이 구조적으로 작다\" 이며, 근거는 g(L) 이 아니라 "
      "절편 b 와 바닥 비율이다. 4.2절이 통째로 사라지지는 않지만 **주장·지표·그림을 모두 갈아야 한다.**")
    w("")

    w("### (B) SEAL 의 매끄러움 — **부분 성립** (비용 쪽은 성립, digit 쪽은 동어반복)")
    w("")
    w("- **digit 쪽(B-1)은 검증이 아니다.** SEAL 하네스는 `digit = level+1` 을 그냥 출력한다"
      "(`src/presetsearch_seal.cpp:169-171`). \"SEAL 에서 digit 이 레벨에 선형 증가하고 계단이 "
      "없다\" 는 관측이 아니라 **정의의 재진술**이다. 논문에서 이를 실측 결과로 제시하면 안 된다. "
      "Lattigo 열도 라이브러리가 노출하지 않는 값을 밖에서 재구성한 추정치다(§1).")
    w("- **비용 쪽(B-3)은 성립한다.** SEAL 의 g(L) 은 레벨의 **완전 단조 함수**다 — "
      "Spearman ρ(level,g) = 1.000 이 12개 (preset×op) 그룹 **전부**에서 나온다. "
      "같은 지표가 OpenFHE 0.55 · Lattigo 0.50 으로 비단조다. 즉 SEAL 의 레벨-비용 곡선에는 "
      "**불연속 점프가 없고**, OpenFHE·Lattigo 에는 있다. 이것이 대조군으로서 유효한 실측 진술이다.")
    w("- 이봉성은 g 분포의 갭 통계로는 잘 갈리지 않는다(`gap_ratio` 0.20~0.79, 라이브러리 간 "
      "구분 안 됨, §4.2). 이봉성의 증거는 갭이 아니라 **계단/비계단 분류의 완전 분리**(§5.5)다.")
    w("")

    w("### (C) 계단 크기 — **성립** (기억 수치는 한쪽이 틀렸다. 아래로 확정)")
    w("")
    w("cv 게이트(>0.05) 통과, key-switch op(rot1·relin·mul_cc_rlk), OpenFHE·Lattigo 기준:")
    w("")
    st_all = Gk[(Gk["mode"] == "1t") & (Gk.library != "seal")]
    a_st, a_ns = st_all[st_all.step].g, st_all[~st_all.step].g
    w(f"- **계단 전이**: g ∈ [{a_st.min():.3f}, {a_st.max():.3f}], 중앙 {a_st.median():.3f}, "
      f"n={len(a_st)}")
    w(f"- **비계단**:   g ∈ [{a_ns.min():.3f}, {a_ns.max():.3f}], 중앙 {a_ns.median():.3f}, "
      f"n={len(a_ns)}")
    w("")
    w(f"- 기억 속 **계단 0.54~0.73 → 실측 {a_st.min():.3f}~{a_st.max():.3f}** (거의 맞음, 상한만 소폭 확장).")
    w(f"- 기억 속 **비계단 0.81~0.93 → 실측 {a_ns.min():.3f}~{a_ns.max():.3f}** (⚠️ **틀렸다**. 실제 범위가 양쪽으로 넓고, "
      "특히 상한이 1.0 을 넘는 쌍이 있다 — A·Lattigo·mul_cc_rlk 의 g=1.010, "
      "레벨을 내렸는데 오히려 느려진 쌍이다). 논문에 0.81~0.93 을 쓰면 안 된다.")
    w("- **네 프리셋 전부에서 재현된다.** (preset × library) 8개 조합 **전부에서 "
      "계단 최대값 < 비계단 최소값** — 완전 분리다(§5.5).")
    w("- **대조군이 정확히 대조군답게 나온다.** key-switch 없는 op 는 digit 전이 여부로 "
      "g 가 갈리지 않는다 (OpenFHE 계단 중앙 0.800 vs 비계단 0.834, 범위 완전 중첩; §5.4). "
      "계단 신호는 key-switch 경로에서만 나온다 — 기전 귀속이 확인된다.")
    w("- ⚠️ **SEAL 은 이 분류에서 빠져야 한다.** 정의상 모든 쌍이 '계단' 이라 대조가 성립하지 않는다.")
    w("")

    w("### (D) mt 의 reps 실태 — **단일 실행 확정. 재측정 시 필수 수정 항목.**")
    w("")
    w("- CSV 의 `reps` 는 **1536행 전부 30** 이고, 이는 **한 프로세스 안의 반복 횟수**다. "
      "프로세스 반복 횟수를 나타내는 열은 이 CSV 에 **없다**.")
    w("- 수집 스크립트 확인 결과 **A·B·C(`run_main_mt.sh`)·D(`run_main_D.sh`) 의 mt 는 전부 "
      "라이브러리당 프로세스 1회 실행**이고, `v3_unify.py` 는 median 을 취하지 않는다. "
      "→ **v3 요약의 mt 열은 5-run median 처리를 거치지 않았다.**")
    w("- 이것이 실제로 위험한 크기임을 같은 저장소의 반복 런 자료가 보여준다: "
      "OpenFHE mt 의 런 간 산포 `(max−min)/median` 이 key-switch op 에서 **중앙 0.208 · 최대 0.459**다. "
      "단일 런이 어디에 떨어졌는지로 결론이 뒤집힐 수 있다.")
    w(f"- 요약 CSV 자체에서도 같은 결론이 나온다: **mt·OpenFHE·key-switch 쌍 {len(mt_of)}개 중 cv≤0.05 를 "
      "통과하는 것이 0개**다. 이 조합은 현재 데이터로 정량 분석이 **불가능**하다 "
      "(본 보고서의 mt·OpenFHE 칸이 전부 비어 있는 이유).")
    w("- ⚠️ **4.1절(스레드 축) 재측정 시 필수:** mt 는 라이브러리당 최소 5회 프로세스 실행 후 "
      "median 을 쓰고, 프로세스 반복 수를 CSV 열로 남길 것. 현재 mt 값으로 4.1절을 쓰면 안 된다.")
    w("")

    w("### 부수 — preset C · OpenFHE 정밀도 예외값")
    w("")
    w("**확인됨.** ks_loss 레벨 간 변화폭 **0.813비트**(1t) / 0.978비트(mt)로, 다른 11개 "
      "(preset×library) 조합의 0.008~0.014비트보다 두 자릿수 크다. 정체는 완만한 레벨 의존이 "
      "아니라 **L5↔L4 의 단일 계단**(L10~L5 ≈ 4.09비트, L4~L1 ≈ 3.28비트, 약 3.8σ)이다. "
      "다만 OpenFHE C 의 digit 전이는 L6→L5 로 **한 레벨 어긋나** 있어 digit 계단으로 바로 "
      "귀속시킬 수 없다. 논문에 넣으려면 별도 확인이 필요하다.")
    w("")

    w("### 측정 오염 표시")
    w("")
    w(f"- cv>{CV_POLLUTED} 인 행: 1t 에서 lattigo 3행뿐(최대 cv 0.675), mt 에서 "
      f"openfhe 79행 · lattigo 5행 · seal 0행. **오염은 mt·OpenFHE 에 집중**되어 있고 "
      "1t 데이터는 대체로 건전하다.")
    w("- 1t·Lattigo 의 cv 최대 0.675 는 특이값이므로 해당 행을 인용할 때 개별 확인이 필요하다 "
      "(`analysis/out/g_table.csv` 에서 `polluted` 로 표시).")
    w("")

    path = os.path.join(OUT, "level_cost_report.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(rep) + "\n")
    print(f"[report] {path}  ({len(rep)}줄)")
    for fn in sorted(os.listdir(OUT)):
        print(f"  out/{fn}")


if __name__ == "__main__":
    main()
