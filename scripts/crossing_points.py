#!/usr/bin/env python3
"""SEAL/OpenFHE 교차점 산출 — docs/PARAMS_dku16c.md §4.1의 정본 계산.

비 r(L) = SEAL(L) / OpenFHE(L) 를 L=1..maxLevel 로 훑어
(r[i]-1)(r[i+1]-1) < 0 인 **첫** 구간에서 선형보간한다.

★ 왜 '첫 교차'인가
  답하려는 질문은 "레벨이 오르면서 SEAL이 OpenFHE보다 **처음으로** 비싸지는 지점"이다.
  저레벨에서는 SEAL이 확실히 우위(large L1에서 0.340)이므로 첫 교차가 그 전환점이다.
  비는 단조가 아니다 — OpenFHE의 digit 수가 min(3, ceil((L+1)/perPart)) 로 계단을 이루고
  (L12->L11에서 3->2, 비용 0.740배 / L6->L5에서 2->1, 0.674배) 그 지점에서 비가 위로 튄다.
  이후의 추가 교차는 전환점이 아니라 계단의 부수 효과다.

  ⚠️ 이전 판은 루프에서 값을 덮어써 **마지막** 교차를 반환했고, L12의 비가 0.999로
     아슬하게 1 아래였던 탓에 relin large 교차가 12.0으로 잘못 나왔다(실제 9.1).

±2% 감도를 함께 낸다 — 이 머신의 실행 간 변동 바닥(PARAMS §6.5).
"""
import csv
import os
import sys

MAXL = {"small": 5, "medium": 10, "large": 15}
DRIFT = 0.02  # 실행 간 변동 바닥

# 이 스크립트가 읽는 CSV의 위치. 스크립트가 scripts/ 로 내려갔으므로 CWD 상대 경로를
# 쓰면 어디서 실행하느냐에 따라 깨진다 → 항상 리포 루트 기준으로 해석한다.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 구 프리셋(v1) 측정본은 2026-08-01 구조 개편에서 archive/v1/results/ 로 옮겼다.
# 새 프리셋 측정본을 볼 때는 RESULTS_DIR 환경변수로 덮어쓴다.
#   RESULTS_DIR=. python3 scripts/crossing_points.py 1t
RESULTS_DIR = os.environ.get("RESULTS_DIR", os.path.join("archive", "v1", "results"))


def load(lib, preset, th="1t"):
    d = {}
    path = os.path.join(ROOT, RESULTS_DIR, f"results_{lib}_{preset}_{th}_dku16c.csv")
    with open(path) as fh:
        for r in csv.DictReader(fh):
            d[(int(r["level"]), r["op"])] = float(r["mean_us"])
    return d


def crossings(num, den, op, maxlevel, scale=1.0):
    """1을 지나는 모든 지점을 낮은 레벨부터 반환(선형보간)."""
    xs = list(range(1, maxlevel + 1))
    r = [(num[(l, op)] * scale) / den[(l, op)] for l in xs]
    out = []
    for i in range(len(r) - 1):
        if (r[i] - 1) * (r[i + 1] - 1) < 0:
            out.append(xs[i] + (1 - r[i]) / (r[i + 1] - r[i]))
    return out, r


# ---------------------------------------------------------------------------
# v3 모드 — 한 파일에 3사가 든 결합 CSV를 읽는다. 보간 방식은 v1과 동일하다.
# ---------------------------------------------------------------------------
V3 = {  # 라벨 → (파일 접두, depth)
    "A": ("results_v3n15d42L12", 12),
    "B": ("results_v3Bn14d42L6", 6),
    "C": ("results_v3Cn15d48L10", 10),
    "D": ("results_v3Dn14d42L4", 4),
}
HEAVY = ["mul_cc_rlk", "relin", "rot1"]
PAIRS = [("seal", "openfhe"), ("seal", "lattigo"), ("openfhe", "lattigo")]
# GC 영향군 — Lattigo 가 낀 쌍에서는 이 op 들을 판정하지 않는다(PROJECT_CONTEXT §8.6).
GC_OPS = {"add_cc", "add_cp", "mul_cp", "mul_cc"}


def load_v3(prefix, mode):
    """{(library, op): {level: mean_us}} 로 읽는다."""
    path = os.path.join(ROOT, f"{prefix}_timing_{mode}_dku16c.csv")
    out = {}
    with open(path) as fh:
        for r in csv.DictReader(fh):
            if r.get("ok") not in (None, "", "1"):
                continue
            out.setdefault((r["library"], r["op"]), {})[int(r["level"])] = float(r["mean_us"])
    return out


def crossings_v3(num, den, scale=1.0):
    """v3 전용. 키가 {level: mean_us} 라 v1의 crossings()(키 (level, op))와 형식이 다르다.
    보간 규칙은 완전히 동일하다 — (r[i]-1)(r[i+1]-1) < 0 인 구간에서 선형보간, 첫 교차를 취한다."""
    xs = sorted(num)
    r = [(num[l] * scale) / den[l] for l in xs]
    out = [xs[i] + (1 - r[i]) / (r[i + 1] - r[i])
           for i in range(len(r) - 1) if (r[i] - 1) * (r[i + 1] - 1) < 0]
    return out, r


