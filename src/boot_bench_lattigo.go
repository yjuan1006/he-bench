//go:build ignore

// boot_bench_lattigo.go — 부트스트래핑 2단계(정밀도 곡선) 측정. **단일 조합 1회 실행.**
//
// `boot_bench_openfhe.cpp` 와 **같은 절차·같은 CSV 스키마**다. 그래야 두 라이브러리를
// 나란히 놓을 수 있다. 정밀도 정의도 8-op 과 같다 —
//   precision_bits = -log2(전 슬롯 평균 |err|), 입력은 xorshift64* (precision_common.h 와 동일 수열).
//
// ⚠️ **스크리닝이다. 본측정이 아니다.** reps 3 / warmup 3 이라 지연시간은 확정값이 아니다.
// ⚠️ **정밀도 숫자만 보지 않는다** — 레벨 전이 / 자릿수 / 유한성 셋을 함께 확인하고
//    하나라도 어긋나면 fail 로 기록한다.
// ⚠️ **rep 마다 CSV 에 append + flush.**
//
// 고정 조건은 1단계와 동일: LogN 16 / 전체 슬롯 / dense Ternary{P:2/3} /
// EphemeralSecretWeight 0 / **K 512** / C2S·S2C 분해깊이 {3,3} / EvalMod scale 60 / P 프라임 61.
package main

import (
	"flag"
	"fmt"
	"math"
	"os"
	"runtime"
	"strings"
	"time"

	"github.com/tuneinsight/lattigo/v6/circuits/ckks/bootstrapping"
	"github.com/tuneinsight/lattigo/v6/core/rlwe"
	"github.com/tuneinsight/lattigo/v6/ring"
	"github.com/tuneinsight/lattigo/v6/schemes/ckks"
)

const csvHeader = "library,logN,numSlots,q0,delta,residual_L,levelBudget_c2s,levelBudget_s2c," +
	"boot_depth,dnum,PCount,logQ_boot,logP_boot,logQP_boot," +
	"rep,precision_bits,worst_slot_bits,boot_us," +
	"level_in,level_out,level_out_expected,magnitude_ratio," +
	"scaling,in_scale_log2,q0_minus_scale_log2,out_scale_log2,correction_factor," +
	"setup_us,keygen_us,peak_rss_mb,ok,fail_reason\n"

func ip(v int) *int { return &v }

// precision_common.h 의 xorshift64* 와 **비트 단위로 같은** 수열이어야 한다.
type rng struct{ s uint64 }

func (r *rng) next() uint64 {
	r.s ^= r.s >> 12
	r.s ^= r.s << 25
	r.s ^= r.s >> 27
	return r.s * 2685821657736338717
}
func (r *rng) val() float64 {
	return float64(r.next()>>11)/9007199254740992.0*2.0 - 1.0
}

// x[0], y[0], x[1], y[1], ... 순서(순서도 규약의 일부). 부트에서는 x 만 쓴다.
func makeInputs(slots int) []float64 {
	r := &rng{s: 0x2026072500000001}
	x := make([]float64, slots)
	for i := 0; i < slots; i++ {
		x[i] = r.val()
		r.val() // y — 버리되 수열 위치는 맞춘다
	}
	return x
}

func precisionBits(got, want []float64) float64 {
	s := 0.0
	for i := range want {
		s += math.Abs(got[i] - want[i])
	}
	m := s / float64(len(want))
	if m <= 0 {
		return 999.0
	}
	return -math.Log2(m)
}

func nominal(q uint64) int { return int(math.Round(math.Log2(float64(q)))) }

func sumNominal(m []uint64) int {
	s := 0
	for _, q := range m {
		s += nominal(q)
	}
	return s
}

func peakRssMb() int64 {
	b, err := os.ReadFile("/proc/self/status")
	if err != nil {
		return -1
	}
	for _, ln := range strings.Split(string(b), "\n") {
		if strings.HasPrefix(ln, "VmHWM:") {
			var v int64
			fmt.Sscanf(strings.TrimPrefix(ln, "VmHWM:"), "%d", &v)
			return v / 1024
		}
	}
	return -1
}

