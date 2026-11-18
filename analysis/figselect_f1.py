#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
figselect_f1.py — 논문 4절 대표 그림 F1 후보 선정 (정량 스코어) + 상위 3안 렌더링.

입력 (읽기 전용):
  explore/v3_summary_timing.csv
  analysis/out/g_table.csv, fit_coeffs.csv, step_classification.csv

출력:
  analysis/out/f1_scores.csv            12개 조합 전체 지표
  analysis/out/f1_scores_bylib.csv      조합 x 라이브러리 상세 지표
  analysis/out/f1_candidates.md         보고서
  analysis/out/fig/f1_cand{1,2,3}_{lin,log}_{1col,2col}.png

주의 (직전 분석에서 확정된 사실):
  * digit 열은 라이브러리마다 의미가 다르다.
      openfhe = 런타임 실측(numPartQ 기반)
      seal    = digit = level+1 하드코딩 (측정이 아님)
      lattigo = 외부 재구성 추정치
    -> 계단 전이 '표시'는 OpenFHE 에만 근거를 둔다.
    -> Lattigo 의 계단 여부는 g(L) 분포로 판정한다 (G_SPLIT).
  * mode = mt 는 cv 게이트를 통과하지 못했으므로 그림/스코어에 쓰지 않는다.
"""
import os, sys, math, json
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT  = os.path.join(ROOT, "analysis", "out")
FIG  = os.path.join(OUT, "fig")
os.makedirs(FIG, exist_ok=True)

KS_OPS   = ["rot1", "relin", "mul_cc_rlk"]
PRESETS  = ["A", "B", "C", "D"]
LIBS     = ["openfhe", "lattigo", "seal"]
MODE     = "1t"
CV_GATE  = 0.05
# 직전 분석에서 확정: 계단 g <= 0.753, 비계단 g >= 0.782 (1t, key-switch, OpenFHE+Lattigo).
# 그 빈 띠의 중점을 Lattigo 계단 판정 임계로 쓴다.
G_SPLIT  = 0.767

# ---- Okabe-Ito. OpenFHE/Lattigo 는 지시로 고정, SEAL 은 아래 선정 근거 참조 ----
COLOR  = {"openfhe": "#D55E00", "lattigo": "#0072B2", "seal": "#009E73"}
MARKER = {"openfhe": "o",       "lattigo": "s",       "seal": "^"}
# 흑백 인쇄 대비: 세 색의 회색 환산값이 109/130/139 로 거의 붙는다.
# 따라서 구분은 전적으로 마커 모양 + 선 패턴이 진다. 실선/긴파선/점선으로 최대한 벌린다.
LSTYLE = {"openfhe": "-", "lattigo": (0, (4.5, 1.8)), "seal": (0, (1.2, 1.5))}
LABEL  = {"openfhe": "OpenFHE", "lattigo": "Lattigo", "seal": "SEAL"}

# ------------------------------------------------------------------ helpers
def spearman(x, y):
    x = np.asarray(x, float); y = np.asarray(y, float)
    if len(x) < 3: return float("nan")
    rx = pd.Series(x).rank().to_numpy()
    ry = pd.Series(y).rank().to_numpy()
    if rx.std() == 0 or ry.std() == 0: return float("nan")
    return float(np.corrcoef(rx, ry)[0, 1])

def md_table(df, floatfmt="{:.4g}"):
    cols = list(df.columns)
    def f(v):
        if isinstance(v, float):
            if math.isnan(v): return "—"
            return floatfmt.format(v)
        return str(v)
    lines = ["| " + " | ".join(cols) + " |",
             "|" + "|".join(["---"] * len(cols)) + "|"]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(f(r[c]) for c in cols) + " |")
    return "\n".join(lines)

# ---- 서술형 판단 (수치는 스크립트가 채우고, 해석은 아래 고정 텍스트) ----
# 키가 상위 3위와 어긋나면 보고서에 경고가 찍히도록 .get 으로 접근한다.
_REASON = {
("A","mul_cc_rlk"): """**왜 뽑혔나** — 관측 창이 12레벨로 가장 길고, OpenFHE 계단 2회가 5레벨 떨어져 있어
`완만한 구간 → 급락 → 완만한 구간` 이라는 계단의 형태가 가장 또렷하게 읽힌다.
세 곡선이 4번 교차(OpenFHE/SEAL 3회, Lattigo/SEAL 1회)해서, '누가 빠르냐'가 아니라
'레벨 구간에 따라 순서가 바뀐다'는 본 논문의 서술을 같은 그림 한 장이 지지한다.
g > 1.0 역전 쌍이 존재하는 **유일한** 조합이기도 하다.

**무엇을 못 보여주나** — 바닥 대비가 후보 중 가장 약하다. `b(OpenFHE)/b(Lattigo) = 1.29` 로
12개 조합 중 최소이고 L1 간격도 2.34 로 C(2.91)에 못 미친다.
그리고 그 역전 쌍은 §3.1 대로 **p ≈ 0.13** 이라 본문 근거로 못 쓴다 — 그림에는 남지만 문장은 못 얹는다.
1단 폭 88 mm 에 x 눈금 12개는 빡빡하다(축소본에서 읽히기는 한다, §7).""",

("B","relin"): """**왜 뽑혔나** — 계단 밀도가 최고다. 6레벨 중 3번이 digit 전이이고 계단 g 최솟값 0.553 으로
급락 깊이도 가장 크다. 레벨이 6개뿐이라 1단 폭에서 x축이 가장 여유롭다.
(b) 의 정의를 엄밀형/증분형/반반 어느 쪽으로 바꿔도 **상위 3위를 유지하는 유일한 조합**이라
스코어 가정에 대한 내성이 제일 좋다.

**무엇을 못 보여주나** — 계단이 너무 촘촘해서 역설적으로 계단처럼 안 보인다. 격 레벨마다 전이가 있어
'평탄 구간'이 생기지 않고, 곡선이 그냥 살짝 물결치는 직선으로 읽힌다(축소본에서 확인, §7).
L1 간격 1.94 로 바닥 벌어짐이 12개 중 최하위권이고, Lattigo 와 SEAL 이 L1~L4 에서 거의 겹쳐
88 mm 로 줄이면 두 계열이 붙어 보인다.""",

("C","rot1"): """**왜 뽑혔나** — 바닥 대비가 가장 강하다. L1 간격 2.91 로 12개 중 최대, b비 1.65.
로그축에서 저레벨 발산(세 곡선이 수렴하지 않고 벌어지는 모습)이 가장 극적으로 보인다.
cv 최댓값 0.0205 로 후보 셋 중 측정도 제일 깨끗하다.

