cmake_minimum_required(VERSION 3.16.3)
project(openfhe_bench CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Release 빌드 강제 (-O3 -DNDEBUG). Debug 측정 금지.
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()

find_package(OpenFHE CONFIG REQUIRED)
if(NOT OpenFHE_FOUND)
    message(FATAL_ERROR "PACKAGE OpenFHE NOT FOUND")
endif()

# OpenFHE 권장 플래그를 쓰되 -Werror는 제거 (벤치 코드 경고로 빌드 실패 방지).
string(REPLACE "-Werror" "" CMAKE_CXX_FLAGS "${OpenFHE_CXX_FLAGS}")

include_directories(${OPENMP_INCLUDES})
include_directories(${OpenFHE_INCLUDE})
include_directories(${OpenFHE_INCLUDE}/third-party/include)
include_directories(${OpenFHE_INCLUDE}/core)
include_directories(${OpenFHE_INCLUDE}/pke)
include_directories(${OpenFHE_INCLUDE}/binfhe)

if(UNIX AND NOT APPLE)
    add_link_options(-Wl,--no-as-needed)
endif()

link_directories(${OpenFHE_LIBDIR})
link_directories(${OPENMP_LIBRARIES})

add_executable(openfhe_bench openfhe_bench.cpp)
target_link_libraries(openfhe_bench ${OpenFHE_SHARED_LIBRARIES})

# 부트스트래핑 벤치 (별도 실행파일 — 프리셋/CSV 모두 기존 8-op 벤치와 분리)
add_executable(openfhe_boot_bench openfhe_boot_bench.cpp)
target_link_libraries(openfhe_boot_bench ${OpenFHE_SHARED_LIBRARIES})

# key-switch 단건 비용 벤치 (logN 16 / boot16 체인) — 부트스트래핑 격차 원인 분해용
add_executable(openfhe_ks_bench openfhe_ks_bench.cpp)
target_link_libraries(openfhe_ks_bench ${OpenFHE_SHARED_LIBRARIES})
