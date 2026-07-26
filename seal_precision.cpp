// seal_precision.cpp — SEAL CKKS 정밀도 검증 (측정 아님, 게이트)
//
// PROJECT_CONTEXT.md §5.1의 교훈: 지연시간만 재면 "틀린 계산의 소요 시간"을 재고도 모른다.
// OpenFHE에서 예외 없이 무의미한 값을 반환하면서 정상적인 지연시간과 정상적인 정성
// 패턴을 보인 이력이 있다. 그래서 본측정 전에 이 게이트를 반드시 통과시킨다.
//
// 방법: 알려진 값 암호화 → 연산 → 복호화 → 기대값과 비교 → -log2(mean|err|) 비트 수.
// 기대: scale 45에서 33~34비트 근처 (SEAL_TASK.md §0 표).
// 크게 벗어나면 체인 매핑이 틀린 것이므로 측정을 진행하면 안 된다.
//
// 체인 구성은 seal_bench.cpp와 **반드시 동일**해야 한다. 여기서 검증한 것이
// 벤치가 실제로 도는 체인이 아니면 게이트 자체가 무의미하기 때문이다.
//   coeff_modulus = { firstMod, scale x maxLevel, P }
//   -> 첫 원소 = 끝까지 살아남는 바닥 프라임 (OpenFHE firstModSize와 같은 역할)
//   -> 마지막 원소 = key switching용 단일 특수 소수 P
//   -> chain_index가 잔여 곱셈 예산과 1:1 (OpenFHE식 maxLevel - GetLevel() 변환 불필요)

#include "seal/seal.h"
#include <cmath>
#include <cstring>
#include <iomanip>
#include <cstdio>
#include <iostream>
#include "precision_common.h"
#include <random>
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
static const int P_BITS = 60;  // 단일 특수 소수; SEAL_TASK.md §2 참조

// -log2(mean|err|). 오차가 0이면(있을 수 없지만) inf 대신 큰 수를 피하려고 클램프.
static double precision_bits(const vector<double> &got, const vector<double> &want)
{
    return precision_common::precision_bits(got, want);
}

