// openfhe_boot_bench.cpp — CKKS 부트스트래핑 latency 벤치마크 (OpenFHE 1.5.x)
// 기존 8-op 벤치(openfhe_bench.cpp)와 분리된 별도 실행파일:
// 부트스트래핑은 곱셈깊이 ~15를 소모하고 1회가 초 단위라 레벨 스윕/reps=30이 성립하지 않는다.
//
// 프리셋 boot16은 Lattigo 공식 검증 파라미터 N16QP1788H32768H32를 기준선으로 삼고
// 여기에 OpenFHE를 맞춘 것이다(logN 16, numSlots 32768, 잔여레벨 9, levelBudget {4,3}, scale 2^45).
// 비밀키 분포는 UNIFORM_TERNARY(조밀) ↔ Lattigo ring.Ternary{H:32768}로 정합시킨다.
//
// 파라미터는 벤치마크용이며 검증된 보안 파라미터가 아님(HEStd_NotSet으로 링차원 강제).
#include "openfhe.h"
#include "schemerns/rns-cryptoparameters.h"  // CryptoParametersRNS: GetParamsP/GetNumPartQ 등

#include <chrono>
#include <cmath>
#include <cstdio>
#include <fstream>
#include <functional>
#include <iomanip>
#include <iostream>
#include <limits>
#include <omp.h>
#include <random>
#include <string>
#include <vector>

using namespace lbcrypto;

// peakRSSMB: /proc/self/status의 VmHWM(프로세스 생애 최대 RSS)을 MB로 반환.
static double peakRSSMB() {
    std::ifstream st("/proc/self/status");
    std::string key;
    while (st >> key) {
        if (key == "VmHWM:") {
            double kb = 0;
            st >> kb;
            return kb / 1024.0;
        }
        st.ignore(std::numeric_limits<std::streamsize>::max(), '\n');
    }
    return 0.0;
}

// currentRSSMB: 현재 RSS(VmRSS). 키 생성 전후 차이를 키 크기 "근사"로 쓴다.
static double currentRSSMB() {
    std::ifstream st("/proc/self/status");
    std::string key;
    while (st >> key) {
        if (key == "VmRSS:") {
            double kb = 0;
            st >> kb;
            return kb / 1024.0;
        }
        st.ignore(std::numeric_limits<std::streamsize>::max(), '\n');
    }
    return 0.0;
}

// dumpChain: GenCryptoContext가 실제로 만든 모듈러스 체인을 stderr로 출력.
// Lattigo와 Q 체인을 강제로 일치시키지 않는다 (Lattigo는 residual/bootstrapping 2겹,
// OpenFHE는 단일 체인 합산 — 맞추려 들면 한쪽이 비최적화되고 logQP가 움직여 보안 수준이 바뀐다).
// 대신 각주용 수치를 남긴다.
// limb(tower) 개수를 담아 호출부로 돌려준다. NTT 호출 횟수가 limb 수에 비례하므로
// logQP(보안 지표)와 달리 limb 개수는 *작업량* 지표다.
struct LimbCount {
    int q = 0;
    int p = 0;
};

