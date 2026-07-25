# HE Library Benchmark — OpenFHE vs Lattigo (CKKS)

CKKS 연산의 **암호문 1개 기준** latency를 OpenFHE(C++)와 Lattigo(Go)에서 측정·비교한다.

## 측정 환경

**dku16c** (현재 baseline, 파일 태그 `_dku16c`) — `ENV_dku16c.txt` 참조.

| 항목 | 값 |
|------|-----|
| CPU | Intel Xeon Processor (SapphireRapids), x86_64 |
| 코어 | 16 physical (`Thread(s) per core: 1` — **SMT 없음**), 16 vCPU |
| 벡터 확장 | AVX-512 지원 (`avx512f/dq/bw/vl/vbmi2/vnni …`) |
| RAM | 62 GB |
| OS / 툴체인 | Ubuntu 24.04.3 · g++ 13.3 · cmake 3.28.3 · Go 1.24.5 |
| OpenFHE | v1.5.1 소스 빌드 (Release, shared, OpenMP=ON, **NATIVEOPT=OFF, INTEL_HEXL=OFF**) |
| Lattigo | v6.2.0 |

> HEXL은 공정 비교(같은 빌드 옵션·다른 하드웨어)를 위해 AVX-512 지원 머신에서도 **OFF**로 둔다.
> 이전 baseline은 **epyc4t**(AMD EPYC 7643, 2물리코어×SMT2 = 4스레드), 파일 태그 `_epyc4t`.

### 결과 파일 규칙

`results_{lib}_{preset}_{1t|mt}_{machine}.csv` — `lib`∈{openfhe,lattigo}, `preset`∈{small,medium,large}.
- `mt` = 멀티스레드(기본): OpenFHE 기본 OpenMP / Lattigo 기본
- `1t` = 싱글스레드: OpenFHE `OMP_NUM_THREADS=1` / Lattigo `GOMAXPROCS=1`
  (Go에는 `OMP_NUM_THREADS`가 무효이므로 반드시 `GOMAXPROCS=1`)

집계는 스레드 모드별로 분리한다(스키마에 스레드 컬럼이 없어 mt/1t를 한 파일에 합치면 충돌):
`aggregate.py --lattigo <merged_lattigo_MODE> --openfhe <merged_openfhe_MODE> --suffix _MODE_dku16c`.

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
