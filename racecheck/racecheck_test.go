// racecheck_test.go — Lattigo BenchmarkConcurrentBootstrap의 동시성 패턴에 데이터 경합이
// 있는지 -race로 검사한다.
//
// 왜 원본을 그대로 안 돌리는가:
// 원본(circuits/ckks/bootstrapping/evaluator_benchmarks_test.go:14)은
// DefaultParametersDense[0] = N16QP1767H32768H32(logN 16, residual 14 limb)를 쓴다.
// 키 생성만 분 단위이고 race 계측 오버헤드가 겹쳐 이 환경의 세션 수명 안에 끝나지 않았다
// (2회 시도 모두 완료 전 강제 종료됨).
//
// 그래서 *코드 패턴은 원본과 동일하게 두고 프리셋만 작은 것으로* 바꿔 검사한다.
// 경합 여부는 파라미터 크기가 아니라 코드 구조(공유 Evaluator + 공유 암호문)에서 결정되므로
// 작은 프리셋에서도 동일하게 드러난다.
//
// 원본과 동일하게 유지한 것:
//   - eval을 RunParallel *밖에서* 1개만 생성해 모든 고루틴이 공유
//   - ct를 RunParallel *밖에서* 1개만 생성해 모든 고루틴이 공유
//   - 고루틴 안에서 eval.Bootstrap(ct) 호출
// 바꾼 것: 프리셋 인덱스만 (환경변수 RACECHECK_PRESET, 기본 3 = N15QP880H16384H32).
//
// 실행: cd he-bench && GOMAXPROCS=2 go test -race -run '^$' -bench . -benchtime 2x ./racecheck/
package racecheck

import (
	"fmt"
	"os"
	"runtime"
	"strconv"
	"testing"

	"github.com/tuneinsight/lattigo/v6/circuits/ckks/bootstrapping"
	"github.com/tuneinsight/lattigo/v6/core/rlwe"
	"github.com/tuneinsight/lattigo/v6/schemes/ckks"
)

func BenchmarkSharedEvaluatorRace(b *testing.B) {
	idx := 3 // 기본: N15QP880H16384H32 (logN 15) — 원본은 0 (logN 16)
	if v := os.Getenv("RACECHECK_PRESET"); v != "" {
		n, err := strconv.Atoi(v)
		if err != nil {
			b.Fatalf("RACECHECK_PRESET 파싱 실패: %v", err)
		}
		idx = n
	}
	if idx < 0 || idx >= len(bootstrapping.DefaultParametersDense) {
		b.Fatalf("프리셋 인덱스 범위 밖: %d (0..%d)",
			idx, len(bootstrapping.DefaultParametersDense)-1)
	}
	paramSet := bootstrapping.DefaultParametersDense[idx]

	params, err := ckks.NewParametersFromLiteral(paramSet.SchemeParams)
	if err != nil {
		b.Fatal(err)
	}
	btpParams, err := bootstrapping.NewParametersFromLiteral(params, paramSet.BootstrappingParams)
	if err != nil {
		b.Fatal(err)
	}

	fmt.Fprintf(os.Stderr,
		"[racecheck] preset[%d]  logN=%d  residual limbs Q=%d P=%d  logQP=%.0f  GOMAXPROCS=%d\n",
		idx, params.LogN(), params.QCount(), params.PCount(), params.LogQP(),
		runtime.GOMAXPROCS(0))

	kgen := rlwe.NewKeyGenerator(params)
	sk := kgen.GenSecretKeyNew()
	evk, _, err := btpParams.GenEvaluationKeys(sk)
	if err != nil {
		b.Fatal(err)
	}

	b.Run("SharedEvalSharedCt", func(b *testing.B) {
		// --- 원본과 동일한 구조: eval 1개, ct 1개를 모든 고루틴이 공유 ---
		eval, err := bootstrapping.NewEvaluator(btpParams, evk)
		if err != nil {
			b.Fatal(err)
		}
		ct1 := ckks.NewCiphertext(params, 1, 0)
		b.ResetTimer()
		b.RunParallel(func(pb *testing.PB) {
			for pb.Next() {
				if _, err := eval.Bootstrap(ct1); err != nil {
					// 경합이 나면 여기서 에러가 날 수도, 안 날 수도 있다.
					// -race 검출기가 판정의 주체이지 이 에러가 아니다.
					b.Log("Bootstrap err:", err)
				}
			}
		})
	})
}