static LimbCount dumpChain(const CryptoContext<DCRTPoly>& cc, uint32_t depth) {
    const auto cp = std::dynamic_pointer_cast<CryptoParametersRNS>(cc->GetCryptoParameters());
    LimbCount lc;
    if (!cp) {
        std::cerr << "[boot16] CryptoParametersRNS 캐스팅 실패\n";
        return lc;
    }
    auto lg = [](const NativeInteger& q) { return std::log2(q.ConvertToDouble()); };

    const auto& towersQ = cc->GetCryptoParameters()->GetElementParams()->GetParams();
    std::cerr << "\n[boot16] === OpenFHE chain dump : towers(Q)=" << towersQ.size() << " ===\n";
    std::cerr << "  idx   msb     log2(q)                     q\n";
    double sumQ = 0;
    for (size_t i = 0; i < towersQ.size(); i++) {
        const NativeInteger q = towersQ[i]->GetModulus();
        double l = lg(q);
        sumQ += l;
        std::cerr << "  " << std::setw(3) << i << "  " << std::setw(4) << q.GetMSB() << "  "
                  << std::setw(10) << std::fixed << std::setprecision(5) << l << "  "
                  << std::setw(20) << q.ToString() << "\n";
    }

    double sumP = 0;
    const auto paramsP = cp->GetParamsP();
    if (paramsP) {
        const auto& towersP = paramsP->GetParams();
        std::cerr << "  --- special primes (P) : count=" << towersP.size() << " ---\n";
        for (size_t i = 0; i < towersP.size(); i++) {
            const NativeInteger pi = towersP[i]->GetModulus();
            double l = lg(pi);
            sumP += l;
            std::cerr << "  " << std::setw(3) << i << "  " << std::setw(4) << pi.GetMSB() << "  "
                      << std::setw(10) << std::fixed << std::setprecision(5) << l << "  "
                      << std::setw(20) << pi.ToString() << "\n";
        }
    } else {
        std::cerr << "  --- special primes (P) : 없음 (non-HYBRID key switching) ---\n";
    }

    lc.q = static_cast<int>(towersQ.size());
    lc.p = paramsP ? static_cast<int>(paramsP->GetParams().size()) : 0;

    std::cerr << "  --- summary ---\n"
              << "  ksTech=" << (cp->GetKeySwitchTechnique() == HYBRID ? "HYBRID" : "BV")
              << "  dnum(numPartQ)=" << cp->GetNumPartQ()
              << "  towersPerPart=" << cp->GetNumPerPartQ()
              << "  auxBits=" << cp->GetAuxBits() << "\n"
              << std::setprecision(2) << "  log2 Q=" << sumQ << "  log2 P=" << sumP
              << "  log2 QP=" << (sumQ + sumP) << "   <- 보안 지표\n"
              << "  limbs  Q=" << lc.q << "  P=" << lc.p << "  QP=" << (lc.q + lc.p)
              << "   <- 작업량 지표 (NTT 호출 횟수가 limb 수에 비례)\n"
              << "  multiplicativeDepth=" << depth << "\n\n";
    return lc;
}

// measure 통계: 평균 + 표본표준편차(n-1), μs.
static std::pair<double, double> meanStd(const std::vector<double>& ts) {
    double sum = 0;
    for (double x : ts) sum += x;
    double mean = sum / ts.size();
    double sd = 0.0;
    if (ts.size() > 1) {
        double ss = 0;
        for (double x : ts) {
            double d = x - mean;
            ss += d * d;
        }
        sd = std::sqrt(ss / (ts.size() - 1));
    }
    return {mean, sd};
}

// steady_clock 기준 경과 μs. high_resolution_clock은 libstdc++에서 system_clock 별칭이라
// 시계 재동기화 시 역행해 음수 latency가 나올 수 있다 (기존 벤치와 동일 규칙).
using Clock = std::chrono::steady_clock;
static double elapsedUS(Clock::time_point t0, Clock::time_point t1) {
    return std::chrono::duration<double, std::nano>(t1 - t0).count() / 1000.0;
}

