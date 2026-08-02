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

int main(int argc, char** argv)
{
    int expSel = 1, reps = 30, warmup = 3, precreps = 5;
    string out = "timing.csv", precout = "precision.csv";
    for (int i = 1; i < argc; i++) {
        string a = argv[i];
        if (a == "-exp" && i + 1 < argc) expSel = stoi(argv[++i]);
        else if (a == "-reps" && i + 1 < argc) reps = stoi(argv[++i]);
        else if (a == "-warmup" && i + 1 < argc) warmup = stoi(argv[++i]);
        else if (a == "-precreps" && i + 1 < argc) precreps = stoi(argv[++i]);
        else if (a == "-out" && i + 1 < argc) out = argv[++i];
        else if (a == "-precout" && i + 1 < argc) precout = argv[++i];
    }

    const int logN = 15, q0 = 60, P_BITS = 60;
    int depth = 13;
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
    csv << "library,exp,logN,q0,delta,depth,dnum,PCount,logP,logQ,logQP,bound,margin,"
           "maxLevel,level,op,mean_us,std_us,reps,digits,ok,err\n";
    csv << fixed;
    const bool wantPrec = (expSel == 1 || expSel == 3 || expSel == 5);
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
                << ",,,,,,,,,,,,,,,0," << err << "\n";
            continue;
        }
        SEALContext ctx(parms, true, sec_level_type::none);
        if (!ctx.parameters_set()) {
            csv << "seal," << expSel << "," << logN << "," << q0 << "," << delta << "," << depth
                << ",,,,,,,,,,,,,,,0," << ctx.parameter_error_message() << "\n";
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
                            << r.second.second << "," << reps << "," << digits << ",1,\n";
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
                for (int L : levels) {
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
    cerr << "wrote " << out << "\n";
    return 0;
}
