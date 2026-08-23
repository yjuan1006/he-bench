#!/usr/bin/env python3
"""leveldrop_net.py — 순수 레벨 강하 비용과 '계단 하나를 건너 얻는 이득'을 비교한다.

논문 5절(레벨 하강 배치 규칙의 정지 조건)의 실측 근거를 만드는 것이 목적이다.
각 (preset, library, level) 에서

    step_gain(L) = mean_us(op, L+1) - mean_us(op, L)   # 한 레벨 내려 아낀 절대 시간
    drop_cost(L) = mean_us(leveldrop, L+1)             # 그 강하 자체의 비용
    net(L)       = step_gain(L) - drop_cost(L)
    n_break(L)   = ceil(drop_cost(L) / step_gain(L))   # 강하를 회수하는 데 필요한 후속 KS 연산 수

입력(읽기 전용): explore/v3_summary_timing.csv · explore/leveldrop_summary_timing.csv
                 explore/leveldrop_verify.csv
출력: analysis/out/leveldrop_report.md + analysis/out/leveldrop_*.csv
"""
import math
import os
import re
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import respath  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "analysis", "out")
PROBE = os.path.join(os.environ.get(
    "SCRATCH", "/tmp/claude-1000/-data/a64558f7-bd42-41a4-ab87-1e037d2b52b0/scratchpad"),
    "leveldrop", "probe")

KS_OPS = ["rot1", "relin", "mul_cc_rlk"]
CV_GATE = 0.05
# 4절에서 확정된 계단/비계단 g 밴드 (analysis/out/level_cost_report.md §5)
#   계단 0.542~0.753 / 비계단 0.782~1.010 → 두 밴드 사이 빈 구간의 중점
G_SPLIT = 0.767


def md_table(df, floatfmt="{:.4g}"):
    d = df.copy()
    for c in d.columns:
        if pd.api.types.is_float_dtype(d[c]):
            d[c] = d[c].map(lambda v: "" if pd.isna(v) else floatfmt.format(v))
        else:
            d[c] = d[c].astype(str)
    cols = list(d.columns)
    return "\n".join(["| " + " | ".join(cols) + " |",
                      "|" + "|".join("---" for _ in cols) + "|"] +
                     ["| " + " | ".join(r[c] for c in cols) + " |" for _, r in d.iterrows()])


def probe_summary():
    """run_warm.sh 가 남긴 전후 DVFS 프로브를 읽어 요약한다."""
    rows = []
    if not os.path.isdir(PROBE):
        return pd.DataFrame()
    for fn in sorted(os.listdir(PROBE)):
        m = re.match(r"(.+)_(pre|post)\.txt$", fn)
        if not m:
            continue
        vals = []
        for ln in open(os.path.join(PROBE, fn)):
            mm = re.match(r"\s*([\d.]+) s\s+([\d.]+) ms", ln)
            if mm:
                vals.append(float(mm.group(2)))
        if vals:
            rows.append(dict(run=m.group(1), side=m.group(2), n=len(vals),
                             med=float(np.median(vals)), max=max(vals),
                             band="FAST" if max(vals) < 100.0 else "SLOW"))
    return pd.DataFrame(rows)


