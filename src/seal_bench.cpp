// seal_bench.cpp — CKKS 8-op latency benchmark for Microsoft SEAL 4.3.x
//
// Mirrors the measurement rules in PROJECT_CONTEXT.md §4:
//   - std::chrono::steady_clock only
//   - level = "remaining multiplicative budget" (SEAL chain_index maps 1:1, no conversion)
//   - timer wraps ONE operation; keygen/encode/output alloc stay outside
//   - out-of-place forms only, so input ciphertexts are never mutated across reps
//   - per-repetition timing recorded individually (mean + sample stddev, n-1), unit us
//
// Chain construction (verified against SEAL 4.3.3):
//   coeff_modulus = { firstMod, scale x maxLevel, P }
//   -> first element is the BOTTOM prime that survives all rescales (== OpenFHE firstModSize)
//   -> last element is the single special prime P used for key switching
//   -> rescale drops scale primes from the end; chain_index goes maxLevel .. 0

#include "seal/seal.h"
#include <chrono>
#include <cmath>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <string>
#include <vector>

using namespace std;
using namespace seal;

struct Preset { string name; size_t logN; int firstMod; int maxLevel; int scaleBits; };

static const Preset PRESETS[] = {
    {"small",  13, 50,  5, 45},
    {"medium", 14, 55, 10, 45},
    {"large",  15, 60, 15, 45},
};
static const int P_BITS = 60;  // single special prime; see NOTE in SEAL_TASK.md

struct Stat { double mean_us, std_us; };

static Stat summarize(const vector<double> &xs)
{
    double s = 0; for (double x : xs) s += x;
    double m = s / xs.size();
    double v = 0; for (double x : xs) v += (x - m) * (x - m);
    v = xs.size() > 1 ? v / (xs.size() - 1) : 0.0;   // sample stddev, n-1
    return {m, sqrt(v)};
}

// Time `fn` for `reps` iterations after `warmup`, recording EVERY repetition.
template <typename F>
static Stat measure(int reps, int warmup, F &&fn)
{
    for (int i = 0; i < warmup; i++) fn();
    vector<double> samples;
    samples.reserve(reps);
    for (int i = 0; i < reps; i++) {
        auto t0 = chrono::steady_clock::now();
        fn();
        auto t1 = chrono::steady_clock::now();
        samples.push_back(chrono::duration<double, nano>(t1 - t0).count() / 1000.0);
    }
    return summarize(samples);
}

