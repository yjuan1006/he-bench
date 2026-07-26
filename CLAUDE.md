# CLAUDE.md — HE Library Benchmark (OpenFHE vs Lattigo vs SEAL)

> 이 문서는 **측정 API 사실** 전용이다. 파라미터 정본은 `PARAMS_dku16c.md`,
> 정합 기준·측정 규칙은 `PROJECT_CONTEXT.md`, 실행/프로토콜은 `README.md`.

## 목적 (Goal)
CKKS 연산의 **암호문 1개 기준** latency를 OpenFHE(C++) · Lattigo(Go) · SEAL(C++)에서 측정·비교한다.
- 연산: 덧셈 / 곱셈 / 회전 (곱셈은 세부 케이스로 분해)
- 조건: (a) 파라미터 프리셋별 + (b) 프리셋 내 레벨별 전수 스윕
- 측정: 각 연산 warm-up 후 **30회**, **평균 + 표본표준편차(n-1)**, μs 단위
- 산출: 라이브러리별 CSV → 병합 → 요약표 + 그래프 (월요일 발표용)

## 환경 (Environment)
- **Windows + WSL2 (Ubuntu 24.04).** VS Code는 WSL 확장으로 연결. sudo 가능.
- Go 1.24.5 설치됨 (/usr/local/go). cmake 3.28, g++ 13.3, Python 3.12 있음. 메모리 15Gi.
- OpenFHE는 **소스 빌드** 필요(apt 패키지 없음). Release 빌드.
- Python은 venv에 pandas + matplotlib 설치해서 집계/플롯.

### WSL 주의사항
- 작업은 리눅스 홈 `~/he-bench`에서. `/mnt/c`(Windows FS)에서 빌드 금지(I/O 느림).
- 파일 인코딩 UTF-8. 코드 주석 한국어 허용.

## 디렉터리 (플랫 구조)
he-bench/ 안에: CLAUDE.md, go.mod, lattigo_bench.go, openfhe_bench.cpp,
CMakeLists.txt, aggregate.py, (+실행 산출) results_*.csv, plot_*.png

## 공통 측정 스펙 (두 구현이 반드시 동일하게)
CSV 스키마(헤더 고정, **세 라이브러리 동일**):
  library,preset,logN,maxLevel,level,op,mean_us,std_us,reps
op 목록(정확히 이 8개):
- add_cc     ct+ct
- add_cp     ct+pt
- mul_cp     ct×pt (relin 불필요)
- mul_cc     ct×ct, relin 없음(결과 degree-2)
- mul_cc_rlk ct×ct, relin 포함(결과 degree-1)
- relin      재선형화 비용 = mul_cc_rlk - mul_cc (음수면 0 clamp, std=0)
- rescale    모듈러스 1개 드롭 (level>0에서만)
- rot1       +1 슬롯 회전
레벨 스윕: 각 프리셋에서 level = maxLevel..1 전부. 프리셋 3종(small/medium/large,
logN 13/14/15). 기본 reps=30, warmup=3. -preset, -reps 플래그 지원.

## 측정 규칙 (정확도/공정성 — 반드시 지킬 것)
- 최적화 빌드에서만 측정. Go: 기본 / C++: -O3 -DNDEBUG (Release). Debug 금지.
- 타이밍은 연산 1회만 감싼다(키 생성·인코딩·할당은 밖으로).
- 출력 암호문은 타이밍 밖에서 미리 할당(가능한 API에서).
- 입력 암호문은 30회 반복 재사용 OK — Add/Mul/Rotate/Rescale은 out-of-place라 입력 불변.
- ns로 재고 μs(float) 환산. 표본표준편차 n-1.
- 파라미터는 벤치마크용 근사치이며 검증된 보안 파라미터 아님(README/코드에 명시).

## 검증된 API 사실 (VERIFIED — 그대로 따를 것, 환각 금지)

### Lattigo v6  (v5와 import 경로가 다름!)
- CKKS는 github.com/tuneinsight/lattigo/v6/schemes/ckks 에 있다.
  (v5의 he/hefloat가 v6에서 schemes/ckks로 이동됨. he/hefloat로 import 금지.)
- 저수준 타입은 github.com/tuneinsight/lattigo/v6/core/rlwe.
- v6.2.0은 Go 1.24 필요(설치됨). go get github.com/tuneinsight/lattigo/v6.

