// presetsearch_openfhe.cpp — 프리셋 확정을 위한 탐색 측정 (OpenFHE). 본측정 아님.
//
// 실험 1: P 탐색   logN15 q0 60 Δ40 depth13 고정, dnum 스윕. level {13,7,1}.
//                  op {relin, rot1, mul_cc_rlk, mul_cc} — P는 key-switch 계열에만 영향.
// 실험 2: Δ 스윕   logP를 120으로 고정(dnum 7)하고 Δ 40..50. maxLevel 한 점, 8-op 전부.
//
// 측정 로직은 openfhe_bench.cpp 를 그대로 옮겼다(비교 성립 조건):
//   - measure(): warmup 후 reps회, 연산 1회만 타이밍, steady_clock, ns→μs, 표본표준편차(n-1)
//   - 레벨 진입: full-level 암호화 후 LevelReduce(스케일 불변). 리포트 level = maxLevel - GetLevel()
//   - relin은 **직접 계측** — size-3 입력을 타이머 밖에서 만들고 out-of-place Relinearize 반복.
//     파생값(mul_cc_rlk − mul_cc) 금지: OpenFHE는 EvalMult가 융합이라 4.4% 과소평가 + std 소실.
//   - relin 블록은 다른 op 측정이 끝난 뒤에 둔다(할당자·메모리 상태 보존).
//
// 정밀도(실험 1)는 별도 스트림으로 기록한다. 비밀키 암호화 — 공개키는 KS 노이즈를 덮는다.
// 타이밍이 끝난 뒤에 재서 타이밍 측정 조건을 건드리지 않는다.
#include "openfhe.h"
#include "precision_common.h"
#include "schemerns/rns-cryptoparameters.h"
#include <omp.h>

#include <chrono>
#include <cmath>
#include <cstring>
#include <fstream>
#include <functional>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
#include <algorithm>
#include <vector>

using namespace lbcrypto;

static int TC128Bound(int logN)
{
    switch (logN) { case 13: return 218; case 14: return 438; case 15: return 881; }
    return -1;
}

static std::pair<double, double> measure(int reps, int warmup, const std::function<void()>& fn)
{
    for (int i = 0; i < warmup; i++) fn();
    std::vector<double> ts(reps);
    for (int i = 0; i < reps; i++) {
        auto t0 = std::chrono::steady_clock::now();
        fn();
        auto t1 = std::chrono::steady_clock::now();
        ts[i] = std::chrono::duration<double, std::nano>(t1 - t0).count() / 1000.0;
    }
    double sum = 0;
    for (double x : ts) sum += x;
    double mean = sum / reps, sd = 0.0;
    if (reps > 1) {
        double ss = 0;
        for (double x : ts) { double d = x - mean; ss += d * d; }
        sd = std::sqrt(ss / (reps - 1));
    }
    return {mean, sd};
}

// 파괴적(in-place) 연산용 배치 계측.
// 순수 레벨 강하는 연산 1회가 타이머 분해능(steady_clock ~20-30ns) 근처거나 그 아래일 수
// 있고, in-place 라 같은 암호문에 반복할 수도 없다(레벨이 계속 내려간다).
//   → 타이머 밖에서 K개 사본을 준비(reset)하고, 타이머 안에서 K회 수행(runK)한 뒤 K로 나눈다.
// ⚠️ 이때 rep 값은 "K회의 평균"이므로 std 는 단발 계측의 std 와 의미가 다르다
//    (K개 평균의 rep 간 산포 → 약 1/√K 로 줄어든다). CSV 의 rep_mode 열로 구분한다.
static std::pair<double, double> measure_batch(int reps, int warmup, int K,
                                               const std::function<void()>& reset,
                                               const std::function<void()>& runK)
{
    for (int i = 0; i < warmup; i++) { reset(); runK(); }
    std::vector<double> ts(reps);
    for (int i = 0; i < reps; i++) {
        reset();
        auto t0 = std::chrono::steady_clock::now();
        runK();
        auto t1 = std::chrono::steady_clock::now();
        ts[i] = std::chrono::duration<double, std::nano>(t1 - t0).count() / 1000.0 / K;
    }
    double sum = 0;
    for (double x : ts) sum += x;
    double mean = sum / reps, sd = 0.0;
    if (reps > 1) {
        double ss = 0;
        for (double x : ts) { double d = x - mean; ss += d * d; }
        sd = std::sqrt(ss / (reps - 1));
    }
    return {mean, sd};
}