func scrub(s string) string {
	return strings.NewReplacer(",", " ", "\n", " ", "\r", " ", "\"", " ").Replace(s)
}

// §8.5 규칙 7 — 잔여 파라미터의 P 는 dnum 최소화 우선(1단계 격자와 같은 규칙).
func bestResidualPCount(qCount, maxPC int) int {
	bestPC, bestDnum := 1, qCount
	for pc := 1; pc <= maxPC; pc++ {
		if d := (qCount + pc - 1) / pc; d < bestDnum {
			bestDnum, bestPC = d, pc
		}
	}
	return bestPC
}

func main() {
	logN := flag.Int("logN", 16, "")
	logSlots := flag.Int("logSlots", 15, "")
	q0 := flag.Int("q0", 45, "")
	delta := flag.Int("delta", 40, "")
	L := flag.Int("L", 12, "잔여 레벨")
	c2s := flag.Int("c2s", 3, "")
	s2c := flag.Int("s2c", 3, "")
	pc := flag.Int("pcount", 8, "부트 파라미터의 PCount")
	scale := flag.Int("evalmod-scale", 60, "")
	// (마) 구성 (2026-08-12 §10.1 정정): dense 메인 + 캡슐화 32 + K16 + InvDeg 0.
	// 캡슐화 off 는 Lattigo v6.2.0 에서 9조합 전수 실패했다(§10.7-17).
	K := flag.Int("K", 16, "(마) 구성: 캡슐화가 켜져 ModUp 이 sparse 임시키 아래라 16 으로 충분")
	eph := flag.Int("ephemeral", 32, "EphemeralSecretWeight. 0 = 캡슐화 끔 — v6.2.0 에서 동작 안 함")
	invDeg := flag.Int("mod1invdegree", 0, "⚠️ 7 로 두면 K512 에서 logQP 1864 로 상한 초과")
	mod1Degree := flag.Int("mod1degree", 0, "0 이면 2*(K-1) 최소요구값을 쓴다")
	// ⚠️ Lattigo 기본값 8 을 유지한다. 낮추면 부트 정밀도가 직접 나빠져 2단계 목적과 충돌한다.
	// ⚠️ 0 이면 **q0 − Δ** 를 쓴다 — OpenFHE 는 입력을 재스케일하지 않으므로 실효
	// message ratio 가 2^(q0−Δ) 다(런타임 실측). 그 값에 맞춰야 양쪽이 **같은 크기의
	// 메시지를 부트**하고, 입력 스케일도 2^Δ 로 양쪽이 같아진다(scaleUp = 1).
	logMsgRatio := flag.Int("logmsgratio", 0, "0 이면 q0−Δ")
	aux := flag.Int("auxbits", 61, "")
	reps := flag.Int("reps", 3, "")
	warmup := flag.Int("warmup", 3, "")
	// ⚠️ mt 는 타이밍과 정밀도를 분리 실행한다(§8.6-2).
	runMode := flag.String("mode", "both", "both|timing|precision")
	out := flag.String("out", "boot_prec_lattigo.csv", "")
	flag.Parse()

	numSlots := 1 << *logSlots

	// ⚠️ **스키마 가드** — OpenFHE 하네스와 같은 이유(2026-08-12 혼입 사고).
	needHeader := true
	if b, err := os.ReadFile(*out); err == nil && len(b) > 0 {
		first, _, _ := strings.Cut(string(b), "\n")
		want := strings.TrimSuffix(csvHeader, "\n")
		if first != want {
			fmt.Fprintf(os.Stderr, "[스키마 불일치] %s 의 헤더가 현재 스키마와 다르다.\n  기존: %s\n  현재: %s\n"+
				"  → 다른 파일명을 쓰거나 기존 파일을 superseded/ 로 옮길 것.\n", *out, first, want)
			os.Exit(2)
		}
		needHeader = false
	}
	fh, err := os.OpenFile(*out, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		panic(err)
	}
	defer fh.Close()
	if needHeader {
		fmt.Fprint(fh, csvHeader)
		fh.Sync()
	}

	var setupUs, kgUs float64
	fail := func(why string) {
		fmt.Fprintf(fh, "lattigo,%d,%d,%d,%d,%d,%d,%d,,,,,,,%d,-1,,,,,,,%s,,,,%d,%d,%d,0,%s\n",
			*logN, numSlots, *q0, *delta, *L, *c2s, *s2c, -1,
			fmt.Sprintf("eph%d_K%d_inv%d", *eph, *K, *invDeg),
			int64(setupUs), int64(kgUs), peakRssMb(), scrub(why))
		fh.Sync()
		fmt.Println("✗", why)
	}

	// --- 파라미터 (1단계 격자와 동일 구성) ---
	logQ := []int{*q0}
	for i := 0; i < *L; i++ {
		logQ = append(logQ, *delta)
	}
	resP := make([]int, bestResidualPCount(*L+1, 8))
	for i := range resP {
		resP[i] = *aux
	}
	res, rerr := ckks.NewParametersFromLiteral(ckks.ParametersLiteral{
		LogN: *logN, LogQ: logQ, LogP: resP, LogDefaultScale: *delta,
		Xs: ring.Ternary{P: 2.0 / 3.0},
	})
	if rerr != nil {
		fail("잔여 파라미터 생성 실패: " + rerr.Error())
		os.Exit(1)
	}

	mrForLit := *logMsgRatio
	if mrForLit == 0 {
		mrForLit = *q0 - *delta
	}
	bootP := make([]int, *pc)
	for i := range bootP {
		bootP[i] = *aux
	}
	c2sD := make([][]int, *c2s)
	for i := range c2sD {
		c2sD[i] = []int{bootstrapping.DefaultCoeffsToSlotsLogScale}
	}
	s2cD := make([][]int, *s2c)
	for i := range s2cD {
		s2cD[i] = []int{bootstrapping.DefaultSlotsToCoeffsLogScale}
	}
	// ⚠️ **Mod1Degree 를 명시해야 한다.** `NewEvaluator` 가 CosDiscrete 에 대해
	// `Mod1Degree >= 2*(K-1)` 을 요구한다(`evaluator.go:89`). 기본값 30 으로 두면
	// 파라미터는 만들어지지만 평가기 생성에서 죽는다(2026-08-12 보정에서 실제 발생).
	// K=512 → 최소 1022. `Depth()` 가 이미 max(Mod1Degree, 2K−1) 을 쓰므로
	// **EvalMod 깊이·체인은 격자값과 동일하다**(실측 확인, boot_evalcheck_lattigo.csv).
	mod1deg := *mod1Degree
	if mod1deg == 0 {
		mod1deg = 2 * (*K - 1)
	}
	btpLit := bootstrapping.ParametersLiteral{
		LogN: ip(*logN), LogSlots: ip(*logSlots), LogP: bootP, Xs: res.Xs(),
		Mod1Degree: ip(mod1deg),
		CoeffsToSlotsFactorizationDepthAndLogScales: c2sD,
		SlotsToCoeffsFactorizationDepthAndLogScales: s2cD,
		EvalModLogScale:                             ip(*scale),
		EphemeralSecretWeight:                       ip(*eph),
		Mod1InvDegree:                               ip(*invDeg),
		LogMessageRatio:                             ip(mrForLit),
		K:                                           ip(*K),
	}
	btp, berr := bootstrapping.NewParametersFromLiteral(res, btpLit)
	if berr != nil {
		fail("부트 파라미터 생성 실패: " + berr.Error())
		os.Exit(1)
	}
	bp := btp.BootstrappingParameters
	lq, lp := sumNominal(bp.Q()), sumNominal(bp.P())
	dnum := bp.BaseRNSDecompositionVectorSize(bp.MaxLevelQ(), bp.MaxLevelP())
	bootDepth := bp.QCount() - res.QCount()

	// --- keygen ---
	t0 := time.Now()
	kgen := rlwe.NewKeyGenerator(res)
	sk := kgen.GenSecretKeyNew()
	evk, _, kerr := btp.GenEvaluationKeys(sk)
	kgUs = float64(time.Since(t0).Microseconds())
	if kerr != nil {
		fail("평가키 생성 실패: " + kerr.Error())
		os.Exit(1)
	}

	// --- setup: DFT 사전계산 (OpenFHE 의 EvalBootstrapSetup 에 대응) ---
	t0 = time.Now()
	eval, eerr := bootstrapping.NewEvaluator(btp, evk)
	setupUs = float64(time.Since(t0).Microseconds())
	if eerr != nil {
		fail("평가기 생성 실패: " + eerr.Error())
		os.Exit(1)
	}

	// --- 입력. ⚠️ 비밀키 암호화 (§8.4 정밀도 정본과 같은 조건) ---
	x := makeInputs(numSlots)
	ecd := ckks.NewEncoder(res)
	enc := rlwe.NewEncryptor(res, sk)
	dec := rlwe.NewDecryptor(res, sk)

	// ⚠️ **부트 입력 스케일을 명시한다** (2026-08-12 결정 1).
	// 잔여 기본 스케일 2^Δ 를 그대로 쓰면 `ScaleDown` 이
	//   Q[0]/스케일 ≥ 0.5×MessageRatio  (evaluator.go:587)
	// 을 요구해 `q0 − Δ ≥ 7` 이 강제되는데, 이는 파라미터 제약이 아니라 **입력 스케일
	// 2^Δ 가정에서 나온 인위적 제약**이다(OpenFHE 의 `q0 − Δ ≤ 7` 과 교집합이 한 점뿐).
	// 실제 파이프라인은 레벨 0 까지 소모된 암호문이 들어오고, Lattigo 설계 의도는
	// Q[0]/|m| = 2^LogMessageRatio 다. 그 값으로 못박는다.
	mr := *logMsgRatio
	if mr == 0 {
		mr = *q0 - *delta
	}
	inScaleLog2 := *q0 - mr
	pt := ckks.NewPlaintext(res, 0) // 잔여 체인의 바닥. 부트가 여기서 끌어올린다
	pt.Scale = rlwe.NewScale(math.Exp2(float64(inScaleLog2)))
	if err := ecd.Encode(x, pt); err != nil {
		fail("인코딩 실패: " + err.Error())
		os.Exit(1)
	}
	// ⚠️ **rep 마다 새로 암호화한다.** 같은 암호문을 복제해 쓰면 부트 근사오차가 지배적이라
	//    반복 간 값이 완전히 동일해지고(2단계 6회 전부 14.562074), §4 의 "평균 + 표본표준편차"
	//    가 의미를 잃는다. 여기서 만드는 것은 메타 추출용 1개다.
	ctProbe, err := enc.EncryptNew(pt)
	if err != nil {
		fail("암호화 실패: " + err.Error())
		os.Exit(1)
	}
	levelIn := ctProbe.Level()
	levelOutExpected := eval.OutputLevel()

	wantMax := 0.0
	for _, v := range x {
		wantMax = math.Max(wantMax, math.Abs(v))
	}

	for r := -*warmup; r < *reps; r++ {
		var why string
		var bootUs, prec, worst, magRatio float64
		levelOut := -1
		outScaleLog2 := 0.0

		func() {
			defer func() {
				if e := recover(); e != nil {
					why = fmt.Sprintf("부트 패닉: %v", e)
				}
			}()
			ctIn, e0 := enc.EncryptNew(pt)   // rep 마다 새 암호문
			if e0 != nil {
				why = "암호화 실패: " + e0.Error()
				return
			}
			s := time.Now()
			ctb, e := eval.Bootstrap(ctIn)
			bootUs = float64(time.Since(s).Microseconds())
			if e != nil {
				why = "부트 실패: " + e.Error()
				return
			}
			levelOut = ctb.Level()
			// ⚠️ 출력 스케일을 **런타임으로** 찍는다. 입력 스케일을 우리가 못박았으므로
			//    라이브러리가 출력 스케일을 어떻게 되돌리는지 확인해야 한다.
			outScaleLog2 = math.Log2(ctb.Scale.Float64())

			if *runMode == "timing" {
				// ⚠️ 정밀도 구간을 돌지 않는다 — mt 에서 직렬이라 post 프로브를 오염시킨다.
				prec, worst, magRatio = -1, -1, -1
				if levelOut != levelOutExpected {
					why = fmt.Sprintf("레벨 이상: out=%d 예상=%d", levelOut, levelOutExpected)
				}
				return
			}
			got := make([]float64, numSlots)
			if e := ecd.Decode(dec.DecryptNew(ctb), got); e != nil {
				why = "디코딩 실패: " + e.Error()
				return
			}
			prec = precisionBits(got, x)
			maxErr, gotMax := 0.0, 0.0
			for i := range x {
				maxErr = math.Max(maxErr, math.Abs(got[i]-x[i]))
				gotMax = math.Max(gotMax, math.Abs(got[i]))
			}
			if maxErr > 0 {
				worst = -math.Log2(maxErr)
			} else {
				worst = 999.0
			}
			if wantMax > 0 {
				magRatio = gotMax / wantMax
			}

			// --- 정상성 검증 셋 ---
			switch {
			case levelOut != levelOutExpected:
				why = fmt.Sprintf("레벨 이상: out=%d 예상=%d", levelOut, levelOutExpected)
			case !(magRatio > 0.5 && magRatio < 2.0):
				why = fmt.Sprintf("자릿수 이상: max|got|/max|want|=%.4f", magRatio)
			case math.IsNaN(prec) || math.IsInf(prec, 0) || prec <= 0:
				why = fmt.Sprintf("정밀도 이상: %.4f비트", prec)
			}
		}()

		// ⚠️ warmup 도 **행으로 남긴다**(rep 음수). 예전에는 warmup 실패 시 즉시 중단해
		//    정밀도 숫자를 하나도 못 남겼다 — "게이트 통과 ≠ 정상" 이므로 실패해도
		//    정밀도·자릿수·시간을 봐야 한다(2026-08-12).
		okv := 1
		if why != "" {
			okv = 0
		}
		fmt.Fprintf(fh, "lattigo,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%g,%g,%d,%d,%d,%d,%g,%s,%d,%d,%g,%d,%d,%d,%d,%d,%s\n",
			*logN, numSlots, *q0, *delta, *L, *c2s, *s2c,
			bootDepth, dnum, bp.PCount(), lq, lp, lq+lp,
			r, prec, worst, int64(bootUs),
			levelIn, levelOut, levelOutExpected, magRatio,
			fmt.Sprintf("eph%d_K%d_mr%d_inv%d|%s", *eph, *K, mrForLit, *invDeg, *runMode),
			inScaleLog2, *q0-inScaleLog2, outScaleLog2, -1,
			int64(setupUs), int64(kgUs), peakRssMb(), okv, scrub(why))
		fh.Sync() // ★ rep 마다 디스크로

		msg := ""
		if why != "" {
			msg = "  ✗ " + why
		}
		fmt.Printf("  rep %d  정밀도 %.4f비트  최악슬롯 %.4f  부트 %dms  레벨 %d→%d%s\n",
			r, prec, worst, int64(bootUs/1000), levelIn, levelOut, msg)
	}
	fmt.Printf("  입력 스케일 2^%d  q0-스케일 = %d  (LogMessageRatio %d, 캡슐화 %d, K %d, InvDeg %d)\n",
		inScaleLog2, *q0-inScaleLog2, mr, *eph, *K, *invDeg)
	fmt.Printf("[boot] lattigo q0=%d Δ=%d L=%d c2s/s2c=%d/%d dnum=%d K=%d Mod1Degree=%d evalScale=%d  setup %ds  keygen %ds  peakRSS %dMB  (GOMAXPROCS=%d)\n",
		*q0, *delta, *L, *c2s, *s2c, dnum, *K, mod1deg, *scale,
		int64(setupUs/1e6), int64(kgUs/1e6), peakRssMb(), runtime.GOMAXPROCS(0))
}
