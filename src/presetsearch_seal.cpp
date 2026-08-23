// presetsearch_seal.cpp — 프리셋 확정을 위한 탐색 측정 (SEAL). 본측정 아님.
//
// ⚠️ SEAL은 P가 자유 변수가 아니다. RNS key-switch가 특수소수 **1개** 구조라
// logP = 60 한 점뿐이고 dnum도 해당 레벨의 Q 프라임 수로 종속 결정된다.
// 따라서 실험 1에서 SEAL은 스윕이 아니라 1점이고, 실험 2에서도 logP를 120으로
// 맞출 수 없다(OpenFHE·Lattigo는 120). 이 비대칭은 결과 해석에 반드시 명시할 것.
//
// 측정 로직은 seal_bench.cpp 그대로:
//   - measure(): warmup 후 reps회, 연산 1회만 타이밍, steady_clock, ns→μs, 표본표준편차(n-1)
//   - 레벨 진입: mod_switch_to_inplace (스케일 불변). chain_index 가 잔여 예산과 1:1
//   - relin 직접 계측: size-3 를 타이머 밖에서 만들고 out-of-place relinearize 반복
#include "precision_common.h"
#include "seal/seal.h"

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

using namespace seal;
using namespace std;

static int TC128Bound(int logN)
{
    switch (logN) { case 13: return 218; case 14: return 438; case 15: return 881; }
    return -1;
}

static pair<double, double> measure(int reps, int warmup, const function<void()>& fn)
{
    for (int i = 0; i < warmup; i++) fn();
    vector<double> ts(reps);
    for (int i = 0; i < reps; i++) {
        auto t0 = chrono::steady_clock::now();
        fn();
        auto t1 = chrono::steady_clock::now();
        ts[i] = chrono::duration<double, nano>(t1 - t0).count() / 1000.0;
    }
    double sum = 0;
    for (double x : ts) sum += x;
    double mean = sum / reps, sd = 0.0;
    if (reps > 1) {
        double ss = 0;
        for (double x : ts) { double d = x - mean; ss += d * d; }
        sd = sqrt(ss / (reps - 1));
    }
    return {mean, sd};
}

// 파괴적(in-place) 연산용 배치 계측 — presetsearch_openfhe.cpp 와 동일 규약.
// 타이머 밖에서 K개 사본을 준비(reset)하고 타이머 안에서 K회 수행(runK)한 뒤 K로 나눈다.
// ⚠️ rep 값이 "K회 평균"이라 std 의 의미가 단발 계측과 다르다(CSV rep_mode 열로 구분).
static pair<double, double> measure_batch(int reps, int warmup, int K,
                                          const function<void()>& reset,
                                          const function<void()>& runK)
{
    for (int i = 0; i < warmup; i++) { reset(); runK(); }
    vector<double> ts(reps);
    for (int i = 0; i < reps; i++) {
        reset();
        auto t0 = chrono::steady_clock::now();
        runK();
        auto t1 = chrono::steady_clock::now();
        ts[i] = chrono::duration<double, nano>(t1 - t0).count() / 1000.0 / K;
    }
    double sum = 0;
    for (double x : ts) sum += x;
    double mean = sum / reps, sd = 0.0;
    if (reps > 1) {
        double ss = 0;
        for (double x : ts) { double d = x - mean; ss += d * d; }
        sd = sqrt(ss / (reps - 1));
    }
    return {mean, sd};
}

static int batch_k_for(int logN, int level, long budget_bytes, int kmax)
{
    const double ct_bytes = 2.0 * (level + 1) * (double)(1u << logN) * 8.0;
    int k = (int)(budget_bytes / ct_bytes);
    if (k < 4) k = 4;
    if (k > kmax) k = kmax;
    return k;
}

