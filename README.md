# HE Library Benchmark — OpenFHE vs Lattigo (CKKS)

CKKS 연산의 **암호문 1개 기준** latency를 OpenFHE(C++)와 Lattigo(Go)에서 측정·비교한다.

## 실행 방법

```bash
# Lattigo (Go)
go run lattigo_bench.go -preset all -reps 30      # → results_lattigo.csv

# OpenFHE (C++, Release)
cmake . && make && ./openfhe_bench -preset all -reps 30   # → results_openfhe.csv

# 집계 + 그래프
./venv/bin/python aggregate.py    # → results_combined.csv, plot_*.png, 콘솔 요약표
```

플래그: `-preset {small|medium|large|all}`, `-reps N`, `-warmup N`, `-out PATH`.

## 프리셋

| preset | logN | ring dim | maxLevel | scale bits |
|--------|------|----------|----------|------------|
| small  | 13   | 8192     | 5        | 45         |
| medium | 14   | 16384    | 10       | 45         |
| large  | 15   | 32768    | 15       | 45         |

각 프리셋에서 level = maxLevel..1 전수 스윕, 8개 op × warmup 3 + 30회 측정, μs 단위 평균/표본표준편차(n-1).

## op 목록

`add_cc`(ct+ct), `add_cp`(ct+pt), `mul_cp`(ct×pt), `mul_cc`(ct×ct relin 없음, degree-2),
`mul_cc_rlk`(ct×ct relin 포함), `relin`(= mul_cc_rlk − mul_cc, 음수 0 clamp),
`rescale`(모듈러스 1개 drop), `rot1`(+1 슬롯 회전).

## ⚠️ 측정 주의 (공정성)

- **파라미터는 벤치마크용 근사치이며 검증된 보안 파라미터가 아님.** OpenFHE는 링차원을 강제하기
  위해 `HEStd_NotSet`을 사용하므로 128-bit 보안이 보장되지 않는다. 상대 비교 목적으로만 사용.
- **스레딩 비대칭:** OpenFHE는 OpenMP로 멀티코어를 기본 사용(`user ≫ real`), Lattigo는 기본
  싱글스레드(`user ≈ real`). 즉 "out of the box" 기본값 비교이며, 코어당 성능을 보려면
  `OMP_NUM_THREADS=1`로 OpenFHE를 재측정해야 한다.
- 최적화 빌드에서만 측정 (Go 기본 / C++ `-O3 -DNDEBUG`). 타이밍은 연산 1회만 감싼다.