int main(int argc, char **argv)
{
    string preset_name = "small", levels_mode = "gate";
    int firstmod_override = 0, pbits_override = 0, reps = 1;
    bool csv = false;
    for (int i = 1; i < argc - 1; i++) {
        if (!strcmp(argv[i], "-preset")) preset_name = argv[++i];
        // -levels all: 전 레벨 스윕. §5.2 이등분 격리용 —
        // 어떤 경로가 레벨(=dnum)에 의존하고 어떤 경로가 N에만 의존하는지 가른다.
        else if (!strcmp(argv[i], "-levels")) levels_mode = argv[++i];
        // 진단 전용 오버라이드. 본측정에 쓰면 안 된다(§3 체인 정합이 깨진다).
        // rot1 정밀도가 바닥 프라임/P 비율에 걸려 있는지 가르는 데 쓴다.
        else if (!strcmp(argv[i], "-firstmod")) firstmod_override = atoi(argv[++i]);
        else if (!strcmp(argv[i], "-pbits"))    pbits_override = atoi(argv[++i]);
        else if (!strcmp(argv[i], "-reps"))     reps = atoi(argv[++i]);
    }
    for (int i = 1; i < argc; i++) if (!strcmp(argv[i], "-csv")) csv = true;

    const Preset *P = nullptr;
    for (auto &p : PRESETS) if (p.name == preset_name) P = &p;
    if (!P) { cerr << "unknown preset: " << preset_name << "\n"; return 1; }

    Preset preset_eff = *P;
    if (firstmod_override) preset_eff.firstMod = firstmod_override;
    P = &preset_eff;
    const int p_bits = pbits_override ? pbits_override : P_BITS;
    if (firstmod_override || pbits_override)
        cout << "[DIAGNOSTIC OVERRIDE] firstMod=" << P->firstMod
             << " P=" << p_bits << " -- 본측정용 아님\n";

    // ---- 파라미터: seal_bench.cpp와 동일 ----
    size_t N = size_t(1) << P->logN;
    vector<int> bit_sizes;
    bit_sizes.push_back(P->firstMod);
    for (int i = 0; i < P->maxLevel; i++) bit_sizes.push_back(P->scaleBits);
    bit_sizes.push_back(p_bits);

    EncryptionParameters parms(scheme_type::ckks);
    parms.set_poly_modulus_degree(N);
    parms.set_coeff_modulus(CoeffModulus::Create(N, bit_sizes));

    // sec_level_type::none == OpenFHE HEStd_NotSet. 보안 미검증 — 상대 비교 목적의 의도된 한계.
    SEALContext ctx(parms, true, sec_level_type::none);
    if (!ctx.parameters_set()) { cerr << ctx.parameter_error_message() << "\n"; return 1; }

    Evaluator evaluator(ctx);
    CKKSEncoder encoder(ctx);

    const double scale = pow(2.0, P->scaleBits);
    const size_t slots = encoder.slot_count();

    // ================= 체인 walk =================
    // 레벨별로 어떤 프라임이 살아있는지 눈으로 확인한다. §3 정합 기준(Q 비트 단위 일치)이
    // 실제로 성립하는지 여기서 드러난다.
    cout << "=== chain walk: preset=" << P->name << " logN=" << P->logN
         << " N=" << N << " slots=" << slots
         << " maxLevel=" << P->maxLevel << " scale=2^" << P->scaleBits << " ===\n";
    cout << "requested bit_sizes = {";
    for (size_t i = 0; i < bit_sizes.size(); i++)
        cout << bit_sizes[i] << (i + 1 < bit_sizes.size() ? "," : "");
    cout << "}  (first=bottom prime, last=special prime P)\n";

    {
        auto kd = ctx.key_context_data();
        cout << "key_context_data  chain_index=" << kd->chain_index() << "  primes(bits)= [";
        int total = 0;
        for (auto &m : kd->parms().coeff_modulus()) {
            cout << " " << m.bit_count();
            total += m.bit_count();
        }
        cout << " ]  logQP=" << total << "\n";
    }
    for (auto cd = ctx.first_context_data(); cd; cd = cd->next_context_data()) {
        cout << "  level " << setw(2) << cd->chain_index() << "  primes(bits)= [";
        int total = 0;
        for (auto &m : cd->parms().coeff_modulus()) {
            cout << " " << m.bit_count();
            total += m.bit_count();
        }
        cout << " ]  logQ=" << total
             << "  data_primes=" << cd->parms().coeff_modulus().size() << "\n";
    }
    cout << "\n";

    // ================= 정밀도 =================
    // 입력 벡터는 precision_common.h 규약 — 세 라이브러리가 동일한 수열을 쓴다.
    vector<double> x, y;
    precision_common::make_inputs(slots, x, y);

    cout << "=== precision: -log2(mean|err|), expect ~33-34 bits at scale 2^45 ===\n";
    cout << left << setw(8) << "preset" << setw(7) << "level"
         << setw(26) << "path" << "bits\n";

    // maxLevel과 level 1 두 지점에서 본다. 체인 매핑이 틀리면 보통 바닥 근처에서 먼저 터진다.
    vector<int> levels;
    if (levels_mode == "all") { for (int l = P->maxLevel; l >= 1; l--) levels.push_back(l); }
    else                      { levels = {P->maxLevel, 1}; }
    bool fail = false;
    if (csv) cout << "library,preset,logN,maxLevel,level,path,rep,bits\n";

    for (int rep = 0; rep < reps; rep++) {
    // 반복마다 키 재생성 — 비밀키·암호화 오차 표본이 산포의 원천이다.
    KeyGenerator keygen(ctx);
    SecretKey sk = keygen.secret_key();
    PublicKey pk;   keygen.create_public_key(pk);
    RelinKeys rlk;  keygen.create_relin_keys(rlk);
    GaloisKeys glk; keygen.create_galois_keys(vector<int>{1}, glk);
    Encryptor encryptor(ctx, pk);
    Decryptor decryptor(ctx, sk);

    for (int level : levels) {
        // 해당 레벨의 parms_id 찾기
        auto cd = ctx.first_context_data();
        while (cd->chain_index() > size_t(level)) cd = cd->next_context_data();

        Plaintext pt_x, pt_y;
        encoder.encode(x, scale, pt_x);
        encoder.encode(y, scale, pt_y);
        Ciphertext ct_x, ct_y;
        encryptor.encrypt(pt_x, ct_x);
        encryptor.encrypt(pt_y, ct_y);
        // 레벨 진입은 mod_switch (rescale 반복 아님) — scale 드리프트 회피
        evaluator.mod_switch_to_inplace(ct_x, cd->parms_id());
        evaluator.mod_switch_to_inplace(ct_y, cd->parms_id());

        // 평문 피연산자는 parms_id와 scale이 암호문과 정확히 일치해야 한다.
        // 아니면 SEAL이 "scale mismatch" 예외를 던진다 (SEAL_TASK.md §0 최대 함정).
        Plaintext pt_y_lv;
        encoder.encode(y, ct_x.parms_id(), ct_x.scale(), pt_y_lv);

        auto dec = [&](const Ciphertext &c) {
            Plaintext p; decryptor.decrypt(c, p);
            vector<double> v; encoder.decode(p, v);
            v.resize(slots);
            return v;
        };
        auto report = [&](const char *path, const vector<double> &got,
                          const vector<double> &want) {
            double b = precision_bits(got, want);
            if (csv) {
                printf("seal,%s,%d,%d,%d,%s,%d,%.4f\n", P->name.c_str(), (int)P->logN,
                       P->maxLevel, level, path, rep, b);
            } else {
                cout << left << setw(8) << P->name << setw(7) << level
                     << setw(26) << path << fixed << setprecision(2) << b << "\n";
            }
            // 게이트: 33~34 기대. 30 미만이면 체인 매핑 파탄으로 본다.
            if (b < 30.0) fail = true;
        };

        vector<double> want_mul(slots), want_rot(slots);
        for (size_t i = 0; i < slots; i++) want_mul[i] = x[i] * y[i];
        for (size_t i = 0; i < slots; i++) want_rot[i] = x[(i + 1) % slots];

        // 기준선: 연산 없이 암호화→복호화. 여기가 깨지면 연산이 아니라 파라미터 문제다.
        report("enc_dec", dec(ct_x), x);

        // 경로 1: mul_cp + rescale
        {
            Ciphertext c;
            evaluator.multiply_plain(ct_x, pt_y_lv, c);
            evaluator.rescale_to_next_inplace(c);
            report("mul_cp_rs", dec(c), want_mul);
        }
        // 경로 2b: relin 단독 — rescale 없이 KS 노이즈를 그대로 노출
        {
            Ciphertext c3, c;
            evaluator.multiply(ct_x, ct_y, c3);          // size-3, scale^2
            evaluator.relinearize(c3, rlk, c);           // size-2, rescale 안 함
            report("relin", dec(c), want_mul);
        }

        // 경로 2: mul_cc + relin + rescale
        {
            Ciphertext c;
            evaluator.multiply(ct_x, ct_y, c);
            evaluator.relinearize_inplace(c, rlk);
            evaluator.rescale_to_next_inplace(c);
            report("mul_cc_relin_rs", dec(c), want_mul);
        }
        // 경로 3: rot1
        {
            Ciphertext c;
            evaluator.rotate_vector(ct_x, 1, glk, c);
            report("rot1", dec(c), want_rot);
        }
    }

    }  // rep 루프
    if (!csv) cout << "\n" << (fail ? "GATE: FAIL (some path < 30 bits)" : "GATE: PASS") << "\n";
    return fail ? 1 : 0;
}
