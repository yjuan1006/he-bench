// openfhe_bench.cpp — CKKS 연산 latency 벤치마크 (OpenFHE 1.x)
// Lattigo 구현과 동일한 프리셋·op·CSV 스키마로 암호문 1개 기준 latency 측정.
// 규칙: warmup 후 reps회, 연산 1회만 타이밍, ns→μs, 표본표준편차(n-1).
// OpenFHE EvalAdd/EvalMult는 새 Ciphertext 반환(functional) → 매 호출 할당이 정상 비용이라 타이밍에 포함.
// 파라미터는 벤치마크용 근사치이며 검증된 보안 파라미터가 아님(HEStd_NotSet으로 링차원 강제).
#include "openfhe.h"
#include "schemerns/rns-cryptoparameters.h"  // CryptoParametersRNS: GetParamsP/GetNumPartQ 등

#include <chrono>
#include <cmath>
#include <fstream>
#include <functional>
#include <iomanip>
#include <iostream>
#include <string>
#include <utility>
#include <vector>

using namespace lbcrypto;

struct Preset {
    std::string name;
    int logN;
    int depth;     // = maxLevel (SetMultiplicativeDepth)
    int firstMod;  // Lattigo LogQ[0]와 정렬
    int scaleMod;  // Lattigo scale=45와 정렬
};

// small/medium/large = logN 13/14/15, maxLevel 5/10/15.
static std::vector<Preset> kPresets = {
    {"small", 13, 5, 50, 45},
    {"medium", 14, 10, 55, 45},
    {"large", 15, 15, 60, 45},
};

// Lattigo lattigo_bench.go가 명시한 체인 (비교용 기대값).
// LogQ[0]=firstMod, 나머지는 scale=45 × depth. LogP는 special prime.
struct LattigoChain {
    std::vector<int> logQ;
    std::vector<int> logP;
};
static LattigoChain lattigoChain(const Preset& p) {
    LattigoChain c;
    c.logQ.push_back(p.firstMod);
    for (int i = 0; i < p.depth; i++) c.logQ.push_back(p.scaleMod);
    if (p.name == "small")
        c.logP = {55};
    else if (p.name == "medium")
        c.logP = {55, 55};
    else
        c.logP = {60, 60};
    return c;
}