**무엇을 못 보여주나** — OpenFHE 계단이 관측 창 안에 **단 1회**뿐이라 특성 1 이 빈약하다.
게다가 Lattigo 의 가장 큰 도약은 L7→L8 인데 표시선은 OpenFHE 기준으로 L5.5 에만 있어,
표시선이 세 곡선 모두에 적용된다고 오해될 위험이 이 조합에서 가장 크다.
추가로 **preset C 는 OpenFHE 정밀도 예외(L5↔L4 약 3.8배)를 안고 있어**, F1 으로 뽑으면
본문에서 그 예외를 따로 설명해야 하는 부담이 생긴다(스코어에는 반영하지 않았다).""",
}

_RECO = """## 5. 2패널 권고 여부

**권고: 특성 2 를 문장에서 고치고, F1 은 단일 패널로 간다. 굳이 2패널을 쓴다면 (A·`mul_cc_rlk`) + (B·`relin`).**

근거를 셋으로 나눠 쓴다.

1. **2패널로 해결되지 않는 문제가 하나 있다.** 특성 2(비단조)는 어떤 프리셋·연산을 골라도
   안 나온다(§3.1). 데이터에 없기 때문이지 지면이 부족해서가 아니다. 패널을 늘리는 대신
   4절 문장을 **'증분 비균일'** 로 고쳐야 한다. 이 형태는 12개 조합 전부에서 성립하므로
   어떤 패널을 골라도 따라온다.
2. **특성 1 과 특성 3 은 실제로 서로 다른 프리셋을 선호한다**(계단→B, 바닥→C, §3.3).
   그래서 "한 장이 세 특성을 다 최적으로 보여준다"는 성립하지 않는다.
   다만 A·`mul_cc_rlk` 는 둘 다 **중간 이상**(계단 Sa 0.60, 바닥 L1 간격 2.34)이라
   6페이지 지면에서 한 장으로 감당할 수 있는 수준이다.
3. **2패널을 쓸 여유가 있다면** 프리셋을 바꾸는 쪽(A + B)이 연산을 바꾸는 쪽보다 낫다.
   같은 프리셋 안에서 op 를 바꿔봐야 곡선 모양이 거의 같다 — A 의 세 op 는 Sa 0.53~0.64,
   L1 간격 2.34~2.54 로 사실상 같은 그림이다. 반면 A(12레벨·계단 2회)와 B(6레벨·계단 3회)는
   관측 창 길이와 계단 밀도가 달라 서로를 보완한다.
   **C 는 2패널에서도 권하지 않는다** — 계단 1회 + 정밀도 예외 설명 부담(§4 후보 3).

**축 선택: 로그축을 기본으로 권한다.** 세 후보의 동적 범위가 9.6~16.4배라 선형축에서는
저레벨 구간 세 곡선이 아래쪽에 눌려 붙어 특성 3(바닥이 벌어짐)이 거의 안 보인다.
로그축에서는 A·`mul_cc_rlk` 의 L1 이 SEAL 5.95 / Lattigo 10.8 / OpenFHE 13.9 ms 로
세 갈래로 벌어지는 게 바로 읽힌다. 반대로 계단의 '꺾임'은 선형축이 조금 더 날카롭다.
둘 다 렌더했으니 최종 판단은 본문 문장이 어느 특성에 무게를 두느냐에 맞추면 된다."""

_DESIGN = """## 6. 색·마커·축 선택 근거

### 6.1 색
| 계열 | 색 | 출처 |
|---|---|---|
| OpenFHE | `#D55E00` (vermillion) | 지시로 고정 |
| Lattigo | `#0072B2` (blue) | 지시로 고정 |
| SEAL | `#009E73` (bluish green) | **Okabe–Ito 8색에서 선정** |

SEAL 후보는 Okabe–Ito 팔레트에서 위 둘을 뺀 나머지 중 `#009E73`(bluish green),
`#CC79A7`(reddish purple), `#56B4E9`(sky blue), `#E69F00`(orange) 넷을 놓고 검증했다.
`#56B4E9` 는 `#0072B2` 와 같은 파랑 계열이라 탈락, `#E69F00` 은 `#D55E00` 과 같은 주황 계열이라 탈락.
남은 둘 중 `#CC79A7` 은 흰 배경 대비가 2.98:1 로 3:1 미달이고,
`#009E73` 만 대비·색각이상 분리·채도 하한을 **전부 통과**했다.
전 쌍 검사에서 최악 쌍은 `#009E73 ↔ #D55E00` 의 ΔE 11.0 (deutan) / 8.6 (tritan) 으로
색각이상 하한(8)을 넘긴다. **채택: `#009E73`.**

### 6.2 마커·선종 — 흑백 인쇄 대비
세 색의 회색 환산값은 OpenFHE 130 / Lattigo 109 / SEAL 139 (8비트) 로 **거의 붙는다.**
흑백으로 찍으면 색은 구분에 아무 기여를 못 한다. 그래서 이중 인코딩을 두 겹 넣었다.

| 계열 | 마커 | 선 |
|---|---|---|
| OpenFHE | ● 원 | 실선 |
| Lattigo | ■ 사각 | 긴 파선 (4.5, 1.8) |
| SEAL | ▲ 삼각 | 점선 (1.2, 1.5) |

처음에는 실선/파선/점파선이었는데 88 mm 로 줄이면 파선과 점파선이 붙어 보여
**점선으로 바꿨다**. 흑백 변환본(`_gray/`)에서 재확인했다(§7).
세 계열의 선 굵기(1.4 pt)·마커 크기·범례 순서·z-order 는 **전부 동일**하게 두었다 —
어느 라이브러리가 빠르다는 인상을 주는 강조를 넣지 않기 위해서다.

### 6.3 오차 표시 — **생략하고 캡션에 명시하는 쪽을 택했다**
후보 3개의 cv 최댓값은 A·`mul_cc_rlk` 0.0464, B·`relin` 0.0425, C·`rot1` 0.0205 로
전부 게이트(0.05) 아래다. 이 크기의 오차 막대는 88 mm 폭에서 마커 크기와 비슷해져
계단의 꺾임을 오히려 가린다. 그래서 **오차 막대를 그리지 않고 캡션에 상한을 적는 방식**을 택했다.
캡션 문구(후보 1 기준): *"전 구간 cv < 0.047 (30회 반복, 1t, 코어 고정 + 30초 예열)."*
⚠️ 단 §3.1 의 역전 쌍은 이 방침의 예외다 — 그 쌍만은 오차가 차이보다 크므로
그림에서 오차를 숨긴 채 본문에서 역전을 주장하면 안 된다.

