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
    int reps = 30, warmup = 3;

    for (int i = 1; i < argc - 1; i++) {
        if (!strcmp(argv[i], "-preset"))  preset_name = argv[++i];
        else if (!strcmp(argv[i], "-reps"))    reps = atoi(argv[++i]);
        else if (!strcmp(argv[i], "-warmup"))  warmup = atoi(argv[++i]);
        else if (!strcmp(argv[i], "-out"))     out_path = argv[++i];
        else if (!strcmp(argv[i], "-machine")) machine = argv[++i];
        else if (!strcmp(argv[i], "-threads")) thread_tag = argv[++i];
    }

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

    ofstream fout;
    ostream &os = out_path.empty() ? cout : (fout.open(out_path), fout);
    os << "library,machine,threads,preset,logN,level,operation,reps,mean_us,std_us\n";
    os << fixed << setprecision(3);

    auto emit = [&](int level, const char *op, Stat s) {
        os << "seal," << machine << "," << thread_tag << "," << P->name << ","
           << P->logN << "," << level << "," << op << "," << reps << ","
           << s.mean_us << "," << s.std_us << "\n";
    };

    // ---- level sweep: maxLevel .. 1 ----
    for (int level = P->maxLevel; level >= 1; level--) {
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
