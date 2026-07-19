// lattigo_ks_bench.go — key-switch 단건 비용 벤치 (Lattigo v6, logN 16 / boot16 체인)
//
// 목적: 부트스트래핑 격차(Lattigo 1.59배 우위)가 *단일 key-switch 성능* 차이인지,
// 아니면 *다수 연산 조합 최적화*(lazy reduction / hoisting / BSGS) 차이인지 구분한다.
// 단건 비용비 ≈ 부트스트래핑 비용비면 전자, 단건은 비슷한데 부트스트래핑만 벌어지면 후자다.
//
// 체인: boot16의 *bootstrapping 파라미터* (Q=28 limb, P=5). residual이 아니다 —
// 부트스트래핑 회로가 실제로 도는 쪽이 이쪽이라 1.59배와 직접 대응된다.
// 측정 op: mul_cc_rlk / rot1 / relin(= mul_cc_rlk - mul_cc). 최상위 레벨만.
// 규칙은 기존 8-op 벤치(lattigo_bench.go)와 동일: warmup 후 reps회, 연산 1회만 타이밍,
// 출력 ct 미리 할당, μs, 표본표준편차(n-1).
//
// 실행: go run lattigo_ks_bench.go -reps 30
package main

import (
	"encoding/csv"
	"flag"
	"fmt"
	"math"
	"os"
	"strconv"
	"time"

	"github.com/tuneinsight/lattigo/v6/circuits/ckks/bootstrapping"
	"github.com/tuneinsight/lattigo/v6/core/rlwe"
	"github.com/tuneinsight/lattigo/v6/ring"
	"github.com/tuneinsight/lattigo/v6/schemes/ckks"
	"github.com/tuneinsight/lattigo/v6/utils"
)

func ksMeasure(reps, warmup int, fn func() error) []float64 {
	for i := 0; i < warmup; i++ {
		if err := fn(); err != nil {
			panic(err)
		}
	}
	ts := make([]float64, reps)
	for i := 0; i < reps; i++ {
		t0 := time.Now()
		if err := fn(); err != nil {
			panic(err)
		}
		ts[i] = float64(time.Since(t0).Nanoseconds()) / 1000.0
	}
	return ts
}

