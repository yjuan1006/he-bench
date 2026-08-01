//go:build ignore

// lattigo_precision.go — Lattigo CKKS 정밀도 측정 (독립 프로그램).
// ★ lattigo_bench.go 는 수정 금지이므로 별도 프로그램으로 만든다.
//
// 절차는 seal_precision.cpp / openfhe_precision.cpp 와 동일해야 한다:
//   - 입력 벡터: precision_common.h 의 xorshift64* 규약과 비트 단위로 동일해야 함
//     (아래 rng.next()/val()이 그 이식본이다. 바꾸면 비교가 깨진다)
//   - 오차 정의: -log2(전 슬롯 평균 |err|)
//   - 레벨 진입: 스케일을 바꾸지 않는 모듈러스 drop = eval.DropLevel
//   - 체인은 lattigo_bench.go 와 동일한 LogQ/LogP
//
// 경로: enc_dec, mul_cp_rs, rot1, relin(rescale 없음), mul_cc_relin_rs
package main

import (
	"flag"
	"fmt"
	"math"
	"os"

	"github.com/tuneinsight/lattigo/v6/core/rlwe"
	"github.com/tuneinsight/lattigo/v6/schemes/ckks"
)

// ---- precision_common.h 이식 (비트 단위 동일해야 함) ----
type rng struct{ s uint64 }

func newRng() *rng { return &rng{s: 0x2026072500000001} }
func (r *rng) next() uint64 {
	r.s ^= r.s >> 12
	r.s ^= r.s << 25
	r.s ^= r.s >> 27
	return r.s * 2685821657736338717
}
func (r *rng) val() float64 {
	return float64(r.next()>>11)/9007199254740992.0*2.0 - 1.0
}
func makeInputs(slots int) (x, y []float64) {
	r := newRng()
	x = make([]float64, slots)
	y = make([]float64, slots)
	for i := 0; i < slots; i++ {
		x[i] = r.val()
		y[i] = r.val()
	}
	return
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

type preset struct {
	Name string
	LogN int
	LogQ []int
	LogP []int
}

func main() {
	presetFlag := flag.String("preset", "small", "small|medium|large")
	reps := flag.Int("reps", 5, "반복 횟수")
	flag.Parse()

	mk := func(name string, logN, first, depth int, logP []int) preset {
		q := []int{first}
		for i := 0; i < depth; i++ {
			q = append(q, 45)
		}
		return preset{name, logN, q, logP}
	}
	all := []preset{
		mk("small", 13, 50, 5, []int{55}),
		mk("medium", 14, 55, 10, []int{55, 55}),
		mk("large", 15, 60, 15, []int{60, 60}),
	}
	var p preset
	found := false
	for _, c := range all {
		if c.Name == *presetFlag {
			p, found = c, true
		}
	}
	if !found {
		fmt.Fprintf(os.Stderr, "unknown preset %q\n", *presetFlag)
		os.Exit(1)
	}

	params, err := ckks.NewParametersFromLiteral(ckks.ParametersLiteral{
		LogN: p.LogN, LogQ: p.LogQ, LogP: p.LogP, LogDefaultScale: 45,
	})
	if err != nil {
		panic(err)
	}
	maxLevel := params.MaxLevel()
	slots := params.MaxSlots()
	x, y := makeInputs(slots)
	wantMul := make([]float64, slots)
	wantRot := make([]float64, slots)
	for i := 0; i < slots; i++ {
		wantMul[i] = x[i] * y[i]
		wantRot[i] = x[(i+1)%slots]
	}

	fmt.Println("library,preset,logN,maxLevel,level,path,rep,bits")

	for rep := 0; rep < *reps; rep++ {
		// 반복마다 키 재생성 — 비밀키·암호화 오차 표본이 산포의 원천이다.
		kgen := ckks.NewKeyGenerator(params)
		sk, pk := kgen.GenKeyPairNew()
		rlk := kgen.GenRelinearizationKeyNew(sk)
		galEl := params.GaloisElementForRotation(1)
		gks := kgen.GenGaloisKeysNew([]uint64{galEl}, sk)
		evk := rlwe.NewMemEvaluationKeySet(rlk, gks...)
		ecd := ckks.NewEncoder(params)
		enc := ckks.NewEncryptor(params, pk)
		dec := ckks.NewDecryptor(params, sk)
		eval := ckks.NewEvaluator(params, evk)

		decode := func(ct *rlwe.Ciphertext) []float64 {
			pt := dec.DecryptNew(ct)
			v := make([]float64, slots)
			if err := ecd.Decode(pt, v); err != nil {
				panic(err)
			}
			return v
		}

		for _, level := range []int{maxLevel, 1} {
			drop := maxLevel - level

			ptX := ckks.NewPlaintext(params, maxLevel)
			ptY := ckks.NewPlaintext(params, maxLevel)
			if err := ecd.Encode(x, ptX); err != nil {
				panic(err)
			}
			if err := ecd.Encode(y, ptY); err != nil {
				panic(err)
			}
			ctX, err := enc.EncryptNew(ptX)
			if err != nil {
				panic(err)
			}
			ctY, err := enc.EncryptNew(ptY)
			if err != nil {
				panic(err)
			}
			// 스케일 불변 레벨 진입 (SEAL mod_switch / OpenFHE LevelReduce 와 동일 의미)
			if drop > 0 {
				eval.DropLevel(ctX, drop)
				eval.DropLevel(ctY, drop)
			}
			ptYlv := ckks.NewPlaintext(params, level)
			if err := ecd.Encode(y, ptYlv); err != nil {
				panic(err)
			}

			report := func(path string, got, want []float64) {
				fmt.Printf("lattigo,%s,%d,%d,%d,%s,%d,%.4f\n",
					p.Name, p.LogN, maxLevel, level, path, rep, precisionBits(got, want))
			}

			report("enc_dec", decode(ctX), x)

			// mul_cp + rescale
			cMulCP, err := eval.MulNew(ctX, ptYlv)
			if err != nil {
				panic(err)
			}
			if err := eval.Rescale(cMulCP, cMulCP); err != nil {
				panic(err)
			}
			report("mul_cp_rs", decode(cMulCP), wantMul)

			// rot1 (rescale 없음)
			cRot, err := eval.RotateNew(ctX, 1)
			if err != nil {
				panic(err)
			}
			report("rot1", decode(cRot), wantRot)

			// relin 단독: Mul(degree2) → Relinearize, rescale 없음
			cMul2, err := eval.MulNew(ctX, ctY)
			if err != nil {
				panic(err)
			}
			if err := eval.Relinearize(cMul2, cMul2); err != nil {
				panic(err)
			}
			report("relin", decode(cMul2), wantMul)

			// mul_cc + relin + rescale
			cRlk, err := eval.MulRelinNew(ctX, ctY)
			if err != nil {
				panic(err)
			}
			if err := eval.Rescale(cRlk, cRlk); err != nil {
				panic(err)
			}
			report("mul_cc_relin_rs", decode(cRlk), wantMul)
		}
	}
}
