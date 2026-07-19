// lattigo_boot_bench.go — CKKS 부트스트래핑 latency 벤치마크 (Lattigo v6)
// 기존 8-op 벤치(lattigo_bench.go)와 분리된 별도 실행파일:
// 부트스트래핑은 곱셈깊이 ~15를 소모하고 1회가 초 단위라 레벨 스윕/reps=30이 성립하지 않는다.
//
// 프리셋 boot16 = Lattigo 공식 검증 파라미터 N16QP1788H32768H32 (정밀도 29.8비트,
// 실패확률 2^-138.7 @ 2^15 슬롯)를 기준선으로 삼는다. OpenFHE 쪽을 여기에 맞춘다.
//
// 실행: go run lattigo_boot_bench.go -reps 1
// (lattigo_bench.go와 같은 package main이므로 파일을 명시해 실행할 것)
package main

import (
	"bufio"
	"encoding/csv"
	"flag"
	"fmt"
	"math"
	"math/rand"
	"os"
	"runtime"
	"runtime/pprof"
	"strconv"
	"strings"
	"time"

	"github.com/tuneinsight/lattigo/v6/circuits/ckks/bootstrapping"
	"github.com/tuneinsight/lattigo/v6/core/rlwe"
	"github.com/tuneinsight/lattigo/v6/ring"
	"github.com/tuneinsight/lattigo/v6/schemes/ckks"
	"github.com/tuneinsight/lattigo/v6/utils"
)

// peakRSSMB: /proc/self/status의 VmHWM(프로세스 생애 최대 RSS)을 MB로 반환.
// runtime.MemStats는 Go 힙만 보므로 평가키(수 GB)가 잡히지 않는다 → VmHWM을 쓴다.
func peakRSSMB() float64 {
	f, err := os.Open("/proc/self/status")
	if err != nil {
		return 0
	}
	defer f.Close()
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		line := sc.Text()
		if !strings.HasPrefix(line, "VmHWM:") {
			continue
		}
		// 형식: "VmHWM:\t  123456 kB"
		fields := strings.Fields(line)
		if len(fields) < 2 {
			return 0
		}
		kb, err := strconv.ParseFloat(fields[1], 64)
		if err != nil {
			return 0
		}
		return kb / 1024.0
	}
	return 0
}

// meanStd: 평균 + 표본표준편차(n-1). 기존 벤치와 동일한 통계 규칙.
func bootMeanStd(xs []float64) (float64, float64) {
	n := float64(len(xs))
	var sum float64
	for _, x := range xs {
		sum += x
	}
	mean := sum / n
	if len(xs) < 2 {
		return mean, 0
	}
	var ss float64
	for _, x := range xs {
		d := x - mean
		ss += d * d
	}
	return mean, math.Sqrt(ss / (n - 1))
}