def main():
    rep = []
    def w(*a):
        rep.append(" ".join(str(x) for x in a))

    v3 = pd.read_csv(respath.find("v3_summary_timing.csv"))
    ld = pd.read_csv(respath.find("leveldrop_summary_timing.csv"))
    vf = pd.read_csv(respath.find("leveldrop_verify.csv"))
    os.makedirs(OUT, exist_ok=True)

    w("# 순수 레벨 강하(leveldrop) 측정 — 5절 정지 조건의 실측 근거")
    w("")
    w("생성: `analysis/leveldrop_net.py` · 하네스: `presetsearch_{openfhe,seal,lattigo}` exp 9 "
      "(`-leveldrop`) · 실행: `scripts/run_leveldrop.sh`")
    w("")
    w("---")
    w("")

    # ── 1. API 확인 ──────────────────────────────────────────────────────────
    w("## 1. 1단계 — API 확인 (스케일을 바꾸지 않고 레벨만 낮추는 연산)")
    w("")
    api = pd.DataFrame([
        dict(library="openfhe",
             함수="`CryptoContext::LevelReduce(ct, evalKey, levels=1)` / `LevelReduceInPlace(...)`",
             스케일보존="예",
             레벨인자="예 (`levels`, 기본 1)",
             형태="`LevelReduce` = Clone + in-place (새 암호문) / `LevelReduceInPlace` = 제자리"),
        dict(library="lattigo",
             함수="`ckks.Evaluator.DropLevel(ct, levels)` / `DropLevelNew(ct, levels)`",
             스케일보존="예",
             레벨인자="예 (`levels`)",
             형태="`DropLevel` = 제자리 / `DropLevelNew` = CopyNew + DropLevel"),
        dict(library="seal",
             함수="`Evaluator::mod_switch_to_next(ct, dst)` / `mod_switch_to_next_inplace(ct)`",
             스케일보존="예",
             레벨인자="**아니오 — 1단계 고정**",
             형태="둘 다 있음. ⚠️ 제자리 쪽이 **더 비싸다**(임시 버퍼 + 2회 복사)"),
    ])
    w(md_table(api))
    w("")
    w("### 1.1 스케일 보존 근거 (소스)")
    w("")
    w("**OpenFHE** — `src/pke/lib/scheme/ckksrns/ckksrns-leveledshe.cpp`")
    w("")
    w("```cpp")
    w("// ModReduceInternalInPlace (= Rescale 의 알맹이)  : 스케일을 나눈다")
    w("    dcrtpoly.DropLastElementAndScale(...);")
    w("    ciphertext->SetScalingFactor(ciphertext->GetScalingFactor() / modReduceFactor);")
    w("")
    w("// LevelReduceInternalInPlace (= LevelReduce 의 알맹이) : 스케일을 손대지 않는다")
    w("void LeveledSHECKKSRNS::LevelReduceInternalInPlace(Ciphertext<DCRTPoly>& ciphertext, size_t levels) const {")
    w("    for (auto& element : ciphertext->GetElements())")
    w("        element.DropLastElements(levels);")
    w("    ciphertext->SetLevel(ciphertext->GetLevel() + levels);")
    w("}   // ← SetScalingFactor 호출이 없다")
    w("```")
    w("")
    w("⚠️ `LevelReduceInPlace` 는 `ScalingTechnique == FIXEDMANUAL` 에서만 실제로 동작한다"
      "(`rns-leveledshe.cpp:339-343`). 이 하네스는 FIXEDMANUAL 이라 조건을 만족하지만, "
      "그래도 **레벨을 매 측정마다 검증**한다(§2).")
    w("")
    w("**Lattigo v6.2.0** — `schemes/ckks/evaluator.go:465-469`")
    w("")
    w("```go")
    w("// DropLevel reduces the level of op0 by levels and returns the result in op0.")
    w("// No rescaling is applied during this procedure.")
    w("func (eval Evaluator) DropLevel(op0 *rlwe.Ciphertext, levels int) {")
    w("\top0.Resize(op0.Degree(), op0.Level()-levels)")
    w("}")
    w("// ring/poly.go:48  Resize → pol.Coeffs = pol.Coeffs[:level+1]   (슬라이스 절단, 산술 없음)")
    w("```")
    w("")
    w("**SEAL 4.3** — `native/src/seal/evaluator.cpp:1382-1414`, `1282-1344`")
    w("")
    w("```cpp")
    w("case scheme_type::ckks:")
    w("    // Modulus switching without scaling")
    w("    mod_switch_drop_to_next(encrypted, destination, std::move(pool));")
    w("...")
    w("    destination.scale() = encrypted.scale();   // ← 스케일을 그대로 복사")
    w("// 반면 rescale_to_next → mod_switch_scale_to_next (스케일을 나눈다). 별개 함수다.")
    w("```")
    w("")
    w("### 1.2 ⚠️ 세 라이브러리의 작업량은 대응하지 않는다")
    w("")
    work = pd.DataFrame([
        dict(library="openfhe", 가장싼형태="in-place",
             하는일="타워 1개 해제(`m_vectors.resize`) + 파라미터 객체 재생성",
             복잡도="O(1) 해제 · 산술 없음"),
        dict(library="lattigo", 가장싼형태="in-place",
             하는일="슬라이스 길이만 줄임(`Coeffs[:level+1]`)",
             복잡도="O(1) · 메모리 해제조차 없음"),
        dict(library="seal", 가장싼형태="**out-of-place**",
             하는일="남는 RNS 성분을 새 버퍼로 복사(`set_uint`)",
             복잡도="**O(N·L)** 복사. O(1) 강하가 없다"),
    ])
    w(md_table(work))
    w("")
    w("따라서 `leveldrop` 열은 **\"그 라이브러리가 레벨을 내리는 가장 싼 정당한 방법\"** 이지 "
      "같은 작업량의 비교가 아니다. 작업량이 대응하는 비교는 `leveldrop_oop`(세 라이브러리 모두 "
      "새 암호문을 하나 만든다) 쪽이다. 두 값을 모두 낸다.")
    w("")
    w("측정 op 4종:")
    w("")
    w("| op | 뜻 |")
    w("|---|---|")
    w("| `leveldrop` | 그 라이브러리의 **가장 싼** 1레벨 강하. openfhe·lattigo = in-place, seal = out-of-place |")
    w("| `leveldrop_ip` | 제자리 형태 |")
    w("| `leveldrop_oop` | 새 암호문 반환 형태 |")
    w("| `clone_only` | 암호문 깊은 복사만 (분해용: `leveldrop_oop ≈ clone_only + leveldrop_ip` 인지 확인) |")
    w("")

    # ── 2. 검증 ──────────────────────────────────────────────────────────────
    w("---")
    w("")
    w("## 2. 정확성 검증 (측정 전에 매 레벨에서 수행)")
    w("")
    vf["dbits"] = (vf.bits_after - vf.bits_before).abs()
    vf["scale_ok"] = np.isclose(vf.scale_ratio, 1.0, rtol=0, atol=1e-12)
    vs = vf.groupby(["preset", "library"]).agg(
        n=("ok", "size"), 레벨_1감소=("ok", "sum"), 스케일보존=("scale_ok", "sum"),
        maxdiff=("max_abs_diff", "max"), dbits_max=("dbits", "max"),
        bits_med=("bits_before", "median")).reset_index()
    w(md_table(vs))
    w("")
    w(f"- 검증 행 {len(vf)}개 전부에서 **레벨이 정확히 1 줄었고**(assert), "
      f"**스케일비가 정확히 1.000**이다 (실패 {int((~vf.scale_ok).sum() + (vf.ok != 1).sum())}건).")
    w("- `maxdiff` = 강하 전후 복호값의 최대 절대차. `dbits_max` = 복호 정밀도(비트)의 최대 변화폭.")
    w("- **Lattigo·SEAL 은 maxdiff 가 정확히 0** — RNS 성분 절단이라 복호 결과가 비트 단위로 같다.")
    of = vf[vf.library == "openfhe"]
    w(f"- **OpenFHE 는 maxdiff 최대 {of.max_abs_diff.max():.3g}**. 같은 암호문의 복호 정밀도가 "
      f"{of.bits_before.median():.1f}비트(= 평균오차 2^-{of.bits_before.median():.1f} ≈ "
      f"{2**-of.bits_before.median():.2g})이므로 이 차이는 **CKKS 오차 범위 안**이고, "
      f"정밀도 변화폭도 최대 {of.dbits.max():.3f}비트로 무의미하다.")
    w("")

    # DVFS 프로브
    pr = probe_summary()
    w("### 2.1 DVFS 프로브 (코어 12 고정 + 30초 사전 가열)")
    w("")
    if len(pr):
        piv = pr.pivot_table(index="run", columns="side", values=["med", "band"], aggfunc="first")
        piv.columns = [f"{b}_{a}" for a, b in piv.columns]
        piv = piv.reset_index()
        w(md_table(piv))
        w("")
        nslow = int((pr.band == "SLOW").sum())
        w(f"- 밴드 근거(dku16c 실측): turbo 82.4~86.8ms / base 137.9~141.3ms, 사이는 비어 있다. "
          f"임계 100ms.")
        w(f"- FAST 밴드 이탈 **{nslow}건** / 전체 {len(pr)}개 프로브.")
    else:
        w("(프로브 파일을 찾지 못했다 — 스크래치가 정리된 경우다)")
    w("")

    w("### 2.2 ⚠️ 폐기한 측정 1회 (기록)")
    w("")
    w("2026-08-19 첫 본측정은 **전량 폐기했다.** 러너를 실수로 두 번 띄워 두 인스턴스가 "
      "**모두 코어 12에 핀**되는 바람에, 12개 실행 전부의 프로브가 **166ms** 로 나왔다 "
      "— 이는 유휴 base(138ms)보다도 느리고 turbo(82.5ms)의 정확히 2배로, "
      "한 코어를 두 CPU-bound 스레드가 나눠 쓴 전형적인 신호다. "
      "`README.md`·`run_main_v3.sh` 의 규칙(\"FAST 밴드를 벗어난 실행은 폐기 대상\")대로 "
      "384행을 지우고 재측정했다. 위 §2.1 표는 **재측정본**이다.")
    w("")
    w("재발 방지로 `run_leveldrop.sh` 에 (1) `flock` 동시 실행 락, (2) 핀 대상 코어가 이미 "
      "바쁘면 시작 거부, (3) 프로브 이탈 시 `LEVELDROP_FAILED` 배너를 넣었다. "
      "재측정에서도 `of_D` 한 실행이 post=138.0ms(base)로 이탈해 **프리셋 D 를 다시 쟀다** "
      "(`run_leveldrop.sh D`). 최종 채택본은 12개 실행 전부 pre/post 모두 FAST 다.")
    w("")
    w("이 사고는 이번 신규 측정에만 해당한다 — `v3_summary_*.csv` 등 기존 8-op 자료는 "
      "읽기만 했고 변경되지 않았다.")
    w("")

    # ── 3. 행 수 회계 + 타이머 분해능 ────────────────────────────────────────
    w("---")
    w("")
    w("## 3. 행 수 회계 · 타이머 분해능 처리")
    w("")
    depths = ld.groupby("preset")["depth"].first().to_dict()
    nlv = sum(depths.values())
    exp_rows = nlv * ld.library.nunique() * ld.op.nunique()
    w(f"- 프리셋별 레벨 수: {', '.join(f'{k}={v}' for k, v in sorted(depths.items()))} → 합 **{nlv}**")
    w(f"- 기대 행 수 = 레벨합 {nlv} × 라이브러리 {ld.library.nunique()} × op {ld.op.nunique()} "
      f"= **{exp_rows}**  →  실제 **{len(ld)}행** "
      f"({'일치' if exp_rows == len(ld) else '불일치 ⚠️'})")
    w(f"- 검증 행 = 레벨합 {nlv} × 라이브러리 3 = **{nlv*3}**  →  실제 **{len(vf)}행** "
      f"({'일치' if nlv*3 == len(vf) else '불일치 ⚠️'})")
    w("- 레벨 연속성: " + ("결측/중복 0건" if all(
        sorted(g.level.unique()) == list(range(1, depths[p] + 1))
        for (p, l, o), g in ld.groupby(["preset", "library", "op"])) else "⚠️ 결측 있음"))
    w("")
    w("### 3.1 타이머 분해능 — 배치 계측이 필요했는가")
    w("")
    w("본측정 전에 예비 실행으로 확인했다(이 저장소 dku16c, 코어 12 고정):")
    w("")
    w("| 시계 | 호출 쌍의 최소 간격 | 중앙값 |")
    w("|---|---|---|")
    w("| C++ `std::chrono::steady_clock` | **40 ns** | 44 ns |")
    w("| Go `time.Now()` | **86 ns** | 90 ns |")
    w("")
    la_ld = ld[(ld.library == "lattigo") & (ld.op == "leveldrop")]
    w(f"Lattigo 의 제자리 강하는 슬라이스 절단이라 실측 **{la_ld.mean_us.min()*1000:.0f}~"
      f"{la_ld.mean_us.max()*1000:.0f} ns** 다 — **Go 시계의 호출 오버헤드(86ns)보다 싸다.** "
      "단발 계측이 원리적으로 불가능하다.")
    w("")
    w("**처리 방식 (배치 계측).** 타이머 밖에서 K개 사본을 만들고 타이머 안에서 K회를 수행한 뒤 "
      "K로 나눈다. 이 rep 값을 30번 반복해 평균·표준편차를 낸다. K 는 암호문 크기로 정한다 "
      "(예산 64MB / `2·(L+1)·N·8` 바이트, 4≤K≤2048).")
    w("")
    w("- 제자리 강하는 **파괴적**이라 같은 암호문에 반복할 수 없다 — 배치는 분해능뿐 아니라 "
      "이 이유로도 필요하다.")
    w("- ⚠️ 배치 rep 의 `std_us` 는 \"K개 평균\"의 rep 간 산포라 단발 계측의 std 와 **의미가 다르다** "
      "(약 1/√K 로 줄어든다). CSV 의 `rep_mode`(single/batch)·`batch_k` 열로 구분한다.")
    w("")
    bk = ld[ld.rep_mode == "batch"].groupby(["preset", "library"])["batch_k"].agg(["min", "max"]).reset_index()
    w("레벨별 K 범위:")
    w("")
    w(md_table(bk))
    w("")

    # ── 4. cv 게이트 ─────────────────────────────────────────────────────────
    w("---")
    w("")
    w("## 4. cv 게이트")
    w("")
    ld["gated"] = ld.cv > CV_GATE
    g = ld.groupby(["library", "op"]).agg(n=("cv", "size"), gated=("gated", "sum"),
                                          cv_med=("cv", "median"), cv_max=("cv", "max")).reset_index()
    w(md_table(g))
    w("")
    w(f"- 임계 cv > {CV_GATE}. 게이트에 걸린 행은 **버리지 않고 표시만** 한다.")
    w(f"- 전체 {len(ld)}행 중 게이트 통과 **{int((~ld.gated).sum())}행** / 걸림 **{int(ld.gated.sum())}행**.")
    w("")
    w("### 4.1 게이트 걸림이 많다 — 측정이 나빴다는 뜻인가")
    w("")
    w("**아니다.** cv 는 **비율**이라 절대량이 작을수록 커진다. 같은 표를 절대 산포(std, ns)로 "
      "다시 보면 성격이 분명해진다:")
    w("")
    ab = ld.groupby(["library", "op"]).agg(
        mean_ns=("mean_us", lambda x: x.median() * 1000),
        std_ns=("std_us", lambda x: x.median() * 1000),
        cv_med=("cv", "median"), gated=("gated", "sum")).reset_index()
    w(md_table(ab, floatfmt="{:.4g}"))
    w("")
    w("- **Lattigo 의 강하는 중앙값 " +
      f"{ab[(ab.library=='lattigo')&(ab.op=='leveldrop')].mean_ns.iloc[0]:.0f} ns** 다. "
      "cv 0.18 은 절대값으로 **" +
      f"{ab[(ab.library=='lattigo')&(ab.op=='leveldrop')].std_ns.iloc[0]:.0f} ns** 의 흔들림이고, "
      "이는 Go 시계의 호출 오버헤드(86ns)와 같은 자릿수다. **측정 하한이지 오염이 아니다.**")
    w("- **OpenFHE·SEAL 의 무거운 op(clone_only, leveldrop_oop)는 cv 중앙 0.026~0.027** 로 "
      "기존 8-op 본측정(1t 중앙 0.012~0.016)과 같은 대역이다 → **측정 조건 자체는 건전했다.** "
      "DVFS 프로브도 12개 실행 전부 FAST 다(§2.1).")
    w("- 즉 게이트에 걸린 202행은 **거의 전부 '연산이 너무 싸서' 걸린 것**이고, "
      "실제로 오염을 의심할 근거(프로브 이탈·무거운 op 의 cv 이상)는 없다.")
    w("")
    w("**결론에 미치는 영향:** §6 의 판정은 `drop_cost` 가 `step_gain` 보다 "
      "**3~5자릿수 작다**는 사실에만 의존한다(§6.3 의 비용비 표). drop_cost 가 2배·10배 "
      "틀려도 net 의 부호는 바뀌지 않는다 — 부호가 바뀌려면 §6.3 의 비용비 역수만큼 "
      "(가장 비싼 SEAL 에서도 32배, Lattigo 는 8000배 이상) 틀려야 한다. "
      "따라서 cv 게이트 결과는 판정을 흔들지 않는다.")
    w("")

    # ── 5. 레벨별 강하 비용 ──────────────────────────────────────────────────
    w("---")
    w("")
    w("## 5. 레벨별 강하 비용 (μs)")
    w("")
    for p in sorted(depths):
        w(f"**preset {p}** (logN {int(ld[ld.preset==p].logN.iloc[0])}, depth {depths[p]})")
        w("")
        t = (ld[ld.preset == p].pivot_table(index="level", columns=["library", "op"],
                                            values="mean_us")
             .sort_index(ascending=False))
        t.columns = [f"{a}·{b}" for a, b in t.columns]
        keep = [c for c in t.columns if c.endswith("leveldrop") or c.endswith("leveldrop_oop")
                or c.endswith("clone_only")]
        w(md_table(t[keep].reset_index(), floatfmt="{:.3g}"))
        w("")
    ld.to_csv(os.path.join(OUT, "leveldrop_cost_by_level.csv"), index=False)

    w("### 5.1 분해 확인 — `leveldrop_oop ≈ clone_only + leveldrop_ip` 인가")
    w("")
    piv = ld.pivot_table(index=["preset", "library", "level"], columns="op", values="mean_us").reset_index()
    piv["clone+ip"] = piv.clone_only + piv.leveldrop_ip
    piv["oop/(clone+ip)"] = piv.leveldrop_oop / piv["clone+ip"]
    dec = piv.groupby("library")["oop/(clone+ip)"].agg(n="size", min="min", med="median", max="max").reset_index()
    w(md_table(dec))
    w("")
    piv.to_csv(os.path.join(OUT, "leveldrop_decomposition.csv"), index=False)
    w("비가 1에 가까우면 out-of-place 비용이 **거의 전부 깊은 복사**라는 뜻이다.")
    w("")

    # ── 6. net(L) ────────────────────────────────────────────────────────────
    w("---")
    w("")
    w("## 6. 계단 이득과의 비교 — `net(L) = step_gain(L) − drop_cost(L)`")
    w("")
    t1 = v3[v3["mode"] == "1t"].copy()
    rows = []
    for (p, lib), g8 in t1.groupby(["preset", "library"]):
        dmap = {}
        for dc in ["leveldrop", "leveldrop_oop"]:
            sub = ld[(ld.preset == p) & (ld.library == lib) & (ld.op == dc)]
            dmap[dc] = dict(zip(sub.level, sub.mean_us))
            dmap[dc + "_cv"] = dict(zip(sub.level, sub.cv))
        for op in KS_OPS:
            s = g8[g8.op == op].set_index("level")
            dg = g8[g8.op == op].set_index("level")["digit"].to_dict()
            for L in sorted(s.index):
                if L + 1 not in s.index:
                    continue
                hi, lo = s.loc[L + 1], s.loc[L]
                gain = float(hi.mean_us - lo.mean_us)
                gL = float(lo.mean_us / hi.mean_us)
                # 계단 판정: OpenFHE 만 digit 사용. Lattigo 는 g 밴드 기반 추정. SEAL 은 판정 안 함.
                if lib == "openfhe":
                    step, how = int(dg[L]) != int(dg[L + 1]), "digit"
                elif lib == "lattigo":
                    step, how = gL < G_SPLIT, "g밴드추정"
                else:
                    step, how = None, "판정안함"
                r = dict(preset=p, library=lib, op=op, level=L,
                         mean_hi=float(hi.mean_us), mean_lo=float(lo.mean_us),
                         g=gL, step=step, step_by=how,
                         cv_hi=float(hi.cv), cv_lo=float(lo.cv),
                         step_gain=gain)
                for dc in ["leveldrop", "leveldrop_oop"]:
                    c = dmap[dc].get(L + 1, np.nan)
                    r[f"drop_{dc}"] = c
                    r[f"net_{dc}"] = gain - c
                    r[f"nbreak_{dc}"] = (math.ceil(c / gain) if gain > 0 and np.isfinite(c)
                                         else np.inf)
                    r[f"cv_{dc}"] = dmap[dc + "_cv"].get(L + 1, np.nan)
                rows.append(r)
    N = pd.DataFrame(rows)
    N.to_csv(os.path.join(OUT, "leveldrop_net.csv"), index=False)
    exp_pairs = sum((d - 1) for d in depths.values()) * 3 * len(KS_OPS)
    w(f"- 인접 레벨쌍 = Σ(depth−1) × 라이브러리 3 × KS-op {len(KS_OPS)} = **{exp_pairs}**  →  "
      f"실제 **{len(N)}쌍** ({'일치' if exp_pairs == len(N) else '불일치 ⚠️'})")
    w(f"- `drop_cost(L)` 는 지시대로 **`mean_us(leveldrop, L+1)`** — L+1 에서 L 로 내리는 비용이다.")
    w("- 계단 판정: **OpenFHE 만 `digit` 사용**. Lattigo 는 4절에서 확정된 g 밴드"
      f"(계단 ≤0.753 / 비계단 ≥0.782)의 중점 {G_SPLIT} 로 **추정**. SEAL 은 판정하지 않는다"
      "(정의상 모든 쌍이 계단이라 대조가 성립하지 않는다).")
    w("")

    w("### 6.1 net(L) 요약 — 주 지표 `leveldrop` (각 라이브러리의 가장 싼 강하)")
    w("")
    for lib in ["openfhe", "lattigo", "seal"]:
        s = N[N.library == lib]
        rows2 = []
        for p in sorted(depths):
            for flag, name in [(True, "계단"), (False, "비계단"), (None, "전체")]:
                if flag is None:
                    sub = s[s.preset == p]
                elif s.step.isna().all():
                    continue
                else:
                    sub = s[(s.preset == p) & (s.step == flag)]
                if not len(sub):
                    continue
                rows2.append(dict(preset=p, 부류=name, n=len(sub),
                                  gain_min=sub.step_gain.min(), gain_med=sub.step_gain.median(),
                                  drop_med=sub.drop_leveldrop.median(),
                                  net_min=sub.net_leveldrop.min(), net_med=sub.net_leveldrop.median(),
                                  net_pos=int((sub.net_leveldrop > 0).sum()),
                                  nbreak_max=sub.nbreak_leveldrop.max()))
        w(f"**{lib}**")
        w("")
        w(md_table(pd.DataFrame(rows2)))
        w("")
    w("`net_pos` = net>0 인 쌍 수 / `nbreak_max` = 강하를 회수하는 데 필요한 후속 KS 연산 수의 최대값")
    w("")

    w("### 6.2 net ≤ 0 인 구간이 있는가 (레벨 축 위에 명시)")
    w("")
    neg = N[N.net_leveldrop <= 0]
    w(f"- 주 지표 `leveldrop` 기준: 전체 {len(N)}쌍 중 **net ≤ 0 은 {len(neg)}쌍**.")
    if len(neg):
        w("")
        w(md_table(neg[["preset", "library", "op", "level", "step_gain",
                        "drop_leveldrop", "net_leveldrop"]]))
    negp = N[N.net_leveldrop_oop <= 0]
    w("")
    w(f"- 보수 지표 `leveldrop_oop`(새 암호문 반환형) 기준: **net ≤ 0 은 {len(negp)}쌍**.")
    if len(negp):
        w("")
        w(md_table(negp[["preset", "library", "op", "level", "g", "step", "step_gain",
                         "drop_leveldrop_oop", "net_leveldrop_oop"]].head(40)))
        if len(negp) > 40:
            w("")
            w(f"(위는 앞 40행. 전체는 `analysis/out/leveldrop_net.csv`)")
    w("")

    w("### 6.3 비용비 — 강하 비용은 계단 이득의 몇 %인가")
    w("")
    N["ratio_ld"] = N.drop_leveldrop / N.step_gain
    N["ratio_oop"] = N.drop_leveldrop_oop / N.step_gain
    rr = []
    for lib in ["openfhe", "lattigo", "seal"]:
        for flag, name in [(True, "계단"), (False, "비계단"), (None, "전체")]:
            s = N[N.library == lib]
            if flag is None:
                sub = s
            else:
                if s.step.isna().all():
                    continue
                sub = s[s.step == flag]
            if not len(sub):
                continue
            rr.append(dict(library=lib, 부류=name, n=len(sub),
                           ld_min=sub.ratio_ld.min(), ld_med=sub.ratio_ld.median(),
                           ld_max=sub.ratio_ld.max(),
                           oop_min=sub.ratio_oop.min(), oop_med=sub.ratio_oop.median(),
                           oop_max=sub.ratio_oop.max()))
    w(md_table(pd.DataFrame(rr)))
    w("")
    w("(`ld_*` = drop_cost/step_gain, 주 지표 / `oop_*` = out-of-place 형태 기준)")
    w("")

    # ── 7. 규모 감각 — 강하 비용은 8-op 중 어디쯤인가 ────────────────────────
    w("---")
    w("")
    w("## 7. 규모 감각 — 강하 비용을 기존 8-op 와 같은 레벨에서 나란히")
    w("")
    scale_rows = []
    for (p_, lib), g8 in t1.groupby(["preset", "library"]):
        for L in sorted(g8.level.unique()):
            s8 = g8[g8.level == L].set_index("op")["mean_us"].to_dict()
            sl = ld[(ld.preset == p_) & (ld.library == lib) & (ld.level == L)]
            if not len(sl):
                continue
            d = sl.set_index("op")["mean_us"].to_dict()
            scale_rows.append(dict(
                preset=p_, library=lib, level=L,
                leveldrop=d.get("leveldrop"), leveldrop_oop=d.get("leveldrop_oop"),
                add_cc=s8.get("add_cc"), rescale=s8.get("rescale"), rot1=s8.get("rot1"),
                ld_over_add=d.get("leveldrop") / s8["add_cc"] if s8.get("add_cc") else np.nan,
                ld_over_rescale=d.get("leveldrop") / s8["rescale"] if s8.get("rescale") else np.nan,
                ld_over_rot1=d.get("leveldrop") / s8["rot1"] if s8.get("rot1") else np.nan,
                oop_over_add=d.get("leveldrop_oop") / s8["add_cc"] if s8.get("add_cc") else np.nan))
    S = pd.DataFrame(scale_rows)
    S.to_csv(os.path.join(OUT, "leveldrop_vs_8op.csv"), index=False)
    sm = S.groupby("library")[["ld_over_add", "ld_over_rescale", "ld_over_rot1", "oop_over_add"]] \
          .agg(["min", "median", "max"])
    sm.columns = [f"{a}_{b}" for a, b in sm.columns]
    w(md_table(sm.reset_index()))
    w("")
    w("- `ld_over_rescale` 가 특히 중요하다: **rescale 은 스케일까지 나누는 연산**이고 "
      "leveldrop 은 모듈러스만 버린다. 두 값의 비가 곧 \"스케일 나눗셈을 생략해서 얼마나 싸지는가\"다.")
    w("")
    w("프리셋 A 상세 (모든 레벨):")
    w("")
    w(md_table(S[S.preset == "A"].sort_values(["library", "level"], ascending=[True, False])[
        ["library", "level", "leveldrop", "leveldrop_oop", "add_cc", "rescale", "rot1",
         "ld_over_rescale"]], floatfmt="{:.4g}"))
    w("")

    # ── 8. 판정 ──────────────────────────────────────────────────────────────
    w("---")
    w("")
    w("## 8. 판정 — 5절 정지 조건에 대해")
    w("")
    w("> §1~§7 표는 스크립트가 자동 산출한 숫자다. 아래는 그 숫자를 읽고 쓴 **결론**이다.")
    w("")
    ldm = ld[ld.op == "leveldrop"].groupby("library")["mean_us"].agg(["min", "max"])
    w("### 8.1 순수 레벨 강하는 얼마인가 — 라이브러리별로 **4자릿수** 차이가 난다")
    w("")
    w(md_table(ldm.reset_index().rename(columns={"min": "min_us", "max": "max_us"})))
    w("")
    w("- **Lattigo** — 슬라이스 절단이라 산술도 메모리 해제도 없다. 사실상 **공짜**다.")
    w("- **OpenFHE** — 타워 1개 해제 + 파라미터 객체 재생성. **레벨과 거의 무관하게 ~1~2μs** 로 "
      "평평하다(전 프리셋·전 레벨). 강하 비용을 레벨 상수로 봐도 되는 유일한 경우다.")
    w("- **SEAL** — O(1) 강하가 **없다**. 남는 RNS 성분을 복사해야 해서 비용이 "
      "**레벨에 비례**한다(프리셋 A 에서 L1 10.7μs → L12 363μs, 34배). "
      "add_cc 의 " + f"{S[S.library=='seal'].ld_over_add.median():.2f}배" + " 수준이다.")
    w("")
    w("이것 자체가 논문 주제(레벨-비용 프로파일의 라이브러리 의존성)의 사례다: "
      "**같은 의미의 연산이 한쪽에서는 레벨 상수, 다른 쪽에서는 레벨 비례다.**")
    w("")

    w("### 8.2 \"계단 하나를 건너 얻는 이득 > 강하 비용\" 이 성립하는 구간")
    w("")
    npos = int((N.net_leveldrop > 0).sum())
    w(f"**주 지표 기준으로 252쌍 중 {npos}쌍에서 성립한다.** `n_break`(강하를 회수하는 데 "
      "필요한 후속 key-switch 연산 수)는 **네 프리셋·세 라이브러리·세 op 전부에서 1** 이다 "
      "— 강하 뒤 key-switch 를 **한 번만** 해도 본전을 넘는다.")
    w("")
    w("- 비용비 `drop/gain` 중앙값: OpenFHE " +
      f"{N[N.library=='openfhe'].ratio_ld.median()*100:.3f}% · Lattigo " +
      f"{N[N.library=='lattigo'].ratio_ld.median()*100:.4f}% · SEAL " +
      f"{N[N.library=='seal'].ratio_ld.median()*100:.2f}%. " +
      f"가장 비싼 SEAL 조차 최대 {N[N.library=='seal'].ratio_ld.max()*100:.1f}% 다.")
    w("- 계단 전이에서는 이득이 더 커서 비율이 더 낮다(OpenFHE 계단 0.022% vs 비계단 0.044%).")
    w("")
    w("**유일한 예외 1쌍**: preset A · Lattigo · `mul_cc_rlk` · L11→L10. 여기서 net<0 인 것은 "
      "강하 비용(0.097μs) 때문이 **아니라** `step_gain` 자체가 **음수(−527μs)** 이기 때문이다 — "
      "기존 v3 8-op 자료에서 레벨을 내렸는데 오히려 느려진 그 쌍(g=1.010)이다"
      "(`analysis/out/level_cost_report.md` §5 에서 이미 확인된 이상치). "
      "**강하 비용의 문제가 아니다.**")
    w("")

    w("### 8.3 그래서 5절의 정지 조건은 무엇이 지배하는가")
    w("")
    w("**강하 비용이 아니다.** 이 측정의 결론은 \"강하는 싸다\" 가 아니라 "
      "**\"강하 비용은 정지 조건을 결정하는 항이 아니다\"** 이다. "
      "후속 key-switch 1회면 회수되므로, 경제적 손익분기는 실질적으로 항상 만족된다. "
      "따라서 5절의 정지 조건은 비용이 아니라 **남은 레벨 예산(곱셈 깊이)과 정밀도**가 "
      "결정한다고 써야 한다. 배치 규칙은 \"내려도 되는가(비용)\" 가 아니라 "
      "\"내릴 레벨이 남아 있는가 · 내려도 정밀도가 버티는가\" 로 정식화되어야 한다.")
    w("")
    w("⚠️ **단, 원본 암호문을 보존해야 하는 배치에서는 결론이 바뀐다.** 새 암호문을 만드는 "
      f"`leveldrop_oop` 기준으로는 net≤0 이 {int((N.net_leveldrop_oop <= 0).sum())}쌍 나온다 "
      "(전부 preset A · Lattigo · L11→L10). 깊은 복사가 이득을 잡아먹기 때문이다. "
      "5절에서 강하를 **제자리로 하는지 사본을 남기는지 명시**해야 한다.")
    w("")

    w("### 8.4 인용 시 반드시 함께 밝힐 것")
    w("")
    w("1. `leveldrop` 은 라이브러리마다 **다른 작업**이다(§1.2). 세 값을 나란히 두고 "
      "\"SEAL 이 느리다\" 고 쓰면 안 된다 — SEAL 은 O(1) 강하 API 가 없어서 더 많은 일을 한다. "
      "작업량이 대응하는 비교는 `leveldrop_oop` 쪽이다.")
    w("2. `rep_mode=batch` 행의 `std_us` 는 단발 계측의 std 와 의미가 다르다(§3.1).")
    w("3. **Lattigo 의 `leveldrop_oop`·`clone_only` 는 신뢰하지 말 것.** "
      f"`oop/(clone+ip)` 비가 {dec[dec.library=='lattigo']['min'].iloc[0]:.2f}~"
      f"{dec[dec.library=='lattigo']['max'].iloc[0]:.2f} 로 튄다(§5.1) — Go GC 가 "
      "6.8MB 할당을 30 reps 안에서 불규칙하게 처리한 결과다. "
      "OpenFHE 는 같은 비가 0.98~1.05 로 안정적이다.")
    w("4. mt 는 재지 않았다(범위 밖). 이 결과는 **1t 전용**이다.")
    w("")

    path = os.path.join(OUT, "leveldrop_report.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(rep) + "\n")
    print(f"[report] {path} ({len(rep)}줄)")


if __name__ == "__main__":
    main()
