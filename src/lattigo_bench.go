// lattigo_bench.go — CKKS 연산 latency 벤치마크 (Lattigo v6)
// 암호문 1개 기준으로 add/mul/relin/rescale/rotate 비용을 프리셋×레벨 전수 측정.
// 측정 규칙: warmup 후 reps회, 연산 1회만 타이밍, 출력 ct는 밖에서 미리 할당, μs 단위, 표본표준편차(n-1).
package main

import (
	"encoding/csv"
	"flag"
	"fmt"
	"math"
	"os"
	"strconv"
	"time"

	"github.com/tuneinsight/lattigo/v6/core/rlwe"
	"github.com/tuneinsight/lattigo/v6/schemes/ckks"
)

// 프리셋 정의. maxLevel = len(LogQ)-1.
// 파라미터는 벤치마크용 근사치이며 검증된 보안 파라미터가 아님.
type Preset struct {
	Name  string
	LogN  int
	LogQ  []int
	LogP  []int
	Scale int
}

// rep: 값 v를 n개 가진 슬라이스 (모듈러스 체인 구성용).
func rep(v, n int) []int {
	s := make([]int, n)
	for i := range s {
		s[i] = v
	}
	return s
}

// small/medium/large = logN 13/14/15. maxLevel = 5/10/15.
func allPresets() []Preset {
	return []Preset{
		{"small", 13, append([]int{50}, rep(45, 5)...), []int{55}, 45},
		{"medium", 14, append([]int{55}, rep(45, 10)...), []int{55, 55}, 45},
		{"large", 15, append([]int{60}, rep(45, 15)...), []int{60, 60}, 45},
	}
}

