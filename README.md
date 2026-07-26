# HE Library Benchmark — OpenFHE vs Lattigo vs SEAL (CKKS)

CKKS 연산의 **암호문 1개 기준** latency를 OpenFHE(C++) · Lattigo(Go) · Microsoft SEAL(C++)
세 라이브러리에서 측정·비교한다.

> 파라미터 정본(logQ/logP/logQP·레벨별 digit 수·보안 여유)은 **`PARAMS_dku16c.md`** 참조.

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
| SEAL | **v4.3.3 (태그 `v4.3.3`, 커밋 `02a5c345`)** 소스 빌드 (Release, shared, **SEAL_USE_INTEL_HEXL=OFF**) |

> HEXL은 공정 비교(같은 빌드 옵션·다른 하드웨어)를 위해 AVX-512 지원 머신에서도 **OFF**로 둔다.
> SEAL도 동일 — 빌드 산출물에서 확인했다(생성 `config.h`에 `SEAL_USE_INTEL_HEXL` 미정의,
> 바이너리에 hexl 심볼·문자열 0건, AVX-512(zmm) 명령 0개).
> SEAL은 `main`이 이미 v4.4.0이므로 **태그 `v4.3.3`으로 핀**해야 검증 사실이 유지된다.
> 소스/설치는 `third_party/SEAL/`(`.gitignore` 대상).
> 이전 baseline은 **epyc4t**(AMD EPYC 7643, 2물리코어×SMT2 = 4스레드), 파일 태그 `_epyc4t`.

### 결과 파일 규칙

`results_{lib}_{preset}_{1t|mt}_{machine}.csv` — `lib`∈{openfhe,lattigo,**seal**}, `preset`∈{small,medium,large}.
현재 dku16c는 **18개**(3 lib × 3 preset × {1t,mt}).
- `mt` = 멀티스레드(기본): OpenFHE 기본 OpenMP / Lattigo 기본
- `1t` = 싱글스레드: OpenFHE `OMP_NUM_THREADS=1` / Lattigo `GOMAXPROCS=1`
  (Go에는 `OMP_NUM_THREADS`가 무효이므로 반드시 `GOMAXPROCS=1`)
- **Lattigo·SEAL은 단건 연산 내부를 병렬화하지 않아 `mt ≈ 1t`다**(실측 mt/1t = 0.99~1.01).
  실제로 병렬화되는 것은 OpenFHE뿐(mt/1t = 0.80/0.47/0.37).

집계는 스레드 모드별로 분리한다(스키마에 스레드 컬럼이 없어 mt/1t를 한 파일에 합치면 충돌):
`aggregate.py --lattigo <...> --openfhe <...> --seal <...> --suffix _MODE_dku16c`.
`--seal`도 `--openfhe`와 같은 입력 가드가 걸려 있다(지정 누락 시 조용히 2자로 진행하지 않고 중단).

## 실행 방법

18개 CSV 전체는 드라이버로 돌린다(프리셋마다 자동 커밋):

```bash
./run_all_dku16c.sh          # 3 lib × 3 preset × {1t,mt} = 18 CSV
```

개별 실행은 반드시 **코어 고정 + 사전 가열 래퍼**를 거친다(아래 측정 프로토콜 참조):

```bash
# <고정코어> <가열스레드> <가열초> <프로브경로> -- 실행할 명령
./run_warm.sh 12 1 30 traces/of ./build_openfhe/openfhe_bench -preset large -reps 30 -out OUT.csv
./run_warm.sh 12 1 30 traces/la go run lattigo_bench.go       -preset large -reps 30 -out OUT.csv
./run_warm.sh 12 1 30 traces/se ./build_seal/seal_bench -preset large -reps 30 -warmup 3 -warmsec 0 \
                                -machine dku16c -threads 1t -sweep desc -out OUT.csv
python3 probe_check.py traces/of      # 측정 전/후 클럭이 fast 밴드였는지 확인
```

빌드: `cmake -S . -B build_openfhe -DCMAKE_PREFIX_PATH=/data/yja/openfhe-install`,
`cmake -S . -B build_seal -DBENCH_OPENFHE=OFF -DBENCH_SEAL=ON -DCMAKE_PREFIX_PATH=$PWD/third_party/SEAL/install`.

플래그: `-preset {small|medium|large|all}`, `-reps N`, `-warmup N`, `-out PATH`.
`seal_bench`는 추가로 `-sweep {asc|desc}`, `-warmsec N`(래퍼로 가열하므로 본측정은 **0**),
`-machine`, `-threads`를 받는다.

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

## 측정 프로토콜 (dku16c 필수)

이 머신은 **코어 단위 DVFS**가 있다 — 유휴 코어는 base(2.2 GHz)로 떨어지고 부하 후 약 6.7초에
turbo(3.7 GHz)에 도달하며 유휴 약 1초면 base로 되돌아간다(**비 1.675**). 스윕이 maxLevel에서
시작하므로 콜드 상태로 시작하면 **높은 레벨만 선택적으로 부풀려져 레벨-지연 기울기가 가짜로
가팔라진다.** 실제로 이 편향이 이전 12개 CSV를 오염시켰다(최대 3.02배, 파일마다 오염 구간이 달랐다).