// 배치 크기 — 암호문 1개의 바이트 수로 상한을 건다(logN15·L12 는 1개가 ~6.8MB).
static int batch_k_for(int logN, int level, long budget_bytes, int kmax)
{
    const double ct_bytes = 2.0 * (level + 1) * (double)(1u << logN) * 8.0;
    int k = (int)(budget_bytes / ct_bytes);
    if (k < 4) k = 4;
    if (k > kmax) k = kmax;
    return k;
}

struct Cfg { int exp, logN, q0, delta, depth; uint32_t dnum; };

int main(int argc, char** argv)
{
    int expSel = 1, reps = 30, warmup = 3, precreps = 5;
    std::string out = "timing.csv", precout = "precision.csv", spec, thlabel = "1t";
    std::string opsFilter;   // "-ops a,b,c" — ops 목록을 이 집합으로 제한(시간 절약). 순서는 원 목록 유지.
    std::string verifyout = "";                 // exp 9 전용 검증 CSV
    long batchbudget = 64L * 1024 * 1024;       // in-place 배치 메모리 예산
    int  batchkmax = 2048;
    bool ldasc = false, ldclone = false;   // exp 9 진단 스위치
    for (int i = 1; i < argc; i++) {
        std::string a = argv[i];
        if (a == "-exp" && i + 1 < argc) expSel = std::stoi(argv[++i]);
        else if (a == "-reps" && i + 1 < argc) reps = std::stoi(argv[++i]);
        else if (a == "-warmup" && i + 1 < argc) warmup = std::stoi(argv[++i]);
        else if (a == "-precreps" && i + 1 < argc) precreps = std::stoi(argv[++i]);
        else if (a == "-out" && i + 1 < argc) out = argv[++i];
        else if (a == "-precout" && i + 1 < argc) precout = argv[++i];
        // -combos "logN:depth:delta:dnum,..." → maxLevel 한 점, heavy 3종 (exp 6)
        else if (a == "-combos" && i + 1 < argc) { spec = argv[++i]; expSel = 6; }
        // -mainrun "logN:depth:delta:dnum" → 레벨 전수 · 8-op · 정밀도 (임의 프리셋 본측정)
        else if (a == "-mainrun" && i + 1 < argc) { spec = argv[++i]; expSel = 7; }
        // -hexlrun "logN:depth:delta:dnum" → HEXL 아암 최소 규모 (exp 8)
        else if (a == "-hexlrun" && i + 1 < argc) { spec = argv[++i]; expSel = 8; }
        // -leveldrop "logN:depth:delta:dnum" → 순수 레벨 강하 전용 (exp 9). 8-op 경로와 분리.
        else if (a == "-leveldrop" && i + 1 < argc) { spec = argv[++i]; expSel = 9; }
        else if (a == "-verifyout" && i + 1 < argc) verifyout = argv[++i];
        else if (a == "-batchbudget" && i + 1 < argc) batchbudget = std::stol(argv[++i]);
        else if (a == "-batchkmax" && i + 1 < argc) batchkmax = std::stoi(argv[++i]);
        else if (a == "-ldasc") ldasc = true;        // 진단: 레벨 오름차순
        else if (a == "-ldclone") ldclone = true;    // 진단: maxLevel 도 Clone 경유
        else if (a == "-threads" && i + 1 < argc) thlabel = argv[++i];
        else if (a == "-ops" && i + 1 < argc) opsFilter = argv[++i];
    }

    std::vector<Cfg> cfgs;
    std::vector<int> levels;
    std::vector<std::string> ops;
    if (expSel == 1) {
        // param_dump 에서 logQP ≤ 881 을 만족한 dnum 전부 (Δ40 depth13).
        for (uint32_t d : {2u, 3u, 4u, 5u, 7u, 14u}) cfgs.push_back({1, 15, 60, 40, 13, d});
        levels = {13, 7, 1};
        ops = {"mul_cc", "mul_cc_rlk", "relin", "rot1"};
    } else if (expSel == 2) {
        // logP 를 120으로 고정해야 Δ의 순수 효과가 보인다. dnum=7 이면 digit0 = q0+Δ ∈ [100,110]
        // → ceil(digit/60) = 2 → logP 120 이 Δ 40..50 전 구간에서 성립한다(실측으로 재확인).
        for (int dl = 40; dl <= 50; dl++) cfgs.push_back({2, 15, 60, dl, 13, 7u});
        levels = {13};
        ops = {"add_cc", "add_cp", "mul_cp", "mul_cc", "mul_cc_rlk", "relin", "rescale", "rot1"};
    } else if (expSel == 4) {
        // P 선택 확인: depth 12 / Δ 42 에서 logP 240 을 내는 dnum 3 과 4 를 비교한다.
        // depth 13 탐색에서는 dnum 3 이 ~20% 빨랐으나 depth 가 바뀌면 레벨별 digit 수열이
        // 달라지므로 순서가 유지되는지 재확인이 필요하다.
        cfgs.push_back({4, 15, 60, 42, 12, 3u});
        cfgs.push_back({4, 15, 60, 42, 12, 4u});
        levels = {12};
        ops = {"mul_cc_rlk", "relin", "rot1"};
    } else if (expSel == 5) {
        // v3 본측정: logN15 q0 60 Δ42 depth12 (QCount 13, logQ 564).
        // dnum 3 → PCount 4 / logP 240 / logQP 804 / 여유 77.
        // dnum 4 도 같은 logP 240 을 내지만 digit 수열이 L12~L4 에서 더 많아 ~20% 느리다.
        // dnum 2 는 logP 360 이 되어 logQP 924 로 상한을 43비트 초과한다(선택지 아님).
        cfgs.push_back({5, 15, 60, 42, 12, 3u});
        for (int L = 12; L >= 1; L--) levels.push_back(L);
        ops = {"add_cc", "add_cp", "mul_cp", "mul_cc", "mul_cc_rlk", "relin", "rescale", "rot1"};
    } else if (expSel == 8) {
        // HEXL 아암(2026-08-02). OFF baseline 과 **다른 질문**에 답하는 별도 측정이라
        // 전수 스윕을 하지 않는다 — 배수만 본다.
        //   레벨 3점(maxLevel / 중간 / L1) × heavy 3종. 정밀도는 maxLevel 만.
        // 타이밍·정밀도 코드 경로는 exp 5/7 과 완전히 동일하다(measure() 를 그대로 쓴다).
        int ln = 0, dp = 0, dl = 0; unsigned dn = 0;
        if (sscanf(spec.c_str(), "%d:%d:%d:%u", &ln, &dp, &dl, &dn) != 4) {
            std::cerr << "-hexlrun 파싱 실패: " << spec << "\n"; return 2;
        }
        cfgs.push_back({8, ln, 60, dl, dp, dn});
        ops = {"mul_cc_rlk", "relin", "rot1"};
    } else if (expSel == 9) {
        // 순수 레벨 강하 전용. **기존 8-op 경로는 전혀 건드리지 않는다** —
        // op 목록도 파일도 따로 나가므로 aggregate.py 의 op 어휘 게이트와 무관하다.
        int ln = 0, dp = 0, dl = 0; unsigned dn = 0;
        if (sscanf(spec.c_str(), "%d:%d:%d:%u", &ln, &dp, &dl, &dn) != 4) {
            std::cerr << "-leveldrop 파싱 실패: " << spec << "\n"; return 2;
        }
        cfgs.push_back({9, ln, 60, dl, dp, dn});
        for (int L = dp; L >= 1; L--) levels.push_back(L);
        ops = {"leveldrop", "leveldrop_ip", "leveldrop_oop", "clone_only"};
    } else if (expSel == 7) {
        int ln = 0, dp = 0, dl = 0; unsigned dn = 0;
        if (sscanf(spec.c_str(), "%d:%d:%d:%u", &ln, &dp, &dl, &dn) != 4) {
            std::cerr << "-mainrun 파싱 실패: " << spec << "\n"; return 2;
        }
        cfgs.push_back({7, ln, 60, dl, dp, dn});
        ops = {"add_cc", "add_cp", "mul_cp", "mul_cc", "mul_cc_rlk", "relin", "rescale", "rot1"};
    } else if (expSel == 6) {
        // 최적 P 선정용: 임의 조합의 maxLevel 성능만 본다. 레벨은 각 조합의 depth 로 잡는다.
        size_t i = 0;
        while (i < spec.size()) {
            size_t j = spec.find(',', i); if (j == std::string::npos) j = spec.size();
            int ln = 0, dp = 0, dl = 0; unsigned dn = 0;
            if (sscanf(spec.substr(i, j - i).c_str(), "%d:%d:%d:%u", &ln, &dp, &dl, &dn) == 4)
                cfgs.push_back({6, ln, 60, dl, dp, dn});
            else std::cerr << "[warn] 조합 파싱 실패: " << spec.substr(i, j - i) << "\n";
            i = j + 1;
        }
        ops = {"mul_cc_rlk", "relin", "rot1"};
    } else {
        // 본측정: 탐색으로 확정된 프리셋. dnum 3 → PCount 4 / logP 240 / logQP 820.
        // (logP 300 = dnum 2 가 더 빠르지만 rot1 정밀도 23.31로 하한 25비트 미달.
        //  같은 logP 240 의 dnum 4 보다 dnum 3 이 maxLevel에서 ~20% 빠르다.)
        cfgs.push_back({3, 15, 60, 40, 13, 3u});
        for (int L = 13; L >= 1; L--) levels.push_back(L);
        ops = {"add_cc", "add_cp", "mul_cp", "mul_cc", "mul_cc_rlk", "relin", "rescale", "rot1"};
    }

    if (!opsFilter.empty()) {
        // 요청된 op 만 남긴다(원 ops 의 순서 유지). leveldrop(exp 9) 어휘는 별도라 건드리지 않는다.
        std::vector<std::string> want;
        size_t p = 0;
        while (p < opsFilter.size()) {
            size_t q = opsFilter.find(',', p); if (q == std::string::npos) q = opsFilter.size();
            want.push_back(opsFilter.substr(p, q - p));
            p = q + 1;
        }
        std::vector<std::string> filtered;
        for (const auto& op : ops)
            if (std::find(want.begin(), want.end(), op) != want.end()) filtered.push_back(op);
        ops = filtered;
    }

    std::ofstream csv(out), pcsv;
    // nthreads = omp_get_max_threads() 런타임 실측 — OMP_NUM_THREADS 가 실제로 먹혔는지 기록한다.
    const int nthreads = omp_get_max_threads();
    std::cerr << "[openfhe] threads=" << thlabel << " omp_get_max_threads()=" << nthreads << "\n";
    csv << "library,exp,logN,q0,delta,depth,dnum,PCount,logP,logQ,logQP,bound,margin,"
           "maxLevel,level,op,mean_us,std_us,reps,digits,threads,nthreads,ok,err"
        << (expSel == 9 ? ",batch_k,rep_mode\n" : "\n");
    // exp 9 검증 스트림 — 레벨/스케일/복호값이 실제로 보존되는지 행 단위로 남긴다.
    std::ofstream vcsv;
    if (expSel == 9 && !verifyout.empty()) {
        vcsv.open(verifyout);
        vcsv << "library,logN,depth,delta,dnum,level,level_before,level_after,"
                "scale_before,scale_after,scale_ratio,max_abs_diff,bits_before,bits_after,ok\n";
    }
    csv << std::fixed;
    const bool wantPrec = (expSel == 1 || expSel == 3 || expSel == 5 || expSel == 7 || expSel == 8);
    if (wantPrec) {
        pcsv.open(precout);
        pcsv << "library,exp,logN,q0,delta,depth,dnum,PCount,logP,maxDigitBits,level,path,rep,bits\n";
    }

    for (const auto& c : cfgs) {
        CCParams<CryptoContextCKKSRNS> params;
        params.SetMultiplicativeDepth(c.depth);
        params.SetScalingModSize(c.delta);
        params.SetFirstModSize(c.q0);
        params.SetScalingTechnique(FIXEDMANUAL);
        params.SetSecurityLevel(HEStd_NotSet);
        params.SetRingDim(1u << c.logN);
        params.SetNumLargeDigits(c.dnum);

        CryptoContext<DCRTPoly> cc;
        try { cc = GenCryptoContext(params); }
        catch (const std::exception& e) {
            std::string err = e.what();
            for (auto& ch : err) if (ch == ',' || ch == '\n' || ch == '\r') ch = ' ';
            csv << "openfhe," << c.exp << "," << c.logN << "," << c.q0 << "," << c.delta << ","
                << c.depth << "," << c.dnum << ",,,,,,,,,,,,,," << thlabel << "," << nthreads << ",0," << err << "\n";
            std::cerr << "[skip] delta=" << c.delta << " dnum=" << c.dnum << ": " << err << "\n";
            continue;
        }
        cc->Enable(PKE); cc->Enable(KEYSWITCH); cc->Enable(LEVELEDSHE); cc->Enable(ADVANCEDSHE);

        // 링 차원이 요청대로인지 확인 — 검사가 켜지면 OpenFHE가 N을 조용히 올린다.
        if (cc->GetRingDimension() != (1u << c.logN)) {
            csv << "openfhe," << c.exp << "," << c.logN << "," << c.q0 << "," << c.delta << ","
                << c.depth << "," << c.dnum << ",,,,,,,,,,,,,," << thlabel << "," << nthreads << ",0,ring dim changed\n";
            continue;
        }

        auto cp = std::dynamic_pointer_cast<CryptoParametersRNS>(cc->GetCryptoParameters());
        // 런타임 API에서 뽑는다 — 명목값·추정치 금지.
        int logQ = 0, logP = 0; size_t pCount = 0;
        for (auto& t : cp->GetElementParams()->GetParams())
            logQ += (int)llround(std::log2(t->GetModulus().ConvertToDouble()));
        if (auto pp = cp->GetParamsP())
            for (auto& t : pp->GetParams()) {
                logP += (int)llround(std::log2(t->GetModulus().ConvertToDouble()));
                pCount++;
            }
        int maxDigitBits = 0;
        for (uint32_t j = 0; j < cp->GetNumPartQ(); j++) {
            int b = 0;
            for (auto& t : cp->GetParamsPartQ(j)->GetParams())
                b += (int)llround(std::log2(t->GetModulus().ConvertToDouble()));
            if (b > maxDigitBits) maxDigitBits = b;
        }
        const uint32_t dnum = cp->GetNumPartQ(), perPart = cp->GetNumPerPartQ();
        const int bound = TC128Bound(c.logN), logQP = logQ + logP, margin = bound - logQP;
        // 레벨별 digit 수 — keyswitch-hybrid.cpp:325-329
        std::ostringstream ds;
        for (int L = c.depth; L >= 1; L--) {
            uint32_t parts = ((uint32_t)L + 1 + perPart - 1) / perPart;
            if (parts > dnum) parts = dnum;
            if (L != c.depth) ds << ";";
            ds << "L" << L << "=" << parts;
        }
        const std::string digits = ds.str();

        std::cerr << "[openfhe exp" << c.exp << "] Δ=" << c.delta << " dnum=" << dnum
                  << " PCount=" << pCount << " logP=" << logP << " logQP=" << logQP
                  << " 여유=" << margin << "\n";

        auto keys = cc->KeyGen();
        cc->EvalMultKeyGen(keys.secretKey);
        cc->EvalRotateKeyGen(keys.secretKey, {1});

        const size_t slots = (size_t(1) << c.logN) / 2;
        std::vector<double> vec(slots, 0.5);

        // ══════════════════════════════════════════════════════════════════
        // exp 9 — 순수 레벨 강하(leveldrop). 아래 기존 8-op 루프는 건드리지 않는다.
        //
        // rescale 과 다른 연산이다(소스 확인, ckksrns-leveledshe.cpp):
        //   ModReduceInternalInPlace  : DropLastElementAndScale + SetScalingFactor(/factor)  → 스케일 나눔
        //   LevelReduceInternalInPlace: DropLastElements + SetLevel                          → 스케일 보존
        // ⚠️ LevelReduceInPlace 는 ScalingTechnique==FIXEDMANUAL 에서만 실제로 동작한다
        //    (rns-leveledshe.cpp:339-343). 이 하네스는 FIXEDMANUAL 이라 조건을 만족한다.
        //    그래도 no-op 가능성이 있으므로 레벨을 매번 검증한다.
        if (c.exp == 9) {
            std::vector<double> xv, yv;
            precision_common::make_inputs(slots, xv, yv);
            auto dec = [&](const Ciphertext<DCRTPoly>& z) {
                Plaintext r; cc->Decrypt(keys.secretKey, z, &r); r->SetLength(slots);
                return r->GetRealPackedValue();
            };
            std::vector<int> ldlv = levels;
            if (ldasc) std::reverse(ldlv.begin(), ldlv.end());
            for (int L : ldlv) {
                const uint32_t gEnter = (uint32_t)(c.depth - L);
                Plaintext ptx = cc->MakeCKKSPackedPlaintext(xv, 1, 0);
                auto ct = cc->Encrypt(keys.publicKey, ptx);
                if (gEnter > 0) ct = cc->LevelReduce(ct, nullptr, gEnter);
                else if (ldclone) ct = ct->Clone();

                // ---- 검증: 레벨 -1, 스케일 보존, 복호값 불변 ----
                const uint32_t lvB = ct->GetLevel();
                const double   sfB = ct->GetScalingFactor();
                std::vector<double> vB = dec(ct);
                auto ctD = cc->LevelReduce(ct, nullptr, 1);
                const uint32_t lvA = ctD->GetLevel();
                const double   sfA = ctD->GetScalingFactor();
                std::vector<double> vA = dec(ctD);
                double mx = 0.0;
                for (size_t i = 0; i < slots; i++) mx = std::max(mx, std::fabs(vB[i] - vA[i]));
                const bool okLv = (lvA == lvB + 1);
                const double bitsB = precision_common::precision_bits(vB, xv);
                const double bitsA = precision_common::precision_bits(vA, xv);
                if (!okLv) {
                    std::cerr << "  !! L=" << L << " 레벨이 1 줄지 않았다 ("
                              << lvB << " -> " << lvA << ") — LevelReduce 가 no-op\n";
                }
                if (vcsv.is_open())
                    vcsv << "openfhe," << c.logN << "," << c.depth << "," << c.delta << ","
                         << dnum << "," << L << "," << (c.depth - (int)lvB) << ","
                         << (c.depth - (int)lvA) << ","
                         << std::setprecision(17) << sfB << "," << sfA << ","
                         << (sfB > 0 ? sfA / sfB : 0.0) << ","
                         << std::setprecision(6) << mx << "," << bitsB << "," << bitsA << ","
                         << (okLv ? 1 : 0) << "\n";
                csv << std::setprecision(3);

                const auto emit = [&](const char* op, std::pair<double,double> r, int bk, const char* rm) {
                    csv << "openfhe," << c.exp << "," << c.logN << "," << c.q0 << ","
                        << c.delta << "," << c.depth << "," << dnum << "," << pCount << ","
                        << logP << "," << logQ << "," << logQP << "," << bound << ","
                        << margin << "," << c.depth << "," << L << "," << op << ","
                        << r.first << "," << r.second << "," << reps << "," << digits << ","
                        << thlabel << "," << nthreads << ",1,," << bk << "," << rm << "\n";
                };

                // ---- 계측 1: out-of-place (새 암호문 반환). 기존 8-op 와 같은 measure() ----
                //   Clone(전 타워 깊은 복사) + DropLastElements 다. "새 암호문을 하나 만든다"는
                //   점이 세 라이브러리에서 대응하므로 작업량 비교가 가능한 쪽이다.
                auto rOop = measure(reps, warmup, [&]{ cc->LevelReduce(ct, nullptr, 1); });

                // ---- 계측 2(분해용): Clone 만. leveldrop_oop = clone + drop 로 나눠 본다 ----
                auto rCl = measure(reps, warmup, [&]{ ct->Clone(); });

                // ---- 계측 3: in-place = OpenFHE 가 레벨을 내리는 **가장 싼 방법**.
                //   파괴적이라 같은 암호문에 반복할 수 없다 → 타이머 밖에서 K개 사본을 만들고
                //   타이머 안에서 K회 수행한 뒤 K로 나눈다. 메모리를 많이 쓰므로 레벨당 마지막에 둔다.
                const int K = batch_k_for(c.logN, L, batchbudget, batchkmax);
                std::vector<Ciphertext<DCRTPoly>> pool(K);
                auto reset = [&]{ for (int i = 0; i < K; i++) pool[i] = ct->Clone(); };
                auto runK  = [&]{ for (int i = 0; i < K; i++) cc->LevelReduceInPlace(pool[i], nullptr, 1); };
                auto rIp = measure_batch(reps, warmup, K, reset, runK);
                if (pool[0]->GetLevel() != lvB + 1)
                    std::cerr << "  !! L=" << L << " in-place 강하가 레벨을 바꾸지 않았다\n";

                // 네 op 를 세 라이브러리가 모두 같은 이름으로 낸다.
                //   leveldrop     = 그 라이브러리가 레벨을 내리는 **가장 싼** 정당한 방법
                //   leveldrop_ip  = in-place 형 / leveldrop_oop = 새 암호문 반환형
                //   clone_only    = 분해용(복사만)
                // OpenFHE 는 in-place 가 가장 싸다 → leveldrop == leveldrop_ip.
                emit("leveldrop", rIp, K, "batch");
                emit("leveldrop_ip", rIp, K, "batch");
                emit("leveldrop_oop", rOop, 1, "single");
                emit("clone_only", rCl, 1, "single");
                csv.flush();
                if (vcsv.is_open()) vcsv.flush();
                std::cerr << "  L=" << L << " leveldrop=" << rIp.first << "us(K=" << K << ")"
                          << " oop=" << rOop.first << "us"
                          << " clone=" << rCl.first << "us"
                          << " lv " << (c.depth - (int)lvB) << "->" << (c.depth - (int)lvA)
                          << " scale " << (sfB > 0 ? sfA / sfB : 0.0)
                          << " maxdiff " << mx << "\n";
            }
            continue;   // 기존 8-op 루프·정밀도 블록을 건너뛴다
        }

        std::vector<int> lv = levels;
        if (c.exp == 6) lv = {c.depth};
        else if (c.exp == 7) { lv.clear(); for (int L = c.depth; L >= 1; L--) lv.push_back(L); }
        else if (c.exp == 8) lv = {c.depth, c.depth / 2, 1};
        for (int L : lv) {
            const uint32_t g = (uint32_t)(c.depth - L);
            Plaintext pt = cc->MakeCKKSPackedPlaintext(vec, 1, g);
            Plaintext pt0 = cc->MakeCKKSPackedPlaintext(vec, 1, 0);
            auto ctA = cc->Encrypt(keys.publicKey, pt0);
            auto ctB = cc->Encrypt(keys.publicKey, pt0);
            if (g > 0) {
                ctA = cc->LevelReduce(ctA, nullptr, g);
                ctB = cc->LevelReduce(ctB, nullptr, g);
            }
            auto cRes = cc->EvalMult(ctA, ctB);   // rescale 입력(스케일 제곱 상태)

            std::vector<std::pair<std::string, std::function<void()>>> jobs;
            for (const auto& op : ops) {
                if (op == "add_cc")     jobs.push_back({op, [&]{ cc->EvalAdd(ctA, ctB); }});
                else if (op == "add_cp")jobs.push_back({op, [&]{ cc->EvalAdd(ctA, pt); }});
                else if (op == "mul_cp")jobs.push_back({op, [&]{ cc->EvalMult(ctA, pt); }});
                else if (op == "mul_cc")jobs.push_back({op, [&]{ cc->EvalMultNoRelin(ctA, ctB); }});
                else if (op == "mul_cc_rlk") jobs.push_back({op, [&]{ cc->EvalMult(ctA, ctB); }});
                else if (op == "rescale")jobs.push_back({op, [&]{ cc->Rescale(cRes); }});
                else if (op == "rot1")  jobs.push_back({op, [&]{ cc->EvalRotate(ctA, 1); }});
            }
            std::vector<std::pair<std::string, std::pair<double, double>>> res;
            for (auto& j : jobs) res.push_back({j.first, measure(reps, warmup, j.second)});

            // relin 직접 계측 — 반드시 다른 op 측정 뒤에.
            bool wantRelin = false;
            for (const auto& op : ops) if (op == "relin") wantRelin = true;
            if (wantRelin) {
                auto cProd3 = cc->EvalMultNoRelin(ctA, ctB);
                res.push_back({"relin", measure(reps, warmup, [&]{ cc->Relinearize(cProd3); })});
            }

            for (const auto& op : ops)
                for (auto& r : res)
                    if (r.first == op)
                        csv << "openfhe," << c.exp << "," << c.logN << "," << c.q0 << ","
                            << c.delta << "," << c.depth << "," << dnum << "," << pCount << ","
                            << logP << "," << logQ << "," << logQP << "," << bound << ","
                            << margin << "," << c.depth << "," << L << "," << op << ","
                            << std::setprecision(3) << r.second.first << "," << r.second.second
                            << "," << reps << "," << digits << "," << thlabel << "," << nthreads << ",1,\n";
            csv.flush();
            std::cerr << "  L=" << L << " done\n";
        }

        // ---- 정밀도 : 타이밍이 끝난 뒤 ----
        // 반복마다 키를 새로 만들고(비밀키·암호화 오차 표본이 산포의 원천), 그 안에서 레벨을 훑는다.
        // ★ 각 레벨에서 **새로 암호화**한 뒤 그 레벨로 내린다 — 암호문을 레벨을 따라 끌고
        //   내려가면 누적 노이즈가 섞여 "그 레벨의 KS 손실"이 아니게 된다.
        //   레벨 진입은 스케일 불변 drop(LevelReduce) — ModReduce를 쓰면 스케일까지 나뉜다.
        if (wantPrec) {
            // exp 8(HEXL 아암)은 정밀도를 maxLevel 한 점만 본다 — HEXL 이 연산 순서를 바꿔
            // 정밀도가 흔들리는지 확인하는 것이 목적이고, 그 확인에는 한 점이면 족하다.
            std::vector<int> plv = (c.exp == 8) ? std::vector<int>{c.depth} : lv;
            std::vector<double> x, y;
            precision_common::make_inputs(slots, x, y);
            std::vector<double> want_rot(slots);
            for (size_t i = 0; i < slots; i++) want_rot[i] = x[(i + 1) % slots];
            for (int rep = 0; rep < precreps; rep++) {
                auto pk2 = cc->KeyGen();
                cc->EvalRotateKeyGen(pk2.secretKey, {1});
                auto dec = [&](const Ciphertext<DCRTPoly>& z) {
                    Plaintext r; cc->Decrypt(pk2.secretKey, z, &r); r->SetLength(slots);
                    return r->GetRealPackedValue();
                };
                for (int L : plv) {
                    const uint32_t gp = (uint32_t)(c.depth - L);
                    Plaintext ptx = cc->MakeCKKSPackedPlaintext(x, 1, 0);
                    auto ct = cc->Encrypt(pk2.secretKey, ptx);   // ★ 비밀키 암호화, 레벨마다 새로
                    if (gp > 0) ct = cc->LevelReduce(ct, nullptr, gp);
                    auto prow = [&](const char* path, const std::vector<double>& got,
                                    const std::vector<double>& want) {
                        pcsv << "openfhe," << c.exp << "," << c.logN << "," << c.q0 << "," << c.delta
                             << "," << c.depth << "," << dnum << "," << pCount << "," << logP << ","
                             << maxDigitBits << "," << L << "," << path << "," << rep << ","
                             << std::fixed << std::setprecision(4)
                             << precision_common::precision_bits(got, want) << "\n";
                    };
                    prow("enc_dec", dec(ct), x);
                    prow("rot1", dec(cc->EvalRotate(ct, 1)), want_rot);
                }
                pcsv.flush();
            }
        }
    }
    csv.close();
    if (pcsv.is_open()) pcsv.close();
    if (vcsv.is_open()) vcsv.close();
    std::cerr << "wrote " << out << (wantPrec ? (" + " + precout) : "") << "\n";
    return 0;
}
