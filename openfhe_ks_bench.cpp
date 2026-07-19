// openfhe_ks_bench.cpp — key-switch 단건 비용 벤치 (OpenFHE, logN 16 / boot16 체인)
//
// 목적: 부트스트래핑 격차(Lattigo 1.59배 우위)가 *단일 key-switch 성능* 차이인지,
// 아니면 *다수 연산 조합 최적화*(lazy reduction / hoisting / BSGS) 차이인지 구분한다.
// 단건 비용비 ≈ 부트스트래핑 비용비면 전자, 단건은 비슷한데 부트스트래핑만 벌어지면 후자다.
//
// 체인: boot16 OpenFHE 설정과 동일 (depth 29 → Q=30 limb, P=10, scale 2^59, FLEXIBLEAUTO).
// 측정 op: mul_cc_rlk / rot1 / relin(= mul_cc_rlk - mul_cc). 최상위 레벨만.
// 규칙은 기존 8-op 벤치(openfhe_bench.cpp)와 동일: steady_clock, warmup 후 reps회,
// 연산 1회만 타이밍, μs, 표본표준편차(n-1).
//
// 주의: FLEXIBLEAUTO에서 EvalMult는 자동 rescale을 포함하므로 mul 계열에는 rescale 비용이 섞인다.
// 순수 key-switch 비교에는 EvalRotate(rot1)가 가장 깨끗한 지표다.
#include "openfhe.h"
#include "schemerns/rns-cryptoparameters.h"

#include <chrono>
#include <cmath>
#include <fstream>
#include <functional>
#include <iomanip>
#include <iostream>
#include <string>
#include <vector>

using namespace lbcrypto;

using Clock = std::chrono::steady_clock;

static std::pair<double, double> measure(int reps, int warmup, const std::function<void()>& fn) {
    for (int i = 0; i < warmup; i++) fn();
    std::vector<double> ts(reps);
    for (int i = 0; i < reps; i++) {
        auto t0 = Clock::now();
        fn();
        auto t1 = Clock::now();
        ts[i] = std::chrono::duration<double, std::nano>(t1 - t0).count() / 1000.0;
    }
    double sum = 0;
    for (double x : ts) sum += x;
    double mean = sum / reps;
    double sd = 0.0;
    if (reps > 1) {
        double ss = 0;
        for (double x : ts) {
            double d = x - mean;
            ss += d * d;
        }
        sd = std::sqrt(ss / (reps - 1));
    }
    return {mean, sd};
}