func ksMeanStd(xs []float64) (float64, float64) {
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
	reps := flag.Int("reps", 30, "측정 반복 횟수")
	warmup := flag.Int("warmup", 3, "warm-up 횟수")
	out := flag.String("out", "results_ks_lattigo.csv", "출력 CSV 경로")
	flag.Parse()

	// boot16과 동일한 residual + 부트스트래핑 리터럴 → 같은 bootstrapping 파라미터를 얻는다.
	logQ := []int{60}
	for i := 0; i < 9; i++ {
		logQ = append(logQ, 45)
	}
	residual, err := ckks.NewParametersFromLiteral(ckks.ParametersLiteral{
		LogN:            16,
		LogQ:            logQ,
		LogP:            []int{61, 61, 61, 61, 61},
		Xs:              ring.Ternary{H: 32768},
		LogDefaultScale: 45,
	})
	if err != nil {
		panic(err)
	}
	btpParams, err := bootstrapping.NewParametersFromLiteral(residual, bootstrapping.ParametersLiteral{
		SlotsToCoeffsFactorizationDepthAndLogScales: [][]int{{42}, {42}, {42}},
		CoeffsToSlotsFactorizationDepthAndLogScales: [][]int{{58}, {58}, {58}, {58}},
		LogMessageRatio: utils.Pointy(2),
		Mod1InvDegree:   utils.Pointy(7),
	})
	if err != nil {
		panic(err)
	}

	// 부트스트래핑 회로가 실제로 도는 파라미터.
	params := btpParams.BootstrappingParameters
	maxLevel := params.MaxLevel()
	limbsQ, limbsP := params.QCount(), params.PCount()

	fmt.Fprintf(os.Stderr, "[boot16-ks] logN=%d maxLevel=%d limbs Q=%d P=%d QP=%d  logQP=%.2f\n",
		params.LogN(), maxLevel, limbsQ, limbsP, limbsQ+limbsP, params.LogQP())

	// 키/평가자 준비 (타이밍 밖).
	kgen := ckks.NewKeyGenerator(params)
	sk, pk := kgen.GenKeyPairNew()
	rlk := kgen.GenRelinearizationKeyNew(sk)
	galEl := params.GaloisElementForRotation(1)
	gks := kgen.GenGaloisKeysNew([]uint64{galEl}, sk)
	evk := rlwe.NewMemEvaluationKeySet(rlk, gks...)

	ecd := ckks.NewEncoder(params)
	enc := ckks.NewEncryptor(params, pk)
	eval := ckks.NewEvaluator(params, evk)

	// 입력값 0.5 (기존 8-op 벤치와 동일).
	values := make([]float64, params.MaxSlots())
	for i := range values {
		values[i] = 0.5
	}

	// 최상위 레벨만.
	L := maxLevel
	pt := ckks.NewPlaintext(params, L)
	if err := ecd.Encode(values, pt); err != nil {
		panic(err)
	}
	ctA := ckks.NewCiphertext(params, 1, L)
	if err := enc.Encrypt(pt, ctA); err != nil {
		panic(err)
	}
	ctB := ckks.NewCiphertext(params, 1, L)
	if err := enc.Encrypt(pt, ctB); err != nil {
		panic(err)
	}

	// 출력 ct 미리 할당. mul_cc는 relin 없이 degree-2.
	outMul2 := ckks.NewCiphertext(params, 2, L)
	outMulRlk := ckks.NewCiphertext(params, 1, L)
	outRot := ckks.NewCiphertext(params, 1, L)

	type job struct {
		op string
		fn func() error
	}
	jobs := []job{
		{"mul_cc", func() error { return eval.Mul(ctA, ctB, outMul2) }},
		{"mul_cc_rlk", func() error { return eval.MulRelin(ctA, ctB, outMulRlk) }},
		{"rot1", func() error { return eval.Rotate(ctA, 1, outRot) }},
	}

	results := map[string][2]float64{}
	for _, j := range jobs {
		m, s := ksMeanStd(ksMeasure(*reps, *warmup, j.fn))
		results[j.op] = [2]float64{m, s}
		fmt.Fprintf(os.Stderr, "  %-11s %10.1f us  (sd %.1f)\n", j.op, m, s)
	}

	// relin = mul_cc_rlk - mul_cc (음수면 0 clamp, std=0). 기존 벤치와 동일 규칙.
	relin := results["mul_cc_rlk"][0] - results["mul_cc"][0]
	if relin < 0 {
		relin = 0
	}
	results["relin"] = [2]float64{relin, 0}
	fmt.Fprintf(os.Stderr, "  %-11s %10.1f us  (파생값)\n", "relin", relin)

	rows := [][]string{{"library", "preset", "logN", "maxLevel", "level", "op",
		"mean_us", "std_us", "reps", "limbs_q", "limbs_p"}}
	for _, op := range []string{"mul_cc", "mul_cc_rlk", "relin", "rot1"} {
		r := results[op]
		rows = append(rows, []string{
			"lattigo", "boot16-ks",
			strconv.Itoa(params.LogN()), strconv.Itoa(maxLevel), strconv.Itoa(L), op,
			strconv.FormatFloat(r[0], 'f', 3, 64),
			strconv.FormatFloat(r[1], 'f', 3, 64),
			strconv.Itoa(*reps),
			strconv.Itoa(limbsQ), strconv.Itoa(limbsP),
		})
	}

	f, err := os.Create(*out)
	if err != nil {
		panic(err)
	}
	defer f.Close()
	w := csv.NewWriter(f)
	if err := w.WriteAll(rows); err != nil {
		panic(err)
	}
	w.Flush()
	fmt.Fprintf(os.Stderr, "wrote %s (%d rows)\n", *out, len(rows)-1)
}