- **대책: 코어 고정 + 사전 가열.** `run_warm.sh`가 `taskset`으로 핀한 셸 안에서 30초 가열한 뒤
  **`exec`으로 벤치 바이너리로 전환**한다. 새 프로세스를 띄우면 그 틈에 base로 떨어지므로 exec이 필수다.
- **채택/기각 장치는 쓰지 않는다.** 전용 코어의 모니터는 측정 프로세스가 올라간 코어의 상태를
  원리적으로 알 수 없고(오염된 실행을 통과시킨 사례 확인), mt에서는 코어를 뺏어 OpenFHE의 OMP
  조건을 깨뜨린다(rot1/relin 4.3~5.2배 왜곡). 대신 측정 **직전/직후에만** 캘리브레이션 프로브를
  1회씩 재어 기록한다(`probe_check.py`). 18개 실행 × 전후 36개 프로브 전부 fast 밴드(82.5~82.9 ms)였다.
- 고정 코어: 단일스레드 실행은 **코어 12**, OpenFHE mt만 **전 코어(0–15) 고정 + 전 코어 가열**.
- 수용 검사 통과 기준(asc/desc 방향 편향): small 0.62% · medium 0.55%, 상/하 비 1.00±0.01.

## ⚠️ 측정 주의 (공정성)

- **파라미터는 벤치마크용 근사치이며 검증된 보안 파라미터가 아니다.** 링차원을 강제하기 위해
  OpenFHE는 `HEStd_NotSet`, SEAL은 `sec_level_type::none`을 쓴다.
  **⚠️ 프리셋마다 비대칭이므로 뭉뚱그리지 말 것** — 실효 보안은 `logQ`가 아니라 **`logQP`**로
  판정해야 한다(하이브리드 key-switch의 평가키는 QP 위에 정의된다):

  | preset | N | tc128 상한 | OpenFHE | Lattigo | SEAL |
  |--------|---|-----------:|--------:|--------:|-----:|
  | small  | 8192  | 218 | 395 ✗ | 330 ✗ | 335 ✗ |
  | medium | 16384 | 438 | 745 ✗ | 615 ✗ | 565 ✗ |
  | large  | 32768 | 881 | **1035 ✗** | 855 ✓ | 795 ✓ |

  - small·medium은 `logQ` 자체가 상한을 넘어(275>218, 505>438) **세 라이브러리 모두 128비트가 아니다.**
  - **large는 Lattigo·SEAL만 상한 이내이고 OpenFHE는 초과한다.** `logQ`(735)만 보면 셋 다
    이내로 보이므로 logQ로 판정하면 놓친다.
  - **세 프리셋 모두 OpenFHE가 상한에서 가장 멀다** — 같은 Q 위에 가장 큰 P를 얹기 때문이다.
    (여유 순서는 medium·large가 OpenFHE < Lattigo < SEAL, small은 Lattigo가 SEAL보다 5비트 앞선다.)
  - 즉 **Q는 비트 단위로 맞췄으나 보안 수준까지 정합되지는 않았다.** 3자 비교는 "동일 Q 체인
    위의 비교"이지 "동일 보안 수준에서의 비교"가 아니다. 자세한 근거는 `PARAMS_dku16c.md`.
- **SEAL의 특수소수는 자동 결정되지 않아 60비트 1개로 명시 고정**했다(SEAL 관례상 최대 프라임 크기).
  위 logQP 차이의 직접 원인이므로 발표 각주에 반드시 명시할 것.
- **key-switch 계열은 "동일 조건"이 아니라 "비교 가능"이다.** P와 digit 분해 구조가 셋 다 다르다.
  digit 수는 세 라이브러리 모두 레벨의 함수이며 증가 기울기가 다르다(SEAL 1.00 / Lattigo 0.50 /
  OpenFHE 0.17~0.50, 3에서 포화). `PARAMS_dku16c.md` 참조.
- **스레딩 비대칭:** 실제로 단건 연산을 병렬화하는 것은 **OpenFHE뿐**이다(mt/1t = 0.80/0.47/0.37).
  Lattigo·SEAL은 내부 병렬화가 없어 `mt ≈ 1t`(0.99~1.01).
  ⚠️ mt에서 OpenFHE만 분산이 크다 — key-switch 계열 CV 중앙값이 1t 0.004~0.008 대비
  **mt 0.18~0.52(최대 1.23)**. OMP 스케줄링 지터이므로 **에러바 크기가 다른 계열을 같은 근거로
  쓰지 말 것.** 레벨 대비 기울기 분석은 전부 1t로만 수행했다.
- 최적화 빌드에서만 측정 (Go 기본 / C++ `-O3 -DNDEBUG`). 타이밍은 연산 1회만 감싼다.
- 측정 전 반드시 `run_warm.sh`를 거칠 것 — 위 "측정 프로토콜" 참조.

<sup>주) SEAL `large`의 최상위 레벨 `add_cc`/`add_cp`는 추세 대비 1.3~1.5배 높다. 세 피연산자
작업 세트가 약 23~24 MB를 넘는 지점과 일치하며, 버퍼 정렬·2의 거듭제곱 크기와는 무관함을
확인했다(비2^n 크기에서도 동일, 정렬 교란으로 회수되지 않음). 다만 이 게스트에는 가상 PMU가
없어 `perf`로 LLC-miss를 확인하지 못했으므로 **기제는 단정하지 않는다.** 무거운 op에는 영향이
미미하여 3자 비교 결론에는 영향이 없다.</sup>
