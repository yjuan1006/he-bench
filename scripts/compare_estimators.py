#!/usr/bin/env python3
"""교차 검증: 본측정 평균값 vs 반복 실행 per-(level,op) 최소값.

두 추정량은 서로 독립적인 가정 위에 있다.
  - 본측정 평균: 코어 고정 + 사전 가열로 실행 전체가 turbo였다고 가정
  - 반복 최소값: turbo 상태가 단단한 하한이므로 여러 실행의 최소가 turbo 값으로 수렴
일치하면 "실행이 실제로 전 구간 turbo였다"는 강한 근거가 된다.
사용법: compare_estimators.py <main_csv> <repeat_csv...>
"""
import csv
import statistics
import sys

OPS = ["add_cp", "add_cc", "mul_cp", "mul_cc", "rescale", "relin", "rot1", "mul_cc_rlk"]


def load(path):
    # 참조 구현 시절의 SEAL 헤더(operation)와 정규 스키마(op)를 모두 받는다.
    d = {}
    for r in csv.DictReader(open(path)):
        op = r.get("op") or r["operation"]
        d[(int(r["level"]), op)] = float(r["mean_us"])
    return d


def main(main_csv, repeats):
    m = load(main_csv)
    runs = [load(p) for p in repeats]
    keys = [k for k in m if all(k in r for r in runs)]
    mn = {k: min(r[k] for r in runs) for k in keys}
    lv = sorted({l for l, _ in keys}, reverse=True)

    print(f"{main_csv}  vs  {len(runs)}회 최소값")
    print("lvl " + "".join(f"{o:>10}" for o in OPS) + "     행평균")
    for l in lv:
        vals = [m[(l, o)] / mn[(l, o)] for o in OPS if (l, o) in m]
        print(f"{l:<4}" + "".join(f"{m[(l,o)]/mn[(l,o)]:10.3f}" for o in OPS if (l, o) in m)
              + f"{statistics.mean(vals):11.3f}")
    allr = [m[k] / mn[k] for k in keys]
    print(f"\n  전체 평균 {statistics.mean(allr):.4f}  중앙값 {statistics.median(allr):.4f}  "
          f"범위 [{min(allr):.3f}, {max(allr):.3f}]")
    half = len(lv) // 2
    hi = statistics.mean(m[(l, o)] / mn[(l, o)] for l in lv[:half] for o in OPS if (l, o) in m)
    lo = statistics.mean(m[(l, o)] / mn[(l, o)] for l in lv[half:] for o in OPS if (l, o) in m)
    print(f"  상위레벨 {hi:.4f} / 하위레벨 {lo:.4f} → 상/하 {hi/lo:.4f} "
          f"(1보다 크면 높은 레벨이 여전히 부풀려진 것)")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