int main(int argc, char** argv) {
    int reps = 30, warmup = 3;
    std::string out = "results_ks_openfhe.csv";
    for (int i = 1; i < argc; i++) {
        std::string a = argv[i];
        if (a == "-reps" && i + 1 < argc)
            reps = std::stoi(argv[++i]);
        else if (a == "-warmup" && i + 1 < argc)
            warmup = std::stoi(argv[++i]);
        else if (a == "-out" && i + 1 < argc)
            out = argv[++i];
    }

    // boot16 OpenFHE 설정과 동일. depth는 boot16의 levels(8) + GetBootstrapDepth({4,3}) = 29.
    const uint32_t logN = 16;
    std::vector<uint32_t> levelBudget = {4, 3};
    uint32_t btpDepth = FHECKKSRNS::GetBootstrapDepth(levelBudget, UNIFORM_TERNARY);
    uint32_t depth    = 8 + btpDepth;

    CCParams<CryptoContextCKKSRNS> params;
    params.SetRingDim(1u << logN);
    params.SetSecurityLevel(HEStd_NotSet);
    params.SetSecretKeyDist(UNIFORM_TERNARY);
    params.SetScalingModSize(59);
    params.SetFirstModSize(60);
    params.SetScalingTechnique(FLEXIBLEAUTO);
    params.SetMultiplicativeDepth(depth);

    CryptoContext<DCRTPoly> cc = GenCryptoContext(params);
    cc->Enable(PKE);
    cc->Enable(KEYSWITCH);
    cc->Enable(LEVELEDSHE);
    cc->Enable(ADVANCEDSHE);

    const auto cp = std::dynamic_pointer_cast<CryptoParametersRNS>(cc->GetCryptoParameters());
    const auto& towersQ = cc->GetCryptoParameters()->GetElementParams()->GetParams();
    const auto paramsP  = cp ? cp->GetParamsP() : nullptr;
    int limbsQ = static_cast<int>(towersQ.size());
    int limbsP = paramsP ? static_cast<int>(paramsP->GetParams().size()) : 0;

    double sumQ = 0, sumP = 0;
    for (const auto& t : towersQ) sumQ += std::log2(t->GetModulus().ConvertToDouble());
    if (paramsP)
        for (const auto& t : paramsP->GetParams())
            sumP += std::log2(t->GetModulus().ConvertToDouble());

    int maxLevel = static_cast<int>(depth);
    std::cerr << "[boot16-ks] logN=" << logN << " ringDim=" << cc->GetRingDimension()
              << " depth=" << depth << " (8 + GetBootstrapDepth=" << btpDepth << ")\n"
              << "  limbs Q=" << limbsQ << " P=" << limbsP << " QP=" << (limbsQ + limbsP)
              << std::fixed << std::setprecision(2) << "  logQP=" << (sumQ + sumP)
              << "  dnum=" << (cp ? cp->GetNumPartQ() : 0) << "\n";

    auto keys = cc->KeyGen();
    cc->EvalMultKeyGen(keys.secretKey);
    cc->EvalRotateKeyGen(keys.secretKey, {1});

    size_t slots = cc->GetRingDimension() / 2;
    std::vector<double> vec(slots, 0.5);

    // 최상위 레벨: fresh ciphertext (GetLevel()==0 → 리포트 level = maxLevel).
    Plaintext pt = cc->MakeCKKSPackedPlaintext(vec, 1, 0, nullptr, slots);
    auto ctA = cc->Encrypt(keys.publicKey, pt);
    auto ctB = cc->Encrypt(keys.publicKey, pt);

    auto [m_mulcc, s_mulcc] = measure(reps, warmup, [&]() { cc->EvalMultNoRelin(ctA, ctB); });
    auto [m_rlk, s_rlk]     = measure(reps, warmup, [&]() { cc->EvalMult(ctA, ctB); });
    auto [m_rot, s_rot]     = measure(reps, warmup, [&]() { cc->EvalRotate(ctA, 1); });

    // relin = mul_cc_rlk - mul_cc (음수면 0 clamp, std=0). 기존 벤치와 동일 규칙.
    double relin = m_rlk - m_mulcc;
    if (relin < 0) relin = 0;

    std::cerr << std::setprecision(1) << "  mul_cc      " << m_mulcc << " us (sd " << s_mulcc
              << ")\n  mul_cc_rlk  " << m_rlk << " us (sd " << s_rlk << ")\n  rot1        "
              << m_rot << " us (sd " << s_rot << ")\n  relin       " << relin << " us (파생값)\n";

    std::ofstream csv(out);
    csv << "library,preset,logN,maxLevel,level,op,mean_us,std_us,reps,limbs_q,limbs_p\n";
    csv << std::fixed;
    auto row = [&](const std::string& op, double m, double s) {
        csv << "openfhe,boot16-ks," << logN << "," << maxLevel << "," << maxLevel << "," << op
            << "," << std::setprecision(3) << m << "," << s << "," << reps << "," << limbsQ << ","
            << limbsP << "\n";
    };
    row("mul_cc", m_mulcc, s_mulcc);
    row("mul_cc_rlk", m_rlk, s_rlk);
    row("relin", relin, 0.0);
    row("rot1", m_rot, s_rot);
    csv.close();
    std::cerr << "wrote " << out << "\n";
    return 0;
}