def verdict(c, lo, hi, r, xs, a, b):
    """판정 문자열 + 신뢰도 메모.

    교차가 없을 때 '전 구간 느림'과 '관측 창 밖'을 구분한다 —
    비가 1 아래에서 maxLevel 로 갈수록 커지고 있으면 더 깊은 레벨에서 교차할 뿐이다.
    """
    if bool(c) != bool(lo) or bool(c) != bool(hi):
        return "±2% 안에서 갈림 → 판정 보류", ""
    if c:
        return "역전", ""
    # 비가 1 아래인데 레벨이 오를수록 커지고 있으면, 교차가 없는 게 아니라
    # **더 깊은 레벨에 있어 관측 창 밖**인 것이다. 둘을 구분해 표기한다.
    # ⚠️ 마지막 두 점만 보면 국소 요동에 걸린다(B seal/openfhe 가 실제로 그랬다).
    #    전 구간 추세(r[-1] > r[0])로 판정하고, 외삽은 뒤쪽 절반의 최소제곱 기울기로 한다.
    if r[-1] < 1 and len(r) >= 3 and r[-1] > r[0]:
        k = max(2, len(r) // 2)
        ys, xx = r[-k:], xs[-k:]
        mx = sum(xx) / k
        my = sum(ys) / k
        den = sum((x - mx) ** 2 for x in xx)
        slope = sum((x - mx) * (y - my) for x, y in zip(xx, ys)) / den if den else 0
        est = xs[-1] + (1 - r[-1]) / slope if slope > 0 else None
        e = f" (외삽 L≈{est:.1f})" if est and est < xs[-1] + 25 else ""
        return f"관측 창 밖 — depth {xs[-1]} < 교차 레벨{e}", ""
    return f"전 구간 {a if r[0] > 1 else b} 느림", ""


def main_v3(mode="1t"):
    print(f"=== v3 교차점 ({mode}) — 첫 교차, 선형보간, ±{DRIFT:.0%} 감도 ===")
    print(f"{'preset':8}{'쌍':20}{'op':11}{'교차':>7}{'−2%':>7}{'+2%':>7}{'횟수':>5}"
          f"{'L1비':>7}{'Lmax비':>8}  판정")
    print("-" * 108)
    for label, (prefix, depth) in V3.items():
        data = load_v3(prefix, mode)
        note = "  ⚠️ 관측점 4개 — 보간 구간이 넓어 소수점 신뢰도 낮음" if depth <= 4 else ""
        for a, b in PAIRS:
            for op in HEAVY:
                A, B = data.get((a, op)), data.get((b, op))
                if not A or not B:
                    continue
                xs = sorted(A)
                c, r = crossings_v3(A, B)
                lo, _ = crossings_v3(A, B, 1 - DRIFT)
                hi, _ = crossings_v3(A, B, 1 + DRIFT)
                v, _ = verdict(c, lo, hi, r, xs, a, b)
                f = lambda x: f"{x[0]:.2f}" if x else "없음"
                print(f"{label:8}{a+'/'+b:20}{op:11}{f(c):>7}{f(lo):>7}{f(hi):>7}{len(c):>5}"
                      f"{r[0]:>7.3f}{r[-1]:>8.3f}  {v}")
        if note:
            print(f"{'':8}{note}")
        print()
    print(f"※ 관측점 수: A 12 · C 10 · B 6 · D 4. 보간은 인접 레벨 사이에서만 하므로")
    print(f"  교차 '유무'는 관측점 수와 무관하지만, 교차 레벨의 소수점 신뢰도는 D에서 가장 낮다.")
    print(f"※ Lattigo 가 낀 쌍의 경량 op({', '.join(sorted(GC_OPS))})는 Go GC 로 측정 불가라 제외했다.")


def main(th="1t"):
    print(f"SEAL / OpenFHE 교차점 ({th}) — 첫 교차를 취한다  [입력: {RESULTS_DIR}/]")
    print(f"{'preset':8}{'op':7}{'교차':>9}{'−2%':>9}{'+2%':>9}{'교차횟수':>9}   L1 / Lmax")
    for preset in ["small", "medium", "large"]:
        M = MAXL[preset]
        S, O = load("seal", preset, th), load("openfhe", preset, th)
        for op in ["relin", "rot1"]:
            c, r = crossings(S, O, op, M)
            lo, _ = crossings(S, O, op, M, 1 - DRIFT)
            hi, _ = crossings(S, O, op, M, 1 + DRIFT)
            f = lambda v: f"{v[0]:.2f}" if v else "없음"
            print(f"{preset:8}{op:7}{f(c):>9}{f(lo):>9}{f(hi):>9}{len(c):>9}"
                  f"   {r[0]:.3f} / {r[-1]:.3f}")
    print("\n※ 교차 '유무'는 ±2%로 뒤집히지 않는다. 폭이 걸리는 것은 교차 레벨의 소수점뿐이다.")


if __name__ == "__main__":
    # v1:  crossing_points.py [1t|mt]
    # v3:  crossing_points.py v3 [1t|mt]
    if len(sys.argv) > 1 and sys.argv[1] == "v3":
        main_v3(sys.argv[2] if len(sys.argv) > 2 else "1t")
    else:
        main(sys.argv[1] if len(sys.argv) > 1 else "1t")
