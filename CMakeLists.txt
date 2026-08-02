cmake_minimum_required(VERSION 3.16.3)
project(he_bench CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Release 빌드 강제 (-O3 -DNDEBUG). Debug 측정 금지.
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()

# 라이브러리별 타깃을 선택적으로 켠다. 한 빌드 디렉터리에 한 라이브러리만 두는
# 관례(build_openfhe/, build_seal/)라 필요한 쪽만 configure 하면 된다.
option(BENCH_OPENFHE "build openfhe_bench" ON)
option(BENCH_SEAL    "build seal_bench / seal_precision" OFF)

# --------------------------------------------------------------------------
# OpenFHE
# --------------------------------------------------------------------------
# 컴파일 플래그는 전역(CMAKE_CXX_FLAGS)이 아니라 타깃 단위로 건다.
# 전역으로 걸면 SEAL 타깃까지 -fopenmp/-DMATHBACKEND 를 물려받아
# "두 라이브러리를 같은 조건으로 빌드한다"는 전제가 조용히 깨진다.
if(BENCH_OPENFHE)
    find_package(OpenFHE CONFIG REQUIRED)
    if(NOT OpenFHE_FOUND)
        message(FATAL_ERROR "PACKAGE OpenFHE NOT FOUND")
    endif()

    # OpenFHE 권장 플래그를 쓰되 -Werror는 제거 (벤치 코드 경고로 빌드 실패 방지).
    string(REPLACE "-Werror" "" OPENFHE_BENCH_CXX_FLAGS "${OpenFHE_CXX_FLAGS}")
    separate_arguments(OPENFHE_BENCH_CXX_FLAGS_LIST UNIX_COMMAND "${OPENFHE_BENCH_CXX_FLAGS}")

    add_executable(openfhe_bench src/openfhe_bench.cpp)
    target_compile_options(openfhe_bench PRIVATE ${OPENFHE_BENCH_CXX_FLAGS_LIST})
    target_include_directories(openfhe_bench PRIVATE
        ${OPENMP_INCLUDES}
        ${OpenFHE_INCLUDE}
        ${OpenFHE_INCLUDE}/third-party/include
        ${OpenFHE_INCLUDE}/core
        ${OpenFHE_INCLUDE}/pke
        ${OpenFHE_INCLUDE}/binfhe)
    target_link_directories(openfhe_bench PRIVATE ${OpenFHE_LIBDIR} ${OPENMP_LIBRARIES})
    target_link_options(openfhe_bench PRIVATE ${OPENFHE_BENCH_CXX_FLAGS_LIST})
    if(UNIX AND NOT APPLE)
        target_link_options(openfhe_bench PRIVATE -Wl,--no-as-needed)
    endif()
    target_link_libraries(openfhe_bench ${OpenFHE_SHARED_LIBRARIES})

    # 진단 전용 파라미터 덤프. 벤치와 같은 include/link 설정을 그대로 물려준다.
    # (예전에는 수동 g++로 빌드해 루트에 바이너리만 남아 있었다.)
    add_executable(param_dump_openfhe src/param_dump_openfhe.cpp)
    target_compile_options(param_dump_openfhe PRIVATE ${OPENFHE_BENCH_CXX_FLAGS_LIST})
    target_include_directories(param_dump_openfhe PRIVATE
        ${OPENMP_INCLUDES}
        ${OpenFHE_INCLUDE}
        ${OpenFHE_INCLUDE}/third-party/include
        ${OpenFHE_INCLUDE}/core
        ${OpenFHE_INCLUDE}/pke
        ${OpenFHE_INCLUDE}/binfhe)
    target_link_directories(param_dump_openfhe PRIVATE ${OpenFHE_LIBDIR} ${OPENMP_LIBRARIES})
    target_link_options(param_dump_openfhe PRIVATE ${OPENFHE_BENCH_CXX_FLAGS_LIST})
    if(UNIX AND NOT APPLE)
        target_link_options(param_dump_openfhe PRIVATE -Wl,--no-as-needed)
    endif()
    target_link_libraries(param_dump_openfhe ${OpenFHE_SHARED_LIBRARIES})

    # 새 프리셋 후보 key-switch 정밀도 사전 측정 (비밀키 암호화 · rot1 경로).
    add_executable(ksprec_openfhe src/ksprec_openfhe.cpp)
    target_compile_options(ksprec_openfhe PRIVATE ${OPENFHE_BENCH_CXX_FLAGS_LIST})
    target_include_directories(ksprec_openfhe PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/src
        ${OPENMP_INCLUDES}
        ${OpenFHE_INCLUDE}
        ${OpenFHE_INCLUDE}/third-party/include
        ${OpenFHE_INCLUDE}/core
        ${OpenFHE_INCLUDE}/pke
        ${OpenFHE_INCLUDE}/binfhe)
    target_link_directories(ksprec_openfhe PRIVATE ${OpenFHE_LIBDIR} ${OPENMP_LIBRARIES})
    target_link_options(ksprec_openfhe PRIVATE ${OPENFHE_BENCH_CXX_FLAGS_LIST})
    if(UNIX AND NOT APPLE)
        target_link_options(ksprec_openfhe PRIVATE -Wl,--no-as-needed)
    endif()
    target_link_libraries(ksprec_openfhe ${OpenFHE_SHARED_LIBRARIES})

    # 프리셋 확정용 탐색 측정 (P 탐색 · Δ 스윕). 본측정 아님.
    add_executable(presetsearch_openfhe src/presetsearch_openfhe.cpp)
    target_compile_options(presetsearch_openfhe PRIVATE ${OPENFHE_BENCH_CXX_FLAGS_LIST})
    target_include_directories(presetsearch_openfhe PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/src
        ${OPENMP_INCLUDES}
        ${OpenFHE_INCLUDE}
        ${OpenFHE_INCLUDE}/third-party/include
        ${OpenFHE_INCLUDE}/core
        ${OpenFHE_INCLUDE}/pke
        ${OpenFHE_INCLUDE}/binfhe)
    target_link_directories(presetsearch_openfhe PRIVATE ${OpenFHE_LIBDIR} ${OPENMP_LIBRARIES})
    target_link_options(presetsearch_openfhe PRIVATE ${OPENFHE_BENCH_CXX_FLAGS_LIST})
    if(UNIX AND NOT APPLE)
        target_link_options(presetsearch_openfhe PRIVATE -Wl,--no-as-needed)
    endif()
    target_link_libraries(presetsearch_openfhe ${OpenFHE_SHARED_LIBRARIES})
endif()

# --------------------------------------------------------------------------
# Microsoft SEAL
# --------------------------------------------------------------------------
# CMAKE_PREFIX_PATH=third_party/SEAL/install 로 configure 할 것.
# HEXL은 반드시 OFF 상태로 빌드된 SEAL이어야 한다 (docs/PROJECT_CONTEXT.md §2):
# dku16c는 AVX-512가 있어 HEXL을 켜면 SEAL만 부당하게 유리해진다.
if(BENCH_SEAL)
    find_package(SEAL 4.3 REQUIRED)
    if(SEAL_USE_INTEL_HEXL)
        message(FATAL_ERROR
            "Installed SEAL was built with Intel HEXL ON. "
            "Baseline requires HEXL OFF (docs/PROJECT_CONTEXT.md §2). Rebuild SEAL with "
            "-DSEAL_USE_INTEL_HEXL=OFF, or tag the outputs with _hexl and keep them separate.")
    endif()

    # SEAL은 BUILD_SHARED_LIBS=ON으로 빌드하면 SEAL::seal_shared를, 정적이면 SEAL::seal을
    # export한다. 우리는 OpenFHE(shared)와 맞추려고 shared로 빌드하므로 전자가 나온다.
    if(TARGET SEAL::seal_shared)
        set(SEAL_TARGET SEAL::seal_shared)
    elseif(TARGET SEAL::seal)
        set(SEAL_TARGET SEAL::seal)
    else()
        message(FATAL_ERROR "SEAL found but neither SEAL::seal_shared nor SEAL::seal target exists")
    endif()
    message(STATUS "SEAL ${SEAL_VERSION} -> ${SEAL_TARGET} (HEXL=${SEAL_USE_INTEL_HEXL})")

    add_executable(seal_bench src/seal_bench.cpp)
    target_compile_options(seal_bench PRIVATE -Wall -O3)
    target_link_libraries(seal_bench ${SEAL_TARGET})

    add_executable(seal_precision src/seal_precision.cpp)
    target_compile_options(seal_precision PRIVATE -Wall -O3)
    target_link_libraries(seal_precision ${SEAL_TARGET})

    # 새 프리셋 후보 비교 참조 (비밀키 암호화 · rot1 경로).
    add_executable(ksprec_seal src/ksprec_seal.cpp)
    target_compile_options(ksprec_seal PRIVATE -Wall -O3)
    target_include_directories(ksprec_seal PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src)
    target_link_libraries(ksprec_seal ${SEAL_TARGET})

    # 프리셋 확정용 탐색 측정 (P 탐색 · Δ 스윕). 본측정 아님.
    add_executable(presetsearch_seal src/presetsearch_seal.cpp)
    target_compile_options(presetsearch_seal PRIVATE -Wall -O3)
    target_include_directories(presetsearch_seal PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src)
    target_link_libraries(presetsearch_seal ${SEAL_TARGET})
endif()