int main(int argc, char **argv)
{
    string preset_name = "small", out_path = "", machine = "unknown", thread_tag = "1t";
    string sweep = "desc";
    int reps = 30, warmup = 3, warmsec = 30;

    for (int i = 1; i < argc - 1; i++) {
        if (!strcmp(argv[i], "-preset"))  preset_name = argv[++i];
        else if (!strcmp(argv[i], "-reps"))    reps = atoi(argv[++i]);
        else if (!strcmp(argv[i], "-warmup"))  warmup = atoi(argv[++i]);
        // 전역 웜업(초). op별 warmup 3회로는 머신이 안 데워진다 — 실측으로
        // 실행 초반이 약 1.67배 부풀려지는 것을 확인했다. 스윕이 maxLevel에서
        // 시작하므로 높은 레벨만 선택적으로 오염되고, 레벨-지연 기울기가
        // 가짜로 가팔라진다. 0이면 전역 웜업 없음(오염 재현용).
        else if (!strcmp(argv[i], "-warmsec")) warmsec = atoi(argv[++i]);
        // 스윕 방향. asc/desc 결과가 일치하면 웜업이 충분하다는 뜻이다
        // (오염이 남아 있으면 먼저 도는 쪽이 느리게 나오므로 방향에 따라 갈린다).
        else if (!strcmp(argv[i], "-sweep"))   sweep = argv[++i];
        else if (!strcmp(argv[i], "-out"))     out_path = argv[++i];
        else if (!strcmp(argv[i], "-machine")) machine = argv[++i];
        else if (!strcmp(argv[i], "-threads")) thread_tag = argv[++i];
    }
    if (sweep != "asc" && sweep != "desc") { cerr << "unknown -sweep: " << sweep << "\n"; return 1; }

    const Preset *P = nullptr;
    for (auto &p : PRESETS) if (p.name == preset_name) P = &p;
    if (!P) { cerr << "unknown preset: " << preset_name << "\n"; return 1; }

    // ---- parameters ----
    size_t N = size_t(1) << P->logN;
    vector<int> bit_sizes;
    bit_sizes.push_back(P->firstMod);
    for (int i = 0; i < P->maxLevel; i++) bit_sizes.push_back(P->scaleBits);
    bit_sizes.push_back(P_BITS);

    EncryptionParameters parms(scheme_type::ckks);
    parms.set_poly_modulus_degree(N);
    parms.set_coeff_modulus(CoeffModulus::Create(N, bit_sizes));

    // sec_level_type::none == OpenFHE HEStd_NotSet. Security is NOT validated;
    // this is the intended limitation for like-for-like relative comparison.
    SEALContext ctx(parms, true, sec_level_type::none);
    if (!ctx.parameters_set()) { cerr << ctx.parameter_error_message() << "\n"; return 1; }

    KeyGenerator keygen(ctx);
    SecretKey sk = keygen.secret_key();
    PublicKey pk;   keygen.create_public_key(pk);
    RelinKeys rlk;  keygen.create_relin_keys(rlk);
    GaloisKeys glk; keygen.create_galois_keys(vector<int>{1}, glk);   // step 1 only

    Encryptor encryptor(ctx, pk);
    Evaluator evaluator(ctx);
    CKKSEncoder encoder(ctx);

    double scale = pow(2.0, P->scaleBits);
    vector<double> msg(encoder.slot_count(), 1.5);

    // ---- 전역 웜업 ----
    // 스윕 시작 전에 벽시계 기준 고정 시간 동안 대표 연산(key-switch 포함)을 돌려
    // 머신을 정상 상태로 올린다. 측정 대상이 아니므로 결과는 버린다.
    // 진단 출력은 stderr로 — stdout은 -out 없을 때 CSV가 나가는 통로다.
    if (warmsec > 0) {
        Plaintext pt_w; encoder.encode(msg, scale, pt_w);
        Ciphertext wa, wb, wdst;
        encryptor.encrypt(pt_w, wa);
        encryptor.encrypt(pt_w, wb);
        auto t_start = chrono::steady_clock::now();
        long iters = 0;
        while (chrono::duration<double>(chrono::steady_clock::now() - t_start).count() < warmsec) {
            evaluator.add(wa, wb, wdst);
            evaluator.multiply(wa, wb, wdst);
            evaluator.relinearize_inplace(wdst, rlk);
            evaluator.rotate_vector(wa, 1, glk, wdst);
            iters++;
        }
        double el = chrono::duration<double>(chrono::steady_clock::now() - t_start).count();
        cerr << "[warmup] " << P->name << " " << el << " s, " << iters << " iters (target "
             << warmsec << " s)\n";
    } else {
        cerr << "[warmup] DISABLED (-warmsec 0)\n";
    }

    ofstream fout;
    ostream &os = out_path.empty() ? cout : (fout.open(out_path), fout);
    os << "library,preset,logN,maxLevel,level,op,mean_us,std_us,reps\n";
    os << fixed << setprecision(3);

    auto emit = [&](int level, const char *op, Stat s) {
        os << "seal," << P->name << "," << P->logN << "," << P->maxLevel << ","
           << level << "," << op << "," << s.mean_us << "," << s.std_us << ","
           << reps << "\n";
    };

    // ---- level sweep: desc = maxLevel..1 (기본), asc = 1..maxLevel ----
    vector<int> sweep_levels;
    if (sweep == "desc") for (int l = P->maxLevel; l >= 1; l--) sweep_levels.push_back(l);
    else                 for (int l = 1; l <= P->maxLevel; l++) sweep_levels.push_back(l);

    for (int level : sweep_levels) {
        // locate the parms_id for this level
        auto cd = ctx.first_context_data();
        while (cd->chain_index() > size_t(level)) cd = cd->next_context_data();

        // operands prepared OUTSIDE the timer, at the target level
        Plaintext pt; encoder.encode(msg, scale, pt);
        Ciphertext a, b;
        encryptor.encrypt(pt, a);
        encryptor.encrypt(pt, b);
        evaluator.mod_switch_to_inplace(a, cd->parms_id());
        evaluator.mod_switch_to_inplace(b, cd->parms_id());

        // plaintext operand MUST match both parms_id and scale, or SEAL throws "scale mismatch"
        Plaintext pt_lv;
        encoder.encode(msg, a.parms_id(), a.scale(), pt_lv);

        // size-3 ciphertext for the standalone relin measurement, built outside the timer
        Ciphertext prod3;
        evaluator.multiply(a, b, prod3);

        Ciphertext dst;   // reused output buffer; every op below is out-of-place

        emit(level, "add_cc",  measure(reps, warmup, [&]{ evaluator.add(a, b, dst); }));
        emit(level, "add_cp",  measure(reps, warmup, [&]{ evaluator.add_plain(a, pt_lv, dst); }));
        emit(level, "mul_cp",  measure(reps, warmup, [&]{ evaluator.multiply_plain(a, pt_lv, dst); }));
        emit(level, "mul_cc",  measure(reps, warmup, [&]{ evaluator.multiply(a, b, dst); }));
        emit(level, "mul_cc_rlk", measure(reps, warmup, [&]{
            evaluator.multiply(a, b, dst);
            evaluator.relinearize_inplace(dst, rlk);
        }));
        emit(level, "relin",   measure(reps, warmup, [&]{ evaluator.relinearize(prod3, rlk, dst); }));
        emit(level, "rescale", measure(reps, warmup, [&]{ evaluator.rescale_to_next(a, dst); }));
        emit(level, "rot1",    measure(reps, warmup, [&]{ evaluator.rotate_vector(a, 1, glk, dst); }));
    }

    if (fout.is_open()) fout.close();
    return 0;
}
