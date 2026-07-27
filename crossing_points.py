#!/usr/bin/env python3
"""SEAL/OpenFHE 교차점 산출 — PARAMS_dku16c.md §4.1의 정본 계산.

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
import sys

MAXL = {"small": 5, "medium": 10, "large": 15}
DRIFT = 0.02  # 실행 간 변동 바닥


def load(lib, preset, th="1t"):
    d = {}
    with open(f"results_{lib}_{preset}_{th}_dku16c.csv") as fh:
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


def main(th="1t"):
    print(f"SEAL / OpenFHE 교차점 ({th}) — 첫 교차를 취한다")
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
    main(sys.argv[1] if len(sys.argv) > 1 else "1t")
