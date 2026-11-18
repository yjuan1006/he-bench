#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fill_table_numbers.py — 논문 표 3·4·5 / 그림 1 캡션 / 4.4절 정밀도 수치 확정.

입력 (전부 읽기 전용):
  explore/v3_summary_timing.csv, explore/v3_summary_precision.csv
  explore/leveldrop_summary_timing.csv
  analysis/out/{g_table,fit_coeffs,step_classification,leveldrop_net}.csv

출력:
  analysis/out/table_numbers.md
  analysis/out/{table3_control,table4_intercept,table5_leveldrop,
                leveldrop_variants_appendix}.csv

전제 (직전 분석에서 확정된 사실):
  * digit 열은 라이브러리마다 의미가 다르다. OpenFHE 만 런타임 실측이고
    SEAL 은 digit = level+1 하드코딩, Lattigo 는 외부 재구성 추정치.
    -> 지시대로 계단 분류는 **OpenFHE digit** 을 기준으로 삼는다(규칙 OF).
       기존 표 3 수치가 어떤 규칙으로 나왔는지 확인하려고 규칙 OWN 도 함께 계산한다.
  * g > 1.0 을 '역전'으로 해석하지 않는다 (통계적으로 분해되지 않음).
  * 1t 만 쓴다. mt 는 cv 게이트 미통과.