// dumpChain: GenCryptoContext가 실제로 만든 모듈러스 체인을 stderr로 출력.
// OpenFHE는 firstMod/scaleMod를 "요청"으로 받고 NTT 조건(q ≡ 1 mod 2N)을 만족하는
// 실제 소수를 고른다 → 요청 비트수와 실제 비트수가 1비트 어긋날 수 있어 확인이 필요.
static void dumpChain(const CryptoContext<DCRTPoly>& cc, const Preset& p) {
    const auto cp = std::dynamic_pointer_cast<CryptoParametersRNS>(cc->GetCryptoParameters());
    if (!cp) {
        std::cerr << "[" << p.name << "] CryptoParametersRNS 캐스팅 실패\n";
        return;
    }
    const LattigoChain want = lattigoChain(p);

    // GetMSB()는 비트 길이(=ceil). OpenFHE는 2^b 바로 위/아래의 NTT 친화 소수를 번갈아 고르므로
    // 45비트 요청에 q가 2^45보다 조금 크면 GetMSB()=46이 된다 — 크기는 사실상 45비트다.
    // 따라서 일치 판정은 GetMSB가 아니라 log2(q) 반올림으로 한다.
    auto msb = [](const NativeInteger& q) { return static_cast<int>(q.GetMSB()); };
    auto lg = [](const NativeInteger& q) { return std::log2(q.ConvertToDouble()); };

    // 한 tower 줄 출력. req<0이면 Lattigo 쪽에 대응 항목이 없다는 뜻.
    auto printTower = [&](size_t i, const NativeInteger& q, int req) {
        double l = lg(q);
        std::cerr << "  " << std::setw(3) << i << "  ";
        if (req >= 0)
            std::cerr << std::setw(3) << req;
        else
            std::cerr << "  -";
        std::cerr << "  " << std::setw(4) << msb(q) << "  " << std::setw(10) << std::fixed
                  << std::setprecision(5) << l << "  " << std::setw(20) << q.ToString();
        if (req < 0)
            std::cerr << "   <-- Lattigo에 없음";
        else if (std::fabs(l - req) > 0.5)
            std::cerr << "   <-- MISMATCH";
        std::cerr << "\n";
    };

    // --- Q 체인 (ciphertext modulus towers) ---
    const auto& towersQ = cc->GetCryptoParameters()->GetElementParams()->GetParams();
    std::cerr << "\n[" << p.name << "] === modulus chain (Q) : towers=" << towersQ.size()
              << " (Lattigo LogQ 개수=" << want.logQ.size() << ") ===\n";
    std::cerr << "  idx  req   msb     log2(q)                     q\n";
    double sumQ = 0;
    for (size_t i = 0; i < towersQ.size(); i++) {
        const NativeInteger q = towersQ[i]->GetModulus();
        sumQ += lg(q);
        printTower(i, q, (i < want.logQ.size()) ? want.logQ[i] : -1);
    }

    // --- P 체인 (special primes, HYBRID key switching) ---
    const auto paramsP = cp->GetParamsP();
    double sumP = 0;
    if (paramsP) {
        const auto& towersP = paramsP->GetParams();
        std::cerr << "  --- special primes (P) : count=" << towersP.size()
                  << " (Lattigo LogP 개수=" << want.logP.size() << ") ---\n";
        std::cerr << "  idx  req   msb     log2(p)                     p\n";
        for (size_t i = 0; i < towersP.size(); i++) {
            const NativeInteger pi = towersP[i]->GetModulus();
            sumP += lg(pi);
            printTower(i, pi, (i < want.logP.size()) ? want.logP[i] : -1);
        }
    } else {
        std::cerr << "  --- special primes (P) : 없음 (non-HYBRID key switching) ---\n";
    }

    // --- 요약: 키스위칭 구조 + 총 비트수 ---
    // dnum(numPartQ)이 Lattigo와 다르면 P 개수/크기가 달라져 relin·rotation 비용이 직접 영향받음.
    double wantQ = 0, wantP = 0;
    for (int b : want.logQ) wantQ += b;
    for (int b : want.logP) wantP += b;
    // Lattigo는 dnum을 직접 노출하지 않지만 HYBRID 분해 digit 수 = ceil(#Q / #P)로 결정된다.
    int lattigoDnum = static_cast<int>((want.logQ.size() + want.logP.size() - 1) / want.logP.size());
    std::cerr << "  --- summary ---\n"
              << "  ksTech=" << (cp->GetKeySwitchTechnique() == HYBRID ? "HYBRID" : "BV")
              << "  dnum(numPartQ)=" << cp->GetNumPartQ() << " (lattigo≈" << lattigoDnum << ")"
              << "  towersPerPart=" << cp->GetNumPerPartQ() << "  auxBits=" << cp->GetAuxBits()
              << "\n"
              << std::setprecision(2) << "  logQ  actual=" << sumQ << "  lattigo=" << wantQ
              << "  (diff " << (sumQ - wantQ) << ")\n"
              << "  logP  actual=" << sumP << "  lattigo=" << wantP << "  (diff " << (sumP - wantP)
              << ")\n"
              << "  logQP actual=" << (sumQ + sumP) << "  lattigo=" << (wantQ + wantP) << "\n\n";
}

