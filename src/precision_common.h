// precision_common.h — 세 라이브러리 정밀도 프로그램이 공유하는 절차 정의.
//
// 왜 공용 파일인가: 절차가 조금이라도 다르면 라이브러리 간 비교가 성립하지 않는다.
// 특히 입력 벡터가 다르면 -log2(mean|err|)를 나란히 놓을 수 없다.
//
// ⚠️ std::mt19937_64 + uniform_real_distribution은 Go에서 비트 단위로 재현할 수 없다.
// 그래서 xorshift64* 로 통일했다 — C++/Go에서 동일한 uint64 수열이 나온다.
// lattigo_precision.go 의 next()/nextVal() 이 아래와 정확히 같아야 한다.
#pragma once
#include <cmath>
#include <cstdint>
#include <vector>

namespace precision_common {

// xorshift64* — 언어 간 비트 단위 재현 가능
struct Rng {
    uint64_t s;
    explicit Rng(uint64_t seed = 0x2026072500000001ULL) : s(seed) {}
    uint64_t next()
    {
        s ^= s >> 12;
        s ^= s << 25;
        s ^= s >> 27;
        return s * 2685821657736338717ULL;
    }
    // [-1, 1) 균등. 상위 53비트만 써서 double 정밀도 안에서 정확히 표현된다.
    double val() { return (double)(next() >> 11) / 9007199254740992.0 * 2.0 - 1.0; }
};

// 입력 벡터 생성: x[0], y[0], x[1], y[1], ... 순서로 뽑는다(순서도 규약의 일부).
inline void make_inputs(size_t slots, std::vector<double> &x, std::vector<double> &y)
{
    Rng rng;
    x.resize(slots);
    y.resize(slots);
    for (size_t i = 0; i < slots; i++) {
        x[i] = rng.val();
        y[i] = rng.val();
    }
}

// 오차 정의: 전 슬롯 평균 절대오차의 -log2. 세 라이브러리 동일.
inline double precision_bits(const std::vector<double> &got, const std::vector<double> &want)
{
    double s = 0;
    size_t n = want.size();
    for (size_t i = 0; i < n; i++) s += std::fabs(got[i] - want[i]);
    double mean_err = s / (double)n;
    if (mean_err <= 0) return 999.0;
    return -std::log2(mean_err);
}

}  // namespace precision_common