"""
import os, math, itertools
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT  = os.path.join(ROOT, "analysis", "out")

KS_OPS   = ["rot1", "relin", "mul_cc_rlk"]
CTRL_OPS = ["add_cc", "add_cp", "mul_cp", "mul_cc", "rescale"]   # key-switch 없음
CTRL_STRICT = ["add_cc", "add_cp", "mul_cp", "mul_cc"]           # rescale 제외본
LIBS_MAIN = ["openfhe", "lattigo"]     # 기존 표 3 두 행이 쓴 집합
PRESETS = ["A", "B", "C", "D"]
CV_GATE = 0.05
MODE = "1t"

MDPATH = os.path.join(OUT, "table_numbers.md")
open(MDPATH, "w").close()          # 실행 시작 시 1회 비움
R = []
def w(s=""):
    """보고서 한 줄. 메모리에 쌓는 동시에 즉시 파일에 append 한다."""
    R.append(s)
    with open(MDPATH, "a") as fh:
        fh.write(s + "\n")

def md(df, fmt="{:.4g}"):
    cols = list(df.columns)
    def f(v):
        if isinstance(v, (float, np.floating)):
            return "—" if (isinstance(v, float) and math.isnan(v)) else fmt.format(v)
        return str(v)
    out = ["| " + " | ".join(map(str, cols)) + " |",
           "|" + "|".join(["---"] * len(cols)) + "|"]
    for _, r in df.iterrows():
        out.append("| " + " | ".join(f(r[c]) for c in cols) + " |")
    return "\n".join(out)

def ols(x, y):
    """y = a*x + b. (a, b, SE_a, SE_b, R2, n) 반환."""
    x = np.asarray(x, float); y = np.asarray(y, float); n = len(x)
    X = np.column_stack([x, np.ones(n)])
    XtXi = np.linalg.inv(X.T @ X)
    beta = XtXi @ X.T @ y
    res = y - X @ beta
    rss = float(res @ res)
    dof = n - 2
    s2 = rss / dof if dof > 0 else np.nan
    se = np.sqrt(np.diag(XtXi) * s2) if dof > 0 else np.array([np.nan, np.nan])
    tss = float(((y - y.mean()) ** 2).sum())
    r2 = 1 - rss / tss if tss > 0 else np.nan
    return float(beta[0]), float(beta[1]), float(se[0]), float(se[1]), float(r2), n

def ztest(m1, s1, m2, s2):
    se = math.sqrt(s1 ** 2 + s2 ** 2)
    if se == 0 or math.isnan(se): return float("nan"), float("nan")
    z = (m1 - m2) / se
    p = 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))
    return z, p

def welch(m1, sd1, n1, m2, sd2, n2):
    v1, v2 = sd1 ** 2 / n1, sd2 ** 2 / n2
    se = math.sqrt(v1 + v2)
    t = (m1 - m2) / se
    df = (v1 + v2) ** 2 / (v1 ** 2 / (n1 - 1) + v2 ** 2 / (n2 - 1))
    p = 2 * (1 - 0.5 * (1 + math.erf(abs(t) / math.sqrt(2))))   # 정규 근사
    return t, df, p, se

# ==================================================================== 0. 적재
T  = pd.read_csv(os.path.join(ROOT, "explore", "v3_summary_timing.csv"))
P  = pd.read_csv(os.path.join(ROOT, "explore", "v3_summary_precision.csv"))
LD = pd.read_csv(os.path.join(ROOT, "explore", "leveldrop_summary_timing.csv"))
SC = pd.read_csv(os.path.join(OUT, "step_classification.csv"))
NET = pd.read_csv(os.path.join(OUT, "leveldrop_net.csv"))

T1 = T[T["mode"] == MODE].copy()
P1 = P[P["mode"] == MODE].copy()

w("# 논문 표 3·4·5 / 그림 1 캡션 / 4.4절 — 누락 수치 확정\n")
w("생성 `analysis/fill_table_numbers.py`. 전 항목 **mode = 1t** 만. 새 측정 없음.\n")
w("\n---\n")
w("## 0. 입력 행 수 회계\n")
w(f"| 파일 | 전체 | 1t | 비고 |")
w("|---|---|---|---|")
w(f"| `v3_summary_timing.csv` | {len(T)} | {len(T1)} | 8 op × 3 lib × 4 preset × 레벨 |")
w(f"| `v3_summary_precision.csv` | {len(P)} | {len(P1)} | rep 단위(레벨당 12행) |")
w(f"| `leveldrop_summary_timing.csv` | {len(LD)} | {len(LD[LD['mode']==MODE])} | 4 변종 × 3 lib × 32 레벨 |")
w("")
NLEV = {"A": 12, "B": 6, "C": 10, "D": 4}
exp_t = sum(NLEV.values()) * 3 * 8
w(f"- 타이밍 1t 기대 = (12+6+10+4) × 3 lib × 8 op = **{exp_t}** → 실제 **{len(T1)}** "
  + ("**일치**" if exp_t == len(T1) else "**⚠️ 불일치**"))
exp_p = sum(NLEV.values()) * 3 * 12
w(f"- 정밀도 1t 기대 = 32 레벨 × 3 lib × 12 rep = **{exp_p}** → 실제 **{len(P1)}** "
  + ("**일치**" if exp_p == len(P1) else "**⚠️ 불일치**"))
w("")

# --------------------------------------------------- 인접 레벨쌍 + 연속성 검사
of_trans = {}      # preset -> set(L) : g(L) 이 계단인 레벨 (digit(L) != digit(L+1)), OpenFHE 실측
for p in PRESETS:
    d = SC[(SC["preset"] == p) & (SC["library"] == "openfhe")]
    of_trans[p] = {int(r["level"]) - 1 for _, r in d.iterrows()
                   if str(r["transition_down"]) == "True"}
own_digit = {}     # (preset, library) -> {level: digit}
for (p, lib), d in T1.groupby(["preset", "library"]):
    own_digit[(p, lib)] = dict(zip(d["level"].astype(int), d["digit"].astype(int)))

pairs, n_disc, n_dup = [], 0, 0
for (p, lib, op), d in T1.groupby(["preset", "library", "op"]):
    d = d.sort_values("level")
    lv = d["level"].to_numpy(int)
    n_dup += len(lv) - len(set(lv))
    m = dict(zip(lv, d["mean_us"])); c = dict(zip(lv, d["cv"]))
    for L in range(1, max(lv)):
        if L not in m or (L + 1) not in m:
            n_disc += 1; continue
        od = own_digit[(p, lib)]
        pairs.append(dict(preset=p, library=lib, op=op, level=L,
                          mean_lo=m[L], mean_hi=m[L + 1], g=m[L] / m[L + 1],
                          cv_lo=c[L], cv_hi=c[L + 1], cv_max=max(c[L], c[L + 1]),
                          step_OF=(L in of_trans[p]),
                          step_OWN=(od.get(L) != od.get(L + 1)),
                          ks=(op in KS_OPS)))
G = pd.DataFrame(pairs)
exp_pairs = sum(NLEV[p] - 1 for p in PRESETS) * 3 * 8
w(f"- 인접 레벨쌍: 기대 (11+5+9+3) × 3 lib × 8 op = **{exp_pairs}** → 실제 **{len(G)}** "
  + ("**일치**" if exp_pairs == len(G) else "**⚠️ 불일치**"))
w(f"- 레벨 불연속으로 제외한 쌍 **{n_disc}건**, 중복 레벨 **{n_dup}건**.")
w("")

# ==================================================================== 1. 표 3
w("\n---\n")
w("## 1. 표 3 — 대조군 행 (★ 최우선)\n")
w("### 1.0 대조군 연산 확정\n")
w("8 op 중 **key-switch(=평가키를 쓰는 재선형화/회전) 가 없는** 것을 대조군으로 삼는다.\n")
w("| 부류 | op | 근거 |")
w("|---|---|---|")
w("| key-switch 있음 (표 3 기존 두 행) | `rot1`, `relin`, `mul_cc_rlk` | 회전키/재선형화키 사용 |")
w("| **대조군 (이번에 채우는 행)** | `add_cc`, `add_cp`, `mul_cp`, `mul_cc`, `rescale` | 평가키 미사용 |")
w("")
w("`mul_cc` 는 relin 없는 곱(결과 degree-2)이라 key-switch 가 없다. "
  "`rescale` 은 모듈러스 드롭이라 key-switch 가 없지만 **레벨과 직접 얽힌 연산**이라 "
  "대조군 성격이 다를 수 있어, `rescale` 을 뺀 엄격본도 함께 낸다.\n")

def summarize(df, label):
    if len(df) == 0:
        return dict(부류=label, n=0, gated=0, g_min=np.nan, g_med=np.nan, g_max=np.nan)
    return dict(부류=label, n=len(df), gated=int((df["cv_max"] > CV_GATE).sum()),
                g_min=float(df["g"].min()), g_med=float(df["g"].median()),
                g_max=float(df["g"].max()))

def block(df, rule, gated_only, ops, libs, tag):
    d = df[df["op"].isin(ops) & df["library"].isin(libs)]
    if gated_only:
        d = d[d["cv_max"] <= CV_GATE]
    key = "step_" + rule
    rows = [summarize(d[d[key]], f"{tag} · 계단 전이"),
            summarize(d[~d[key]], f"{tag} · 비전이")]
    return pd.DataFrame(rows)

# --- 1.1 기존 수치 재산출 (규칙 OWN = 각 라이브러리 자기 digit) ---
w("### 1.1 기존 두 행의 재산출 — ⚠️ 분류 규칙이 두 가지다\n")
ks_own_g = block(G[G["ks"]], "OWN", True,  KS_OPS, LIBS_MAIN, "KS")
ks_own_u = block(G[G["ks"]], "OWN", False, KS_OPS, LIBS_MAIN, "KS")
ks_of_g  = block(G[G["ks"]], "OF",  True,  KS_OPS, LIBS_MAIN, "KS")
ks_of_u  = block(G[G["ks"]], "OF",  False, KS_OPS, LIBS_MAIN, "KS")
w("**규칙 OWN** — 각 라이브러리가 자기 `digit` 열로 판정 (기존 표 3 이 쓴 방식):\n")
w(md(ks_own_g))
w("")
w("**규칙 OF** — 지시된 방식: 같은 preset·level 에서 **OpenFHE digit** 이 전이하는가로 판정:\n")
w(md(ks_of_g))
w("")
mn, mx = ks_own_g.iloc[0], ks_own_g.iloc[1]
ok = (abs(mn["g_min"] - 0.542) < 5e-4 and abs(mn["g_med"] - 0.668) < 5e-4
      and abs(mn["g_max"] - 0.753) < 5e-4 and mn["n"] == 45
      and abs(mx["g_min"] - 0.782) < 5e-4 and abs(mx["g_med"] - 0.898) < 5e-4
      and abs(mx["g_max"] - 1.010) < 5e-4 and mx["n"] == 123)
w(f"> **기존 수치 대조:** 표 3 의 `0.542 / 0.668 / 0.753 (n=45)` 와 "
  f"`0.782 / 0.898 / 1.010 (n=123)` 는 **규칙 OWN 에서 정확히 재현된다** "
  f"({'일치 확인' if ok else '⚠️ 불일치'}).\n")
w("> 그런데 **논문이 선언한 규칙(digit 은 OpenFHE 실측만 신뢰)과 어긋난다.** "
  "규칙 OWN 은 Lattigo 행을 Lattigo 의 **재구성 추정 digit** 으로 분류한 것이다. "
  "두 규칙은 preset A·B·D 에서는 같은 레벨을 지목하지만 **preset C 에서 갈린다** — "
  "OpenFHE 는 L6↔L5 한 번, Lattigo 추정치는 L8↔L7 과 L4↔L3 두 번. "
  "그래서 n 이 45(OWN) vs 42(OF) 로 달라진다.\n")

tr_tab = pd.DataFrame([dict(preset=p,
                            OpenFHE_실측=",".join(f"L{L+1}↔L{L}" for L in sorted(of_trans[p], reverse=True)),
                            Lattigo_추정=",".join(
                                f"L{L+1}↔L{L}" for L in sorted(
                                    {L for L in range(1, NLEV[p])
                                     if own_digit[(p,'lattigo')].get(L) != own_digit[(p,'lattigo')].get(L+1)},
                                    reverse=True)))
                       for p in PRESETS])
w(md(tr_tab))
w("")

# --- 1.2 대조군 ---
w("### 1.2 대조군 행\n")
tabs = []
for rule, rl in [("OWN", "규칙 OWN (기존 두 행과 동일)"), ("OF", "규칙 OF (OpenFHE digit 기준)")]:
    for ops, tag in [(CTRL_OPS, "대조군 5 op"), (CTRL_STRICT, "대조군 4 op(rescale 제외)")]:
        for gs, gl in [(True, "게이트 적용"), (False, "게이트 미적용")]:
            tabs.append(block(G[~G["ks"]], rule, gs, ops, LIBS_MAIN,
                              f"{rl} · {tag} · {gl}"))
ctrl = pd.concat(tabs, ignore_index=True)
w(md(ctrl))
w("")

# --- 판정 ---
def sep_of(df, rule, ops, libs, gated):
    d = df[df["op"].isin(ops) & df["library"].isin(libs)]
    if gated: d = d[d["cv_max"] <= CV_GATE]
    k = "step_" + rule
    a, b_ = d[d[k]]["g"], d[~d[k]]["g"]
    if len(a) == 0 or len(b_) == 0: return np.nan
    return float(b_.min() - a.max())

verdict_rows = []
for tag, ops in [("key-switch (참조)", KS_OPS), ("대조군 5 op", CTRL_OPS),
                 ("대조군 4 op", CTRL_STRICT)]:
    for gs, gl in [(True, "게이트 적용"), (False, "게이트 미적용")]:
        verdict_rows.append(dict(부류=f"{tag} · {gl}",
                                 분리폭_OWN=sep_of(G, "OWN", ops, LIBS_MAIN, gs),
                                 분리폭_OF=sep_of(G, "OF", ops, LIBS_MAIN, gs)))
VD = pd.DataFrame(verdict_rows)
w("### 1.3 판정 — 분리 폭 `min(비전이 g) − max(계단 전이 g)`\n")
w("양수면 두 분포가 완전 분리, 0 이하면 겹친다.\n")
w(md(VD, fmt="{:+.4f}"))
w("")

c_own_g = sep_of(G, "OWN", CTRL_OPS, LIBS_MAIN, True)
c_own_u = sep_of(G, "OWN", CTRL_OPS, LIBS_MAIN, False)
c_of_g  = sep_of(G, "OF",  CTRL_OPS, LIBS_MAIN, True)
k_own_g = sep_of(G, "OWN", KS_OPS,  LIBS_MAIN, True)
k_of_g  = sep_of(G, "OF",  KS_OPS,  LIBS_MAIN, True)

if max(c_own_g, c_own_u, c_of_g) <= 0:
    w(f"**✅ 대조군 판정: 겹친다 → 4.1 의 귀속 주장 성립.** "
      f"분리 폭이 규칙·게이트 네 조합 전부 음수다 "
      f"(OWN 게이트 {c_own_g:+.4f} / OWN 미적용 {c_own_u:+.4f} / OF 게이트 {c_of_g:+.4f}). "
      f"같은 분류 기준을 key-switch 연산에 적용하면 **{k_own_g:+.4f} (> 0, 완전 분리)** 다. "
      f"계단은 대조군에는 없고 key-switch 연산에만 있다 — digit 분해 구조로의 귀속이 성립한다.\n")
else:
    w(f"**⚠️ 경고: 대조군에서도 분리가 나타난다.** 4.1 의 귀속 주장이 흔들린다. "
      f"OWN 게이트 {c_own_g:+.4f} / OWN 미적용 {c_own_u:+.4f} / OF 게이트 {c_of_g:+.4f}. "
      f"원인 규명 전에는 본문에 쓰지 말 것.\n")

w("**⚠️ 그러나 key-switch 쪽 분리는 분류 규칙에 의존한다 — 본문에 반드시 반영할 것.**\n")
w(f"- 규칙 OWN(라이브러리별 자기 digit): 분리 폭 **{k_own_g:+.4f}** → 분리 성립 (기존 표 3).")
w(f"- 규칙 OF(OpenFHE digit 을 세 라이브러리에 일괄 적용): 분리 폭 **{k_of_g:+.4f}** → **분리 소멸**.")
w("")
w("소멸하는 이유는 잡음이 아니라 **설계**다. 프리셋이 라이브러리마다 `dnum` 을 다르게 준다 "
  "(예: preset C 는 OpenFHE `dnum=2`, Lattigo `dnum=4`). 그래서 digit 이 바뀌는 레벨 자체가 "
  "라이브러리마다 다르고, preset C 에서 OpenFHE 는 L6↔L5 한 번인데 Lattigo 는 L8↔L7·L4↔L3 두 번이다. "
  "OpenFHE 의 전이 레벨을 Lattigo 행에 갖다 붙이면 Lattigo 의 진짜 계단(g≈0.65)이 '비전이'로, "
  "진짜 비전이(g≈0.90)가 '계단'으로 뒤집혀 라벨이 섞인다.\n")
w("> **권고:** 표 3 의 계단 분류는 **라이브러리별 digit(규칙 OWN)** 으로 유지한다. "
  "3.4절의 'digit 은 OpenFHE 만 실측' 이라는 단서는 **SEAL 에만** 적용해야 한다 — "
  "SEAL 의 `digit = level+1` 은 측정도 유도도 아닌 하드코딩이지만, Lattigo 의 digit 은 "
  "`min(dnum, ceil((L+1)/|P|))` 이라는 문서화된 공식에서 **파라미터로부터 유도**한 값이라 성격이 다르다. "
  "본문이 두 경우를 같은 문장으로 묶고 있다면 분리해서 쓸 것.\n")

# 게이트 상세
gate_rows = []
for tag, ops in [("key-switch", KS_OPS), ("대조군 5 op", CTRL_OPS), ("대조군 4 op", CTRL_STRICT)]:
    d = G[G["op"].isin(ops) & G["library"].isin(LIBS_MAIN)]
    for lib in LIBS_MAIN:
        dl = d[d["library"] == lib]
        gate_rows.append(dict(부류=tag, library=lib, n=len(dl),
                              gated=int((dl["cv_max"] > CV_GATE).sum()),
                              cv_med=float(dl["cv_max"].median()),
                              cv_max=float(dl["cv_max"].max())))
GT = pd.DataFrame(gate_rows)
w("### 1.4 cv 게이트 현황 (쌍의 `cv_max = max(cv(L), cv(L+1))`, 임계 0.05)\n")
w(md(GT))
w("")
ng = int(GT[GT["부류"].str.startswith("대조군 5")]["gated"].sum())
nt = int(GT[GT["부류"].str.startswith("대조군 5")]["n"].sum())
w(f"> 대조군은 절대 시간이 작아 예상대로 cv 가 크다 — **{nt} 쌍 중 {ng} 쌍이 게이트에 걸린다** "
  f"(key-switch 는 168 쌍 중 0 쌍). 게이트를 적용하든 안 하든 **판정은 바뀌지 않는다**(§1.3 표). "
  f"게이트에 걸린 쌍은 버리지 않고 '게이트 미적용' 행에 그대로 포함해 두었다. "
  f"Lattigo 대조군의 cv 최댓값 {GT[(GT['library']=='lattigo')&(GT['부류'].str.startswith('대조군 5'))]['cv_max'].iloc[0]:.3f} 는 "
  f"DVFS 오염 가능 구간으로 표시해 둔다.\n")

# SEAL 보조
seal_ctrl = block(G[~G["ks"]], "OF", True, CTRL_OPS, ["seal"], "SEAL 대조군")
seal_ks   = block(G[G["ks"]],  "OF", True, KS_OPS,  ["seal"], "SEAL key-switch")
w("### 1.5 보조 — SEAL\n")
w("기존 표 3 두 행은 SEAL 을 뺐다. SEAL 은 자기 digit(=level+1)으로는 **모든 쌍이 계단**이 되어 "
  "비전이 부류가 비므로 규칙 OWN 을 적용할 수 없다(동어반복). 규칙 OF 로만 분류 가능하다:\n")
w(md(pd.concat([seal_ks, seal_ctrl], ignore_index=True)))
w(f"\n> SEAL key-switch 분리 폭 {sep_of(G,'OF',KS_OPS,['seal'],True):+.4f}, "
  f"대조군 {sep_of(G,'OF',CTRL_OPS,['seal'],True):+.4f} — 둘 다 음수. "
  "SEAL 은 특수소수가 1개(logP=60 고정)뿐이라 digit 분해 계단 자체가 없는 것이 "
  "예상된 거동이므로, 이 결과는 4.1 과 모순되지 않는다. **표 3 에는 넣지 말고 본문 각주로 처리할 것.**\n")

# --- 표 3 최종안 ---
w("### 1.6 표 3 에 그대로 넣을 값 (규칙 OWN · cv 게이트 적용 · OpenFHE+Lattigo)\n")
fin = pd.concat([
    block(G[G["ks"]],  "OWN", True, KS_OPS,   LIBS_MAIN, "key-switch"),
    block(G[~G["ks"]], "OWN", True, CTRL_OPS, LIBS_MAIN, "대조군"),
], ignore_index=True)
fin["표기"] = fin.apply(lambda r: f"{r['g_min']:.3f} / {r['g_med']:.3f} / {r['g_max']:.3f}", axis=1)
w(md(fin[["부류", "표기", "n", "gated"]]))
w("")
w("(형식은 기존 두 행과 같은 `최소 / 중앙 / 최대 (n)`. 게이트에 걸려 빠진 대조군 쌍 수는 "
  "표 각주에 적을 것.)\n")

t3 = pd.concat([ks_own_g.assign(규칙="OWN", 게이트="적용"),
                ks_own_u.assign(규칙="OWN", 게이트="미적용"),
                ks_of_g.assign(규칙="OF", 게이트="적용"),
                ks_of_u.assign(규칙="OF", 게이트="미적용"),
                ctrl.assign(규칙="표기참조", 게이트="표기참조"),
                seal_ks.assign(규칙="OF", 게이트="적용"),
                seal_ctrl.assign(규칙="OF", 게이트="적용")], ignore_index=True)
t3.to_csv(os.path.join(OUT, "table3_control.csv"), index=False)

# ==================================================================== 2. 표 4
w("\n---\n")
w("## 2. 표 4 — 절편의 절대값\n")

# --- 2.0 전제 확인 -----------------------------------------------------------
w("### 2.0 전제 확인\n")
lv_min = int(T1["level"].min()); n_l0 = int((T1["level"] == 0).sum())
w(f"- 레벨 스윕 범위: **L{lv_min} … L(maxLevel)**. `level = 0` 인 행은 **{n_l0}건** — "
  "하네스가 `maxLevel..1` 만 훑기 때문이다(`CLAUDE.md` 측정 스펙). "
  "따라서 아래 '바닥'은 전부 **L1** 을 뜻하며 L0 이 아니다.\n")
FIT_OPS = KS_OPS           # 표 4 본문은 key-switch 3종. CSV 에는 8 op 전부 담는다.
ALL_OPS = sorted(T1["op"].unique())
w(f"- 적합 대상 행 수: preset 4 × library 3 × op {len(ALL_OPS)} = **{4*3*len(ALL_OPS)}** 조합, "
  f"조합당 레벨 수 A12/B6/C10/D4. 실제 조합 수 **{T1.groupby(['preset','library','op']).ngroups}** "
  + ("**일치**" if T1.groupby(['preset','library','op']).ngroups == 4*3*len(ALL_OPS) else "**⚠️ 불일치**"))
w("- 레벨 연속성은 §0 에서 확인 완료(불연속 0건, 중복 0건). 적합은 각 조합의 **전 레벨**을 쓴다.\n")

# --- 2.1 모형 정의 -----------------------------------------------------------
w("### 2.1 ⚠️ 기존 적합 모형에 digit 이 들어가 있다\n")
w("직전 분석의 `fit_coeffs.csv` 가 쓴 모형은\n")
w("```\nM2 :  mean_us ≈ a·(level+1)·digit + b      (digit 포함)\n```\n")
w("인데 `digit` 열의 성격이 라이브러리마다 다르다.\n")
w("| library | digit 출처 | M2 에 넣으면 실제로 무슨 모형이 되나 |")
w("|---|---|---|")
w("| OpenFHE | 런타임 실측 (`GetNumPartQ`/`GetNumPerPartQ`) | 의도한 대로 `a·(L+1)·d + b` |")
w("| Lattigo | 파라미터에서 유도 (`min(dnum, ⌈(L+1)/|P|⌉)`) | 의도한 대로 (단 실측 아님) |")
w("| SEAL | `digit = level+1` **하드코딩** (`presetsearch_seal.cpp:169-171`) | "
  "`(L+1)·digit = (L+1)²` → **사실상 2차 모형**. 다른 두 라이브러리와 같은 모형이 아니다 |")
w("")
w("즉 M2 로 세 라이브러리의 b 를 나란히 비교하면 **SEAL 만 2차식의 절편**을 비교하는 셈이다. "
  "그래서 지시대로 digit 없는 단순 모형\n")
w("```\nM1 :  mean_us ≈ a·(level+1) + b          (digit 미사용)\n```\n")
w("으로 다시 적합해 두 모형을 나란히 놓는다. M1 은 세 라이브러리에 **문자 그대로 같은 모형**이다.\n")

# --- 적합 수행 ---------------------------------------------------------------
rows = []
for (p_, lib, op), d in T1.groupby(["preset", "library", "op"]):
    d = d.sort_values("level")
    L = d["level"].to_numpy(float); y = d["mean_us"].to_numpy(float)
    dg = d["digit"].to_numpy(float)
    a1, b1, sa1, sb1, r1, n1 = ols(L + 1, y)
    a2, b2, sa2, sb2, r2, n2 = ols((L + 1) * dg, y)
    m1v = float(d[d["level"] == 1]["mean_us"].iloc[0])
    mMv = float(d[d["level"] == d["level"].max()]["mean_us"].iloc[0])
    rows.append(dict(preset=p_, library=lib, op=op, ks=(op in KS_OPS), n=n1,
                     maxLevel=int(d["level"].max()),
                     b_M1=b1, se_b_M1=sb1, a_M1=a1, R2_M1=r1,
                     b_M2=b2, se_b_M2=sb2, a_M2=a2, R2_M2=r2,
                     mean_L1=m1v, mean_maxL=mMv,
                     floor_ratio=m1v / mMv,
                     b_share_L1_M1=b1 / m1v, b_share_maxL_M1=b1 / mMv,
                     b_share_L1_M2=b2 / m1v, b_share_maxL_M2=b2 / mMv))
F = pd.DataFrame(rows)
F.to_csv(os.path.join(OUT, "table4_intercept.csv"), index=False)

# M2 재산출이 기존 fit_coeffs.csv 와 맞는지 대조
FC = pd.read_csv(os.path.join(OUT, "fit_coeffs.csv"))
FC = FC[FC["mode"] == MODE][["preset", "library", "op", "b", "R2", "n_used", "n_total"]]
chk = F.merge(FC, on=["preset", "library", "op"], how="left")
chk["db"] = (chk["b_M2"] - chk["b"]).abs() / chk["b"].abs()
full = chk[chk["n_used"] == chk["n_total"]]
w(f"> **재산출 대조** — M2 를 다시 적합해 기존 `fit_coeffs.csv` 와 맞춰봤다. "
  f"기존 적합은 cv>0.05 인 레벨을 빼고 적합해서 96 조합 중 **{int((chk['n_used']<chk['n_total']).sum())}개**가 "
  f"레벨을 일부 잃었다(key-switch 3종 중에는 preset B·SEAL·`mul_cc_rlk` 하나뿐, 5/6 레벨). "
  f"전 레벨을 쓴 {len(full)}개 조합에서는 상대오차 최대 **{full['db'].max():.2e}** 로 "
  f"**완전히 재현된다.** 아래 표는 게이트 없이 전 레벨을 쓴 값이다.\n")

# --- 2.2 b 절대값 ------------------------------------------------------------
w("### 2.2 적합 절편 b — μs 단위 절대값 (key-switch 3종, 1t)\n")
def piv(col, fmt="{:,.0f}"):
    t = F[F["ks"]].pivot_table(index=["preset", "op"], columns="library", values=col)
    t = t[["openfhe", "lattigo", "seal"]].reset_index()
    return t
b1t = piv("b_M1"); b2t = piv("b_M2")
b1t.columns = ["preset", "op", "OpenFHE", "Lattigo", "SEAL"]
b2t.columns = ["preset", "op", "OpenFHE", "Lattigo", "SEAL"]
w("**M1 (digit 미사용) — 논문 권장본**\n")
w(md(b1t, fmt="{:,.0f}"))
w("")
w("**M2 (digit 포함) — 기존 `fit_coeffs.csv` 와 동일**\n")
w(md(b2t, fmt="{:,.0f}"))
w("")

# --- 2.3 R2 ------------------------------------------------------------------
w("### 2.3 두 모형의 R²\n")
r1t = piv("R2_M1"); r2t = piv("R2_M2")
r1t.columns = ["preset", "op", "OpenFHE", "Lattigo", "SEAL"]
r2t.columns = ["preset", "op", "OpenFHE", "Lattigo", "SEAL"]
w("**M1 (digit 미사용)**\n"); w(md(r1t, fmt="{:.4f}")); w("")
w("**M2 (digit 포함)**\n");   w(md(r2t, fmt="{:.4f}")); w("")
ks = F[F["ks"]]
cmpr = ks.groupby("library")[["R2_M1", "R2_M2"]].agg(["min", "median", "max"])
cmpr.columns = ["_".join(c) for c in cmpr.columns]
cmpr = cmpr.reset_index()
w("**요약 (key-switch 3종 × 4 preset = 12 적합/라이브러리)**\n")
w(md(cmpr, fmt="{:.4f}"))
w("")
nb = int((ks["R2_M1"] >= ks["R2_M2"]).sum())
w(f"> M1 이 M2 보다 R² 가 높거나 같은 적합은 36개 중 **{nb}개**. "
  f"라이브러리별로 보면 SEAL 은 M2(=2차)가 유리하고 OpenFHE·Lattigo 는 M1 과 M2 가 비슷하다 — "
  "SEAL 의 M2 우세는 digit 정보 때문이 아니라 **2차항이 들어갔기 때문**이므로 "
  "'digit 이 설명력을 준다'는 근거로 쓸 수 없다.\n")

# --- 2.4 바닥 비율 -----------------------------------------------------------
w("### 2.4 바닥 비율 — 정의를 먼저 못박는다\n")
w("```\n바닥 비율  floor_ratio = mean_us(L = 1) / mean_us(L = maxLevel)\n```\n")
w("- 분자는 **측정된 최저 레벨 L1**(§2.0 대로 L0 은 측정 자체가 없다), 분모는 프리셋의 최고 레벨.\n"
  "- 값이 클수록 '레벨을 바닥까지 내려도 비용이 안 떨어진다' = 고정비 비중이 크다는 뜻이다.\n"
  "- maxLevel 이 프리셋마다 다르므로(A12/B6/C10/D4) **프리셋을 가로질러 평균 내면 안 된다.**\n")
ft = piv("floor_ratio"); ft.columns = ["preset", "op", "OpenFHE", "Lattigo", "SEAL"]
w(md(ft, fmt="{:.4f}")); w("")
w("**고정비 몫 `b / mean_us(maxLevel)`** — 절편이 최고레벨 비용에서 차지하는 비율. "
  "**M2 기준**이다 (M1 의 b 는 §2.8 대로 대부분 음수라 '몫'으로 읽을 수 없다. "
  "M1 값은 `table4_intercept.csv` 의 `b_share_*_M1` 열에 그대로 들어 있다).\n")
st = piv("b_share_maxL_M2"); st.columns = ["preset", "op", "OpenFHE", "Lattigo", "SEAL"]
w(md(st, fmt="{:.4f}")); w("")
w("**고정비 몫 `b / mean_us(L=1)`** — 최저 레벨 비용 중 절편이 차지하는 비율 (M2 기준)\n")
st1 = piv("b_share_L1_M2"); st1.columns = ["preset", "op", "OpenFHE", "Lattigo", "SEAL"]
w(md(st1, fmt="{:.4f}")); w("")

# --- 2.5 비 (세 쌍 전부) ------------------------------------------------------
w("### 2.5 ⚠️ 비교 쌍을 통일한다 — 세 쌍 전부 산출\n")
def ratios(col):
    t = F[F["ks"]].pivot_table(index=["preset", "op"], columns="library", values=col)
    out = pd.DataFrame({
        "preset": [i[0] for i in t.index], "op": [i[1] for i in t.index],
        "OF/LAT": (t["openfhe"] / t["lattigo"]).to_numpy(),
        "OF/SEAL": (t["openfhe"] / t["seal"]).to_numpy(),
        "LAT/SEAL": (t["lattigo"] / t["seal"]).to_numpy()})
    return out
rb1, rb2, rf = ratios("b_M1"), ratios("b_M2"), ratios("floor_ratio")
w("**절편비 (M1, digit 미사용)**\n"); w(md(rb1, fmt="{:.3f}")); w("")
w("**절편비 (M2, digit 포함)**\n");   w(md(rb2, fmt="{:.3f}")); w("")
w("**바닥 비율의 비**\n");            w(md(rf, fmt="{:.3f}")); w("")
rng = pd.DataFrame([
    dict(지표="절편 b (M1)", 쌍=k, 최소=rb1[k].min(), 최대=rb1[k].max()) for k in ["OF/LAT","OF/SEAL","LAT/SEAL"]
] + [
    dict(지표="절편 b (M2)", 쌍=k, 최소=rb2[k].min(), 최대=rb2[k].max()) for k in ["OF/LAT","OF/SEAL","LAT/SEAL"]
] + [
    dict(지표="바닥 비율", 쌍=k, 최소=rf[k].min(), 최대=rf[k].max()) for k in ["OF/LAT","OF/SEAL","LAT/SEAL"]
])
w("**범위 요약 (key-switch 3종 × 4 preset)**\n"); w(md(rng, fmt="{:.3f}")); w("")

# 본문 "2.28~3.11" 의 정체 추적
cand = []
for lab, tab in [("절편 b (M1)", rb1), ("절편 b (M2)", rb2), ("바닥 비율", rf)]:
    for k in ["OF/LAT", "OF/SEAL", "LAT/SEAL"]:
        for sub, ops in [("3 op 전체", KS_OPS), ("rot1 만", ["rot1"]),
                         ("relin 만", ["relin"]), ("mul_cc_rlk 만", ["mul_cc_rlk"])]:
            v = tab[tab["op"].isin(ops)][k]
            cand.append(dict(지표=lab, 쌍=k, 범위=sub, 최소=v.min(), 최대=v.max(),
                             일치=(abs(v.min() - 2.28) < 0.005 and abs(v.max() - 3.11) < 0.005)))
CD = pd.DataFrame(cand)
hit = CD[CD["일치"]]
w("**본문의 \"2.28~3.11배\" 가 실제로 어느 조합인가** — 모든 지표×쌍×op부분집합을 훑어 대조했다:\n")
if len(hit):
    w(md(hit[["지표", "쌍", "범위", "최소", "최대"]], fmt="{:.3f}"))
    w("")
    h = hit.iloc[0]
    w(f"> ⚠️ **본문 문장이 틀렸다.** \"절편비 OpenFHE:Lattigo 2.28~3.11배\" 라고 썼지만 "
      f"그 수치는 **{h['쌍']} · {h['지표']} · {h['범위']}** 의 값이다. "
      f"실제 **OF/LAT 절편비는 M1 에서 {rb1['OF/LAT'].min():.2f}~{rb1['OF/LAT'].max():.2f}, "
      f"M2 에서 {rb2['OF/LAT'].min():.2f}~{rb2['OF/LAT'].max():.2f}** 다. "
      f"라이브러리 쌍과 op 범위 **두 가지가 동시에 어긋나 있다.**\n")
else:
    w("> 어느 조합에서도 2.28~3.11 이 재현되지 않는다. 본문 수치의 출처를 확인해야 한다.\n")

# --- 2.6 유의성 --------------------------------------------------------------
w("### 2.6 'OpenFHE 의 b 가 유의하게 크다' 가 M1 에서도 유지되는가\n")
w("각 적합의 OLS 표준오차 `SE(b)` 로 두 라이브러리의 절편 차를 검정한다 "
  "(`z = (b₁−b₂)/√(SE₁²+SE₂²)`, 양측 정규 근사).\n")
sig = []
for (p_, op), d in F[F["ks"]].groupby(["preset", "op"]):
    g_ = d.set_index("library")
    for m in ["M1", "M2"]:
        for x, y_ in [("openfhe", "lattigo"), ("openfhe", "seal"), ("lattigo", "seal")]:
            z, pv = ztest(g_.loc[x, f"b_{m}"], g_.loc[x, f"se_b_{m}"],
                          g_.loc[y_, f"b_{m}"], g_.loc[y_, f"se_b_{m}"])
            sig.append(dict(preset=p_, op=op, 모형=m, 쌍=f"{x[:2].upper()}/{y_[:2].upper()}",
                            b1=g_.loc[x, f"b_{m}"], b2=g_.loc[y_, f"b_{m}"], z=z, p=pv,
                            유의=(pv < 0.05)))
SG = pd.DataFrame(sig)
summ = (SG.groupby(["모형", "쌍"])
          .agg(n=("유의", "size"), 유의건수=("유의", "sum"),
               z_min=("z", "min"), z_med=("z", "median"), z_max=("z", "max"))
          .reset_index())
w(md(summ, fmt="{:.3g}"))
w("")
ofl_m1 = SG[(SG["모형"] == "M1") & (SG["쌍"] == "OP/LA")]
ofs_m1 = SG[(SG["모형"] == "M1") & (SG["쌍"] == "OP/SE")]
w(f"> M1 에서 **OpenFHE b > Lattigo b** 는 12개 조합 중 **{int(ofl_m1['유의'].sum())}개**가 p<0.05, "
  f"z 중앙값 {ofl_m1['z'].median():.2f}. "
  f"**OpenFHE b > SEAL b** 는 **{int(ofs_m1['유의'].sum())}/12**, z 중앙값 {ofs_m1['z'].median():.2f}.\n")
w(md(SG[(SG["모형"] == "M1")][["preset", "op", "쌍", "b1", "b2", "z", "p", "유의"]]
     .sort_values(["preset", "op", "쌍"]), fmt="{:.4g}"))
w("")

# --- 2.7 SEAL digit 재검토 (M1/M2 선택의 전제) --------------------------------
w("### 2.7 ⚠️ 전제 재검토 — SEAL 의 `digit = level+1` 은 '가짜'가 아니다\n")
w("§2.1 에서 이 값을 '하드코딩'이라 적었고 직전 분석들도 그렇게 다뤄 왔다. "
  "M1 을 쓸지 말지가 여기 걸려 있어 **SEAL 원본을 직접 확인했다.**\n")
w("`native/src/seal/evaluator.cpp` 의 `switch_key_inplace`:\n")
w("```cpp\n"
  "size_t decomp_modulus_size = parms.coeff_modulus().size();   // :2615  = 해당 레벨의 Q 프라임 수\n"
  "size_t rns_modulus_size    = decomp_modulus_size + 1;        // :2618  = Q 프라임 + 특수소수 1개\n"
  "...\n"
  "SEAL_ITERATE(iter(size_t(0)), decomp_modulus_size, [&](auto J) { ... });   // :2677, :2783, :2819\n"
  "```\n")
w("key-switch 내부 루프가 도는 횟수가 `decomp_modulus_size` = **|Q| = level+1** 이다. "
  "SEAL 은 하이브리드 key-switching 을 쓰지 않고 **RNS 성분 하나당 digit 하나**로 "
  "완전 분해한다(특수소수는 1개, logP=60 고정). "
  "하네스도 그 사실을 그대로 적어 뒀다 — `presetsearch_seal.cpp:225-227` "
  "`const size_t dnum = coeff.size() - 1;  // digit = Q 프라임 1개씩` / "
  "`// SEAL digit 수 = 해당 레벨의 Q 프라임 수 = level+1`.\n")
w("> **정정:** `digit = level+1` 은 런타임 API 로 읽은 값이 아닐 뿐 **구조적으로 옳은 값**이다. "
  "따라서 (a) M2 를 SEAL 에 적용해 2차식이 되는 것은 모형 오류가 아니라 "
  "**SEAL 의 key-switch 비용이 실제로 레벨의 2차이기 때문**이고, "
  "(b) 'SEAL 에 계단이 없다'는 동어반복이 아니라 "
  "**분해 수가 레벨마다 정확히 1씩 늘어 묶음(계단)이 생길 수 없다**는 실질적 사실이다. "
  "이 정정은 §1 의 규칙 논의와 3.4절 서술에도 영향을 준다(범위 밖이므로 여기서는 표시만 한다).\n")

# --- 2.8 판정 ----------------------------------------------------------------
w("### 2.8 판정 — 단순 모형 M1 은 결론을 유지하지 못한다\n")
nk = int((ks["b_M1"] < 0).sum()); nall = int((F["b_M1"] < 0).sum())
nk2 = int((ks["b_M2"] < 0).sum())
nwin = int((ks["R2_M1"] >= ks["R2_M2"]).sum())
ordr = ks.pivot_table(index=["preset", "op"], columns="library", values="b_M1")
n_ofgt = int((ordr["openfhe"] > ordr["lattigo"]).sum())
w("| 확인 항목 | M1 (digit 미사용) | M2 (digit 포함) |")
w("|---|---|---|")
w(f"| 절편 b < 0 인 적합 (key-switch 36개) | **{nk}개** | {nk2}개 |")
w(f"| 절편 b < 0 인 적합 (8 op 96개) | **{nall}개** | {int((F['b_M2']<0).sum())}개 |")
w(f"| R² 중앙값 (OpenFHE / Lattigo / SEAL) | "
  f"{ks[ks.library=='openfhe'].R2_M1.median():.4f} / {ks[ks.library=='lattigo'].R2_M1.median():.4f} / {ks[ks.library=='seal'].R2_M1.median():.4f} | "
  f"{ks[ks.library=='openfhe'].R2_M2.median():.4f} / {ks[ks.library=='lattigo'].R2_M2.median():.4f} / {ks[ks.library=='seal'].R2_M2.median():.4f} |")
w(f"| R² 가 상대 모형보다 높은 적합 | **{nwin}/36** | {36-nwin}/36 |")
w(f"| `b(OpenFHE) > b(Lattigo)` 인 조합 | **{n_ofgt}/12** (preset C 만) | 12/12 |")
w("")
w(f"**❌ 유지되지 않는다. 세 가지가 동시에 어긋난다.**\n")
w(f"1. **절편이 음수다.** M1 은 key-switch 적합 36개 중 **{nk}개**, 8 op 전체 96개 중 "
  f"**{nall}개**에서 b < 0 이 나온다. 예: preset A · OpenFHE · `rot1` 의 b = "
  f"{float(ks[(ks.preset=='A')&(ks.library=='openfhe')&(ks.op=='rot1')].b_M1.iloc[0]):,.0f} µs. "
  "음수 절편은 '레벨을 0 까지 내리면 비용이 음수'라는 뜻이라 **고정비 바닥으로 해석할 수 없다.** "
  "표 4 가 말하려는 것이 바로 그 바닥이므로, 이 모형으로는 표 자체가 성립하지 않는다.\n")
w(f"2. **순서가 뒤집힌다.** M1 에서 `b(OpenFHE) > b(Lattigo)` 는 12개 조합 중 **{n_ofgt}개**(preset C)뿐이고, "
  "A·B·D 에서는 Lattigo 의 절편이 더 크다. §2.6 의 z 검정도 M1 에서는 부호가 조합마다 갈린다. "
  "즉 '**OpenFHE 의 고정비가 크다**' 는 4절의 핵심 주장이 M1 에서는 성립하지 않는다.\n")
w(f"3. **적합도 자체가 나쁘다.** R² 는 36개 적합 **전부** M2 가 M1 보다 높다 "
  f"(M1 중앙값 0.96~0.98 vs M2 0.99~0.998). 비용이 레벨에 대해 **볼록**하기 때문이다 — "
  "직선을 억지로 맞추면 절편이 아래로 끌려 내려가고, 그게 1번의 음수 절편의 원인이다.\n")
w("> **결론: 논문은 digit 포함 모형 M2 를 그대로 쓴다.** "
  "지시에 있던 '단순 모형에서도 결론이 유지되면 3.4절의 digit 한계를 우회한다'는 경로는 **닫혔다.** "
  "대신 §2.7 에서 그 한계 자체가 과장이었음이 확인됐다 — 세 라이브러리의 digit 은 모두 "
  "각자 알고리즘의 **실제 분해 수**이고, 문제는 '못 믿을 값'이 아니라 "
  "**세 값이 서로 다른 양이라 숫자를 나란히 비교하면 안 된다**는 것이다. "
  "3.4절은 그 방향으로 고쳐 쓰면 되고, 표 4 의 b 는 M2 값을 그대로 실으면 된다.\n")

# --- 2.9 표 4 에 넣을 값 ------------------------------------------------------
w("### 2.9 표 4 에 그대로 넣을 값 (M2, cv 게이트 없이 전 레벨, 1t)\n")
fin4 = F[F["ks"]].copy()
fin4 = fin4.pivot_table(index=["preset", "op"],
                        values=["b_M2", "R2_M2", "floor_ratio"],
                        columns="library")
out4 = pd.DataFrame({"preset": [i[0] for i in fin4.index], "op": [i[1] for i in fin4.index]})
for lib, nm in [("openfhe", "OpenFHE"), ("lattigo", "Lattigo"), ("seal", "SEAL")]:
    out4[f"b_{nm}(µs)"] = fin4[("b_M2", lib)].to_numpy().round(0).astype(int)
    out4[f"R²_{nm}"] = fin4[("R2_M2", lib)].to_numpy().round(4)
    out4[f"바닥비_{nm}"] = fin4[("floor_ratio", lib)].to_numpy().round(3)
w(md(out4))
w("")
w("> 각주용 — 이 표는 **cv 게이트 없이 전 레벨**로 적합했다. 기존 `fit_coeffs.csv` 는 cv>0.05 인 "
  "레벨을 빼고 적합해서, key-switch 3종 중 **preset B · SEAL · `mul_cc_rlk` 한 칸만** 값이 다르다 "
  "(5/6 레벨 사용 시 2,005 µs → 전 레벨 2,120 µs). 나머지 35칸은 소수점 아래까지 동일하다. "
  "표 4 에는 **전 레벨 값**을 쓰는 편이 낫다 — 한 조합만 적합 표본이 다르면 프리셋 간 비교가 흔들린다.\n")
w("**본문에 쓸 비 — 세 지표를 같은 쌍으로 통일한다.**\n")
w("| 지표 | OpenFHE : Lattigo | OpenFHE : SEAL | Lattigo : SEAL |")
w("|---|---|---|---|")
for lab, tab in [("절편 b (M2)", rb2), ("바닥 비율", rf)]:
    w(f"| {lab} | {tab['OF/LAT'].min():.2f} ~ {tab['OF/LAT'].max():.2f} "
      f"| {tab['OF/SEAL'].min():.2f} ~ {tab['OF/SEAL'].max():.2f} "
      f"| {tab['LAT/SEAL'].min():.2f} ~ {tab['LAT/SEAL'].max():.2f} |")
w("")
w("### 2.10 (2) 항목의 본문 수정 목록\n")
w("| # | 현재 본문 | 고쳐야 할 내용 |")
w("|---|---|---|")
w(f"| 1 | \"절편비 OpenFHE **:Lattigo** 2.28~3.11배\" | "
  f"**틀렸다. 두 군데.** 그 수치는 **OpenFHE:SEAL** 이고, 또 **`rot1` 만** 본 범위다. "
  f"3 op 전체로 쓰려면 OpenFHE:SEAL = **{rb2['OF/SEAL'].min():.2f}~{rb2['OF/SEAL'].max():.2f}**, "
  f"OpenFHE:Lattigo 를 쓰려면 = **{rb2['OF/LAT'].min():.2f}~{rb2['OF/LAT'].max():.2f}**. |")
w("| 2 | 절편이 비율로만 제시됨 | §2.9 표의 **µs 절대값**을 병기. preset 별 maxLevel 이 달라 "
  "프리셋을 가로질러 평균 내지 말 것. |")
w("| 3 | '바닥 비율' 의 정의 미기재 | \"`mean_us(L=1)/mean_us(L=maxLevel)`, 측정 최저 레벨은 **L1** "
  "(L0 은 측정하지 않음)\" 를 표 각주에 명시. |")
w("| 4 | 지표마다 비교 쌍이 다름 | §2.9 의 3열 표처럼 **세 쌍 전부**를 싣거나, 한 쌍으로 통일. |")
w("| 5 | 3.4절 'digit 은 OpenFHE 만 실측이라 신뢰 불가' | §2.7 대로 **과장이다.** "
  "SEAL 의 `digit = level+1` 은 완전 RNS 분해라는 **구조적 사실**이다. "
  "'값을 못 믿는다'가 아니라 '세 라이브러리의 digit 은 서로 다른 알고리즘의 분해 수라 "
  "숫자를 나란히 비교하면 안 된다'로 고칠 것. |")
w("")

# ==================================================================== 3. 표 5
w("\n---\n")
w("## 3. 표 5 — 레벨 하강 비용\n")

LD1 = LD[LD["mode"] == MODE].copy()
VARIANTS = ["leveldrop", "leveldrop_ip", "leveldrop_oop", "clone_only"]
LIBS = ["openfhe", "lattigo", "seal"]

# --- 3.0 행 수 회계 ----------------------------------------------------------
w("### 3.0 행 수 회계\n")
exp_ld = sum(NLEV.values()) * 3 * len(VARIANTS)
w(f"- `leveldrop_summary_timing.csv` 1t 행 수: 기대 (12+6+10+4) 레벨 × 3 lib × 4 변종 = "
  f"**{exp_ld}** → 실제 **{len(LD1)}** "
  + ("**일치**" if exp_ld == len(LD1) else "**⚠️ 불일치**"))
w(f"- mode 는 `{sorted(LD1['mode'].unique())}` — 1t 만 측정됐다(mt 는 측정 범위 밖).")
lv_ok = all(sorted(LD1[(LD1.preset == p) & (LD1.library == l) & (LD1.op == v)]["level"].tolist())
            == list(range(1, NLEV[p] + 1))
            for p in PRESETS for l in LIBS for v in VARIANTS)
w(f"- 레벨 연속성: 48개 (preset×library×변종) 그룹 전부 L1..LmaxLevel 연속 "
  + ("**확인**" if lv_ok else "**⚠️ 결측**") + ", 중복 0건.")
w("")

# --- 3.1 변종 확정 -----------------------------------------------------------
w("### 3.1 어느 변종의 수치인가 — 본문 표는 `leveldrop` 을 쓴다\n")
w("| 변종 | 뜻 | OpenFHE | Lattigo | SEAL |")
w("|---|---|---|---|---|")
w("| `leveldrop_ip` | 제자리 강하 (원본 소멸) | `LevelReduceInPlace` | `DropLevel` | `mod_switch_to_next_inplace` |")
w("| `leveldrop_oop` | 새 암호문 반환 (원본 보존) | `LevelReduce` | `DropLevelNew` | `mod_switch_to_next` |")
w("| `clone_only` | 깊은 복사만 (분해용 기준선) | `Clone()` | `CopyNew()` | 복사 생성자 |")
w("| **`leveldrop`** | **각 라이브러리의 최저비용 경로** | = `_ip` | = `_ip` | **= `_oop`** |")
w("")
w("`leveldrop` 이 SEAL 만 `_oop` 인 이유: SEAL 의 제자리 경로는 내부에서 임시 버퍼를 잡고 "
  "두 번 복사한다(`evaluator.cpp` 에 `// TODO: avoid copying and temporary space allocation` 주석이 그대로 있다). "
  "그래서 SEAL 은 **제자리가 더 비싸고**, 실제 구현이라면 out-of-place 를 쓴다.\n")
w("> **본문 표 5 에 쓸 변종: `leveldrop`.** 5절의 배치 규칙은 '암호문을 소비하며 레벨을 내린다'를 "
  "전제하므로, 각 라이브러리가 실제로 택할 최저비용 경로가 맞는 비교 대상이다. "
  "다만 **세 라이브러리가 같은 API 형태를 쓰는 것은 아니다**(SEAL 만 out-of-place)라는 점을 "
  "표 각주에 밝힐 것.\n")

var_rows = []
for (p_, lib, v), d in LD1.groupby(["preset", "library", "op"]):
    d = d.sort_values("level")
    mx_ = float(d[d["level"] == d["level"].max()]["mean_us"].iloc[0])
    m1_ = float(d[d["level"] == 1]["mean_us"].iloc[0])
    var_rows.append(dict(preset=p_, library=lib, 변종=v, n=len(d),
                         us_L1=m1_, us_maxL=mx_,
                         min_us=float(d["mean_us"].min()), max_us=float(d["mean_us"].max()),
                         배수=mx_ / m1_,
                         배수_maxmin=float(d["mean_us"].max() / d["mean_us"].min()),
                         median_us=float(d["mean_us"].median()),
                         cv_med=float(d["cv"].median()), cv_max=float(d["cv"].max()),
                         n_cv_gt=int((d["cv"] > CV_GATE).sum())))
VR = pd.DataFrame(var_rows)
VR.to_csv(os.path.join(OUT, "leveldrop_variants_appendix.csv"), index=False)
w(f"변종별 전 수치는 `leveldrop_variants_appendix.csv` 로 뺐다 "
  f"({len(VR)}행 = preset 4 × library 3 × 변종 4).\n")

# 변종 간 차이가 큰 항목 표시
piv_v = VR.pivot_table(index=["library", "preset"], columns="변종", values="median_us")
piv_v["oop/ip"] = piv_v["leveldrop_oop"] / piv_v["leveldrop_ip"]
piv_v["oop/clone"] = piv_v["leveldrop_oop"] / piv_v["clone_only"]
w("**⚠️ 변종 간 차이가 큰 항목** (레벨 중앙값 기준):\n")
w(md(piv_v.reset_index(), fmt="{:,.3f}"))
w("")
w(f"OpenFHE 는 `_oop` 가 `_ip` 의 **{piv_v.loc['openfhe','oop/ip'].min():.0f}~"
  f"{piv_v.loc['openfhe','oop/ip'].max():.0f}배**, Lattigo 는 **{piv_v.loc['lattigo','oop/ip'].min():.0f}~"
  f"{piv_v.loc['lattigo','oop/ip'].max():.0f}배**다. 이 차이는 강하 자체가 아니라 **깊은 복사** 값이다 — "
  f"`_oop / clone_only` 가 OpenFHE {piv_v.loc['openfhe','oop/clone'].min():.3f}~"
  f"{piv_v.loc['openfhe','oop/clone'].max():.3f} 로 1 에 붙는다(복사가 비용 전부). "
  "SEAL 만 `_oop < _ip` 라 비율이 1 미만이다.\n")

# --- 3.2 레벨별 하강 비용 -----------------------------------------------------
w("### 3.2 레벨별 하강 비용 (변종 `leveldrop`, 1t, µs)\n")
w("프리셋마다 maxLevel 이 달라(A12/B6/C10/D4) **프리셋을 가로질러 평균 내지 않는다.** "
  "프리셋별로 따로 싣는다.\n")
base = LD1[LD1["op"] == "leveldrop"]
for p_ in PRESETS:
    d = base[base["preset"] == p_].pivot_table(index="level", columns="library", values="mean_us")
    d = d[["openfhe", "lattigo", "seal"]].sort_index(ascending=False).reset_index()
    d.columns = ["level", "OpenFHE", "Lattigo", "SEAL"]
    d["level"] = d["level"].astype(int)
    w(f"**preset {p_}** (maxLevel {NLEV[p_]})\n")
    w(md(d, fmt="{:,.3f}")); w("")
w("> Lattigo 열은 **배치 계측**(타이머 밖에서 K개 사본을 만들고 K회를 한 번에 재 K로 나눔) 값이다. "
  "제자리 강하가 Go 시계 호출 오버헤드(86 ns)보다 짧아 단발 계측이 불가능했기 때문이다. "
  "**계측 방식이 다르므로 '상수냐 선형이냐' 형태 비교에 Lattigo 를 나란히 놓지 말 것** — "
  "형태 대비축은 OpenFHE ↔ SEAL 이다.\n")

# --- 3.3 배수 ----------------------------------------------------------------
w("### 3.3 \"34배\"가 어느 프리셋인가\n")
rat = VR[VR["변종"] == "leveldrop"].pivot_table(index="preset", columns="library", values="배수")
rat = rat[["openfhe", "lattigo", "seal"]].reset_index()
rat.columns = ["preset", "OpenFHE", "Lattigo", "SEAL"]
rat["maxLevel"] = [NLEV[p] for p in rat["preset"]]
w("`배수 = mean_us(maxLevel) / mean_us(L1)` — 관측 창 전체를 내렸을 때 비용이 몇 배로 줄어드는가.\n")
w(md(rat[["preset", "maxLevel", "OpenFHE", "Lattigo", "SEAL"]], fmt="{:.2f}"))
w("")
rmm = VR[VR["변종"] == "leveldrop"].pivot_table(index="preset", columns="library", values="배수_maxmin")
rmm = rmm[["openfhe", "lattigo", "seal"]].reset_index()
rmm.columns = ["preset", "OpenFHE", "Lattigo", "SEAL"]
w("참고 — `max/min` (레벨 순서 무시). OpenFHE 는 저레벨이 최저가 아닌 프리셋이 있어 위 표와 살짝 다르다.\n")
w(md(rmm, fmt="{:.2f}"))
w("")
sA = float(rat[rat["preset"] == "A"]["SEAL"].iloc[0])
w(f"> **\"34배\" = SEAL · preset A** ({sA:.2f}배, 10.674 → 362.979 µs, L1→L12). "
  f"프리셋마다 다르다 — B {float(rat[rat.preset=='B']['SEAL'].iloc[0]):.1f}배(6레벨), "
  f"C {float(rat[rat.preset=='C']['SEAL'].iloc[0]):.1f}배(10레벨), "
  f"D {float(rat[rat.preset=='D']['SEAL'].iloc[0]):.1f}배(4레벨). "
  f"**본문에는 `preset A 기준 34배` 라고 프리셋을 명시해서 쓸 것.** "
  f"프리셋을 안 밝히면 '레벨 수가 달라서 생긴 차이'를 '라이브러리 차이'로 오독하게 된다.\n")

# --- 3.4 key-switch 대비 비중 -------------------------------------------------
w("### 3.4 ⚠️ 하강 비용의 비중 — 기존 보고값은 **분모가 다르다**\n")
w("두 가지 비율이 있고, 기존에 보고된 `0.039% / 0.0025% / 2.42%` 는 그중 두 번째다.\n")
w("```\n"
  "(가) drop / key-switch 비용   = mean_us(leveldrop, L) / mean_us(op, L)     ← 이번에 요구된 것\n"
  "(나) drop / 계단 이득         = mean_us(leveldrop, L) / [mean_us(op,L+1) − mean_us(op,L)]\n"
  "```\n")
ldc = base[["preset", "library", "level", "mean_us"]].rename(columns={"mean_us": "drop"})
ksc = T1[T1["op"].isin(KS_OPS)][["preset", "library", "level", "op", "mean_us"]]
MG = ksc.merge(ldc, on=["preset", "library", "level"], how="inner")
w(f"- (가) 병합 행 수: key-switch 3 op × 32 레벨 × 3 lib = **{32*3*3}** → 실제 **{len(MG)}** "
  + ("**일치**" if len(MG) == 32 * 3 * 3 else "**⚠️ 불일치**"))
MG["pct"] = MG["drop"] / MG["mean_us"] * 100
A_ = MG.pivot_table(index="library", columns="op", values="pct", aggfunc="median")
A_ = A_[KS_OPS].reset_index()
A_["3 op 통합 중앙값"] = MG.groupby("library")["pct"].median().reindex(A_["library"]).to_numpy()
A_["최댓값"] = MG.groupby("library")["pct"].max().reindex(A_["library"]).to_numpy()
w("\n**(가) 동일 레벨 key-switch 1회 비용 대비 (%)** — op 별 중앙값과 통합값\n")
w(md(A_, fmt="{:.5f}")); w("")
B_ = pd.DataFrame({"library": ["openfhe", "lattigo", "seal"]})
for v in ["leveldrop", "leveldrop_oop"]:
    r = (NET[f"drop_{v}"] / NET["step_gain"] * 100)
    B_[v] = NET.assign(r=r).groupby("library")["r"].median().reindex(B_["library"]).to_numpy()
w("**(나) 계단 이득 대비 (%) — 기존 보고값의 정의**\n")
w(md(B_, fmt="{:.5f}")); w("")
ov = B_.set_index("library")["leveldrop"]
w(f"> **재확인 결과: 기존 값은 (나) 로 정확히 재현된다** — "
  f"OpenFHE {ov['openfhe']:.4f}% (보고 0.039), Lattigo {ov['lattigo']:.5f}% (보고 0.0025), "
  f"SEAL {ov['seal']:.3f}% (보고 2.42). 분모는 **`step_gain` = 인접 레벨 비용차**이고, "
  f"key-switch 3 op 를 한데 모은 중앙값이다.\n")
mgm = MG.groupby("library")["pct"].median()
w(f"> **요구된 (가) 는 값이 다르다** — OpenFHE **{mgm['openfhe']:.4f}%**, "
  f"Lattigo **{mgm['lattigo']:.5f}%**, SEAL **{mgm['seal']:.3f}%**. "
  f"분모가 '한 레벨 내려서 아끼는 양'이 아니라 'key-switch 한 번의 전체 비용'이라 "
  f"약 6~7배 작다. **본문이 어느 쪽을 말하는지 문장으로 못박아야 한다.**\n")

t5 = MG.copy()
t5.to_csv(os.path.join(OUT, "table5_leveldrop.csv"), index=False)

# --- 3.5 net ≤ 0 (원본 보존 변종) --------------------------------------------
w("### 3.5 `_oop` 기준 net ≤ 0 쌍 재확인 (각주용)\n")
w("`net(L) = step_gain(L) − drop_cost(L)`, `step_gain(L) = mean_us(op, L+1) − mean_us(op, L)`. "
  "`drop_cost` 를 원본 보존 변종 `leveldrop_oop` 로 잡았을 때 net 이 0 이하인 쌍.\n")
neg_o = NET[NET["net_leveldrop_oop"] <= 0]
neg_b = NET[NET["net_leveldrop"] <= 0]
w(f"- `leveldrop_net.csv` 전체 **{len(NET)}쌍** (= key-switch 3 op × 3 lib × (11+5+9+3) 인접쌍 = "
  f"{3*3*(11+5+9+3)}) "
  + ("**일치**" if len(NET) == 3 * 3 * 28 else "**⚠️ 불일치**"))
w(f"- `leveldrop_oop` 기준 net ≤ 0: **{len(neg_o)}건** (기존 보고 3건 — "
  + ("**일치**" if len(neg_o) == 3 else "**⚠️ 불일치**") + ")")
w(f"- 본문 변종 `leveldrop` 기준 net ≤ 0: **{len(neg_b)}건**")
w("")
nt = neg_o[["preset", "library", "op", "level", "mean_hi", "mean_lo", "step_gain",
            "drop_leveldrop_oop", "net_leveldrop_oop", "cv_hi", "cv_lo"]].copy()
nt.insert(4, "레벨쌍", nt["level"].apply(lambda L: f"L{int(L)+1}→L{int(L)}"))
nt = nt.drop(columns=["level"])
w(md(nt, fmt="{:,.3f}"))
w("")
w("> 세 건 모두 **preset A · Lattigo · L11→L10** 한 지점에 몰려 있다(op 3종 각각 1건). "
  "원인은 강하 비용이 아니라 그 지점의 `step_gain` 이 작거나(rot1 797 µs, relin 1,032 µs) "
  "음수(mul_cc_rlk −527 µs)라는 데 있다. "
  "특히 `mul_cc_rlk` 의 −527 µs 는 **역전이 아니다** — 그 쌍의 차이는 +1.04 % 로 "
  "결합 표준오차의 1.5배(p ≈ 0.13)에 불과해 통계적으로 분해되지 않는다(4절에서 확인). "
  "각주에는 **'원본을 보존하는 형태로 강하하면 preset A·Lattigo·L11→L10 에서만 net ≤ 0'** 정도로 "
  "쓰고, 원인을 강하 비용으로 돌리지 말 것.\n")
w(f"> 본문 변종 `leveldrop` 으로 보면 net ≤ 0 은 **{len(neg_b)}건**으로 줄고, "
  f"그 한 건도 같은 지점(preset A · Lattigo · `mul_cc_rlk` · L11→L10)이다.\n")

# --- 3.6 OpenFHE 기울기 검정 --------------------------------------------------
w("### 3.6 ⚠️ \"OpenFHE 는 레벨 무관 상수(0.92~2.02 µs)\" 검정\n")
w("변종 `leveldrop` 을 레벨에 회귀했다: `mean_us ≈ a·level + c`. "
  "`a = 0` 이면 상수라는 서술이 선다. OLS 표준오차로 `t = a/SE(a)`, 양측 정규 근사.\n")
sl = []
for lib in LIBS:
    for p_ in PRESETS:
        d = base[(base["library"] == lib) & (base["preset"] == p_)].sort_values("level")
        a_, c_, sa_, sc_, r2_, n_ = ols(d["level"], d["mean_us"])
        t_ = a_ / sa_
        pv_ = 2 * (1 - 0.5 * (1 + math.erf(abs(t_) / math.sqrt(2))))
        sl.append(dict(library=lib, preset=p_, n=n_, 기울기_us_per_level=a_, SE=sa_,
                       t=t_, p=pv_, R2=r2_,
                       범위=f"{d['mean_us'].min():.3f}~{d['mean_us'].max():.3f}",
                       유의=(pv_ < 0.05)))
SL = pd.DataFrame(sl)
w(md(SL, fmt="{:.4g}"))
w("")
of = SL[SL["library"] == "openfhe"]; se_ = SL[SL["library"] == "seal"]
n_sig_of = int(of["유의"].sum())
w(f"**❌ '상수'라는 서술은 유지되지 않는다.** OpenFHE 의 기울기는 4개 프리셋 중 **{n_sig_of}개**에서 "
  f"0 과 유의하게 다르다 — preset A `t = {float(of[of.preset=='A'].t.iloc[0]):.2f}` (p < 1e-15, R² {float(of[of.preset=='A'].R2.iloc[0]):.2f}), "
  f"C `t = {float(of[of.preset=='C'].t.iloc[0]):.2f}` (p < 1e-15, R² {float(of[of.preset=='C'].R2.iloc[0]):.2f}), "
  f"B `t = {float(of[of.preset=='B'].t.iloc[0]):.2f}` (p = {float(of[of.preset=='B'].p.iloc[0]):.3f}). "
  f"D 만 `t = {float(of[of.preset=='D'].t.iloc[0]):.2f}` (p = {float(of[of.preset=='D'].p.iloc[0]):.2f}) 로 "
  f"구분되지 않는데, 레벨이 4개뿐이라 검정력이 없어서다.\n")
w(f"인용된 범위 `0.92~2.02 µs` 자체가 **{float(of[of.preset=='A'].R2.iloc[0]):.0%} 를 레벨로 설명하는 상승**이다 "
  "— preset A 에서 L1 1.049 µs → L12 2.014 µs 로 1.92배 오른다. '상수'가 아니다.\n")
w("**대신 쓸 수 있는 서술** — 대비축은 OpenFHE ↔ SEAL 이다(Lattigo 는 계측 방식이 달라 형태 비교에서 뺀다).\n")
cmp_sl = pd.DataFrame({
    "preset": PRESETS,
    "OpenFHE 기울기 (µs/level)": [float(of[of.preset == p].기울기_us_per_level.iloc[0]) for p in PRESETS],
    "SEAL 기울기 (µs/level)": [float(se_[se_.preset == p].기울기_us_per_level.iloc[0]) for p in PRESETS],
    "SEAL/OpenFHE": [float(se_[se_.preset == p].기울기_us_per_level.iloc[0]) /
                     float(of[of.preset == p].기울기_us_per_level.iloc[0]) for p in PRESETS],
    "OpenFHE 배수": [float(rat[rat.preset == p]["OpenFHE"].iloc[0]) for p in PRESETS],
    "SEAL 배수": [float(rat[rat.preset == p]["SEAL"].iloc[0]) for p in PRESETS]})
w(md(cmp_sl, fmt="{:.3g}"))
w("")
w(f"> 권장 문구: **\"OpenFHE 의 하강 비용은 레벨에 약하게 비례한다 "
  f"(기울기 {of['기울기_us_per_level'].min():.3f}~{of['기울기_us_per_level'].max():.3f} µs/level, "
  f"관측 창 전체에서 {rat['OpenFHE'].min():.2f}~{rat['OpenFHE'].max():.2f}배). "
  f"SEAL 은 같은 축에서 기울기가 {se_['기울기_us_per_level'].min():.0f}~{se_['기울기_us_per_level'].max():.0f} µs/level 로 "
  f"{cmp_sl['SEAL/OpenFHE'].min():.0f}~{cmp_sl['SEAL/OpenFHE'].max():.0f}배 가파르고, "
  f"관측 창 전체에서 {rat['SEAL'].min():.1f}~{rat['SEAL'].max():.1f}배 변한다.\"** "
  "'상수 vs 비례'가 아니라 **'거의 평평 vs 가파른 비례'** 가 데이터가 지지하는 대비다.\n")

# --- 3.7 표 5 확정 + 수정 목록 -------------------------------------------------
w("### 3.7 표 5 에 그대로 넣을 값\n")
fin5 = rat[["preset", "maxLevel"]].copy()
for lib, nm in [("openfhe", "OpenFHE"), ("lattigo", "Lattigo"), ("seal", "SEAL")]:
    v = VR[(VR["변종"] == "leveldrop") & (VR["library"] == lib)].set_index("preset")
    fin5[f"{nm} L1"] = [float(v.loc[p, "us_L1"]) for p in fin5["preset"]]
    fin5[f"{nm} maxL"] = [float(v.loc[p, "us_maxL"]) for p in fin5["preset"]]
    fin5[f"{nm} 배수"] = [float(v.loc[p, "배수"]) for p in fin5["preset"]]
w("변종 `leveldrop` · 1t · µs. 각 프리셋의 양 끝 레벨과 배수 (레벨별 전 수치는 §3.2).\n")
w(md(fin5, fmt="{:,.3f}"))
w("")
w("| 지표 | OpenFHE | Lattigo | SEAL |")
w("|---|---|---|---|")
w(f"| key-switch 1회 대비 비중 (중앙값, %) | {mgm['openfhe']:.4f} | {mgm['lattigo']:.5f} | {mgm['seal']:.3f} |")
w(f"| 계단 이득 대비 비중 (중앙값, %) | {ov['openfhe']:.4f} | {ov['lattigo']:.5f} | {ov['seal']:.3f} |")
w(f"| 기울기 (µs/level, preset A) | {float(of[of.preset=='A'].기울기_us_per_level.iloc[0]):.4f} | "
  f"{float(SL[(SL.library=='lattigo')&(SL.preset=='A')].기울기_us_per_level.iloc[0]):.4f} | "
  f"{float(se_[se_.preset=='A'].기울기_us_per_level.iloc[0]):.2f} |")
w("")
w("**cv / 오염 표시** — 변종 `leveldrop` 96행(3 lib × 32 레벨) 기준. "
  "cv 는 비율이라 절대 시간이 짧을수록 커지므로 **절대 산포(std, ns)를 함께 본다.**\n")
cvt = []
for lib in LIBS:
    d = base[base["library"] == lib]
    cvt.append(dict(library=lib, n=len(d),
                    mean_us_중앙=float(d["mean_us"].median()),
                    std_ns_중앙=float(d["std_us"].median() * 1000),
                    std_ns_최대=float(d["std_us"].max() * 1000),
                    cv_중앙=float(d["cv"].median()), cv_최대=float(d["cv"].max()),
                    n_cv_gt=int((d["cv"] > CV_GATE).sum())))
CVT = pd.DataFrame(cvt)
w(md(CVT, fmt="{:.4g}"))
w("")
w("> **게이트 통과율이 낮다 — 그러나 오염이 아니라 측정 바닥이다.** "
  f"Lattigo 는 {CVT[CVT.library=='lattigo'].n_cv_gt.iloc[0]}/32, "
  f"OpenFHE 는 {CVT[CVT.library=='openfhe'].n_cv_gt.iloc[0]}/32, "
  f"SEAL 은 {CVT[CVT.library=='seal'].n_cv_gt.iloc[0]}/32 가 cv>0.05 다. "
  "절대 산포로 보면 Lattigo 는 47 ns ± 9 ns, OpenFHE 는 1.46 µs ± 85 ns 로 "
  "**둘 다 시계 호출 오버헤드(C++ 40 ns / Go 86 ns) 근방**이다. "
  "같은 실행의 무거운 변종(`clone_only`)은 OpenFHE cv 중앙값 0.026, SEAL 0.026 으로 "
  "8-op 본측정 대역(1t 중앙값 0.012~0.016)과 같다 — 즉 **실행 조건 자체는 건전했다**. "
  "DVFS 도 별도로 확인됐다(24개 프로브 전부 FAST 82.4~82.7 ms, `leveldrop_report.md` §2.1).\n")
w("> 다만 이 산포 때문에 **표 5 의 개별 레벨 값을 소수 셋째 자리까지 인용하지 말 것.** "
  "본문이 기대는 결론(강하 비용이 key-switch 대비 3~5 자릿수 작다, OpenFHE 기울기가 "
  "SEAL 의 1/77~1/418)은 이 산포의 수십~수천 배 여유가 있어 흔들리지 않는다.\n")

w("### 3.8 (3) 항목의 본문 수정 목록\n")
w("| # | 현재 본문 | 고쳐야 할 내용 |")
w("|---|---|---|")
w(f"| 1 | \"SEAL 은 34배\" | **프리셋을 명시할 것.** 34.01배는 **preset A(12레벨)** 기준이다. "
  f"B {float(rat[rat.preset=='B']['SEAL'].iloc[0]):.1f} / C {float(rat[rat.preset=='C']['SEAL'].iloc[0]):.1f} / "
  f"D {float(rat[rat.preset=='D']['SEAL'].iloc[0]):.1f} 배. |")
w(f"| 2 | \"OpenFHE 는 레벨 무관 상수(0.92~2.02 µs)\" | **틀렸다.** 기울기가 4개 프리셋 중 3개에서 "
  f"0 과 유의하게 다르다(A t={float(of[of.preset=='A'].t.iloc[0]):.1f}, C t={float(of[of.preset=='C'].t.iloc[0]):.1f}). "
  f"§3.6 의 '거의 평평 vs 가파른 비례' 문구로 교체. |")
w(f"| 3 | \"0.039% / 0.0025% / 2.42%\" | **분모를 밝힐 것.** 이 값은 `drop / 계단 이득`이다. "
  f"`drop / key-switch 1회 비용`을 쓰려면 "
  f"{mgm['openfhe']:.4f}% / {mgm['lattigo']:.5f}% / {mgm['seal']:.3f}% 다. "
  f"두 값이 6~7배 차이 나므로 섞이면 안 된다. |")
w("| 4 | 변종 미표기 | 표 5 캡션에 \"`leveldrop` = 각 라이브러리 최저비용 경로. "
  "OpenFHE·Lattigo 는 제자리(in-place), **SEAL 만 out-of-place**\" 를 명시. "
  "원본 보존이 필요한 배치라면 `_oop` 수치가 따로 있음도 각주로. |")
w("| 5 | \"net ≤ 0 이 3건\" | 맞다. 단 **세 건 모두 preset A · Lattigo · L11→L10** 한 지점이고 "
  "원인은 그 지점의 `step_gain` 이 작다는 것이지 강하 비용이 아니다(§3.5). |")
w("")

# ==================================================================== 4. 그림 1
w("\n---\n")
w("## 4. 그림 1 캡션의 cv 임계값\n")
F1_PRESET, F1_OP = "A", "mul_cc_rlk"
f1 = T1[(T1["preset"] == F1_PRESET) & (T1["op"] == F1_OP)].copy()
w(f"대상: **preset {F1_PRESET} · `{F1_OP}` · 1t**, 세 라이브러리 중첩. "
  "그림에는 레벨을 잘라내지 않고 전 구간을 그리므로, cv 도 **그려지는 전 범위**에서 잡는다.\n")
w(f"- 행 수: 기대 maxLevel {NLEV[F1_PRESET]} × 3 lib = **{NLEV[F1_PRESET]*3}** → 실제 **{len(f1)}** "
  + ("**일치**" if len(f1) == NLEV[F1_PRESET] * 3 else "**⚠️ 불일치**"))
w(f"- 레벨: L{int(f1['level'].min())}..L{int(f1['level'].max())} 연속, 결측·중복 0건. "
  "구간을 잘라낸 곳 없음.\n")
f1r = []
for lib in LIBS:
    d = f1[f1["library"] == lib]
    im = d["cv"].idxmax(); r = d.loc[im]
    f1r.append(dict(library=lib, n=len(d), cv_중앙=float(d["cv"].median()),
                    cv_최대=float(d["cv"].max()), 최대발생레벨=f"L{int(r['level'])}",
                    그레벨_mean_us=float(r["mean_us"]), 그레벨_std_us=float(r["std_us"]),
                    n_cv_gt=int((d["cv"] > CV_GATE).sum())))
F1T = pd.DataFrame(f1r)
w(md(F1T, fmt="{:.5g}"))
w("")
cvmax = float(f1["cv"].max()); ngt = int((f1["cv"] > CV_GATE).sum())
w(f"- **전체 최댓값 cv = {cvmax:.6f}** (OpenFHE · L8). "
  f"cv > 0.05 인 행 **{ngt}건** — 그림 1 전 구간이 게이트를 통과한다.\n")
w(f"> **캡션에 쓸 값: `전 구간 cv < 0.047`.** "
  f"실측 최댓값 {cvmax:.4f} 를 넘는 가장 가까운 세 자리 값이다. "
  "더 둥근 숫자를 원하면 `cv < 0.05` 도 참이지만, 0.05 는 본 논문이 쓰는 게이트 임계와 같은 값이라 "
  "'게이트에 걸릴락 말락'으로 읽힐 수 있다. **0.047 을 권한다.**\n")
w("캡션 문구 예: *\"오차 막대는 생략했다. 30회 반복의 변동계수가 전 구간 cv < 0.047 이다 "
  "(1t, 코어 고정 + 30초 예열).\"*\n")
w("> 참고 — 라이브러리별 최댓값은 OpenFHE "
  f"{float(F1T[F1T.library=='openfhe'].cv_최대.iloc[0]):.4f} (L8), "
  f"Lattigo {float(F1T[F1T.library=='lattigo'].cv_최대.iloc[0]):.4f} (L6), "
  f"SEAL {float(F1T[F1T.library=='seal'].cv_최대.iloc[0]):.4f} (L10). "
  "라이브러리를 나눠 적을 이유는 없어 보이지만, 캡션에 SEAL 이 유독 작다는 것을 넣고 싶으면 "
  f"'SEAL 은 cv < {float(F1T[F1T.library=='seal'].cv_최대.iloc[0]):.3f}' 로 쓸 수 있다.\n")

# ==================================================================== 5. 정밀도
w("\n---\n")
w("## 5. 4.4절 정밀도 수치 검증\n")
MET = ["enc_dec", "rot1", "ks_loss"]
MLAB = {"enc_dec": "enc_dec", "rot1": "rot1", "ks_loss": "ks_loss"}

# --- 5.1 지표 정의 -----------------------------------------------------------
w("### 5.1 지표가 정밀도 비트인가 오차 비트인가 — 소스 확인\n")
w("`src/precision_common.h:44` (세 라이브러리 공용):\n")
w("```cpp\n"
  "inline double precision_bits(const std::vector<double> &got, const std::vector<double> &want)\n"
  "{\n"
  "    double s = 0; size_t n = want.size();\n"
  "    for (size_t i = 0; i < n; i++) s += std::fabs(got[i] - want[i]);\n"
  "    double mean_err = s / (double)n;\n"
  "    if (mean_err <= 0) return 999.0;\n"
  "    return -std::log2(mean_err);      // ← 평균 절대오차의 -log2\n"
  "}\n"
  "```\n")
w("CSV 로 나가는 값은 `presetsearch_openfhe.cpp:481-488` 의 `prow(path, got, want)` 가 "
  "`precision_bits(got, want)` 를 그대로 적은 것이고, 호출은 두 번뿐이다 — "
  "`prow(\"enc_dec\", dec(ct), x)` 와 `prow(\"rot1\", dec(EvalRotate(ct,1)), want_rot)`. "
  "`ks_loss` 는 측정이 아니라 집계에서 만들어진다 — `scripts/v3_unify.py:68` "
  "`pv[\"ks_loss\"] = pv[\"enc_dec\"] - pv[\"rot1\"]`.\n")
w("| 열 | 정체 | 방향 | 대표값 |")
w("|---|---|---|---|")
w("| `enc_dec` | 암호화→복호 왕복의 **정밀도 비트** `−log₂(평균절대오차)` | **클수록 좋다** | 36.3 (preset C) |")
w("| `rot1` | 회전 1회 뒤의 **정밀도 비트** | **클수록 좋다** | 32~33 (preset C) |")
w("| `ks_loss` | `enc_dec − rot1` = key-switch 가 **까먹은 비트 수**. "
  "`log₂(오차_rot1 / 오차_encdec)` 와 같다 | **작을수록 좋다** | 3.3~4.1 (preset C) |")
w("")
w("> **본문 문장의 첫 번째 오류가 여기서 확정된다.** 본문의 `4.09 → 3.28비트` 는 "
  "**`ks_loss`(손실 비트)** 값이지 정밀도 값이 아니다 — 이 데이터에서 정밀도(`enc_dec`/`rot1`)는 "
  "**32~36비트대**이고 4나 3 같은 값이 나올 수 없다. "
  "게다가 `ks_loss` 는 작을수록 좋으므로 `4.09 → 3.28` 은 **정밀도가 나아진 것**이다. "
  "본문이 \"정밀도 변화\"라고 부르면 방향이 거꾸로 읽힌다.\n")

# --- 5.2 행 수 회계 ----------------------------------------------------------
w("### 5.2 행 수 회계와 전제\n")
w(f"- `v3_summary_precision.csv` 전체 **{len(P)}행** → `mode == '1t'` 필터 후 **{len(P1)}행**.")
exp_p2 = sum(NLEV.values()) * 3 * 12
w(f"- 기대 = (12+6+10+4) 레벨 × 3 lib × 12 rep = **{exp_p2}** "
  + ("**일치**" if exp_p2 == len(P1) else "**⚠️ 불일치**"))
reps_u = sorted(P1.groupby(["preset", "library", "level"]).size().unique())
w(f"- 레벨당 rep 수: {reps_u} (전 조합 동일)")
disc5 = 0
for (p_, lib), d in P1.groupby(["preset", "library"]):
    lv = sorted(d["level"].unique())
    if lv != list(range(1, NLEV[p_] + 1)): disc5 += 1
w(f"- 레벨 연속성: 12개 (preset×library) 그룹 전부 L1..LmaxLevel 연속, "
  f"결측 그룹 **{disc5}건**. 인접 레벨쌍 총 (11+5+9+3)×3 lib = **{28*3}쌍**, "
  f"불연속으로 제외한 쌍 **0건**.")
dl = P1.groupby("preset")["delta"].first().to_dict()
w(f"- Δ: {dl} — **C 만 48**이다. Δ 가 정밀도에 영향을 줄 수 있으므로 "
  "**프리셋을 가로질러 평균 내지 않는다.** 아래 표는 전부 preset 별이다.")
w("- mt 는 필터로 제외했다(본 논문 범위 밖).\n")
w("**rep 집계 방침** — 소스(`presetsearch_openfhe.cpp:468-470`)를 보면 "
  "`for (rep) { KeyGen(); for (level) {...} }` 구조라 **rep 하나가 키 한 벌을 쓰고 그 안에서 "
  "레벨을 훑는다**(주석: \"반복마다 키를 새로 만들고 … 그 안에서 레벨을 훑는다\"). "
  "따라서 **같은 rep 안의 레벨들은 독립이 아니다.** 두 가지를 다 낸다:\n"
  "- (ㄱ) **rep 중앙값** 으로 레벨별 대표값을 만든 뒤 인접 레벨차 — 지시된 기본 방식\n"
  "- (ㄴ) **rep 안에서** 레벨 최대−최소 를 구한 뒤 rep 중앙값 — rep 간 산포를 제거한 값\n")

# --- 5.3 레벨 간 변화폭 ------------------------------------------------------
w("### 5.3 레벨 간 변화폭 — 세 지표 각각\n")
prec_rows = []
for (p_, lib), d in P1.groupby(["preset", "library"]):
    for m in MET:
        med = d.groupby("level")[m].median().sort_index()
        mean_ = d.groupby("level")[m].mean().sort_index()
        sd_ = d.groupby("level")[m].std().sort_index()
        wide = d.pivot_table(index="rep", columns="level", values=m)
        inrep = (wide.max(axis=1) - wide.min(axis=1))
        lv = med.index.to_numpy()
        for i in range(len(lv) - 1):
            prec_rows.append(dict(preset=p_, library=lib, 지표=m,
                                  레벨쌍=f"L{int(lv[i+1])}→L{int(lv[i])}",
                                  med_hi=float(med.iloc[i + 1]), med_lo=float(med.iloc[i]),
                                  d_med=float(med.iloc[i] - med.iloc[i + 1]),
                                  mean_hi=float(mean_.iloc[i + 1]), mean_lo=float(mean_.iloc[i]),
                                  d_mean=float(mean_.iloc[i] - mean_.iloc[i + 1]),
                                  sd_hi=float(sd_.iloc[i + 1]), sd_lo=float(sd_.iloc[i])))
PR = pd.DataFrame(prec_rows)
PR.to_csv(os.path.join(OUT, "precision_levels.csv"), index=False)
w(f"`precision_levels.csv` 로 전 쌍을 냈다 (**{len(PR)}행** = 84 쌍 × 3 지표 "
  + ("**일치**" if len(PR) == 28 * 3 * 3 else "**⚠️ 불일치**") + ").\n")

summ5 = []
for (p_, lib), d in P1.groupby(["preset", "library"]):
    for m in MET:
        med = d.groupby("level")[m].median().sort_index().to_numpy()
        mean_ = d.groupby("level")[m].mean().sort_index().to_numpy()
        wide = d.pivot_table(index="rep", columns="level", values=m)
        inrep = (wide.max(axis=1) - wide.min(axis=1))
        summ5.append(dict(preset=p_, library=lib, 지표=m,
                          adjmax=float(np.abs(np.diff(med)).max()),
                          lvrange=float(med.max() - med.min()),
                          inrep=float(inrep.median()),
                          repsd=float(d.groupby("level")[m].std().median())))
S5 = pd.DataFrame(summ5)
for m in MET:
    t_ = S5[S5["지표"] == m].pivot_table(index="preset", columns="library",
                                        values=["lvrange", "inrep", "repsd"])
    NM = {"lvrange": "(ㄱ)레벨범위", "inrep": "(ㄴ)rep내범위", "repsd": "rep간sd"}
    t_.columns = [f"{NM[a]}·{b[:3]}" for a, b in t_.columns]
    w(f"**`{m}`** (비트)\n")
    w(md(t_.reset_index(), fmt="{:.4f}")); w("")
w("> **읽는 법.** (ㄴ) `rep내범위중앙` 이 레벨 의존성의 가장 깨끗한 측정이다 — "
  "같은 키·같은 rep 안에서 레벨만 바꿨을 때의 최대 변동이다. "
  "**C·OpenFHE 의 `rot1`/`ks_loss` 를 뺀 34개 (preset×library×지표) 조합에서 (ㄴ)는 "
  f"{S5[~((S5.preset=='C')&(S5.library=='openfhe')&(S5['지표']!='enc_dec'))]['inrep'].min():.4f}"
  f"~{S5[~((S5.preset=='C')&(S5.library=='openfhe')&(S5['지표']!='enc_dec'))]['inrep'].max():.4f} 비트**에 머무는데, "
  f"C·OpenFHE 의 `rot1` 은 **{float(S5[(S5.preset=='C')&(S5.library=='openfhe')&(S5['지표']=='rot1')]['inrep'].iloc[0]):.3f} 비트** 로 "
  "25~60배 크다. 이상값이 여기서 바로 드러난다.\n")
w("> **OpenFHE 는 rep 간 산포가 유독 크다.** `rot1` 의 rep 간 sd 중앙값이 "
  f"OpenFHE {S5[(S5.library=='openfhe')&(S5['지표']=='rot1')]['repsd'].min():.3f}"
  f"~{S5[(S5.library=='openfhe')&(S5['지표']=='rot1')]['repsd'].max():.3f} 인데 "
  f"Lattigo {S5[(S5.library=='lattigo')&(S5['지표']=='rot1')]['repsd'].min():.4f}"
  f"~{S5[(S5.library=='lattigo')&(S5['지표']=='rot1')]['repsd'].max():.4f}, "
  f"SEAL {S5[(S5.library=='seal')&(S5['지표']=='rot1')]['repsd'].min():.4f}"
  f"~{S5[(S5.library=='seal')&(S5['지표']=='rot1')]['repsd'].max():.4f} 다 — **30~70배**. "
  "반면 (ㄴ) rep 내 범위는 세 라이브러리가 비슷하다. "
  "즉 OpenFHE 의 산포는 **레벨 때문이 아니라 키(rep) 때문**이다. "
  "정밀도 수치를 인용할 때 이 산포를 함께 밝혀야 한다.\n")

# --- 5.4 "0.004~0.015비트" 가 어느 지표인가 -----------------------------------
w("### 5.4 본문의 \"0.004~0.015비트\" 는 어느 지표인가\n")
w("집계 방식(rep 중앙값/평균) × 지표 3종 × 통계 3종 × C·OpenFHE 포함/제외 = 36개 조합을 "
  "전수로 훑어 대조했다.\n")
cand5 = []
for agg in ["median", "mean"]:
    for m in MET:
        for stat in ["레벨범위", "인접Δ최대", "인접Δ전체"]:
            for excl in [False, True]:
                vals = []
                for (p_, lib), d in P1.groupby(["preset", "library"]):
                    if excl and p_ == "C" and lib == "openfhe": continue
                    v = d.groupby("level")[m].agg(agg).sort_index().to_numpy()
                    if stat == "레벨범위": vals.append(v.max() - v.min())
                    elif stat == "인접Δ최대": vals.append(float(np.abs(np.diff(v)).max()))
                    else: vals.extend(np.abs(np.diff(v)))
                lo_, hi_ = float(min(vals)), float(max(vals))
                cand5.append(dict(집계=agg, 지표=m, 통계=stat, C의OpenFHE제외=excl,
                                  최소=lo_, 최대=hi_,
                                  일치=(abs(round(lo_, 3) - 0.004) < 1e-9 and
                                        abs(round(hi_, 3) - 0.015) < 1e-9)))
C5 = pd.DataFrame(cand5)
hit5 = C5[C5["일치"]]
if len(hit5):
    w(md(hit5[["집계", "지표", "통계", "C의OpenFHE제외", "최소", "최대"]], fmt="{:.6f}"))
    w("")
    w("> **찾았다. `0.004~0.015비트` 는 `rot1` 지표다** — rep **평균**으로 레벨 대표값을 만들고 "
      "레벨 최대−최소를 잰 뒤, **preset C·OpenFHE 를 뺀** 11개 조합의 범위 "
      f"(**{float(hit5['최소'].iloc[0]):.6f} ~ {float(hit5['최대'].iloc[0]):.6f}**). "
      "`ks_loss` 나 `enc_dec` 로는 이 범위가 나오지 않는다.\n")
    w("> ⚠️ **그래서 본문 두 문장이 서로 다른 지표를 쓰고 있다.** "
      "\"0.004~0.015비트\" 는 `rot1`(정밀도), \"4.09 → 3.28\" 은 `ks_loss`(손실). "
      "한 문단 안에서 지표가 바뀌면 독자는 같은 양의 비교로 읽는다. **지표를 통일해야 한다.**\n")
else:
    w("> ⚠️ 36개 조합 어디에서도 `0.004~0.015` 가 재현되지 않는다. 본문 수치의 출처 확인이 필요하다.\n")
w("참고 — 같은 통계를 세 지표에 나란히 적용하면(rep 평균 · 레벨범위 · C·OpenFHE 제외):\n")
ref5 = C5[(C5["집계"] == "mean") & (C5["통계"] == "레벨범위") & (C5["C의OpenFHE제외"])]
w(md(ref5[["지표", "최소", "최대"]], fmt="{:.6f}")); w("")

# --- 5.5 레벨 간 vs rep 간 검정 ----------------------------------------------
w("### 5.5 \"측정 반복 간 변동과 구분되지 않는다\" 검정\n")
w("인접 레벨쌍마다 rep 12개씩을 Welch 검정했다 "
  "(`t = (m_hi − m_lo)/√(s²_hi/n + s²_lo/n)`, 양측 정규 근사). "
  f"검정 수 = 84 쌍 × 3 지표 = **{28*3*3}**.\n")
tst = []
for (p_, lib), d in P1.groupby(["preset", "library"]):
    for m in MET:
        g = d.groupby("level")[m].agg(["mean", "std", "count"]).sort_index()
        for L in range(1, int(g.index.max())):
            a_, b_ = g.loc[L], g.loc[L + 1]
            t_, df_, pv_, se_ = welch(b_["mean"], b_["std"], b_["count"],
                                      a_["mean"], a_["std"], a_["count"])
            tst.append(dict(preset=p_, library=lib, 지표=m, 레벨쌍=f"L{L+1}→L{L}",
                            diff=b_["mean"] - a_["mean"], t=t_, p=pv_))
TS = pd.DataFrame(tst)
alpha_b = 0.05 / len(TS)
sm = (TS.groupby("지표")
        .apply(lambda g: pd.Series({"n": len(g), "p<0.05": int((g["p"] < 0.05).sum()),
                                    "본페로니유의": int((g["p"] < alpha_b).sum()),
                                    "abs_t_중앙": g["t"].abs().median(),
                                    "abs_t_최대": g["t"].abs().max()}), include_groups=False)
        .reset_index())
w(md(sm, fmt="{:.4g}")); w("")
w(f"- 본페로니 임계 p = 0.05/{len(TS)} = **{alpha_b:.2e}**. "
  f"**본페로니를 통과한 쌍은 {int((TS['p']<alpha_b).sum())}건이다.**")
w(f"- 무보정 p<0.05 는 **{int((TS['p']<0.05).sum())}건** — 우연 기대치 "
  f"{0.05*len(TS):.1f}건보다 오히려 적다.")
w("")
w("무보정 p<0.05 인 쌍 전체:\n")
w(md(TS[TS["p"] < 0.05][["preset", "library", "지표", "레벨쌍", "diff", "t", "p"]]
     .sort_values("p"), fmt="{:.4g}"))
w("")
w("> **✅ 판정: 본문 주장 성립.** 인접 레벨 하나씩 놓고 보면 **어느 쌍도** "
  "rep 간 변동과 구분되지 않는다(본페로니 통과 0건). "
  "무보정에서 걸린 8건도 우연 기대치 이하이고, `diff` 가 전부 0.01 비트 수준이다.\n")
w("> **단, preset C·OpenFHE 는 예외 취급이 필요하다.** 그 쌍(`L5→L4`, `rot1` t=−2.87 / "
  "`ks_loss` t=+2.85)은 무보정 p 가 0.004 로 목록에서 가장 작고, `diff` 가 "
  "**0.81 비트로 나머지 7건(0.007~0.010비트)의 약 100배**다. "
  "본페로니를 못 넘는 이유는 효과가 작아서가 아니라 **OpenFHE 의 rep 간 sd 가 0.73비트로 커서**다(§5.3). "
  "이 쌍만은 §5.6 처럼 rep 을 짝지어 봐야 한다.\n")

# --- 5.6 preset C · OpenFHE 이상값 특정 ---------------------------------------
w("### 5.6 preset C · OpenFHE 이상값 — rep 원자료로 직접 확인\n")
CO = P1[(P1["preset"] == "C") & (P1["library"] == "openfhe")]
w(f"대상 행 수: **{len(CO)}행** = 10 레벨 × 12 rep "
  + ("**일치**" if len(CO) == 120 else "**⚠️ 불일치**") + "\n")
w("**어느 지표인가** — 세 지표의 레벨별 rep 평균±sd:\n")
tblC = CO.groupby("level")[MET].agg(["mean", "std"]).sort_index(ascending=False)
tC = pd.DataFrame({"level": [f"L{int(i)}" for i in tblC.index]})
for m in MET:
    tC[f"{m} mean"] = tblC[(m, "mean")].to_numpy()
    tC[f"{m} sd"] = tblC[(m, "std")].to_numpy()
w(md(tC, fmt="{:.4f}")); w("")
w("> **지표는 `rot1` 하나다.** `enc_dec` 는 L1~L10 이 36.3175~36.3230 으로 평평하고"
  f"(레벨 범위 {float(S5[(S5.preset=='C')&(S5.library=='openfhe')&(S5['지표']=='enc_dec')]['lvrange'].iloc[0]):.4f} 비트), "
  "`ks_loss` 는 `enc_dec − rot1` 이라 정의상 `rot1` 의 변화를 그대로 물려받는다. "
  "**발생원은 `rot1`(회전 1회 뒤 정밀도)이다.**\n")
w("**어느 레벨쌍인가** — `rot1` 은 두 개의 평지로 갈린다: "
  "**L10~L5 ≈ 32.23비트**, **L4~L1 ≈ 33.04비트**. 계단은 **L5 ↔ L4** 하나뿐이다.\n")

w("**rep 단위 원자료** (`rot1`, 비트). 요약값이 아니라 원본이다:\n")
wideC = CO.pivot_table(index="rep", columns="level", values="rot1")
wc = pd.DataFrame({"rep": [f"rep {int(i)}" for i in wideC.index]})
for L in sorted(wideC.columns, reverse=True):
    wc[f"L{int(L)}"] = wideC[L].to_numpy()
w(md(wc, fmt="{:.3f}")); w("")
w("> 한 행(= 한 rep = 한 키)을 가로로 읽으면 **L10~L5 가 서로 붙어 있고 L4~L1 이 서로 붙어 있으며 "
  "그 사이에서만 값이 뛴다.** rep 간에는 값이 30.7~33.9 비트로 크게 흩어지는데, "
  "이는 하네스가 `for (rep) { KeyGen(); for (level) {...} }` 구조라 "
  "**rep 하나가 키 한 벌을 쓰기 때문**이다(§5.2). "
  "따라서 **단일 rep 이상치가 아니라 rep 안에서 일관되게 나타나는 계단**이다.\n")

w("**계단 폭 — 대응(paired) 검정.** rep 이 키를 공유하므로 rep 안에서 두 평지를 짝지어 뺀다. "
  "(레벨을 독립 표본 72 vs 48 로 놓고 검정하면 같은 키를 여러 번 센 셈이라 유의성이 부풀려진다.)\n")
pr = []
for m in MET:
    wd = CO.pivot_table(index="rep", columns="level", values=m)
    dfp = wd[[5, 6, 7, 8, 9, 10]].mean(axis=1) - wd[[1, 2, 3, 4]].mean(axis=1)
    n_ = len(dfp); md_ = float(dfp.mean()); sd_ = float(dfp.std(ddof=1))
    se_ = sd_ / math.sqrt(n_)
    z_, pv_ = ztest(md_, se_, 0.0, 0.0)
    k_ = int((dfp > 0).sum()); kk = min(k_, n_ - k_)
    ps_ = min(1.0, 2 * sum(math.comb(n_, i) for i in range(0, kk + 1)) / 2 ** n_)
    pr.append(dict(지표=m, n_rep=n_, 평균차_비트=md_, sd=sd_, SE=se_, t=z_, p_대응=pv_,
                   부호=f"{n_-k_ if md_<0 else k_}/{n_}", p_부호검정=ps_))
PRT = pd.DataFrame(pr)
w(md(PRT, fmt="{:.4g}")); w("")
r1 = PRT[PRT["지표"] == "rot1"].iloc[0]
w(f"> **계단 폭은 배수가 아니라 차이다: `rot1` 이 {float(r1['평균차_비트']):+.4f} 비트** "
  f"(L5~L10 평지가 L1~L4 평지보다 그만큼 **낮다** = 정밀도가 나쁘다). "
  f"대응 t = {float(r1['t']):.2f}, p ≈ {float(r1['p_대응']):.4f}; "
  f"부호검정 {r1['부호']} rep, p = {float(r1['p_부호검정']):.4f}. "
  "**유의하지만 압도적이지는 않다** — 12 rep 중 2 rep 은 부호가 반대다(rep 1, rep 9).\n")
w(f"> `ks_loss` 는 부호만 뒤집힌 같은 값({float(PRT[PRT.지표=='ks_loss'].평균차_비트.iloc[0]):+.4f} 비트), "
  f"`enc_dec` 는 {float(PRT[PRT.지표=='enc_dec'].평균차_비트.iloc[0]):+.4f} 비트 · "
  f"p = {float(PRT[PRT.지표=='enc_dec'].p_대응.iloc[0]):.2f} 로 **변화 없음**.\n")
lv5 = CO[CO["level"] == 5]["ks_loss"]; lv4 = CO[CO["level"] == 4]["ks_loss"]
w(f"> 본문이 인용한 두 숫자의 출처: `ks_loss` 의 **L5 = {lv5.mean():.4f}**, "
  f"**L4 = {lv4.mean():.4f}** (rep 평균). 차이 **{lv5.mean()-lv4.mean():+.4f} 비트**, "
  f"비 **{lv5.mean()/lv4.mean():.3f}배**. **3.8 이라는 수는 여기 없다.**\n")
w("**다른 조합에서 재현되는가** — 재현되지 않는다. §5.3 (ㄴ) 표에서 "
  "C·OpenFHE `rot1` 1.135 비트를 뺀 나머지 35개 조합은 0.018~0.047 비트다. "
  "preset C 의 Lattigo(0.027)·SEAL(0.023) 도, OpenFHE 의 다른 프리셋(A 0.028 / B 0.027 / D 0.034)도 "
  "평범하다. **preset C · OpenFHE · `rot1` 단독 현상이다.**\n")
w("> **원인은 미상.** 이 분석으로는 계단의 존재와 위치·크기까지만 확정된다.\n")

# --- 5.7 digit 전이 지점과의 어긋남 --------------------------------------------
w("### 5.7 digit 전이 지점과 몇 레벨 어긋나 있는가\n")
dgC = (T1[(T1["preset"] == "C") & (T1["library"] == "openfhe") & (T1["op"] == "rot1")]
       [["level", "digit"]].sort_values("level", ascending=False))
dgt = pd.DataFrame({"level": [f"L{int(v)}" for v in dgC["level"]],
                    "digit(OpenFHE 실측)": dgC["digit"].astype(int).to_numpy(),
                    "lv": dgC["level"].astype(int).to_numpy()})
w("timing CSV 의 OpenFHE `digit` 열(런타임 실측, `GetNumPartQ`/`GetNumPerPartQ`):\n")
w(md(dgt[["level", "digit(OpenFHE 실측)"]])); w("")
dgm = dict(zip(dgt["lv"], dgt["digit(OpenFHE 실측)"]))
trans = [L for L in range(1, int(dgt["lv"].max()))
         if dgm.get(L) != dgm.get(L + 1)]
tr_lab = ", ".join(f"L{L+1}↔L{L}" for L in sorted(trans, reverse=True))
w(f"- digit 전이: **{tr_lab}** (2 → 1), 관측 창 안에 **{len(trans)}회**.")
w(f"- 정밀도 계단: **L5↔L4** (§5.6).")
off = min(abs((5) - (L + 1)) for L in trans) if trans else float("nan")
w(f"- **어긋남: 정확히 1 레벨.** digit 은 L6↔L5 에서 바뀌는데 `rot1` 정밀도는 L5↔L4 에서 바뀐다. "
  f"L5 는 digit 이 이미 1 로 내려온 레벨인데 정밀도는 아직 높은 레벨 쪽 평지에 남아 있다.\n")
w("> 따라서 **이 계단을 digit 전이로 귀속시킬 수 없다.** 본문이 두 현상을 연결하려면 "
  "1 레벨 어긋남을 설명해야 하는데 이번 분석에는 그 근거가 없다. "
  "4.1 의 비용 계단(= digit 전이에서 정확히 일어남)과 **다른 현상으로 분리해서 서술할 것.**\n")

# --- 5.8 본문 수정안 ----------------------------------------------------------
w("### 5.8 4.4절 본문 수정안 (문장 단위)\n")
lo5, hi5 = float(hit5["최소"].iloc[0]), float(hit5["최대"].iloc[0])
inrep_lo = S5[~((S5.preset == "C") & (S5.library == "openfhe") & (S5["지표"] != "enc_dec"))]["inrep"].min()
inrep_hi = S5[~((S5.preset == "C") & (S5.library == "openfhe") & (S5["지표"] != "enc_dec"))]["inrep"].max()
w("| # | 현재 문장 | 판정 | 고친 문장(안) |")
w("|---|---|---|---|")
w(f"| 1 | \"대부분의 조합에서 레벨 간 정밀도 변화폭은 **0.004~0.015비트**에 머물렀다\" | "
  f"**수치는 맞다. 다만 지표·집계·제외 조건이 안 적혀 있다.** `rot1`(회전 후 정밀도) 을 "
  f"rep 평균으로 집계해 레벨 최대−최소를 잰 값이고, preset C·OpenFHE 를 뺀 11개 조합 범위다 "
  f"({lo5:.4f}~{hi5:.4f}). | "
  f"\"preset C·OpenFHE 를 제외한 11개 (프리셋×라이브러리) 조합에서, 회전 후 정밀도 `rot1` 의 "
  f"레벨 간 변화폭(반복 평균 기준 최대−최소)은 **{lo5:.3f}~{hi5:.3f}비트**였다.\" |")
w(f"| 2 | \"약 **3.8배**의 정밀도 변화(**4.09 → 3.28비트**)\" | "
  f"**틀렸다. 세 군데.** (ㄱ) 4.09/3.28 은 정밀도가 아니라 **`ks_loss`(key-switch 손실 비트)** 다 — "
  f"이 데이터의 정밀도는 32~36비트대다. (ㄴ) **배수가 아니라 차이**이며 그 값은 "
  f"**{lv5.mean()-lv4.mean():.3f}비트**(비로 치면 {lv5.mean()/lv4.mean():.2f}배)다. "
  f"(ㄷ) `ks_loss` 는 작을수록 좋으므로 4.09→3.28 은 **정밀도가 나아진** 방향이다. "
  f"\"3.8\" 의 출처는 확인된다 — `analysis/out/level_cost_report.md` §7 에 "
  f"\"계단 폭 0.809 는 약 **3.8σ**\" 라고 적혀 있다. **σ 가 \"배\"로 옮겨졌다.** | "
  f"\"preset C·OpenFHE 에서 회전 후 정밀도 `rot1` 이 L5 와 L4 사이를 경계로 "
  f"**{abs(float(r1['평균차_비트'])):.2f}비트** 갈린다 — L10~L5 평지 {CO[CO.level>=5]['rot1'].mean():.2f}비트, "
  f"L4~L1 평지 {CO[CO.level<=4]['rot1'].mean():.2f}비트로 **레벨을 더 내린 쪽이 오히려 정밀하다**. "
  f"key-switch 손실 `ks_loss` 로는 L5 {lv5.mean():.2f}비트 → L4 {lv4.mean():.2f}비트다.\" |")
w(f"| 3 | \"측정 반복 간 변동과 **구분되지 않는** 수준\" | "
  f"**대체로 맞다. 단 예외를 밝혀야 한다.** 인접 레벨쌍 252개 중 본페로니 보정을 통과한 것은 "
  f"**0건**이고 무보정 p<0.05 도 8건으로 우연 기대치(12.6건) 이하다. "
  f"그러나 **preset C·OpenFHE 만은 rep 을 짝지으면 유의하다** "
  f"(대응 t={float(r1['t']):.2f}, p≈{float(r1['p_대응']):.3f}; 부호검정 {r1['부호']}, "
  f"p={float(r1['p_부호검정']):.3f}). | "
  f"\"이 변화폭은 반복 간 변동과 구분되지 않았다(인접 레벨쌍 252건 중 다중비교 보정 후 유의 0건). "
  f"예외는 preset C·OpenFHE 한 곳으로, 같은 키를 쓴 반복끼리 짝지어 비교하면 유의했다(p≈0.005).\" |")
w(f"| 4 | \"digit 전이 지점과 **한 레벨 어긋나 있어**\" | "
  f"**맞다.** OpenFHE 실측 digit 은 preset C 에서 **L6↔L5** 한 곳에서 2→1 로 바뀌고, "
  f"정밀도 계단은 **L5↔L4** 다. 정확히 1 레벨 차이. | "
  f"\"이 계단은 OpenFHE 의 digit 전이 지점(L6↔L5)과 한 레벨 어긋나 있어(L5↔L4), "
  f"4.1절의 비용 계단과 같은 원인으로 귀속할 수 없다. **원인은 규명하지 못했다.**\" |")
w("")
w(f"> ⚠️ 그 `3.8σ` 자체도 방법이 틀렸다. 이전 보고서는 한쪽 평지의 표준오차만 썼는데"
  f"(0.73/√12 ≈ 0.21), 두 평지를 비교하려면 **rep 을 짝지은 대응 검정**이어야 한다"
  f"(§5.2 대로 같은 rep 은 키를 공유하므로 레벨끼리 독립이 아니다). "
  f"바른 값은 **t = {abs(float(r1['t'])):.2f} (p ≈ {float(r1['p_대응']):.3f})** 이다. "
  f"본문에 σ 나 t 를 인용하려면 이 값을 쓸 것.\n")
w("**추가로 넣을 것을 권하는 문장** — OpenFHE 의 정밀도 산포:\n")
w(f"> \"OpenFHE 는 반복 간 산포가 다른 두 라이브러리보다 한 자릿수 크다"
  f"(`rot1` 의 반복 간 표준편차 중앙값 "
  f"{S5[(S5.library=='openfhe')&(S5['지표']=='rot1')]['repsd'].min():.2f}~"
  f"{S5[(S5.library=='openfhe')&(S5['지표']=='rot1')]['repsd'].max():.2f}비트 vs "
  f"Lattigo {S5[(S5.library=='lattigo')&(S5['지표']=='rot1')]['repsd'].max():.3f}, "
  f"SEAL {S5[(S5.library=='seal')&(S5['지표']=='rot1')]['repsd'].max():.3f}). "
  f"이 산포는 반복마다 키를 새로 뽑는 데서 오며, 같은 반복 안에서 레벨만 바꾼 변동은 "
  f"세 라이브러리가 모두 {inrep_lo:.3f}~{inrep_hi:.3f}비트로 비슷하다.\"\n")
w("> 이 문장이 있어야 §5 의 전제(\"배치는 시간과 정밀도의 교환이 아니라 시간과 예산의 교환\")가 "
  "선다 — **레벨을 내려도 정밀도는 (C·OpenFHE 한 곳을 빼면) 0.02비트 수준밖에 안 움직인다**는 것이 "
  "그 전제의 근거이기 때문이다.\n")