int main(int argc, char** argv) {
    int reps = 10, warmup = 1;
    // levels=8: Lattigo와 복원 레벨을 일치시키기 위한 값(잔여 레벨 자체가 아님).
    // levels=9면 out_level=10이 되어 Lattigo(1→9)보다 1레벨 더 복원한다. bootstrap 비용은
    // 복원 레벨에 비례하지 않으므로 us_per_level 정규화가 OpenFHE 쪽에 유리하게 편향된다.
    // levels=8 → in_level=1, out_level=9 로 Lattigo와 정확히 일치(gain 8) → 절대값 비교 가능.
    // 부수 효과로 logQP 격차도 154비트(1942 vs 1788) → 49비트(1837 vs 1788)로 줄어든다.
    int levels = 8;
    // scaleMod=59 / firstMod=60: OpenFHE 공식 advanced-ckks-bootstrapping.cpp의
    // 64비트 빌드(NATIVEINT != 128) 처방값을 그대로 따른다.
    //   #else  // All modes are supported for 64-bit CKKS bootstrapping.
    //       ScalingTechnique rescaleTech = FLEXIBLEAUTO;
    //       usint dcrtBits = 59;
    //       usint firstMod = 60;
    // (본 빌드의 NATIVEINT는 config_core.h:20에서 64로 확인함 → 위 분기가 적용된다.)
    // 예제 주석: "to obtain a good precision and performance tradeoff.
    //             We recommend keeping the parameters below unless you are an FHE expert."
    //
    // BOOTSTRAP_TASK.md 사양은 scale 2^45였으나, 45비트 스케일에서는 이 파라미터 영역의
    // 부트스트래핑이 성립하지 않는다. 이등분 격리로 확인한 사실(다른 조건 고정, scaleMod만 변경):
    //   scaleMod 59 → 평균 정밀도 12.35비트 (정상)
    //   scaleMod 45 → firstMod 60이면 EvalBootstrap 예외(deg=15 > correctionFactor=8),
    //                 firstMod 52면 예외는 피하지만 정밀도 -1.61비트 = 쓰레기 값(조용한 실패)
    // ringDim/levelBudget/levelsAfterBoot/full packing/HEStd_NotSet은 모두 무관함을 실측 확인.
    //
    // 결과적으로 Lattigo(scale 2^45)와 스케일이 비대칭이다. 이는 함정 5(Q 체인 정합 시도 금지)와
    // 같은 판단이다 — 한쪽을 상대에 억지로 맞추면 자기 최적점을 벗어나 비최적화된다.
    // 단 스케일 비대칭은 정밀도 격차로 직결되므로(OpenFHE 12.35비트 vs Lattigo 29.75비트),
    // 지연시간 비교 시 반드시 정밀도를 함께 명시할 것. precision_bits 행을 CSV에 남기는 이유다.
    int firstMod = 60, scaleMod = 59;
    // FLEXIBLEAUTO: 공식 advanced-ckks-bootstrapping.cpp 64비트 처방의 rescaleTech.
    // 59/60과 한 묶음이므로 스케일만 떼어오지 않고 함께 채택한다.
    // 또한 Lattigo 부트스트래핑은 스케일을 내부에서 자동 관리하므로 FLEXIBLEAUTO가 대응 모드다
    // (FIXEDMANUAL은 Lattigo 쪽에 짝이 없다).
    // 실측 대조: FIXEDMANUAL 10.08비트/27.53s vs FLEXIBLEAUTO 12.34비트/37.66s (reps=1).
    std::string scalingSel = "FLEXIBLEAUTO";
    std::string out = "results_openfhe_boot.csv";
    // -skd: 비밀키 분포. 기본값 uniform(= 확정 설계 결정 1의 조밀 정합)을 바꾸지 말 것.
    // sparse는 *민감도 검증 전용*이다 — Lattigo가 조밀키(H=32768)를 쓰는 상태에서
    // OpenFHE만 희소키로 돌리면 비밀키 분포가 비정합이 되어 본 비교로 쓸 수 없다.
    std::string skdSel = "uniform";

    for (int i = 1; i < argc; i++) {
        std::string a = argv[i];
        if (a == "-reps" && i + 1 < argc)
            reps = std::stoi(argv[++i]);
        else if (a == "-warmup" && i + 1 < argc)
            warmup = std::stoi(argv[++i]);
        else if (a == "-out" && i + 1 < argc)
            out = argv[++i];
        else if (a == "-levels" && i + 1 < argc)
            levels = std::stoi(argv[++i]);
        else if (a == "-scaling" && i + 1 < argc)
            scalingSel = argv[++i];
        else if (a == "-firstmod" && i + 1 < argc)
            firstMod = std::stoi(argv[++i]);
        else if (a == "-scalemod" && i + 1 < argc)
            scaleMod = std::stoi(argv[++i]);
        else if (a == "-skd" && i + 1 < argc)
            skdSel = argv[++i];  // uniform | sparse (sparse는 민감도 검증 전용)
    }

    // -scaling: 기존 8-op 벤치는 rescale 명시 측정을 위해 FIXEDMANUAL을 쓴다.
    // 부트스트래핑은 64비트 CKKS에서 전 모드를 지원하지만 공식 예제 기본은 FLEXIBLEAUTO이고
    // 스케일 관리 실패가 가장 흔한 초기 에러이므로 런타임 전환 가능하게 둔다.
    ScalingTechnique scaling;
    if (scalingSel == "FIXEDMANUAL")
        scaling = FIXEDMANUAL;
    else if (scalingSel == "FIXEDAUTO")
        scaling = FIXEDAUTO;
    else if (scalingSel == "FLEXIBLEAUTO")
        scaling = FLEXIBLEAUTO;
    else if (scalingSel == "FLEXIBLEAUTOEXT")
        scaling = FLEXIBLEAUTOEXT;
    else {
        std::cerr << "알 수 없는 -scaling 값: " << scalingSel << "\n";
        return 1;
    }

    const uint32_t logN = 16;
    const uint32_t ringDimReq = 1u << logN;
    const uint32_t numSlots = ringDimReq / 2;  // 32768
    std::vector<uint32_t> levelBudget = {4, 3};
    std::vector<uint32_t> bsgsDim = {0, 0};  // 자동

    // 깊이 하드코딩 금지: GetBootstrapDepth 반환값은 OpenFHE 버전에 따라 다르다.
    // 반드시 런타임 호출하고 stderr에 찍는다.
    // 비밀키 분포. GetBootstrapDepth도 같은 분포로 호출해야 깊이가 맞는다.
    const bool sparse = (skdSel == "sparse");
    SecretKeyDist skd = sparse ? SPARSE_TERNARY : UNIFORM_TERNARY;
    if (sparse) {
        std::cerr << "\n*** 경고: SPARSE_TERNARY = 비밀키 분포 비정합 (robustness check 전용) ***\n"
                  << "*** Lattigo는 조밀키 H=32768를 쓴다. 본 비교 결과로 인용하지 말 것. ***\n\n";
    }
    uint32_t btpDepth = FHECKKSRNS::GetBootstrapDepth(levelBudget, skd);
    uint32_t depth = static_cast<uint32_t>(levels) + btpDepth;

    std::cerr << "[boot16] GetBootstrapDepth({4,3}, "
              << (sparse ? "SPARSE_TERNARY" : "UNIFORM_TERNARY") << ") = " << btpDepth << "\n"
              << "[boot16] multiplicativeDepth = " << levels << " + " << btpDepth << " = " << depth
              << "\n"
              << "[boot16] scaling = " << scalingSel << "  numSlots = " << numSlots << "\n"
              << "[boot16] firstMod = " << firstMod << "  scaleMod = " << scaleMod
              << "  (deg = firstMod - scaleMod = " << (firstMod - scaleMod)
              << ", 자동 correctionFactor: FIXEDMANUAL 7 / FLEXIBLEAUTO 8 @ logN16·32768슬롯"
              << " — deg가 이 값을 넘으면 EvalBootstrap이 throw)\n";

    CCParams<CryptoContextCKKSRNS> params;
    params.SetRingDim(ringDimReq);
    params.SetSecurityLevel(HEStd_NotSet);  // 링차원 강제 (기존 실험과 동일한 한계)
    params.SetSecretKeyDist(skd);  // 기본 UNIFORM_TERNARY = Lattigo ring.Ternary{H:32768}과 정합
    params.SetScalingModSize(scaleMod);
    params.SetFirstModSize(firstMod);
    params.SetScalingTechnique(scaling);
    params.SetMultiplicativeDepth(depth);

    CryptoContext<DCRTPoly> cc = GenCryptoContext(params);
    cc->Enable(PKE);
    cc->Enable(KEYSWITCH);
    cc->Enable(LEVELEDSHE);
    cc->Enable(ADVANCEDSHE);
    cc->Enable(FHE);  // 부트스트래핑에 필수

    uint32_t ringDim = cc->GetRingDimension();
    LimbCount limbs = dumpChain(cc, depth);

    // --- btp_setup: 사전계산 (OpenFHE만) ---
    auto t0 = Clock::now();
    cc->EvalBootstrapSetup(levelBudget, bsgsDim, numSlots);
    double setupUS = elapsedUS(t0, Clock::now());
    std::cerr << "[boot16] EvalBootstrapSetup = " << setupUS / 1e6 << " s\n";

    // --- btp_keygen: 키 생성 ---
    // 키 크기: OpenFHE에는 Lattigo의 EvaluationKeys::BinarySize()에 대응하는 API가 없다.
    // RSS 증가분을 "근사"로 기록한다 — 정확한 직렬화 크기가 아님에 주의.
    double rssBefore = currentRSSMB();
    t0 = Clock::now();
    auto keys = cc->KeyGen();
    cc->EvalMultKeyGen(keys.secretKey);
    cc->EvalBootstrapKeyGen(keys.secretKey, numSlots);
    double keygenUS = elapsedUS(t0, Clock::now());
    double rssAfter = currentRSSMB();
    double keyBytesApprox = (rssAfter - rssBefore) * 1024.0 * 1024.0;
    if (keyBytesApprox < 0) keyBytesApprox = 0;

    std::cerr << "[boot16] keygen = " << keygenUS / 1e6 << " s\n"
              << "[boot16] key_bytes = " << static_cast<long long>(keyBytesApprox) << " ("
              << (rssAfter - rssBefore) << " MB) — RSS 증가분 기반 *근사*, "
              << "OpenFHE에는 정확한 키 크기 API가 없음\n";

    // --- 입력 준비 ---
    // 모든 슬롯 0.5 (기존 8-op 벤치와 동일).
    // 공식 예제를 따라 level = depth-1 로 인코딩해 마지막 프라임 1개를 예약한다.
    // Lattigo는 level 0(MinimumInputLevel)에서 입력하므로 입력 레벨이 1 다를 수 있다 —
    // 억지로 맞추지 않고 실측 in_level/out_level을 CSV에 그대로 기록해 us_per_level로 정규화한다.
    std::vector<double> vec(numSlots, 0.5);

    auto newCT = [&]() {
        Plaintext pt = cc->MakeCKKSPackedPlaintext(vec, 1, depth - 1, nullptr, numSlots);
        return cc->Encrypt(keys.publicKey, pt);
    };

    // --- 부트스트래핑 측정 ---
    // 타이밍 범위는 EvalBootstrap 호출 1회뿐. 입력 ct 생성은 밖에서.
    for (int i = 0; i < warmup; i++) {
        auto ct = newCT();
        cc->EvalBootstrap(ct);
    }

    // 레벨 방향: OpenFHE GetLevel()은 소모량(0→max), Lattigo는 잔량(max→0).
    // CSV에는 Lattigo 기준 잔량으로 통일 — level = maxLevel - GetLevel().
    int maxLevel = static_cast<int>(depth);
    int inLevel = 0, outLevel = 0;

    std::vector<double> ts(reps);
    for (int i = 0; i < reps; i++) {
        auto ct = newCT();
        inLevel = maxLevel - static_cast<int>(ct->GetLevel());
        auto s = Clock::now();
        auto ctOut = cc->EvalBootstrap(ct);
        ts[i] = elapsedUS(s, Clock::now());
        outLevel = maxLevel - static_cast<int>(ctOut->GetLevel());
        std::cerr << "  rep " << (i + 1) << "/" << reps << "  " << ts[i] << " us ("
                  << ts[i] / 1e6 << " s)  in_level=" << inLevel << " out_level=" << outLevel
                  << "\n";
    }

    auto [mean, sd] = meanStd(ts);

    // --- 정밀도 검증 (타이밍 구간 밖, 1회) ---
    // 알려진 값 암호화 → 부트스트래핑 → 복호화 → 원본과 슬롯별 비교.
    // 타이밍용 입력은 전 슬롯 0.5로 고정돼 정밀도 측정에 부적합하다(단일 값이라 슬롯별
    // 오차 분포를 볼 수 없고, 상수 벡터는 DFT 단계에서 비대표적으로 유리하다).
    // → 정밀도 측정에만 [-1,1) 균등 난수를 쓴다. 시드 고정으로 실행 간 재현 가능.
    // Lattigo 쪽도 동일한 시드(42)·동일 분포를 쓰지만 RNG 구현이 달라 값 자체는 다르다.
    std::mt19937_64 rng(42);
    std::uniform_real_distribution<double> dist(-1.0, 1.0);
    std::vector<double> want(numSlots);
    for (auto& v : want) v = dist(rng);

    Plaintext ptPrec = cc->MakeCKKSPackedPlaintext(want, 1, depth - 1, nullptr, numSlots);
    auto ctPrec    = cc->Encrypt(keys.publicKey, ptPrec);
    auto ctPrecOut = cc->EvalBootstrap(ctPrec);

    // 기준선: 부트스트래핑 *없이* 암호화→복호화만. 이 값이 나쁘면 검증 코드 문제,
    // 좋은데 부트스트래핑 후만 나쁘면 부트스트래핑/스케일 관리 문제로 분리된다.
    Plaintext ptBase;
    cc->Decrypt(keys.secretKey, ctPrec, &ptBase);
    ptBase->SetLength(numSlots);
    const std::vector<double> base = ptBase->GetRealPackedValue();
    double baseMaxErr = 0.0;
    for (uint32_t i = 0; i < numSlots; i++)
        baseMaxErr = std::max(baseMaxErr, std::fabs(base[i] - want[i]));
    std::cerr << std::setprecision(2)
              << "  [기준선] 암호화→복호화만: log2(max_err)=" << std::log2(baseMaxErr)
              << " (= " << -std::log2(baseMaxErr) << "비트)\n";

    Plaintext ptDec;
    cc->Decrypt(keys.secretKey, ctPrecOut, &ptDec);
    ptDec->SetLength(numSlots);
    const std::vector<double> have = ptDec->GetRealPackedValue();

    // 진단: 앞 5개 슬롯의 want/have 및 비율. 비율이 일정하면 스케일 관리 문제,
    // 무작위면 더 근본적인 문제.
    std::cerr << "  [진단] 슬롯  want        have        have/want\n";
    for (int i = 0; i < 5; i++)
        std::cerr << "         " << i << "  " << std::setw(11) << std::setprecision(6) << want[i]
                  << "  " << std::setw(11) << have[i] << "  " << std::setw(11)
                  << (want[i] != 0 ? have[i] / want[i] : 0.0) << "\n";

    // 슬롯별 절대오차의 최대/평균 → log2. CKKS 관례상 정밀도 비트 = -log2(오차).
    double maxErr = 0.0, sumErr = 0.0;
    for (uint32_t i = 0; i < numSlots; i++) {
        double e = std::fabs(have[i] - want[i]);
        if (e > maxErr) maxErr = e;
        sumErr += e;
    }
    double meanErr     = sumErr / numSlots;
    double log2Max     = std::log2(maxErr);
    double log2Mean    = std::log2(meanErr);
    double precMeanBits = -log2Mean;
    double precMinBits  = -log2Max;

    std::cerr << std::setprecision(2) << "  정밀도: log2(max_err)=" << log2Max
              << " log2(mean_err)=" << log2Mean << " → 평균 " << precMeanBits << "비트 / 최악 "
              << precMinBits << "비트\n";

    int levelGain = outLevel - inLevel;
    if (levelGain <= 0) {
        std::cerr << "경고: levelGain=" << levelGain << " (<=0) — us_per_level 계산 불가\n";
        levelGain = 1;
    }
    double perLevelMean = mean / levelGain;
    double perLevelSD = sd / levelGain;

    double peak = peakRSSMB();

    // thread_mechanism: 라벨이 아니라 런타임 실측값(omp_get_max_threads)을 기록한다.
    // OpenFHE는 OpenMP를 쓰므로 OMP_NUM_THREADS가 코어 제한 수단이다
    // (Go/Lattigo에는 무효 — 그쪽은 GOMAXPROCS를 쓴다).
    std::string threadMech = "OMP_NUM_THREADS=" + std::to_string(omp_get_max_threads());
    std::cerr << "  thread_mechanism=" << threadMech << "\n";

    // --- CSV 기록 ---
    std::ofstream csv(out);
    if (sparse) {
        csv << "# 비밀키 분포 비정합 - robustness check 전용. 본 비교 결과 아님.\n"
            << "# OpenFHE=SPARSE_TERNARY, Lattigo=dense H=32768. 확정 설계 결정 1 위반 상태.\n";
    }
    csv << "library,preset,logN,numSlots,in_level,out_level,op,mean_us,std_us,reps,key_bytes,"
           "peak_rss_mb,limbs_q,limbs_p,thread_mechanism\n";
    csv << std::fixed;
    auto row = [&](const std::string& op, double m, double s, int r) {
        csv << "openfhe," << (sparse ? "boot16-sparse-rc" : "boot16") << "," << logN << "," << numSlots << "," << inLevel << "," << outLevel
            << "," << op << "," << std::setprecision(3) << m << "," << s << "," << r << ","
            << static_cast<long long>(keyBytesApprox) << "," << std::setprecision(1) << peak
            << "," << limbs.q << "," << limbs.p << "," << threadMech << "\n";
    };
    row("bootstrap", mean, sd, reps);
    row("btp_setup", setupUS, 0.0, 1);
    row("btp_keygen", keygenUS, 0.0, 1);
    row("us_per_level", perLevelMean, perLevelSD, reps);
    // precision_bits 행은 μs가 아니라 *비트*를 담는다 (스키마 고정이라 컬럼 재사용):
    //   mean_us = 평균 정밀도 비트 = -log2(mean|err|)
    //   std_us  = 최악 슬롯 정밀도 비트 = -log2(max|err|)
    row("precision_bits", precMeanBits, precMinBits, 1);
    csv.close();

    std::cerr << "\n[boot16] ringDim=" << ringDim << "  bootstrap mean=" << mean << " us ("
              << mean / 1e6 << " s)  sd=" << sd << "  us_per_level=" << perLevelMean
              << "  peakRSS=" << peak << " MB\n"
              << "wrote " << out << "\n";
    return 0;
}