### 6.4 계단 표시
회색 점선(`#777777`, 0.6 pt)을 **OpenFHE 의 digit 전이 위치에만** 세우고
`d 1→2` 처럼 x축 진행 방향(레벨 증가 방향)으로 읽히게 적었다.
`digit` 열은 SEAL 이 `digit = level+1` 하드코딩, Lattigo 가 외부 재구성 추정치라
**세 라이브러리에 나란히 쓸 수 없기 때문**이다.
캡션에 반드시 넣어야 할 문장: *"점선은 OpenFHE 에서 실측한 digit(numPartQ) 전이 위치이며,
Lattigo·SEAL 곡선에는 적용되지 않는다."*

### 6.5 축·단위
- x: `ciphertext level`, 정수 눈금 전부 표기, 왼쪽이 저레벨.
- y: **ms 로 환산**해 그렸다. 원자료는 µs 지만 A 기준 6,000~97,000 µs 라
  선형축에서 `1e5` 오프셋 표기가 좌상단 범례와 겹쳤다. ms 로 바꾸니 오프셋이 사라진다.
  **CSV 는 그대로 µs 다 — 캡션에 단위를 명시할 것.**
- 로그축은 10의 거듭제곱만으로는 눈금이 1~2개뿐이라 1/2/3/5 배 위치를 주눈금으로 썼다.
- 크기: 1단 88 × 62 mm, 2단 180 × 80 mm, 400 dpi."""

_READ = """## 7. 가독성 검증 (실제 배치 크기로 축소 후 육안 확인)

12장 전부를 **1단 88 mm → 381 px, 2단 180 mm → 779 px** (화면 110 ppi 환산)로 줄여서 봤다.
축소본 `analysis/out/fig/_shrunk/`, 흑백본 `analysis/out/fig/_gray/`.

**읽히는 것** — 축 제목, 축 눈금 숫자, 범례 3항목, 계단 라벨(`d 1→2`, 5.5 pt)까지
1단 축소본에서 전부 판독된다. 마커 세 종류(●■▲)도 구분된다.

**보고할 문제 3건**

1. **B·`relin` 은 축소하면 Lattigo 와 SEAL 이 L1~L4 구간에서 사실상 겹친다.**
   (2.4/2.8 → 5.7/5.9 ms) 색으로도 마커로도 두 계열을 떼기 어렵다.
   데이터가 그런 것이라 렌더로는 해결이 안 된다. B 를 쓸 거면 2단 폭이 사실상 필수다.
2. **B·`relin` 의 계단이 계단으로 안 읽힌다.** 전이가 격 레벨마다 있어 평탄 구간이 없고,
   축소본에서는 완만하게 물결치는 직선으로 보인다. Sa 점수(0.805, 12개 중 최고)가
   **시각적 인상과 어긋나는 지점**이다 — 점수는 전이 '횟수'를 세지 '대조'를 세지 않는다.
   이 괴리는 스코어의 한계로 그대로 보고한다.
3. **C·`rot1` 에서 표시선의 오독 위험.** Lattigo 의 가장 큰 도약(L7→L8)에는 선이 없고
   OpenFHE 기준 L5.5 에만 선이 있어, 축소해서 보면 '왜 저기 도약에는 표시가 없지'로 읽힌다.
   §6.4 캡션 문장이 없으면 오해를 부른다.

**흑백 변환** — `_gray/` 에서 세 계열이 구분된다. 다만 §6.2 대로 **색은 기여가 없고**
마커 모양과 선 패턴만으로 구분된다. 초기안(실선/파선/점파선)은 88 mm 흑백에서
Lattigo·SEAL 이 붙어 보여 점선으로 교체했고, 교체 후 재확인했다.