func main() {
	reps := flag.Int("reps", 10, "측정 반복 횟수")
	warmup := flag.Int("warmup", 1, "warm-up 횟수")
	out := flag.String("out", "results_lattigo_boot.csv", "출력 CSV 경로")
	cpuprofile := flag.String("cpuprofile", "", "CPU 프로파일 출력 경로 (빈 값이면 프로파일링 안 함)")
	// -preset: 기본 boot16(조밀키)을 바꾸지 말 것. sparse는 *대조군 확보용*이다 —
	// OpenFHE 희소 측정(-skd sparse)과 짝을 맞추기 위한 것이며, 조밀 Lattigo vs 희소 OpenFHE
	// 같은 비정합 비교를 막는 것이 목적이다. 본 결과와 섞지 말 것.
	presetSel := flag.String("preset", "boot16", "boot16(조밀, 기본) | sparse(N16QP1546H192H32, 대조군)")
	flag.Parse()

	sparse := *presetSel == "sparse"
	presetName := "boot16"
	if sparse {
		presetName = "boot16-sparse"
	} else if *presetSel != "boot16" {
		fmt.Fprintf(os.Stderr, "알 수 없는 -preset %q (boot16 | sparse)\n", *presetSel)
		os.Exit(1)
	}

	// --- residual 파라미터 (부트스트래핑 이후 남는 파라미터) ---
	// LogQ = {60, 45×9} → MaxLevel 9. Xs는 조밀 삼항(H=N/2=32768):
	// OpenFHE UNIFORM_TERNARY와 비밀키 분포를 맞추기 위함. 기본값 H=192(희소)를 쓰면
	// Lattigo가 부당하게 유리해진다.
	logQ := []int{60}
	for i := 0; i < 9; i++ {
		logQ = append(logQ, 45)
	}
	residualLit := ckks.ParametersLiteral{
		LogN:            16,
		LogQ:            logQ,
		LogP:            []int{61, 61, 61, 61, 61},
		Xs:              ring.Ternary{H: 32768},
		LogDefaultScale: 45,
	}
	// --- 부트스트래핑 회로 리터럴 ---
	// levelBudget {C2S, S2C} = {4, 3} → C2S 4단계, S2C 3단계.
	btpLit := bootstrapping.ParametersLiteral{
		SlotsToCoeffsFactorizationDepthAndLogScales: [][]int{{42}, {42}, {42}},
		CoeffsToSlotsFactorizationDepthAndLogScales: [][]int{{58}, {58}, {58}, {58}},
		LogMessageRatio: utils.Pointy(2),
		Mod1InvDegree:   utils.Pointy(7),
	}

	// 대조군: 공식 희소 프리셋 N16QP1546H192H32를 라이브러리 정의에서 그대로 가져온다
	// (하드코딩 전사 오류를 원천 차단). DefaultParametersSparse[0]이 해당 프리셋이다.
	// 문서값: Residual Q {60, 40×9}, scale 2^40, Xs H=192, 정밀도 26.6비트 @ 2^15 슬롯.
	// 주의: boot16과 달리 scale이 2^45가 아니라 2^40이고 btp 리터럴도 전부 기본값이다
	// (levelBudget C2S 4 / S2C 3은 같지만 EvalMod 깊이·LogMessageRatio가 다르다).
	if sparse {
		fmt.Fprintf(os.Stderr,
			"\n*** 경고: -preset sparse = 희소키 H=192 (대조군 전용) ***\n"+
				"*** 조밀키 boot16 결과와 섞지 말 것. OpenFHE -skd sparse와 짝을 이룬다. ***\n\n")
		def := bootstrapping.DefaultParametersSparse[0] // N16QP1546H192H32
		residualLit = def.SchemeParams
		btpLit = def.BootstrappingParams
	}

	residual, err := ckks.NewParametersFromLiteral(residualLit)
	if err != nil {
		panic(err)
	}

	btpParams, err := bootstrapping.NewParametersFromLiteral(residual, btpLit)
	if err != nil {
		panic(err)
	}

	// --- 체인 덤프 (각주용 수치) ---
	// OpenFHE와 Q 체인을 강제로 일치시키지 않는다: Lattigo는 residual/bootstrapping을
	// 2겹으로 분리하고 OpenFHE는 단일 체인에 합산하므로, 맞추려 들면 한쪽이 자기
	// 최적점을 벗어나고 logQP가 따라 움직여 보안 수준까지 바뀐다.
	bp := btpParams.BootstrappingParameters
	fmt.Fprintf(os.Stderr, "\n[%s] === Lattigo chain dump ===\n", presetName)
	fmt.Fprintf(os.Stderr, "  residual      LogN=%d  MaxLevel=%d  MaxSlots=%d  LogDefaultScale=%d\n",
		residual.LogN(), residual.MaxLevel(), residual.MaxSlots(), residual.LogDefaultScale())
	fmt.Fprintf(os.Stderr, "  residual      logQ=%.2f  logP=%.2f  logQP=%.2f\n",
		residual.LogQ(), residual.LogP(), residual.LogQP())
	fmt.Fprintf(os.Stderr, "  bootstrapping LogN=%d  MaxLevel=%d  logQ=%.2f  logP=%.2f  logQP=%.2f\n",
		bp.LogN(), bp.MaxLevel(), bp.LogQ(), bp.LogP(), bp.LogQP())
	// limb(tower) 개수: NTT 호출 횟수가 limb 수에 비례하므로 logQP(보안 지표)와 달리
	// limb 개수는 *작업량* 지표다. 부트스트래핑 회로가 실제로 도는 것은 bootstrapping
	// 파라미터 쪽이므로 CSV에는 그쪽 값을 기록한다(residual은 참고용).
	limbsQ, limbsP := bp.QCount(), bp.PCount()
	fmt.Fprintf(os.Stderr, "  limbs  residual: Q=%d P=%d QP=%d\n",
		residual.QCount(), residual.PCount(), residual.QCount()+residual.PCount())
	fmt.Fprintf(os.Stderr, "  limbs  bootstrapping: Q=%d P=%d QP=%d   <- 작업량 지표 (NTT 호출 횟수가 limb 수에 비례)\n",
		limbsQ, limbsP, limbsQ+limbsP)
	fmt.Fprintf(os.Stderr, "  depth total=%d  (C2S=%d  EvalMod=%d  S2C=%d)\n",
		btpParams.Depth(), btpParams.DepthCoeffsToSlots(),
		btpParams.DepthEvalMod(), btpParams.DepthSlotsToCoeffs())
	xsLabel := "dense ternary H=32768"
	if sparse {
		xsLabel = "SPARSE ternary H=192 (대조군)"
	}
	fmt.Fprintf(os.Stderr, "  EphemeralSecretWeight=%d  Xs=%s  LogDefaultScale=%d\n",
		btpParams.EphemeralSecretWeight, xsLabel, residual.LogDefaultScale())

	// --- 키 생성 (타이밍 대상: btp_keygen) ---
	kgen := ckks.NewKeyGenerator(residual)
	sk, pk := kgen.GenKeyPairNew()

	tKeygen := time.Now()
	// GenEvaluationKeys는 3개를 반환한다: 평가키, 부트스트래핑용 밀집 비밀키(skN2), error.
	btpKeys, _, err := btpParams.GenEvaluationKeys(sk)
	if err != nil {
		panic(err)
	}
	keygenUS := float64(time.Since(tKeygen).Nanoseconds()) / 1000.0

	// 키 크기: Lattigo는 정확한 직렬화 크기를 노출한다 (OpenFHE에는 대응 API 없음).
	keyBytes := btpKeys.BinarySize()

	btpEval, err := bootstrapping.NewEvaluator(btpParams, btpKeys)
	if err != nil {
		panic(err)
	}

	inLevel := btpEval.MinimumInputLevel()
	outLevel := btpEval.OutputLevel()
	numSlots := residual.MaxSlots()

	fmt.Fprintf(os.Stderr, "  keygen=%.0f us  keyBytes=%d (%.2f MB)  in_level=%d out_level=%d\n",
		keygenUS, keyBytes, float64(keyBytes)/(1024*1024), inLevel, outLevel)

	// --- 입력 준비 ---
	// 모든 슬롯 0.5 (기존 8-op 벤치와 동일).
	ecd := ckks.NewEncoder(residual)
	enc := ckks.NewEncryptor(residual, pk)
	values := make([]float64, numSlots)
	for i := range values {
		values[i] = 0.5
	}

	// newCT: 최소 입력 레벨의 신선한 암호문 1개. 타이밍 밖에서 매 반복 새로 만든다.
	// Bootstrap은 입력을 in-place로 건드릴 수 있어 재사용이 금지된다.
	newCT := func() *rlwe.Ciphertext {
		pt := ckks.NewPlaintext(residual, inLevel)
		if err := ecd.Encode(values, pt); err != nil {
			panic(err)
		}
		ct, err := enc.EncryptNew(pt)
		if err != nil {
			panic(err)
		}
		return ct
	}

	// --- 부트스트래핑 측정 ---
	// 타이밍 범위는 Bootstrap 호출 1회뿐. 입력 ct 생성은 밖에서.
	for i := 0; i < *warmup; i++ {
		ct := newCT()
		runtime.GC()
		if _, err := btpEval.Bootstrap(ct); err != nil {
			panic(err)
		}
	}

	// CPU 프로파일은 측정 루프만 감싼다. 키 생성(~57초)은 bootstrap 3회(~69초)와 비중이
	// 비슷해서 함께 프로파일하면 keygen 함수가 결과를 절반 가까이 오염시킨다.
	// warmup도 제외 — 첫 호출의 lazy 초기화가 섞이지 않도록.
	if *cpuprofile != "" {
		pf, err := os.Create(*cpuprofile)
		if err != nil {
			panic(err)
		}
		defer pf.Close()
		if err := pprof.StartCPUProfile(pf); err != nil {
			panic(err)
		}
		defer pprof.StopCPUProfile()
		fmt.Fprintf(os.Stderr, "  CPU 프로파일링 시작 (측정 루프만, keygen/warmup 제외) → %s\n",
			*cpuprofile)
	}

	ts := make([]float64, *reps)
	for i := 0; i < *reps; i++ {
		ct := newCT()
		// 타이밍 시작 전에 명시적 GC: 직전 반복이 남긴 암호문·중간 버퍼를 여기서 회수해
		// 피크 RSS를 억제한다. GOGC를 낮추는 방식은 측정 구간 *안*에서 GC 빈도를 올려
		// 타이밍을 오염시키므로 쓰지 않는다 (GC를 타이밍 밖으로 밀어내는 것이 목적).
		runtime.GC()
		t0 := time.Now()
		ctOut, err := btpEval.Bootstrap(ct)
		ts[i] = float64(time.Since(t0).Nanoseconds()) / 1000.0
		if err != nil {
			panic(err)
		}
		fmt.Fprintf(os.Stderr, "  rep %2d/%d  %.0f us (%.3f s)  outLevel=%d\n",
			i+1, *reps, ts[i], ts[i]/1e6, ctOut.Level())
	}

	mean, sd := bootMeanStd(ts)

	// --- 정밀도 검증 (타이밍 구간 밖, 1회) ---
	// 알려진 값 암호화 → 부트스트래핑 → 복호화 → 원본과 슬롯별 비교.
	// 타이밍용 입력은 전 슬롯 0.5로 고정돼 있어 정밀도 측정에 부적합하다(단일 값이라
	// 슬롯별 오차 분포를 볼 수 없고, 상수 벡터는 DFT 단계에서 비대표적으로 유리하다).
	// → 정밀도 측정에만 [-1,1) 균등 난수를 쓴다. 시드 고정으로 실행 간 재현 가능.
	dec := ckks.NewDecryptor(residual, sk)
	rng := rand.New(rand.NewSource(42))
	want := make([]float64, numSlots)
	for i := range want {
		want[i] = 2*rng.Float64() - 1
	}
	ptPrec := ckks.NewPlaintext(residual, inLevel)
	if err := ecd.Encode(want, ptPrec); err != nil {
		panic(err)
	}
	ctPrec, err := enc.EncryptNew(ptPrec)
	if err != nil {
		panic(err)
	}
	ctPrecOut, err := btpEval.Bootstrap(ctPrec)
	if err != nil {
		panic(err)
	}
	have := make([]float64, numSlots)
	if err := ecd.Decode(dec.DecryptNew(ctPrecOut), have); err != nil {
		panic(err)
	}

	// 슬롯별 절대오차의 최대/평균 → log2. CKKS 관례상 정밀도 비트 = -log2(오차).
	var maxErr, sumErr float64
	for i := range want {
		e := math.Abs(have[i] - want[i])
		if e > maxErr {
			maxErr = e
		}
		sumErr += e
	}
	meanErr := sumErr / float64(numSlots)
	log2Max, log2Mean := math.Log2(maxErr), math.Log2(meanErr)
	precMeanBits, precMinBits := -log2Mean, -log2Max

	fmt.Fprintf(os.Stderr,
		"  정밀도: log2(max_err)=%.2f log2(mean_err)=%.2f → 평균 %.2f비트 / 최악 %.2f비트\n",
		log2Max, log2Mean, precMeanBits, precMinBits)

	// us_per_level: 소모 레벨당 정규화. Lattigo/OpenFHE의 입력 레벨이 1 다를 수 있으므로
	// 절대 지연시간 대신 이 지표로 비교한다.
	levelGain := outLevel - inLevel
	if levelGain <= 0 {
		fmt.Fprintf(os.Stderr, "경고: levelGain=%d (<=0) — us_per_level 계산 불가\n", levelGain)
		levelGain = 1
	}
	perLevelMean := mean / float64(levelGain)
	perLevelSD := sd / float64(levelGain)

	peak := peakRSSMB()

	// thread_mechanism: 라벨이 아니라 런타임 실측값을 기록한다.
	// Go는 OMP_NUM_THREADS를 무시하므로 GOMAXPROCS가 유일한 코어 제한 수단이다.
	threadMech := fmt.Sprintf("GOMAXPROCS=%d", runtime.GOMAXPROCS(0))
	fmt.Fprintf(os.Stderr, "  thread_mechanism=%s\n", threadMech)

	// --- CSV 기록 ---
	rows := [][]string{{
		"library", "preset", "logN", "numSlots", "in_level", "out_level",
		"op", "mean_us", "std_us", "reps", "key_bytes", "peak_rss_mb",
		"limbs_q", "limbs_p", "thread_mechanism",
	}}
	row := func(op string, m, s float64, r int) {
		rows = append(rows, []string{
			"lattigo", presetName,
			strconv.Itoa(residual.LogN()), strconv.Itoa(numSlots),
			strconv.Itoa(inLevel), strconv.Itoa(outLevel),
			op,
			strconv.FormatFloat(m, 'f', 3, 64),
			strconv.FormatFloat(s, 'f', 3, 64),
			strconv.Itoa(r),
			strconv.Itoa(keyBytes),
			strconv.FormatFloat(peak, 'f', 1, 64),
			strconv.Itoa(limbsQ), strconv.Itoa(limbsP), threadMech,
		})
	}
	row("bootstrap", mean, sd, *reps)
	// btp_setup은 OpenFHE 전용(EvalBootstrapSetup 사전계산). Lattigo는 대응 단계가
	// NewEvaluator 내부에 흡수돼 별도 행을 남기지 않는다.
	row("btp_keygen", keygenUS, 0, 1)
	row("us_per_level", perLevelMean, perLevelSD, *reps)
	// precision_bits 행은 μs가 아니라 *비트*를 담는다 (스키마 고정이라 컬럼 재사용):
	//   mean_us = 평균 정밀도 비트 = -log2(mean|err|)
	//   std_us  = 최악 슬롯 정밀도 비트 = -log2(max|err|)
	row("precision_bits", precMeanBits, precMinBits, 1)

	f, err := os.Create(*out)
	if err != nil {
		panic(err)
	}
	defer f.Close()
	if sparse {
		fmt.Fprintln(f, "# 희소키 H=192 대조군 - 본 결과(조밀 boot16)와 섞지 말 것.")
		fmt.Fprintln(f, "# 공식 프리셋 N16QP1546H192H32. OpenFHE -skd sparse와 짝을 이룬다.")
	}
	w := csv.NewWriter(f)
	if err := w.WriteAll(rows); err != nil {
		panic(err)
	}
	w.Flush()

	fmt.Fprintf(os.Stderr,
		"\n[%s] bootstrap mean=%.0f us (%.3f s) sd=%.0f  us_per_level=%.0f  peakRSS=%.1f MB\n",
		presetName, mean, mean/1e6, sd, perLevelMean, peak)
	fmt.Fprintf(os.Stderr, "wrote %s (%d rows)\n", *out, len(rows)-1)
}