정확한 시그니처(확인됨):
  params, err := ckks.NewParametersFromLiteral(ckks.ParametersLiteral{
      LogN: 14, LogQ: []int{...}, LogP: []int{...}, LogDefaultScale: 45})
  params.MaxLevel(); params.MaxSlots(); params.LogN()
  params.GaloisElementForRotation(k int) uint64
  kgen := ckks.NewKeyGenerator(params)
  sk, pk := kgen.GenKeyPairNew()
  rlk := kgen.GenRelinearizationKeyNew(sk)
  gks := kgen.GenGaloisKeysNew([]uint64{galEl}, sk)
  evk := rlwe.NewMemEvaluationKeySet(rlk, gks...)
  ecd  := ckks.NewEncoder(params)
  enc  := ckks.NewEncryptor(params, pk)
  eval := ckks.NewEvaluator(params, evk)
  pt := ckks.NewPlaintext(params, level)
  ecd.Encode(values []float64, pt)          // returns error
  ct := ckks.NewCiphertext(params, degree, level)   // degree 1 or 2
  enc.Encrypt(pt, ct)                        // returns error
  // 연산: 전부 opOut 인자 받고 error 반환. op1은 rlwe.Operand (ct/pt 둘 다 가능)
  eval.Add(a, op1, out)        // ct+ct 또는 ct+pt
  eval.Mul(a, op1, out)        // relin 없음. ct*ct면 out은 degree-2
  eval.MulRelin(a, op1, out)   // relin 포함. out degree-1
  eval.Rescale(a, out)         // out은 level-1
  eval.Rotate(a, k, out)       // 회전키 필요
함정: eval.Mul(ct,ct,out)의 out은 NewCiphertext(params,2,level)(degree 2).
Add/MulRelin/Rotate/Rescale의 out은 degree 1. Rescale out은 level-1.

### OpenFHE 1.x (CKKS)
정확한 API(확인됨):
  CCParams<CryptoContextCKKSRNS> params;
  params.SetMultiplicativeDepth(depth);      // = maxLevel
  params.SetScalingModSize(bits);
  params.SetFirstModSize(bits);
  params.SetScalingTechnique(FIXEDMANUAL);   // rescale 명시 측정용
  params.SetSecurityLevel(HEStd_128_classic);
  // 링차원 강제 시: params.SetRingDim(1u<<14); + SetSecurityLevel(HEStd_NotSet);
  auto cc = GenCryptoContext(params);
  cc->Enable(PKE); cc->Enable(KEYSWITCH); cc->Enable(LEVELEDSHE); cc->Enable(ADVANCEDSHE);
  cc->GetRingDimension();
  auto keys = cc->KeyGen();
  cc->EvalMultKeyGen(keys.secretKey);              // relin 키
  cc->EvalRotateKeyGen(keys.secretKey, {1,-1});    // 회전 키
  Plaintext pt = cc->MakeCKKSPackedPlaintext(vec); // 필요시 (vec,1,level)
  auto c = cc->Encrypt(keys.publicKey, pt);
  cc->EvalAdd(c1,c2); cc->EvalAdd(c1,pt);          // 덧셈
  cc->EvalMultNoRelin(c1,c2);                       // relin 없는 곱
  cc->EvalMult(c1,c2); cc->EvalMult(c1,pt);        // relin 포함 곱 / ct*pt
  cc->Relinearize(cMul);                            // size-3 → size-2
  cc->Rescale(c); cc->ModReduce(c);                 // FIXEDMANUAL rescale/레벨드롭
  cc->EvalRotate(c,1);
  c->GetLevel();
함정: FIXEDMANUAL에선 곱 후 스케일 제곱됨 → Rescale은 그 상태 ct에(level>0).
레벨 내리려면 ModReduce 반복. level 리포트는 maxLevel - GetLevel()로 Lattigo와 정렬.
OpenFHE EvalAdd/EvalMult는 새 Ciphertext 반환(functional) → 매 호출 할당이 정상 비용.

## 코딩 규칙
- 주석 한국어 OK. 왜(원리)를 짧게 남긴다.
- 각 구현 완성 후 작게 검증(-preset small -reps 5): 레벨↓일수록 빨라지고
  relin/rotation이 add보다 훨씬 큰지 확인 후 30회 본실행.
- 빌드/실행 에러는 추측 말고 실제 메시지 기준으로 수정.

## 완료 기준 (Definition of Done)
1. go run lattigo_bench.go → results_lattigo.csv (레벨×op 전부, 30회 평균·표준편차)
2. cmake . && make && ./openfhe_bench → results_openfhe.csv (동일 스키마)
3. python3 aggregate.py → results_combined.csv + plot_*.png + 콘솔 요약표
4. 세 라이브러리 값이 정성적으로 일관(relin/rotation ≫ mul ≫ add, 레벨 단조 감소)