// measure: warmup 후 reps회, 각 호출을 1회씩 타이밍. 평균 + 표본표준편차(n-1) μs 반환.
static std::pair<double, double> measure(int reps, int warmup,
                                         const std::function<void()>& fn) {
    for (int i = 0; i < warmup; i++) fn();
    std::vector<double> ts(reps);
    for (int i = 0; i < reps; i++) {
        // steady_clock: 단조 증가 보장. high_resolution_clock은 libstdc++에서 system_clock의
        // 별칭(=CLOCK_REALTIME)이라 NTP/WSL 시계 재동기화 시 역행해 음수 latency가 나올 수 있다.
        // (Go의 time.Since는 이미 monotonic이라 Lattigo 쪽은 영향 없음)
        auto t0 = std::chrono::steady_clock::now();
        fn();
        auto t1 = std::chrono::steady_clock::now();
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
    std::string presetSel = "all";
    int reps = 30, warmup = 3;
    bool chainOnly = false;  // 체인만 덤프하고 벤치는 건너뜀 (컨텍스트 생성만이라 빠름)
    std::string out = "results_openfhe.csv";
    for (int i = 1; i < argc; i++) {
        std::string a = argv[i];
        if (a == "-preset" && i + 1 < argc)
            presetSel = argv[++i];
        else if (a == "-reps" && i + 1 < argc)
            reps = std::stoi(argv[++i]);
        else if (a == "-warmup" && i + 1 < argc)
            warmup = std::stoi(argv[++i]);
        else if (a == "-out" && i + 1 < argc)
            out = argv[++i];
        else if (a == "-chain-only")
            chainOnly = true;
    }

    // -chain-only일 땐 기존 결과 CSV를 덮어쓰지 않는다.
    std::ofstream csv;
    if (!chainOnly) {
        csv.open(out);
        csv << "library,preset,logN,maxLevel,level,op,mean_us,std_us,reps\n";
        csv << std::fixed;
    }

    for (const auto& p : kPresets) {
        if (presetSel != "all" && presetSel != p.name) continue;

        CCParams<CryptoContextCKKSRNS> params;
        params.SetMultiplicativeDepth(p.depth);   // = maxLevel
        params.SetScalingModSize(p.scaleMod);
        params.SetFirstModSize(p.firstMod);
        params.SetScalingTechnique(FIXEDMANUAL);  // rescale를 명시적으로 측정
        params.SetSecurityLevel(HEStd_NotSet);    // 링차원 강제 위해 보안레벨 해제
        params.SetRingDim(1u << p.logN);

        CryptoContext<DCRTPoly> cc = GenCryptoContext(params);
        cc->Enable(PKE);
        cc->Enable(KEYSWITCH);
        cc->Enable(LEVELEDSHE);
        cc->Enable(ADVANCEDSHE);

        int maxLevel = p.depth;
        uint32_t ringDim = cc->GetRingDimension();

        // GenCryptoContext가 실제로 고른 모듈러스 체인을 확인 (Lattigo 명시 체인과 대조).
        dumpChain(cc, p);
        if (chainOnly) continue;

        auto keys = cc->KeyGen();
        cc->EvalMultKeyGen(keys.secretKey);           // relin 키
        cc->EvalRotateKeyGen(keys.secretKey, {1, -1}); // 회전 키

        size_t slots = ringDim / 2;
        std::vector<double> vec(slots, 0.5);

        std::cerr << "[" << p.name << "] logN=" << p.logN
                  << " ringDim=" << ringDim << " maxLevel=" << maxLevel << "\n";

        // 레벨 전수 스윕: 리포트 level = maxLevel..1.
        // OpenFHE는 fresh ct의 GetLevel()=0 → 리포트 level = maxLevel - GetLevel()로 Lattigo와 정렬.
        for (int L = maxLevel; L >= 1; L--) {
            uint32_t g = static_cast<uint32_t>(maxLevel - L); // 목표 GetLevel

            // pt는 ct와 같은 레벨(g)로 인코딩해야 EvalAdd/EvalMult(ct,pt) 유효.
            Plaintext pt = cc->MakeCKKSPackedPlaintext(vec, 1, g);
            // ct는 full-level 평문을 암호화한 뒤 LevelReduce로 목표 레벨(g)에 위치.
            // (레벨-g 평문을 바로 암호화하면 이미 g만큼 drop된 상태라 이중 drop 주의)
            Plaintext pt0 = cc->MakeCKKSPackedPlaintext(vec, 1, 0);
            Ciphertext<DCRTPoly> ctA = cc->Encrypt(keys.publicKey, pt0);
            Ciphertext<DCRTPoly> ctB = cc->Encrypt(keys.publicKey, pt0);
            if (g > 0) {
                // LevelReduce: 스케일 변화 없이 모듈러스만 drop해 목표 레벨로 위치.
                ctA = cc->LevelReduce(ctA, nullptr, g);
                ctB = cc->LevelReduce(ctB, nullptr, g);
            }

            // rescale 입력: 곱으로 스케일 제곱된 ct에 Rescale(level>0에서만 유효).
            Ciphertext<DCRTPoly> cRes = cc->EvalMult(ctA, ctB);

            auto [m_addcc, s_addcc] = measure(reps, warmup, [&]() { cc->EvalAdd(ctA, ctB); });
            auto [m_addcp, s_addcp] = measure(reps, warmup, [&]() { cc->EvalAdd(ctA, pt); });
            auto [m_mulcp, s_mulcp] = measure(reps, warmup, [&]() { cc->EvalMult(ctA, pt); });
            auto [m_mulcc, s_mulcc] = measure(reps, warmup, [&]() { cc->EvalMultNoRelin(ctA, ctB); });
            auto [m_rlk, s_rlk] = measure(reps, warmup, [&]() { cc->EvalMult(ctA, ctB); });
            auto [m_res, s_res] = measure(reps, warmup, [&]() { cc->Rescale(cRes); });
            auto [m_rot, s_rot] = measure(reps, warmup, [&]() { cc->EvalRotate(ctA, 1); });

            // relin: 직접 계측. (2026-07-26 변경)
            // 예전에는 relin = m_rlk - m_mulcc 파생값이었고 std=0으로 기록했다. 그 방식은
            //   (1) 분산 정보가 사라지고(std=0이 CV 통계를 인공적으로 낮춤),
            //   (2) EvalMult가 융합 경로라 "두 평균의 차"가 독립 Relinearize 비용과 다른 양이며,
            //   (3) SEAL 하네스는 직접 계측이라 라이브러리 간 계측 방식이 불일치했다.
            // SEAL과 동일한 패턴으로 맞춘다: size-3 입력을 타이머 밖에서 1회 만들고
            // out-of-place Relinearize를 반복(입력 무오염, §4).
            // ※ 이 블록은 기존 7개 measure() 뒤에 둔다 — 앞에 두면 할당자·메모리 상태가
            //    달라져 다른 op의 측정 조건이 바뀐다.
            Ciphertext<DCRTPoly> cProd3 = cc->EvalMultNoRelin(ctA, ctB);
            auto [m_relin, s_relin] = measure(reps, warmup, [&]() { cc->Relinearize(cProd3); });

            auto row = [&](const std::string& op, double mean, double sd) {
                csv << "openfhe," << p.name << "," << p.logN << "," << maxLevel << ","
                    << L << "," << op << "," << std::setprecision(3) << mean << ","
                    << sd << "," << reps << "\n";
            };
            row("add_cc", m_addcc, s_addcc);
            row("add_cp", m_addcp, s_addcp);
            row("mul_cp", m_mulcp, s_mulcp);
            row("mul_cc", m_mulcc, s_mulcc);
            row("mul_cc_rlk", m_rlk, s_rlk);
            row("relin", m_relin, s_relin);
            row("rescale", m_res, s_res);
            row("rot1", m_rot, s_rot);

            std::cerr << "  L=" << L << " add_cc=" << m_addcc << " mul_cc=" << m_mulcc
                      << " relin=" << m_relin << " rot1=" << m_rot << " rescale=" << m_res << "\n";
        }
    }

    if (chainOnly) {
        std::cerr << "chain-only: 벤치마크 생략 (CSV 미기록)\n";
        return 0;
    }
    csv.close();
    std::cerr << "wrote " << out << "\n";
    return 0;
}