// measure: warmup 후 reps회 fn을 1회씩 감싸 ns→μs로 기록.
func measure(reps, warmup int, fn func() error) []float64 {
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

// meanStd: 평균 + 표본표준편차(n-1).
func meanStd(xs []float64) (float64, float64) {
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
	presetFlag := flag.String("preset", "all", "small|medium|large|all")
	reps := flag.Int("reps", 30, "측정 반복 횟수")
	warmup := flag.Int("warmup", 3, "warm-up 횟수")
	out := flag.String("out", "results_lattigo.csv", "출력 CSV 경로")
	flag.Parse()

	var presets []Preset
	for _, p := range allPresets() {
		if *presetFlag == "all" || *presetFlag == p.Name {
			presets = append(presets, p)
		}
	}
	if len(presets) == 0 {
		fmt.Fprintf(os.Stderr, "unknown preset %q\n", *presetFlag)
		os.Exit(1)
	}

	rows := [][]string{{"library", "preset", "logN", "maxLevel", "level", "op", "mean_us", "std_us", "reps"}}

	for _, p := range presets {
		params, err := ckks.NewParametersFromLiteral(ckks.ParametersLiteral{
			LogN: p.LogN, LogQ: p.LogQ, LogP: p.LogP, LogDefaultScale: p.Scale,
		})
		if err != nil {
			panic(err)
		}
		maxLevel := params.MaxLevel()

		// 키/평가자 준비 (타이밍 밖).
		kgen := ckks.NewKeyGenerator(params)
		sk, pk := kgen.GenKeyPairNew()
		rlk := kgen.GenRelinearizationKeyNew(sk)
		galEl := params.GaloisElementForRotation(1) // +1 슬롯 회전
		gks := kgen.GenGaloisKeysNew([]uint64{galEl}, sk)
		evk := rlwe.NewMemEvaluationKeySet(rlk, gks...)

		ecd := ckks.NewEncoder(params)
		enc := ckks.NewEncryptor(params, pk)
		eval := ckks.NewEvaluator(params, evk)

		values := make([]float64, params.MaxSlots())
		for i := range values {
			values[i] = 0.5
		}

		fmt.Fprintf(os.Stderr, "[%s] logN=%d maxLevel=%d\n", p.Name, p.LogN, maxLevel)

		// 레벨 전수 스윕: maxLevel..1.
		for L := maxLevel; L >= 1; L-- {
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

			// 출력 암호문 미리 할당.
			outAdd := ckks.NewCiphertext(params, 1, L)
			outMulCP := ckks.NewCiphertext(params, 1, L)
			outMul2 := ckks.NewCiphertext(params, 2, L) // ct*ct relin 없음 → degree 2
			outMulRlk := ckks.NewCiphertext(params, 1, L)
			outRot := ckks.NewCiphertext(params, 1, L)
			outRescale := ckks.NewCiphertext(params, 1, L-1) // rescale → level-1

			// rescale 입력: 곱으로 스케일을 default^2로 만들어 두면 1프라임 rescale이 유효.
			ctResIn := ckks.NewCiphertext(params, 1, L)
			if err := eval.MulRelin(ctA, ctB, ctResIn); err != nil {
				panic(err)
			}

			type job struct {
				op string
				fn func() error
			}
			jobs := []job{
				{"add_cc", func() error { return eval.Add(ctA, ctB, outAdd) }},
				{"add_cp", func() error { return eval.Add(ctA, pt, outAdd) }},
				{"mul_cp", func() error { return eval.Mul(ctA, pt, outMulCP) }},
				{"mul_cc", func() error { return eval.Mul(ctA, ctB, outMul2) }},
				{"mul_cc_rlk", func() error { return eval.MulRelin(ctA, ctB, outMulRlk) }},
				{"rescale", func() error { return eval.Rescale(ctResIn, outRescale) }},
				{"rot1", func() error { return eval.Rotate(ctA, 1, outRot) }},
			}

			results := map[string][2]float64{} // op -> [mean,std]
			for _, j := range jobs {
				m, s := meanStd(measure(*reps, *warmup, j.fn))
				results[j.op] = [2]float64{m, s}
			}

			// relin: 직접 계측. (2026-07-26 변경)
			// 예전에는 relin = mul_cc_rlk - mul_cc 파생값이었고 std=0으로 기록했다. 그 방식은
			//   (1) 분산 정보가 사라지고(std=0이 CV 통계를 인공적으로 낮춤),
			//   (2) MulRelin이 융합 경로라 "두 평균의 차"가 독립 Relinearize 비용과 다른 양이며,
			//   (3) SEAL 하네스는 직접 계측이라 라이브러리 간 계측 방식이 불일치했다.
			// SEAL과 동일한 패턴: size-3(degree 2) 입력을 타이머 밖에서 1회 만들고
			// out-of-place Relinearize를 반복한다. Relinearize는 ctIn을 읽기만 하므로
			// (core/rlwe/evaluator_evaluationkey.go: ctIn.Value[0..2] 읽기, opOut에만 기록)
			// 반복해도 입력이 오염되지 않는다(§4).
			// ※ 이 블록은 기존 7개 측정이 끝난 뒤에 둔다 — 앞에 두면 할당자·메모리 상태가
			//    달라져 다른 op의 측정 조건이 바뀐다.
			relinIn := ckks.NewCiphertext(params, 2, L)
			if err := eval.Mul(ctA, ctB, relinIn); err != nil {
				panic(err)
			}
			outRelin := ckks.NewCiphertext(params, 1, L)
			mRelin, sRelin := meanStd(measure(*reps, *warmup, func() error {
				return eval.Relinearize(relinIn, outRelin)
			}))
			results["relin"] = [2]float64{mRelin, sRelin}

			// CSV 출력 순서 = 스펙의 8-op 순서.
			order := []string{"add_cc", "add_cp", "mul_cp", "mul_cc", "mul_cc_rlk", "relin", "rescale", "rot1"}
			for _, op := range order {
				r := results[op]
				rows = append(rows, []string{
					"lattigo", p.Name,
					strconv.Itoa(p.LogN), strconv.Itoa(maxLevel), strconv.Itoa(L),
					op,
					strconv.FormatFloat(r[0], 'f', 3, 64),
					strconv.FormatFloat(r[1], 'f', 3, 64),
					strconv.Itoa(*reps),
				})
			}

			// 진행 확인용: 이 레벨의 핵심 값 출력.
			fmt.Fprintf(os.Stderr, "  L=%2d add_cc=%7.2f mul_cc=%8.2f relin=%8.2f rot1=%8.2f rescale=%8.2f\n",
				L, results["add_cc"][0], results["mul_cc"][0], results["relin"][0], results["rot1"][0], results["rescale"][0])
		}
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