int main(int argc, char** argv)
{
    int expSel = 1, reps = 30, warmup = 3, precreps = 5;
    string out = "timing.csv", precout = "precision.csv", spec, thlabel = "1t";
    string verifyout = "";
    long batchbudget = 64L * 1024 * 1024;
    int  batchkmax = 2048;
    for (int i = 1; i < argc; i++) {
        string a = argv[i];
        if (a == "-exp" && i + 1 < argc) expSel = stoi(argv[++i]);
        else if (a == "-reps" && i + 1 < argc) reps = stoi(argv[++i]);
        else if (a == "-warmup" && i + 1 < argc) warmup = stoi(argv[++i]);
        else if (a == "-precreps" && i + 1 < argc) precreps = stoi(argv[++i]);
        else if (a == "-out" && i + 1 < argc) out = argv[++i];
        else if (a == "-precout" && i + 1 < argc) precout = argv[++i];
        else if (a == "-mainrun" && i + 1 < argc) { spec = argv[++i]; expSel = 7; }
        // -hexlrun "logN:depth:delta" → HEXL 아암 최소 규모 (exp 8)
        else if (a == "-hexlrun" && i + 1 < argc) { spec = argv[++i]; expSel = 8; }
        // -leveldrop "logN:depth:delta" → 순수 레벨 강하 전용 (exp 9). 8-op 경로와 분리.
        else if (a == "-leveldrop" && i + 1 < argc) { spec = argv[++i]; expSel = 9; }
        else if (a == "-verifyout" && i + 1 < argc) verifyout = argv[++i];
        else if (a == "-batchbudget" && i + 1 < argc) batchbudget = stol(argv[++i]);
        else if (a == "-batchkmax" && i + 1 < argc) batchkmax = stoi(argv[++i]);
        else if (a == "-threads" && i + 1 < argc) thlabel = argv[++i];
    }

    int logN = 15, depth = 13;
    const int q0 = 60, P_BITS = 60;
    vector<int> deltas;
    vector<int> levels;
    vector<string> ops;
    if (expSel == 1) {
        deltas = {40};                       // SEAL은 P 선택지가 없어 1점
        levels = {13, 7, 1};
        ops = {"mul_cc", "mul_cc_rlk", "relin", "rot1"};
    } else if (expSel == 2) {
        for (int d = 40; d <= 50; d++) deltas.push_back(d);
        levels = {13};
        ops = {"add_cc", "add_cp", "mul_cp", "mul_cc", "mul_cc_rlk", "relin", "rescale", "rot1"};
    } else if (expSel == 8) {
        // HEXL 아암(2026-08-02). OFF baseline 과 다른 질문에 답하는 별도 측정 →
        // 전수 스윕 없이 레벨 3점(maxLevel / 중간 / L1) × heavy 3종만 본다.
        // 정밀도는 maxLevel 한 점. 측정 코드 경로는 exp 5/7 과 동일하다.
        int ln = 0, dp = 0, dl = 0;
        if (sscanf(spec.c_str(), "%d:%d:%d", &ln, &dp, &dl) != 3) {
            cerr << "-hexlrun 파싱 실패: " << spec << "\n"; return 2;
        }
        logN = ln; depth = dp; deltas = {dl};
        levels = {depth, depth / 2, 1};
        ops = {"mul_cc_rlk", "relin", "rot1"};
    } else if (expSel == 9) {
        // 순수 레벨 강하 전용. 기존 8-op 경로는 건드리지 않는다.
        int ln = 0, dp = 0, dl = 0;
        if (sscanf(spec.c_str(), "%d:%d:%d", &ln, &dp, &dl) != 3) {
            cerr << "-leveldrop 파싱 실패: " << spec << "\n"; return 2;
        }
        logN = ln; depth = dp; deltas = {dl};
        for (int L = depth; L >= 1; L--) levels.push_back(L);
        ops = {"leveldrop", "leveldrop_ip", "leveldrop_oop", "clone_only"};
    } else if (expSel == 7) {
        int ln = 0, dp = 0, dl = 0;
        if (sscanf(spec.c_str(), "%d:%d:%d", &ln, &dp, &dl) != 3) {
            cerr << "-mainrun 파싱 실패: " << spec << "\n"; return 2;
        }
        logN = ln; depth = dp; deltas = {dl};
        for (int L = depth; L >= 1; L--) levels.push_back(L);
        ops = {"add_cc", "add_cp", "mul_cp", "mul_cc", "mul_cc_rlk", "relin", "rescale", "rot1"};
    } else if (expSel == 5) {
        // v3 본측정: Δ42 depth12. SEAL 은 P 가 구조상 60 고정 (logQP 624, 여유 257).
        depth = 12;
        deltas = {42};
        for (int L = depth; L >= 1; L--) levels.push_back(L);
        ops = {"add_cc", "add_cp", "mul_cp", "mul_cc", "mul_cc_rlk", "relin", "rescale", "rot1"};
    } else {
        // 본측정: 확정 프리셋. SEAL은 P가 구조상 60 고정이라 선택 여지가 없다.
        deltas = {40};
        for (int L = depth; L >= 1; L--) levels.push_back(L);
        ops = {"add_cc", "add_cp", "mul_cp", "mul_cc", "mul_cc_rlk", "relin", "rescale", "rot1"};
    }

    ofstream csv(out), pcsv;
    // SEAL 은 내부 병렬화가 없다(native/src/seal 전체에 #pragma omp 0건) → nthreads 는 항상 1.
    const int nthreads = 1;
    cerr << "[seal] threads=" << thlabel << " (SEAL 내부 병렬화 없음 → 실사용 1)\n";
    csv << "library,exp,logN,q0,delta,depth,dnum,PCount,logP,logQ,logQP,bound,margin,"
           "maxLevel,level,op,mean_us,std_us,reps,digits,threads,nthreads,ok,err"
        << (expSel == 9 ? ",batch_k,rep_mode\n" : "\n");
    ofstream vcsv;
    if (expSel == 9 && !verifyout.empty()) {
        vcsv.open(verifyout);
        vcsv << "library,logN,depth,delta,dnum,level,level_before,level_after,"
                "scale_before,scale_after,scale_ratio,max_abs_diff,bits_before,bits_after,ok\n";
    }
    csv << fixed;
    const bool wantPrec = (expSel == 1 || expSel == 3 || expSel == 5 || expSel == 7 || expSel == 8);
    if (wantPrec) {
        pcsv.open(precout);
        pcsv << "library,exp,logN,q0,delta,depth,dnum,PCount,logP,maxDigitBits,level,path,rep,bits\n";
    }

    for (int delta : deltas) {
        const size_t N = size_t(1) << logN;
        vector<int> bits = {q0};
        for (int i = 0; i < depth; i++) bits.push_back(delta);
        bits.push_back(P_BITS);

        EncryptionParameters parms(scheme_type::ckks);
        parms.set_poly_modulus_degree(N);
        try { parms.set_coeff_modulus(CoeffModulus::Create(N, bits)); }
        catch (const exception& e) {
            string err = e.what();
            for (auto& ch : err) if (ch == ',' || ch == '\n') ch = ' ';
            csv << "seal," << expSel << "," << logN << "," << q0 << "," << delta << "," << depth
                << ",,,,,,,,,,,,,," << thlabel << "," << nthreads << ",0," << err << "\n";
            continue;
        }
        SEALContext ctx(parms, true, sec_level_type::none);
        if (!ctx.parameters_set()) {
            csv << "seal," << expSel << "," << logN << "," << q0 << "," << delta << "," << depth
                << ",,,,,,,,,,,,,," << thlabel << "," << nthreads << ",0," << ctx.parameter_error_message() << "\n";
            continue;
        }

        // 런타임 값에서 뽑는다. 명목 비트(round(log2)) — 세 라이브러리 관례 통일.
        const auto& coeff = parms.coeff_modulus();
        auto nominal = [](const Modulus& m) { return (int)llround(log2((double)m.value())); };
        int logQ = 0;
        for (size_t i = 0; i + 1 < coeff.size(); i++) logQ += nominal(coeff[i]);
        const int logP = nominal(coeff.back());
        const size_t pCount = 1;
        int maxDigitBits = 0;
        for (size_t i = 0; i + 1 < coeff.size(); i++)
            maxDigitBits = max(maxDigitBits, nominal(coeff[i]));
        const size_t dnum = coeff.size() - 1;   // digit = Q 프라임 1개씩
        const int bound = TC128Bound(logN), logQP = logQ + logP, margin = bound - logQP;
        // SEAL digit 수 = 해당 레벨의 Q 프라임 수 = level+1
        ostringstream ds;
        for (int L = depth; L >= 1; L--) { if (L != depth) ds << ";"; ds << "L" << L << "=" << (L + 1); }
        const string digits = ds.str();

        cerr << "[seal exp" << expSel << "] Δ=" << delta << " dnum=" << dnum
             << " logP=" << logP << " logQP=" << logQP << " 여유=" << margin << "\n";

        KeyGenerator keygen(ctx);
        SecretKey sk = keygen.secret_key();
        PublicKey pk;   keygen.create_public_key(pk);
        RelinKeys rlk;  keygen.create_relin_keys(rlk);
        GaloisKeys glk; keygen.create_galois_keys(vector<int>{1}, glk);
        Encryptor encryptor(ctx, pk);
        Evaluator evaluator(ctx);
        CKKSEncoder encoder(ctx);
        const double scale = pow(2.0, delta);
        const size_t slots = encoder.slot_count();
        vector<double> msg(slots, 0.5);

        // ══════════════════════════════════════════════════════════════════
        // exp 9 — 순수 레벨 강하(leveldrop). 아래 기존 8-op 루프는 건드리지 않는다.
        //
        // rescale 과 다른 함수다(소스 확인, evaluator.cpp:1382-1414):
        //   rescale_to_next   → mod_switch_scale_to_next  (모듈러스 버리고 **스케일도 나눔**)
        //   mod_switch_to_next→ mod_switch_drop_to_next   ("Modulus switching without scaling",
        //                        evaluator.cpp:1343 에서 destination.scale() = encrypted.scale())
        // ⚠️ SEAL 은 "몇 레벨 내릴지" 인자가 없다 — 1단계 고정이다(mod_switch_to 로 parms_id 를
        //    지정하는 별도 함수가 여러 단계를 담당한다).
        // ⚠️ SEAL 의 in-place 는 out-of-place 보다 **비싸다**: 같은 버퍼면 임시 공간을 잡고
        //    두 번 복사한다(evaluator.cpp:1319-1332, 소스에 TODO 로 명시). O(1) 강하가 없다.
        if (expSel == 9) {
            vector<double> xv, yv;
            precision_common::make_inputs(slots, xv, yv);
            Decryptor decryptor(ctx, sk);
            auto dec = [&](const Ciphertext& z) {
                Plaintext r; decryptor.decrypt(z, r);
                vector<double> v; encoder.decode(r, v); v.resize(slots); return v;
            };
            for (int L : levels) {
                auto cd = ctx.first_context_data();
                while (cd->chain_index() > size_t(L)) cd = cd->next_context_data();
                Plaintext ptx; encoder.encode(xv, scale, ptx);
                Ciphertext ct; encryptor.encrypt(ptx, ct);
                evaluator.mod_switch_to_inplace(ct, cd->parms_id());

                // ---- 검증: 레벨 -1, 스케일 보존, 복호값 불변 ----
                const size_t lvB = ctx.get_context_data(ct.parms_id())->chain_index();
                const double sfB = ct.scale();
                vector<double> vB = dec(ct);
                Ciphertext ctD;
                evaluator.mod_switch_to_next(ct, ctD);
                const size_t lvA = ctx.get_context_data(ctD.parms_id())->chain_index();
                const double sfA = ctD.scale();
                vector<double> vA = dec(ctD);
                double mx = 0.0;
                for (size_t i = 0; i < slots; i++) mx = max(mx, fabs(vB[i] - vA[i]));
                const bool okLv = (lvA + 1 == lvB);
                const double bitsB = precision_common::precision_bits(vB, xv);
                const double bitsA = precision_common::precision_bits(vA, xv);
                if (!okLv)
                    cerr << "  !! L=" << L << " 레벨이 1 줄지 않았다 (" << lvB << " -> " << lvA << ")\n";
                if (vcsv.is_open())
                    vcsv << "seal," << logN << "," << depth << "," << delta << "," << dnum << ","
                         << L << "," << lvB << "," << lvA << ","
                         << setprecision(17) << sfB << "," << sfA << ","
                         << (sfB > 0 ? sfA / sfB : 0.0) << ","
                         << setprecision(6) << mx << "," << bitsB << "," << bitsA << ","
                         << (okLv ? 1 : 0) << "\n";
                csv << setprecision(3);

                const auto emit = [&](const char* op, pair<double,double> r, int bk, const char* rm) {
                    csv << "seal," << expSel << "," << logN << "," << q0 << "," << delta << ","
                        << depth << "," << dnum << "," << pCount << "," << logP << "," << logQ
                        << "," << logQP << "," << bound << "," << margin << "," << depth << ","
                        << L << "," << op << "," << r.first << "," << r.second << "," << reps
                        << "," << digits << "," << thlabel << "," << nthreads << ",1,,"
                        << bk << "," << rm << "\n";
                };

                // ---- 계측 1: out-of-place. SEAL 의 표준형이자 **가장 싼** 강하 방법이다 ----
                Ciphertext dstD;
                auto rOop = measure(reps, warmup, [&]{ evaluator.mod_switch_to_next(ct, dstD); });

                // ---- 계측 2(분해용): 암호문 깊은 복사만 ----
                Ciphertext dstC;
                auto rCl = measure(reps, warmup, [&]{ dstC = ct; });

                // ---- 계측 3: in-place. 파괴적이라 K개 사본을 타이머 밖에서 준비한다 ----
                const int K = batch_k_for(logN, L, batchbudget, batchkmax);
                vector<Ciphertext> pool(K);
                auto reset = [&]{ for (int i = 0; i < K; i++) pool[i] = ct; };
                auto runK  = [&]{ for (int i = 0; i < K; i++) evaluator.mod_switch_to_next_inplace(pool[i]); };
                auto rIp = measure_batch(reps, warmup, K, reset, runK);
                if (ctx.get_context_data(pool[0].parms_id())->chain_index() + 1 != lvB)
                    cerr << "  !! L=" << L << " in-place 강하가 레벨을 바꾸지 않았다\n";

                // SEAL 은 O(1) 강하가 없고 in-place 가 오히려 더 비싸다(임시 버퍼 + 2회 복사)
                // → **out-of-place 가 가장 싼 방법**이므로 leveldrop == leveldrop_oop.
                emit("leveldrop", rOop, 1, "single");
                emit("leveldrop_ip", rIp, K, "batch");
                emit("leveldrop_oop", rOop, 1, "single");
                emit("clone_only", rCl, 1, "single");
                csv.flush();
                if (vcsv.is_open()) vcsv.flush();
                cerr << "  L=" << L << " leveldrop(oop)=" << rOop.first << "us"
                     << " ip=" << rIp.first << "us(K=" << K << ")"
                     << " clone=" << rCl.first << "us"
                     << " lv " << lvB << "->" << lvA
                     << " scale " << (sfB > 0 ? sfA / sfB : 0.0)
                     << " maxdiff " << mx << "\n";
            }
            continue;   // 기존 8-op 루프·정밀도 블록을 건너뛴다
        }

        for (int L : levels) {
            auto cd = ctx.first_context_data();
            while (cd->chain_index() > size_t(L)) cd = cd->next_context_data();
            Plaintext pt; encoder.encode(msg, scale, pt);
            Ciphertext a, b;
            encryptor.encrypt(pt, a);
            encryptor.encrypt(pt, b);
            evaluator.mod_switch_to_inplace(a, cd->parms_id());
            evaluator.mod_switch_to_inplace(b, cd->parms_id());
            Plaintext pt_lv; encoder.encode(msg, a.parms_id(), a.scale(), pt_lv);
            Ciphertext dst;

            vector<pair<string, pair<double, double>>> res;
            for (const auto& op : ops) {
                if (op == "add_cc") res.push_back({op, measure(reps, warmup, [&]{ evaluator.add(a, b, dst); })});
                else if (op == "add_cp") res.push_back({op, measure(reps, warmup, [&]{ evaluator.add_plain(a, pt_lv, dst); })});
                else if (op == "mul_cp") res.push_back({op, measure(reps, warmup, [&]{ evaluator.multiply_plain(a, pt_lv, dst); })});
                else if (op == "mul_cc") res.push_back({op, measure(reps, warmup, [&]{ evaluator.multiply(a, b, dst); })});
                else if (op == "mul_cc_rlk") res.push_back({op, measure(reps, warmup, [&]{
                    evaluator.multiply(a, b, dst); evaluator.relinearize_inplace(dst, rlk); })});
                else if (op == "rescale") res.push_back({op, measure(reps, warmup, [&]{ evaluator.rescale_to_next(a, dst); })});
                else if (op == "rot1") res.push_back({op, measure(reps, warmup, [&]{ evaluator.rotate_vector(a, 1, glk, dst); })});
            }
            // relin 직접 계측 — 다른 op 뒤에.
            for (const auto& op : ops) if (op == "relin") {
                Ciphertext prod3; evaluator.multiply(a, b, prod3);
                res.push_back({"relin", measure(reps, warmup, [&]{ evaluator.relinearize(prod3, rlk, dst); })});
            }

            for (const auto& op : ops)
                for (auto& r : res)
                    if (r.first == op)
                        csv << "seal," << expSel << "," << logN << "," << q0 << "," << delta << ","
                            << depth << "," << dnum << "," << pCount << "," << logP << "," << logQ
                            << "," << logQP << "," << bound << "," << margin << "," << depth << ","
                            << L << "," << op << "," << setprecision(3) << r.second.first << ","
                            << r.second.second << "," << reps << "," << digits << "," << thlabel << "," << nthreads << ",1,\n";
            csv.flush();
            cerr << "  L=" << L << " done\n";
        }

        // ---- 정밀도 : 타이밍이 끝난 뒤, 비밀키 암호화 ----
        // ★ 각 레벨에서 새로 암호화한 뒤 mod_switch 로 그 레벨에 진입한다 —
        //   암호문을 레벨 따라 끌고 내려가면 누적 노이즈가 섞인다.
        if (wantPrec) {
            vector<double> x, y;
            precision_common::make_inputs(slots, x, y);
            vector<double> want_rot(slots);
            for (size_t i = 0; i < slots; i++) want_rot[i] = x[(i + 1) % slots];
            for (int rep = 0; rep < precreps; rep++) {
                KeyGenerator kg2(ctx);
                SecretKey sk2 = kg2.secret_key();
                GaloisKeys g2; kg2.create_galois_keys(vector<int>{1}, g2);
                Encryptor enc2(ctx, sk2);
                Decryptor dec2(ctx, sk2);
                Evaluator ev2(ctx);
                auto dec = [&](const Ciphertext& z) {
                    Plaintext r; dec2.decrypt(z, r);
                    vector<double> v; encoder.decode(r, v); v.resize(slots); return v;
                };
                // exp 8(HEXL 아암)은 정밀도를 maxLevel 한 점만 본다.
                for (int L : (expSel == 8 ? vector<int>{depth} : levels)) {
                    auto cdp = ctx.first_context_data();
                    while (cdp->chain_index() > size_t(L)) cdp = cdp->next_context_data();
                    Plaintext ptx; encoder.encode(x, scale, ptx);
                    Ciphertext ct; enc2.encrypt_symmetric(ptx, ct);   // 레벨마다 새로 암호화
                    ev2.mod_switch_to_inplace(ct, cdp->parms_id());
                    auto prow = [&](const char* path, const vector<double>& got, const vector<double>& want) {
                        pcsv << "seal," << expSel << "," << logN << "," << q0 << "," << delta << ","
                             << depth << "," << dnum << "," << pCount << "," << logP << ","
                             << maxDigitBits << "," << L << "," << path << "," << rep << ","
                             << fixed << setprecision(4)
                             << precision_common::precision_bits(got, want) << "\n";
                    };
                    prow("enc_dec", dec(ct), x);
                    Ciphertext crot; ev2.rotate_vector(ct, 1, g2, crot);
                    prow("rot1", dec(crot), want_rot);
                }
                pcsv.flush();
            }
        }
    }
    csv.close();
    if (pcsv.is_open()) pcsv.close();
    if (vcsv.is_open()) vcsv.close();
    cerr << "wrote " << out << "\n";
    return 0;
}
