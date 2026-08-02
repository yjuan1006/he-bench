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

#include <chrono>
#include <cmath>
#include <cstring>
#include <fstream>
#include <functional>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
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

struct Cfg { int exp, logN, q0, delta, depth; uint32_t dnum; };

int main(int argc, char** argv)
{
    int expSel = 1, reps = 30, warmup = 3, precreps = 5;
    std::string out = "timing.csv", precout = "precision.csv", spec;
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

    std::ofstream csv(out), pcsv;
    csv << "library,exp,logN,q0,delta,depth,dnum,PCount,logP,logQ,logQP,bound,margin,"
           "maxLevel,level,op,mean_us,std_us,reps,digits,ok,err\n";
    csv << std::fixed;
    const bool wantPrec = (expSel == 1 || expSel == 3 || expSel == 5);
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
                << c.depth << "," << c.dnum << ",,,,,,,,,,,,,,0," << err << "\n";
            std::cerr << "[skip] delta=" << c.delta << " dnum=" << c.dnum << ": " << err << "\n";
            continue;
        }
        cc->Enable(PKE); cc->Enable(KEYSWITCH); cc->Enable(LEVELEDSHE); cc->Enable(ADVANCEDSHE);

        // 링 차원이 요청대로인지 확인 — 검사가 켜지면 OpenFHE가 N을 조용히 올린다.
        if (cc->GetRingDimension() != (1u << c.logN)) {
            csv << "openfhe," << c.exp << "," << c.logN << "," << c.q0 << "," << c.delta << ","
                << c.depth << "," << c.dnum << ",,,,,,,,,,,,,,0,ring dim changed\n";
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

        std::vector<int> lv = (c.exp == 6) ? std::vector<int>{c.depth} : levels;
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
                            << "," << reps << "," << digits << ",1,\n";
            csv.flush();
            std::cerr << "  L=" << L << " done\n";
        }

        // ---- 정밀도 : 타이밍이 끝난 뒤 ----
        // 반복마다 키를 새로 만들고(비밀키·암호화 오차 표본이 산포의 원천), 그 안에서 레벨을 훑는다.
        // ★ 각 레벨에서 **새로 암호화**한 뒤 그 레벨로 내린다 — 암호문을 레벨을 따라 끌고
        //   내려가면 누적 노이즈가 섞여 "그 레벨의 KS 손실"이 아니게 된다.
        //   레벨 진입은 스케일 불변 drop(LevelReduce) — ModReduce를 쓰면 스케일까지 나뉜다.
        if (wantPrec) {
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
                for (int L : levels) {
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
    std::cerr << "wrote " << out << (wantPrec ? (" + " + precout) : "") << "\n";
    return 0;
}