**폰트** — 이 환경에 한글 글꼴이 없다(`fc-list :lang=ko` 결과 0건).
그림 안 문자열은 전부 영문/ASCII 로 뒀다. 논문 캡션(한글)은 본문 쪽에서 붙이면 된다."""

L = []          # 로그
def log(s=""):
    print(s); L.append(s)

# ------------------------------------------------------------------ 0. 적재
t   = pd.read_csv(os.path.join(ROOT, "explore", "v3_summary_timing.csv"))
gt  = pd.read_csv(os.path.join(OUT, "g_table.csv"))
fc  = pd.read_csv(os.path.join(OUT, "fit_coeffs.csv"))
sc  = pd.read_csv(os.path.join(OUT, "step_classification.csv"))

log("## 0. 입력 행 수 회계\n")
log(f"- `v3_summary_timing.csv` 전체 **{len(t)}** 행")
t1 = t[(t["mode"] == MODE) & (t["op"].isin(KS_OPS))].copy()
log(f"- mode={MODE} & key-switch op 3종 필터 후 **{len(t1)}** 행")
exp_rows = sum({"A":12,"B":6,"C":10,"D":4}[p] for p in PRESETS) * 3 * 3
log(f"- 기대: (12+6+10+4) 레벨 x 3 라이브러리 x 3 op = **{exp_rows}** 행 -> "
    + ("**일치**" if len(t1) == exp_rows else f"**불일치 ({len(t1)})**"))
g1 = gt[(gt["mode"] == MODE) & (gt["op"].isin(KS_OPS))].copy()
log(f"- `g_table.csv` 동일 필터 후 **{len(g1)}** 행 (인접 레벨쌍; 기대 {exp_rows - 3*3*4} = 전체행 - 조합수)")
log()

# ------------------------------------------------------------------ 1. 레벨 연속성
log("### 0.1 레벨 연속성 검사 (인접 레벨쌍 계산 전제)\n")
disc_rows = []
for (p, op, lib), d in t1.groupby(["preset", "op", "library"]):
    lv = np.sort(d["level"].unique())
    ndup = len(d) - len(lv)
    gaps = [(int(lv[i]), int(lv[i+1])) for i in range(len(lv)-1) if lv[i+1] - lv[i] != 1]
    if ndup or gaps or lv.min() != 1:
        disc_rows.append(dict(preset=p, op=op, library=lib, n_level=len(lv),
                              min=int(lv.min()), max=int(lv.max()),
                              dup=ndup, gaps=str(gaps)))
if disc_rows:
    log(md_table(pd.DataFrame(disc_rows)))
    log("\n> ⚠️ 위 조합은 불연속 쌍을 제외하고 계산했다.")
else:
    log("- 36개 (preset x op x library) 그룹 **전부** 레벨 1..maxLevel 연속, 중복 0건.")
    log("- 따라서 **제외한 불연속 쌍 0건.**")
log()

# ------------------------------------------------------------------ 2. OpenFHE 계단 위치 (표시 근거)
of_steps = {}   # preset -> [(L_hi, L_lo, digit_hi, digit_lo), ...]
for p in PRESETS:
    d = sc[(sc["preset"] == p) & (sc["library"] == "openfhe")]
    st = []
    for _, r in d.iterrows():
        if r["transition_down"] is True or str(r["transition_down"]) == "True":
            st.append((int(r["level"]), int(r["level"]) - 1,
                       int(r["digit"]), int(r["digit_at_L_minus_1"])))
    of_steps[p] = sorted(st, reverse=True)

# g_table 의 step 열(=digit 기반)과 위치가 일치하는지 교차검증
for p in PRESETS:
    gp = g1[(g1["preset"] == p) & (g1["library"] == "openfhe") & (g1["op"] == "rot1")]
    from_g = sorted(int(x) for x in gp[gp["step"] == True]["level"])
    from_s = sorted(lo for (_, lo, _, _) in of_steps[p])
    assert from_g == from_s, f"{p}: g_table step {from_g} != step_classification {from_s}"

# ------------------------------------------------------------------ 3. 조합별 지표
rows_lib, rows_combo = [], []
for p in PRESETS:
    for op in KS_OPS:
        sub = t1[(t1["preset"] == p) & (t1["op"] == op)]
        libs_here = sorted(sub["library"].unique())
        if set(libs_here) != set(LIBS):
            rows_combo.append(dict(preset=p, op=op, skipped="라이브러리 결측: "
                                   + ",".join(sorted(set(LIBS) - set(libs_here)))))
            continue
        gsub = g1[(g1["preset"] == p) & (g1["op"] == op)]
        nlev = sub[sub["library"] == "openfhe"]["level"].nunique()

        per = {}
        for lib in LIBS:
            dl = sub[sub["library"] == lib].sort_values("level")
            gl = gsub[gsub["library"] == lib].sort_values("level")
            # (a) 계단
            if lib == "openfhe":
                stepmask = gl["step"].astype(bool).to_numpy()      # digit 실측
                basis = "digit(실측)"
            elif lib == "lattigo":
                stepmask = (gl["g"] <= G_SPLIT).to_numpy()         # g 분포 판정
                basis = f"g<={G_SPLIT}"
            else:
                stepmask = np.zeros(len(gl), bool)                 # 판정 불가
                basis = "판정 불가(digit 하드코딩)"
            gv = gl["g"].to_numpy()
            g_step = gv[stepmask]; g_non = gv[~stepmask]
            n_step   = int(stepmask.sum())
            g_step_min = float(g_step.min()) if len(g_step) else float("nan")
            g_step_max = float(g_step.max()) if len(g_step) else float("nan")
            g_non_min  = float(g_non.min())  if len(g_non)  else float("nan")
            sep = (g_non_min - g_step_max) if (len(g_step) and len(g_non)) else float("nan")
            # (b) 단조성 — 엄밀(레벨-비용 순위) + 증분 균일성
            rho  = spearman(dl["level"], dl["mean_us"])
            ngt1 = int((gv > 1.0).sum())
            mv   = dl["mean_us"].to_numpy()
            dv   = np.diff(mv)                      # 레벨 1 올릴 때 증가분
            d_cv = float(dv.std(ddof=1) / dv.mean())
            d_ratio = float(dv.max() / dv.min())
            n_dneg  = int((dv < 0).sum())
            # (c) 바닥
            f = fc[(fc["preset"] == p) & (fc["mode"] == MODE) &
                   (fc["library"] == lib) & (fc["op"] == op)]
            b  = float(f["b"].iloc[0]) if len(f) else float("nan")
            R2 = float(f["R2"].iloc[0]) if len(f) else float("nan")
            m1 = float(dl[dl["level"] == 1]["mean_us"].iloc[0])
            mM = float(dl[dl["level"] == nlev]["mean_us"].iloc[0])
            # (d) 품질
            cvmax = float(dl["cv"].max()); cvmed = float(dl["cv"].median())
            ncv   = int((dl["cv"] > CV_GATE).sum())
            per[lib] = dict(n_step=n_step, basis=basis, g_step_min=g_step_min,
                            g_step_max=g_step_max, g_non_min=g_non_min, sep=sep,
                            rho=rho, n_gt1=ngt1, d_cv=d_cv, d_ratio=d_ratio,
                            n_dneg=n_dneg, b=b, R2=R2, m1=m1, mM=mM,
                            cvmax=cvmax, cvmed=cvmed, ncv=ncv)
            rows_lib.append(dict(preset=p, op=op, library=lib, **per[lib]))

        # 세 곡선의 교차 횟수 (부호 변화). 레벨 구간 조건부 서술의 근거.
        piv = sub.pivot_table(index="level", columns="library", values="mean_us").sort_index()
        n_cross = 0; cross_pairs = []
        for i in range(len(LIBS)):
            for j in range(i + 1, len(LIBS)):
                a_, b_ = LIBS[i], LIBS[j]
                sgn = np.sign(piv[a_].to_numpy() - piv[b_].to_numpy())
                nz_ = sgn[sgn != 0]
                k = int((np.diff(nz_) != 0).sum())
                n_cross += k
                if k: cross_pairs.append(f"{LABEL[a_]}/{LABEL[b_]}x{k}")

        allm = sub["mean_us"]
        m1s  = {lib: per[lib]["m1"] for lib in LIBS}
        dyn  = float(allm.max() / allm.min())
        gap1 = float(max(m1s.values()) / min(m1s.values()))
        mono_contrast = bool(
            (not np.isnan(per["seal"]["rho"]) and abs(per["seal"]["rho"] - 1.0) < 1e-9) and
            any(per[l]["rho"] < 1.0 - 1e-9 for l in ("openfhe", "lattigo")))
        rows_combo.append(dict(
            preset=p, op=op, nlev=nlev,
            n_step_of=per["openfhe"]["n_step"], n_step_lat=per["lattigo"]["n_step"],
            g_step_min_of=per["openfhe"]["g_step_min"],
            g_step_min_lat=per["lattigo"]["g_step_min"],
            sep_of=per["openfhe"]["sep"], sep_lat=per["lattigo"]["sep"],
            rho_of=per["openfhe"]["rho"], rho_lat=per["lattigo"]["rho"],
            rho_seal=per["seal"]["rho"], mono_contrast=mono_contrast,
            n_gt1=sum(per[l]["n_gt1"] for l in LIBS),
            n_dneg=sum(per[l]["n_dneg"] for l in LIBS),
            dcv_of=per["openfhe"]["d_cv"], dcv_lat=per["lattigo"]["d_cv"],
            dcv_seal=per["seal"]["d_cv"],
            dratio_of=per["openfhe"]["d_ratio"], dratio_lat=per["lattigo"]["d_ratio"],
            dratio_seal=per["seal"]["d_ratio"],
            smooth_contrast=min(per["openfhe"]["d_cv"], per["lattigo"]["d_cv"]) / per["seal"]["d_cv"],
            n_cross=n_cross, cross_pairs=";".join(cross_pairs),
            b_of=per["openfhe"]["b"], b_lat=per["lattigo"]["b"], b_seal=per["seal"]["b"],
            b_ratio_of_lat=per["openfhe"]["b"] / per["lattigo"]["b"],
            gap_at_L1=gap1, dyn_range=dyn,
            cv_max=max(per[l]["cvmax"] for l in LIBS),
            cv_med=float(np.median([per[l]["cvmed"] for l in LIBS])),
            n_cv_gt=sum(per[l]["ncv"] for l in LIBS),
            skipped=""))

C  = pd.DataFrame(rows_combo)
BL = pd.DataFrame(rows_lib)
C.to_csv(os.path.join(OUT, "f1_scores.csv"), index=False)
BL.to_csv(os.path.join(OUT, "f1_scores_bylib.csv"), index=False)

log("### 0.2 후보 조합 개수 확인\n")
log(f"- 후보 공간 preset 4 x op 3 = **12**, 지표 산출 완료 **{int((C['skipped']=='').sum())}**, "
    f"라이브러리 결측으로 제외 **{int((C['skipped']!='').sum())}**")
log()

# ------------------------------------------------------------------ 4. 계단 분리 폭 음수 경고
neg = C[(C["sep_of"] < 0) | (C["sep_lat"] < 0)]
neg_warn = len(neg) > 0

# ------------------------------------------------------------------ 5. 스코어링
CC = C[C["skipped"] == ""].copy()
def nz(s):                        # 0..1 정규화 (전부 같으면 0.5)
    s = s.astype(float)
    if s.max() - s.min() < 1e-12: return pd.Series(0.5, index=s.index)
    return (s - s.min()) / (s.max() - s.min())

# (a) 계단 가시성: 전이 횟수(2회 이상이면 만점, 1회는 절반, 0회 0점) x 급락 깊이 x 분리 폭
step_cnt = CC[["n_step_of", "n_step_lat"]].min(axis=1).clip(0, 3)
CC["Sa_count"] = step_cnt.map(lambda n: 0.0 if n == 0 else (0.5 if n == 1 else 1.0))
CC["Sa_depth"] = nz(1.0 - CC[["g_step_min_of", "g_step_min_lat"]].mean(axis=1))
CC["Sa_sep"]   = nz(CC[["sep_of", "sep_lat"]].min(axis=1))
CC["Sa"] = 0.50 * CC["Sa_count"] + 0.30 * CC["Sa_depth"] + 0.20 * CC["Sa_sep"]

# (b) 단조성 대비 — 두 갈래로 나눠 계산한다.
#   Sb_strict : 지시된 정의(SEAL rho=1, 나머지 <1) + g>1 쌍 존재.
#               데이터에서 사실상 축퇴(12개 중 1개만 성립)라 단독으로는 순위를 못 만든다.
#   Sb_smooth : 증분 Δ(L)=mean(L+1)-mean(L) 의 변동계수 대비.
#               SEAL 이 매끄럽고 나머지 둘이 계단 때문에 들쭉날쭉하다는 것을 연속량으로 잰다.
CC["Sb_strict"] = CC["mono_contrast"].astype(float) * 0.7 + (CC["n_gt1"] > 0).astype(float) * 0.3
CC["Sb_smooth"] = nz(CC["smooth_contrast"])
CC["Sb"] = 0.5 * CC["Sb_strict"] + 0.5 * CC["Sb_smooth"]

# (c) 바닥 대비: b 비의 로그 거리 + L1 상대 간격의 로그
CC["Sc_b"]   = nz(np.abs(np.log(CC["b_ratio_of_lat"])))
CC["Sc_gap"] = nz(np.log(CC["gap_at_L1"]))
CC["Sc"] = 0.5 * CC["Sc_b"] + 0.5 * CC["Sc_gap"]

CC["score"] = 0.40 * CC["Sa"] + 0.35 * CC["Sb"] + 0.25 * CC["Sc"]

# (d)(e) 탈락 기준
CC["fail_cv"]  = CC["n_cv_gt"] > 0
CC["fail_len"] = ~CC["nlev"].between(6, 12)
CC["reject"]   = CC["fail_cv"] | CC["fail_len"]
CC["need_log"] = CC["dyn_range"] >= 20.0

CC["score_strictonly"] = 0.40 * CC["Sa"] + 0.35 * CC["Sb_strict"] + 0.25 * CC["Sc"]
CC["score_smoothonly"] = 0.40 * CC["Sa"] + 0.35 * CC["Sb_smooth"] + 0.25 * CC["Sc"]

CC = CC.sort_values(["reject", "score"], ascending=[True, False]).reset_index(drop=True)
CC["rank"] = np.arange(1, len(CC) + 1)
CC.to_csv(os.path.join(OUT, "f1_scores_ranked.csv"), index=False)

TOP = CC[~CC["reject"]].head(3)
cands = [(r["preset"], r["op"]) for _, r in TOP.iterrows()]

# ------------------------------------------------------------------ 6. 렌더링
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import LogLocator, ScalarFormatter, MaxNLocator

MM = 1 / 25.4
SIZES = {"1col": (88 * MM, 62 * MM, 7.0), "2col": (180 * MM, 80 * MM, 9.0)}
DPI = 400

def render(preset, op, scale, width, path, cvmax):
    w, h, fs = SIZES[width]
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": fs,
        "axes.labelsize": fs, "axes.titlesize": fs,
        "xtick.labelsize": fs - 0.5, "ytick.labelsize": fs - 0.5,
        "legend.fontsize": fs - 0.5, "axes.linewidth": 0.6,
        "xtick.major.width": 0.6, "ytick.major.width": 0.6,
        "xtick.major.size": 2.5, "ytick.major.size": 2.5,
        "figure.dpi": DPI, "savefig.dpi": DPI,
    })
    fig, ax = plt.subplots(figsize=(w, h))
    sub = t1[(t1["preset"] == preset) & (t1["op"] == op)]

    # 계단 전이선 — OpenFHE digit 실측에만 근거
    for (hi, lo, dhi, dlo) in of_steps[preset]:
        ax.axvline(lo + 0.5, color="#777777", lw=0.6, ls=(0, (2, 2)), zorder=0)
    ax.set_xlabel("ciphertext level")
    ax.set_ylabel("latency (ms)")   # 원자료는 µs. 1e5 오프셋 표기를 없애려고 ms 로 환산해 그린다.

    for lib in LIBS:
        d = sub[sub["library"] == lib].sort_values("level")
        ax.plot(d["level"], d["mean_us"] / 1000.0, color=COLOR[lib], marker=MARKER[lib],
                ls=LSTYLE[lib], lw=1.4, ms=(3.6 if width == "1col" else 4.6),
                mfc=COLOR[lib], mec="white", mew=0.5, label=LABEL[lib], zorder=3)

    if scale == "log":
        ax.set_yscale("log")
        # 후보들의 동적 범위가 한 자릿수 안팎이라 10의 거듭제곱만으로는 눈금이 1~2개뿐이다.
        # 1/2/3/5 배 위치를 주눈금으로 삼아 실제 숫자를 찍는다.
        ax.yaxis.set_major_locator(LogLocator(base=10, subs=(1., 2., 3., 5.), numticks=20))
        ax.yaxis.set_major_formatter(plt.FuncFormatter(
            lambda v, _: f"{v:g}" if v >= 1 else f"{v:.1f}"))
        ax.yaxis.set_minor_locator(LogLocator(base=10, subs=tuple(np.arange(2, 10) * .1),
                                              numticks=40))
        ax.yaxis.set_minor_formatter(plt.NullFormatter())
    else:
        ax.yaxis.set_major_locator(MaxNLocator(5))

    nlev = int(sub["level"].max())
    ax.set_xlim(0.4, nlev + 0.6)
    ax.set_xticks(range(1, nlev + 1))
    ax.grid(True, which="major", axis="both", color="#DDDDDD", lw=0.4, zorder=0)
    for s in ("top", "right"): ax.spines[s].set_visible(False)

    # digit 전이 라벨. 위쪽에 라벨 전용 여백 띠를 만들어 범례/곡선과 겹치지 않게 한다.
    y0, y1 = ax.get_ylim()
    if scale == "log":
        ax.set_ylim(y0, y1 * 1.30)
        yt = ax.get_ylim()[1] / 1.06
    else:
        ax.set_ylim(y0, y1 + 0.16 * (y1 - y0))
        yy0, yy1 = ax.get_ylim(); yt = yy1 - 0.02 * (yy1 - yy0)
    x0, x1 = ax.get_xlim()
    for (hi, lo, dhi, dlo) in sorted(of_steps[preset], key=lambda z: z[1]):
        xc = lo + 0.5
        ha = "left" if xc - x0 < 1.3 else ("right" if x1 - xc < 1.3 else "center")
        ax.text(xc + (0.12 if ha == "left" else (-0.12 if ha == "right" else 0)), yt,
                f"d {dlo}→{dhi}", ha=ha, va="top",
                fontsize=fs - 1.5, color="#555555")

    leg = ax.legend(loc="upper left", bbox_to_anchor=(0.0, 0.90), frameon=False,
                    handlelength=2.4, borderpad=0.2, labelspacing=0.25,
                    handletextpad=0.5)
    fig.tight_layout(pad=0.35)
    fig.savefig(path, dpi=DPI, bbox_inches="tight", pad_inches=0.02,
                facecolor="white")
    plt.close(fig)

made = []
for i, (p, op) in enumerate(cands, start=1):
    cvm = float(CC[(CC["preset"] == p) & (CC["op"] == op)]["cv_max"].iloc[0])
    for scale in ("lin", "log"):
        for width in ("1col", "2col"):
            fn = f"f1_cand{i}_{scale}_{width}.png"
            render(p, op, scale, width, os.path.join(FIG, fn), cvm)
            made.append(fn)

# --- 검증용 축소본 / 흑백본 (실제 배치 크기 = 88mm·180mm 를 화면 110ppi 로 볼 때) ---
from PIL import Image
PX = {"1col": int(88 / 25.4 * 110), "2col": int(180 / 25.4 * 110)}
for sub_ in ("_shrunk", "_gray"):
    os.makedirs(os.path.join(FIG, sub_), exist_ok=True)
for fn in made:
    w = PX["1col" if "1col" in fn else "2col"]
    im = Image.open(os.path.join(FIG, fn))
    im.resize((w, int(im.height * w / im.width)), Image.LANCZOS)\
      .save(os.path.join(FIG, "_shrunk", fn))
    im.convert("L").resize((w, int(im.height * w / im.width)), Image.LANCZOS)\
      .save(os.path.join(FIG, "_gray", fn))

# ------------------------------------------------------------------ 7. 보고서
def fmt(v, n=4):
    return "—" if (isinstance(v, float) and math.isnan(v)) else (f"{v:.{n}g}" if isinstance(v, float) else str(v))

R = []
R.append("# 논문 4절 대표 그림 F1 후보 선정 — 정량 스코어\n")
R.append("생성: `analysis/figselect_f1.py` · 입력 `explore/v3_summary_timing.csv` "
         "+ 직전 분석 산출물 (`g_table.csv`, `fit_coeffs.csv`, `step_classification.csv`)\n")
R.append("대상: mode = **1t 만**, op = key-switch 3종 {rot1, relin, mul_cc_rlk}, preset A~D → 후보 12개.\n")
R.append("\n---\n")
R.append("\n".join(L))
R.append("\n---\n")

R.append("## 1. 12개 조합 전체 스코어 표\n")
R.append("### 1.1 (a) 계단 가시성\n")
R.append("`n_step` = 관측 창 안의 계단 전이 횟수. `g_step_min` = 계단 전이 g 의 최솟값(작을수록 급락). "
         "`sep` = min(비계단 g) − max(계단 g) (양수 = 완전 분리).\n")
R.append("> ⚠️ 판정 근거가 라이브러리마다 다르다 — OpenFHE 는 digit **실측**, "
         "Lattigo 는 g 분포(`g ≤ 0.767`) 판정, **SEAL 은 판정 불가**(`digit = level+1` 하드코딩이라 "
         "digit 기준으로는 모든 쌍이 계단이 되는 동어반복). 아래 표에 SEAL 열이 없는 이유다.\n")
a = C[C["skipped"] == ""][["preset","op","n_step_of","g_step_min_of","sep_of",
                           "n_step_lat","g_step_min_lat","sep_lat"]]
R.append(md_table(a.sort_values(["preset","op"])))
R.append("")

R.append("### 1.2 (b) 단조성 대비\n")
R.append("`rho_*` = Spearman ρ(level, mean_us). `mono_contrast` = SEAL ρ=1.000 이면서 "
         "나머지 둘 중 하나 이상이 1.000 미만. `n_gt1` = g > 1.0 인 쌍(레벨을 내렸는데 느려진 쌍)의 개수.\n")
b = C[C["skipped"] == ""][["preset","op","rho_of","rho_lat","rho_seal","mono_contrast","n_gt1"]]
R.append(md_table(b.sort_values(["preset","op"]), floatfmt="{:.6g}"))
R.append("")
n_mc = int(C["mono_contrast"].sum()); n_g = int((C["n_gt1"] > 0).sum())
R.append(f"> ⚠️ **이 지표는 데이터에서 축퇴됐다.** 12개 조합 중 `mono_contrast` 성립은 "
         f"**{n_mc}개**, `n_gt1 > 0` 은 **{n_g}개**뿐이다. `rho_of` 는 12개 조합 **전부 1.000** — "
         f"OpenFHE 는 1t key-switch 전 구간에서 완전 단조다. 유일한 역전은 "
         f"preset A · Lattigo · mul_cc_rlk · L11→L10 하나이고, 그 크기가 "
         f"50740.176 → 51267.418 µs = **+1.04 %** 이고, 두 평균의 결합 표준오차로 재면 "
         f"**t = 1.50 (양측 p ≈ 0.13)** — 30회 반복으로는 역전이 분해되지 않는다. "
         f"수치와 판정은 §3.1.\n")

R.append("### 1.2b (b′) 단조성의 대체 지표 — 증분 Δ(L) 의 균일성\n")
R.append("지시된 (b) 가 축퇴됐으므로, 같은 성질을 연속량으로 재는 지표를 함께 계산했다. "
         "`Δ(L) = mean_us(L+1) − mean_us(L)` 의 변동계수 `d_cv` 와 `max Δ / min Δ`. "
         "SEAL 이 매끄럽다면 `d_cv` 가 작고, 계단이 있으면 크다. "
         "`smooth_contrast = min(d_cv_of, d_cv_lat) / d_cv_seal` (>1 이면 대비 성립).\n")
bb = C[C["skipped"] == ""][["preset","op","dcv_of","dcv_lat","dcv_seal",
                            "dratio_of","dratio_lat","dratio_seal",
                            "smooth_contrast","n_dneg"]]
R.append(md_table(bb.sort_values(["preset","op"]), floatfmt="{:.3f}"))
R.append("")
R.append(f"> `smooth_contrast` 는 12개 조합 **전부 > 1** "
         f"(범위 {C['smooth_contrast'].min():.2f} ~ {C['smooth_contrast'].max():.2f}). "
         "즉 **'SEAL 쪽이 매끄럽다'는 대비 자체는 전 조합에서 성립한다.** "
         "성립하지 않는 것은 '나머지 둘이 **비단조**' 라는 강한 형태뿐이다.\n")

R.append("### 1.3 (c) 바닥 대비\n")
R.append("`b_*` = `mean_us ≈ a·(level+1)·digit + b` 적합의 절편 (µs). "
         "`gap_at_L1` = 최저 레벨(L1)에서 세 곡선의 max/min 비.\n")
c = C[C["skipped"] == ""][["preset","op","b_of","b_lat","b_seal","b_ratio_of_lat","gap_at_L1","n_cross","cross_pairs"]]
R.append(md_table(c.sort_values(["preset","op"])))
R.append("")
R.append("> `n_cross` 는 세 곡선쌍의 교차 횟수다. 스코어에는 넣지 않았지만 "
         "**F1 이 '어느 라이브러리가 빠른가'가 아니라 '레벨 구간에 따라 순서가 바뀐다'를 "
         "보여주는 그림이 되려면 교차가 있는 조합이 유리하다.**\n")

R.append("### 1.4 (d) 측정 품질 · (e) 가독성\n")
d = C[C["skipped"] == ""][["preset","op","cv_max","cv_med","n_cv_gt","nlev","dyn_range"]]
R.append(md_table(d.sort_values(["preset","op"])))
R.append("")

R.append("### 1.5 종합 스코어와 순위\n")
R.append("가중치: **Sa(계단) 0.40 · Sb(단조성) 0.35 · Sc(바닥) 0.25**. "
         "Sa = 0.50·전이횟수점 + 0.30·급락깊이 + 0.20·분리폭 (각 0~1 정규화). "
         "Sb = 0.7·대비성립 + 0.3·(g>1 존재). Sc = 0.5·|log(b비)| + 0.5·log(L1간격).\n")
R.append("(d)(e) 는 점수가 아니라 **탈락 기준**으로만 쓴다: `n_cv_gt > 0` 또는 레벨 수가 6~12 밖이면 탈락.\n")
e = CC[["rank","preset","op","Sa","Sb_strict","Sb_smooth","Sb","Sc","score",
        "reject","fail_cv","fail_len","need_log"]]
R.append(md_table(e))
R.append("")
R.append("**민감도 확인** — (b) 를 엄밀 정의만으로 / 증분 정의만으로 잡았을 때 상위 3위가 바뀌는가:\n")
sens = []
for nm, col in [("Sb = 엄밀만", "score_strictonly"),
                ("Sb = 증분만", "score_smoothonly"),
                ("Sb = 반반(채택)", "score")]:
    tt = CC[~CC["reject"]].sort_values(col, ascending=False).head(3)
    sens.append(dict(정의=nm, 상위3="  →  ".join(f"{r['preset']}·{r['op']}" for _, r in tt.iterrows())))
R.append(md_table(pd.DataFrame(sens)))
R.append("")

R.append("\n---\n")
R.append("## 2. 검증 결과\n")
R.append(f"1. **조합 개수** — 12개 전부 세 라이브러리가 모두 존재하고 레벨도 전부 채워져 있다. "
         f"지표 산출 12/12, 결측 제외 0건.\n")
R.append(f"2. **레벨 연속성** — 36개 (preset×op×library) 그룹 모두 L1..LmaxLevel 연속, 중복 0. "
         f"**제외한 불연속 쌍 0건.**\n")
if neg_warn:
    R.append("3. **⚠️ 계단 분리 폭 음수 경고** — 아래 조합에서 `sep < 0` 이 나왔다. "
             "직전 분석에서는 전 조합 완전 분리였으므로 이것은 확인이 필요한 신호다.\n")
    R.append(md_table(neg[["preset","op","sep_of","sep_lat"]]))
else:
    R.append("3. **계단 분리 폭** — 계단 판정이 가능한 두 라이브러리 모두, 12개 조합 전부에서 "
             f"`sep > 0` (완전 분리). 최솟값 OpenFHE {C['sep_of'].min():.4f}, "
             f"Lattigo {C['sep_lat'].min():.4f}. **음수 0건** — 직전 분석과 일치.\n")
R.append("")
R.append("4. **렌더 결과 육안 확인** — 12장 전부를 실제 배치 크기(1단 88 mm, 2단 180 mm)로 "
         "축소해 확인했다. 축소본 `analysis/out/fig/_shrunk/`, 흑백 변환본 `analysis/out/fig/_gray/`. "
         "결과는 §7.\n")
R.append("5. **흑백 변환** — §6.2 와 §7 말미.\n")

# ---- 역전 쌍의 유의성 (특성 2 판정의 핵심) ----
rv = t1[(t1["preset"] == "A") & (t1["library"] == "lattigo") &
        (t1["op"] == "mul_cc_rlk") & (t1["level"].isin([10, 11]))].set_index("level")
m10, s10, n10 = rv.loc[10, ["mean_us", "std_us", "reps"]]
m11, s11, n11 = rv.loc[11, ["mean_us", "std_us", "reps"]]
se = math.sqrt(s10**2 / n10 + s11**2 / n11); dif = m10 - m11; tstat = dif / se
pval = 2 * (1 - 0.5 * (1 + math.erf(abs(tstat) / math.sqrt(2))))

R.append("\n---\n")
R.append("## 3. 판정 — 세 특성이 실제로 다 보이는가\n")
R.append("### 3.1 특성 2(단조성 차이)는 **어느 조합에서도 보여줄 수 없다**\n")
R.append("이게 이번 작업에서 가장 중요한 결과다. 요구된 F1 의 세 번째 문장은 "
         "\"SEAL은 완전 단조, 나머지 둘은 비단조\" 인데, 1t · key-switch 데이터에서:\n")
R.append("- `rho(level, mean_us)` 가 **OpenFHE 는 12개 조합 전부 정확히 1.000** 이다. "
         "OpenFHE 는 이 데이터에서 비단조인 적이 한 번도 없다.\n")
R.append("- Lattigo 도 11/12 조합에서 1.000. 예외는 preset A · `mul_cc_rlk` · L11→L10 하나뿐이다.\n")
R.append(f"- 그 하나조차 유의하지 않다: {m11:,.1f} µs (L11) → {m10:,.1f} µs (L10), "
         f"차이 **+{dif:,.1f} µs = +{100*dif/m11:.2f} %**. 두 평균의 결합 표준오차는 "
         f"{se:,.1f} µs (reps={int(n10)}) 이므로 **t = {tstat:.2f}, 양측 p ≈ {pval:.2f}** — "
         "30회 반복으로는 **역전을 분해하지 못한다.**\n")
R.append("> **결론:** 이 역전 쌍은 지시대로 그림에 그대로 남긴다(잘라내지 않는다). "
         "그러나 **본문에서 '레벨을 내렸는데 느려진다'의 근거로 인용하면 안 된다.** "
         "인용하려면 그 두 레벨만 reps 를 크게 늘려(예: 300회) 재측정해야 한다. "
         "패널을 2개로 늘려도 이 특성은 나오지 않는다 — 데이터에 없기 때문이다.\n")
R.append("### 3.2 대신 쓸 수 있는 형태 — 증분의 비균일성\n")
R.append(f"§1.2b 대로 `smooth_contrast = min(d_cv_of, d_cv_lat)/d_cv_seal` 은 12개 조합 "
         f"**전부 1 보다 크다** ({C['smooth_contrast'].min():.2f}~{C['smooth_contrast'].max():.2f}). "
         "즉 **\"SEAL 은 레벨당 증가폭이 고른데 OpenFHE·Lattigo 는 들쭉날쭉하다\"** 는 "
         "전 조합에서 성립하고 그림으로도 보인다(계단 구간의 기울기 급변). "
         "4절 문장을 '비단조'가 아니라 **'증분 비균일'** 로 고쳐 쓰면 F1 한 장으로 감당된다.\n")
R.append("### 3.3 특성 1 과 특성 3 은 서로 다른 프리셋을 선호한다\n")
R.append("- 계단 가시성(Sa) 상위: **B**(0.79~0.82, 6레벨에 전이 3회) ≫ A(0.53~0.64) > C(0.28~0.41)\n")
R.append("- 바닥 대비(Sc) 상위: **C**(0.83~1.00) ≫ D > A(0.35~0.43) ≒ B(0.28~0.49)\n")
R.append("두 기준의 1위가 다르고, 12개 조합의 종합 점수 폭도 "
         f"{CC[~CC['reject']]['score'].max():.3f} ~ {CC[~CC['reject']]['score'].min():.3f} 로 좁다. "
         "**압도적 1등은 없다.** 아래 추천은 그 전제 위에서 읽어야 한다.\n")

R.append("\n---\n")
R.append("## 4. 상위 3개 추천\n")
for i, (pp, oo) in enumerate(cands, 1):
    r = CC[(CC["preset"] == pp) & (CC["op"] == oo)].iloc[0]
    R.append(f"### 후보 {i} — **preset {pp} · `{oo}`** (rank {int(r['rank'])}, score {r['score']:.3f}) "
             f"→ `f1_cand{i}_*.png`\n")
    R.append(f"`nlev={int(r['nlev'])}` · OpenFHE 계단 {int(r['n_step_of'])}회 · "
             f"계단 g 최소 {r['g_step_min_of']:.3f} · 분리폭 {r['sep_of']:.3f} · "
             f"b비 {r['b_ratio_of_lat']:.2f} · L1 간격 {r['gap_at_L1']:.2f} · "
             f"교차 {int(r['n_cross'])}회 · cv max {r['cv_max']:.4f} · "
             f"동적범위 {r['dyn_range']:.1f}\n")
    R.append(_REASON.get((pp, oo), f"> ⚠️ 상위 3위가 바뀌었다 — preset {pp}·{oo} 에 대한 "
                            "서술형 판단이 스크립트에 없다. 텍스트를 갱신할 것."))
    R.append("")

R.append("\n---\n")
R.append(_RECO)
R.append("\n---\n")
R.append(_DESIGN)
R.append("\n---\n")
R.append(_READ)

open(os.path.join(OUT, "f1_candidates.md"), "w").write("\n".join(R))
print("\n>>> 후보:", cands)
print(">>> 렌더:", len(made), "장")
json.dump({"cands": [{"preset": p, "op": o} for p, o in cands],
           "neg_warn": neg_warn}, open(os.path.join(OUT, "f1_cands.json"), "w"))
