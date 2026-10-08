cmake_minimum_required(VERSION 3.25)

project(FSR4Navi10 VERSION 0.1.0 LANGUAGES CXX)

if(NOT WIN32 OR NOT MSVC)
    message(FATAL_ERROR "FSR4-Navi10 currently requires Windows x64 and MSVC.")
endif()

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

include(cmake/CompilerWarnings.cmake)
list(APPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake")
find_package(Python3 3.11 REQUIRED COMPONENTS Interpreter)
find_package(DXC REQUIRED)
find_package(RGA QUIET)
include(cmake/ShaderBuild.cmake)

add_library(fsr4n10_core STATIC
    src/core/device_caps.cpp
    src/core/model_pack.cpp
)
target_include_directories(fsr4n10_core
    PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/include"
)
target_link_libraries(fsr4n10_core PUBLIC d3d12 dxgi dxguid)
fsr4n10_enable_warnings(fsr4n10_core)

add_executable(fsr4n10_harness
    src/harness/main.cpp
    src/harness/fp16_probe.cpp
    src/harness/dot4_probe.cpp
    src/harness/fsr4_post_oracle.cpp
    src/harness/upstream_pass0_smoke.cpp
    src/harness/frame_pipeline.cpp
    src/naviqsr/naviqsr_gpu.cpp
    src/naviqsr/naviqsr_network_gpu.cpp
    src/naviprism/msad4_validation.cpp
)
target_link_libraries(fsr4n10_harness PRIVATE fsr4n10_core bcrypt)
fsr4n10_enable_warnings(fsr4n10_harness)

add_library(fsr4n10_sequence STATIC src/sequence/f4seq_reader.cpp)
target_include_directories(fsr4n10_sequence PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/include")
target_compile_definitions(fsr4n10_sequence PRIVATE NOMINMAX)
target_link_libraries(fsr4n10_sequence PUBLIC bcrypt)
fsr4n10_enable_warnings(fsr4n10_sequence)

fsr4n10_compile_hlsl(
    fsr4n10_compile_fp16_probe
    "${CMAKE_CURRENT_SOURCE_DIR}/shaders/runtime/fp16_probe.hlsl"
    main
    "${CMAKE_CURRENT_BINARY_DIR}/generated-shaders/fp16_probe.dxil"
    cs_6_6
)
add_custom_target(compile_shaders ALL DEPENDS "${FSR4N10_COMPILED_SHADER}")
add_dependencies(fsr4n10_harness compile_shaders)
add_custom_command(TARGET fsr4n10_harness POST_BUILD
    COMMAND "${CMAKE_COMMAND}" -E copy_if_different
            "${FSR4N10_COMPILED_SHADER}"
            "$<TARGET_FILE_DIR:fsr4n10_harness>/fp16_probe.dxil"
    VERBATIM
)

fsr4n10_compile_hlsl(
    compile_dot4_conformance
    "${CMAKE_CURRENT_SOURCE_DIR}/shaders/runtime/dot4_conformance.hlsl"
    main
    "${CMAKE_CURRENT_BINARY_DIR}/generated-shaders/dot4_conformance.dxil"
    cs_6_6
)
set(DOT4_CONFORMANCE_SHADER "${compile_dot4_conformance_OUTPUT}")
add_custom_target(compile_dot4_conformance_shader ALL
    COMMAND "${CMAKE_COMMAND}" -E copy_if_different
            "${DOT4_CONFORMANCE_SHADER}"
            "$<TARGET_FILE_DIR:fsr4n10_harness>/dot4_conformance.dxil"
    DEPENDS "${DOT4_CONFORMANCE_SHADER}"
    VERBATIM
)
add_dependencies(fsr4n10_harness compile_dot4_conformance_shader)

fsr4n10_compile_hlsl(
    compile_fsr4_post_oracle
    "${CMAKE_CURRENT_SOURCE_DIR}/shaders/runtime/fsr4_post_oracle.hlsl"
    main
    "${CMAKE_CURRENT_BINARY_DIR}/generated-shaders/fsr4_post_oracle.dxil"
    cs_6_6
)
set(FSR4_POST_ORACLE_SHADER "${compile_fsr4_post_oracle_OUTPUT}")
add_custom_target(compile_fsr4_post_oracle_shader ALL
    COMMAND "${CMAKE_COMMAND}" -E copy_if_different
            "${FSR4_POST_ORACLE_SHADER}"
            "$<TARGET_FILE_DIR:fsr4n10_harness>/fsr4_post_oracle.dxil"
    DEPENDS "${FSR4_POST_ORACLE_SHADER}"
    VERBATIM
)
add_dependencies(fsr4n10_harness compile_fsr4_post_oracle_shader)

fsr4n10_compile_hlsl(
    compile_fsr4_scratch_fill
    "${CMAKE_CURRENT_SOURCE_DIR}/shaders/runtime/fsr4_scratch_fill.hlsl"
    main
    "${CMAKE_CURRENT_BINARY_DIR}/generated-shaders/fsr4_scratch_fill.dxil"
    cs_6_6
)
set(FSR4N10_SCRATCH_FILL_SHADER "${compile_fsr4_scratch_fill_OUTPUT}")
add_custom_target(compile_fsr4_scratch_fill_shader ALL
    COMMAND "${CMAKE_COMMAND}" -E copy_if_different
            "${FSR4N10_SCRATCH_FILL_SHADER}"
            "$<TARGET_FILE_DIR:fsr4n10_harness>/fsr4_scratch_fill.dxil"
    DEPENDS "${FSR4N10_SCRATCH_FILL_SHADER}"
    VERBATIM
)
add_dependencies(fsr4n10_harness compile_fsr4_scratch_fill_shader)

fsr4n10_compile_hlsl(
    compile_naviqsr_akr_4tap
    "${CMAKE_CURRENT_SOURCE_DIR}/shaders/naviqsr/analytic_reconstruct.hlsl"
    main
    "${CMAKE_CURRENT_BINARY_DIR}/generated-shaders/naviqsr_akr_4tap.dxil"
    cs_6_6
    -D TAP_COUNT=4
)
set(NAVIQSR_AKR_4TAP_SHADER "${compile_naviqsr_akr_4tap_OUTPUT}")
fsr4n10_compile_hlsl(
    compile_naviqsr_akr_5tap
    "${CMAKE_CURRENT_SOURCE_DIR}/shaders/naviqsr/analytic_reconstruct.hlsl"
    main
    "${CMAKE_CURRENT_BINARY_DIR}/generated-shaders/naviqsr_akr_5tap.dxil"
    cs_6_6
    -D TAP_COUNT=5
)
set(NAVIQSR_AKR_5TAP_SHADER "${compile_naviqsr_akr_5tap_OUTPUT}")
fsr4n10_compile_hlsl(
    compile_naviqsr_akr_8tap
    "${CMAKE_CURRENT_SOURCE_DIR}/shaders/naviqsr/analytic_reconstruct.hlsl"
    main
    "${CMAKE_CURRENT_BINARY_DIR}/generated-shaders/naviqsr_akr_8tap.dxil"
    cs_6_6
    -D TAP_COUNT=8
)
set(NAVIQSR_AKR_8TAP_SHADER "${compile_naviqsr_akr_8tap_OUTPUT}")
add_custom_target(compile_naviqsr_akr ALL
    COMMAND "${CMAKE_COMMAND}" -E copy_if_different
            "${NAVIQSR_AKR_4TAP_SHADER}" "$<TARGET_FILE_DIR:fsr4n10_harness>/naviqsr_akr_4tap.dxil"
    COMMAND "${CMAKE_COMMAND}" -E copy_if_different
            "${NAVIQSR_AKR_5TAP_SHADER}" "$<TARGET_FILE_DIR:fsr4n10_harness>/naviqsr_akr_5tap.dxil"
    COMMAND "${CMAKE_COMMAND}" -E copy_if_different
            "${NAVIQSR_AKR_8TAP_SHADER}" "$<TARGET_FILE_DIR:fsr4n10_harness>/naviqsr_akr_8tap.dxil"
    DEPENDS "${NAVIQSR_AKR_4TAP_SHADER}" "${NAVIQSR_AKR_5TAP_SHADER}" "${NAVIQSR_AKR_8TAP_SHADER}"
    COMMENT "Copying NaviQSR AKR DXIL tap variants to the harness"
    VERBATIM
)
add_dependencies(fsr4n10_harness compile_naviqsr_akr)

fsr4n10_compile_hlsl(
    compile_naviqsr_network_conv
    "${CMAKE_CURRENT_SOURCE_DIR}/shaders/naviqsr/network_conv.hlsl"
    main
    "${CMAKE_CURRENT_BINARY_DIR}/generated-shaders/naviqsr_network_conv.dxil"
    cs_6_6
)
set(NAVIQSR_NETWORK_CONV_SHADER "${compile_naviqsr_network_conv_OUTPUT}")
add_custom_target(compile_naviqsr_network ALL
    COMMAND "${CMAKE_COMMAND}" -E copy_if_different
            "${NAVIQSR_NETWORK_CONV_SHADER}" "$<TARGET_FILE_DIR:fsr4n10_harness>/naviqsr_network_conv.dxil"
    DEPENDS "${NAVIQSR_NETWORK_CONV_SHADER}"
    COMMENT "Copying NaviQSR network convolution DXIL to the harness"
    VERBATIM
)
add_dependencies(fsr4n10_harness compile_naviqsr_network)

fsr4n10_compile_hlsl(
    compile_naviqsr_network_analytic_4tap
    "${CMAKE_CURRENT_SOURCE_DIR}/shaders/naviqsr/network_analytic.hlsl"
    main
    "${CMAKE_CURRENT_BINARY_DIR}/generated-shaders/naviqsr_network_analytic_4tap.dxil"
    cs_6_6
    -D TAP_COUNT=4
)
set(NAVIQSR_NETWORK_ANALYTIC_4TAP_SHADER "${compile_naviqsr_network_analytic_4tap_OUTPUT}")
fsr4n10_compile_hlsl(
    compile_naviqsr_network_analytic_5tap
    "${CMAKE_CURRENT_SOURCE_DIR}/shaders/naviqsr/network_analytic.hlsl"
    main
    "${CMAKE_CURRENT_BINARY_DIR}/generated-shaders/naviqsr_network_analytic_5tap.dxil"
    cs_6_6
    -D TAP_COUNT=5
)
set(NAVIQSR_NETWORK_ANALYTIC_5TAP_SHADER "${compile_naviqsr_network_analytic_5tap_OUTPUT}")
fsr4n10_compile_hlsl(
    compile_naviqsr_network_analytic_8tap
    "${CMAKE_CURRENT_SOURCE_DIR}/shaders/naviqsr/network_analytic.hlsl"
    main
    "${CMAKE_CURRENT_BINARY_DIR}/generated-shaders/naviqsr_network_analytic_8tap.dxil"
    cs_6_6
    -D TAP_COUNT=8
)
set(NAVIQSR_NETWORK_ANALYTIC_8TAP_SHADER "${compile_naviqsr_network_analytic_8tap_OUTPUT}")
add_custom_target(compile_naviqsr_network_analytic ALL
    COMMAND "${CMAKE_COMMAND}" -E copy_if_different
            "${NAVIQSR_NETWORK_ANALYTIC_4TAP_SHADER}" "$<TARGET_FILE_DIR:fsr4n10_harness>/naviqsr_network_analytic_4tap.dxil"
    COMMAND "${CMAKE_COMMAND}" -E copy_if_different
            "${NAVIQSR_NETWORK_ANALYTIC_5TAP_SHADER}" "$<TARGET_FILE_DIR:fsr4n10_harness>/naviqsr_network_analytic_5tap.dxil"
    COMMAND "${CMAKE_COMMAND}" -E copy_if_different
            "${NAVIQSR_NETWORK_ANALYTIC_8TAP_SHADER}" "$<TARGET_FILE_DIR:fsr4n10_harness>/naviqsr_network_analytic_8tap.dxil"
    DEPENDS "${NAVIQSR_NETWORK_ANALYTIC_4TAP_SHADER}"
            "${NAVIQSR_NETWORK_ANALYTIC_5TAP_SHADER}"
            "${NAVIQSR_NETWORK_ANALYTIC_8TAP_SHADER}"
    COMMENT "Copying NaviQSR network analytic DXIL tap variants to the harness"
    VERBATIM
)
add_dependencies(fsr4n10_harness compile_naviqsr_network_analytic)

fsr4n10_compile_hlsl(
    compile_naviprism_msad4
    "${CMAKE_CURRENT_SOURCE_DIR}/shaders/naviprism/msad4_microbench.hlsl"
    main
    "${CMAKE_CURRENT_BINARY_DIR}/generated-shaders/naviprism_msad4.dxil"
    cs_6_6
    -D MSAD_MODE=0
)
set(NAVIPRISM_MSAD4_SHADER "${compile_naviprism_msad4_OUTPUT}")
fsr4n10_compile_hlsl(
    compile_naviprism_msad4_scalar
    "${CMAKE_CURRENT_SOURCE_DIR}/shaders/naviprism/msad4_microbench.hlsl"
    main
    "${CMAKE_CURRENT_BINARY_DIR}/generated-shaders/naviprism_msad4_scalar.dxil"
    cs_6_6
    -D MSAD_MODE=1
)
set(NAVIPRISM_MSAD4_SCALAR_SHADER "${compile_naviprism_msad4_scalar_OUTPUT}")
fsr4n10_compile_hlsl(
    compile_naviprism_msad4_fp16
    "${CMAKE_CURRENT_SOURCE_DIR}/shaders/naviprism/msad4_microbench.hlsl"
    main
    "${CMAKE_CURRENT_BINARY_DIR}/generated-shaders/naviprism_msad4_fp16.dxil"
    cs_6_6
    -D MSAD_MODE=2
)
set(NAVIPRISM_MSAD4_FP16_SHADER "${compile_naviprism_msad4_fp16_OUTPUT}")
add_custom_target(compile_naviprism_msad4_variants ALL
    COMMAND "${CMAKE_COMMAND}" -E copy_if_different
            "${NAVIPRISM_MSAD4_SHADER}" "$<TARGET_FILE_DIR:fsr4n10_harness>/naviprism_msad4.dxil"
    COMMAND "${CMAKE_COMMAND}" -E copy_if_different
            "${NAVIPRISM_MSAD4_SCALAR_SHADER}" "$<TARGET_FILE_DIR:fsr4n10_harness>/naviprism_msad4_scalar.dxil"
    COMMAND "${CMAKE_COMMAND}" -E copy_if_different
            "${NAVIPRISM_MSAD4_FP16_SHADER}" "$<TARGET_FILE_DIR:fsr4n10_harness>/naviprism_msad4_fp16.dxil"
    DEPENDS "${NAVIPRISM_MSAD4_SHADER}"
            "${NAVIPRISM_MSAD4_SCALAR_SHADER}"
            "${NAVIPRISM_MSAD4_FP16_SHADER}"
    COMMENT "Copying NaviPRISM msad4 benchmark DXIL variants"
    VERBATIM
)
add_dependencies(fsr4n10_harness compile_naviprism_msad4_variants)

fsr4n10_compile_hlsl(
    compile_naviprism_sarm_residual
    "${CMAKE_CURRENT_SOURCE_DIR}/shaders/naviprism/sarm_residual.hlsl"
    main
    "${CMAKE_CURRENT_BINARY_DIR}/generated-shaders/naviprism_sarm_residual.dxil"
    cs_6_6
)
set(NAVIPRISM_SARM_RESIDUAL_SHADER "${compile_naviprism_sarm_residual_OUTPUT}")
add_custom_target(compile_naviprism_sarm ALL
    COMMAND "${CMAKE_COMMAND}" -E copy_if_different
            "${NAVIPRISM_SARM_RESIDUAL_SHADER}" "$<TARGET_FILE_DIR:fsr4n10_harness>/naviprism_sarm_residual.dxil"
    DEPENDS "${NAVIPRISM_SARM_RESIDUAL_SHADER}"
    COMMENT "Copying NaviPRISM SARM residual-motion DXIL to the harness"
    VERBATIM
)
add_dependencies(fsr4n10_harness compile_naviprism_sarm)

foreach(THFA_TAP_COUNT IN ITEMS 4 5 8 9)
    fsr4n10_compile_hlsl(
        compile_naviprism_thfa_${THFA_TAP_COUNT}tap
        "${CMAKE_CURRENT_SOURCE_DIR}/shaders/naviprism/thfa_filter.hlsl"
        main
        "${CMAKE_CURRENT_BINARY_DIR}/generated-shaders/naviprism_thfa_${THFA_TAP_COUNT}tap.dxil"
        cs_6_6
        -D FILTER_TAPS=${THFA_TAP_COUNT}
    )
    set(NAVIPRISM_THFA_${THFA_TAP_COUNT}TAP_SHADER
        "${compile_naviprism_thfa_${THFA_TAP_COUNT}tap_OUTPUT}")
    add_custom_target(compile_naviprism_thfa_${THFA_TAP_COUNT}tap ALL
        COMMAND "${CMAKE_COMMAND}" -E copy_if_different
                "${NAVIPRISM_THFA_${THFA_TAP_COUNT}TAP_SHADER}"
                "$<TARGET_FILE_DIR:fsr4n10_harness>/naviprism_thfa_${THFA_TAP_COUNT}tap.dxil"
        DEPENDS "${NAVIPRISM_THFA_${THFA_TAP_COUNT}TAP_SHADER}"
        COMMENT "Copying NaviPRISM THFA ${THFA_TAP_COUNT}-tap DXIL to the harness"
        VERBATIM
    )
    add_dependencies(fsr4n10_harness compile_naviprism_thfa_${THFA_TAP_COUNT}tap)
endforeach()

fsr4n10_compile_hlsl(
    compile_naviprism_thfa_descriptors
    "${CMAKE_CURRENT_SOURCE_DIR}/shaders/naviprism/thfa_descriptors.hlsl"
    main
    "${CMAKE_CURRENT_BINARY_DIR}/generated-shaders/naviprism_thfa_descriptors.dxil"
    cs_6_6
)
add_custom_target(compile_naviprism_thfa_descriptors ALL
    COMMAND "${CMAKE_COMMAND}" -E copy_if_different
            "${compile_naviprism_thfa_descriptors_OUTPUT}"
            "$<TARGET_FILE_DIR:fsr4n10_harness>/naviprism_thfa_descriptors.dxil"
    DEPENDS "${compile_naviprism_thfa_descriptors_OUTPUT}"
    COMMENT "Copying NaviPRISM THFA descriptor DXIL to the harness"
    VERBATIM
)
add_dependencies(fsr4n10_harness compile_naviprism_thfa_descriptors)

fsr4n10_compile_hlsl(
    compile_naviprism_quality_router
    "${CMAKE_CURRENT_SOURCE_DIR}/shaders/naviprism/quality_router.hlsl"
    main
    "${CMAKE_CURRENT_BINARY_DIR}/generated-shaders/naviprism_quality_router.dxil"
    cs_6_6
)
add_custom_target(compile_naviprism_quality_router ALL
    COMMAND "${CMAKE_COMMAND}" -E copy_if_different
            "${compile_naviprism_quality_router_OUTPUT}"
            "$<TARGET_FILE_DIR:fsr4n10_harness>/naviprism_quality_router.dxil"
    DEPENDS "${compile_naviprism_quality_router_OUTPUT}"
    COMMENT "Copying NaviPRISM tile-router DXIL to the harness"
    VERBATIM
)
add_dependencies(fsr4n10_harness compile_naviprism_quality_router)

fsr4n10_compile_hlsl(
    compile_naviprism_phase_reservoir
    "${CMAKE_CURRENT_SOURCE_DIR}/shaders/naviprism/phase_reservoir.hlsl"
    main
    "${CMAKE_CURRENT_BINARY_DIR}/generated-shaders/naviprism_phase_reservoir.dxil"
    cs_6_6
)
add_custom_target(compile_naviprism_phase_reservoir ALL
    COMMAND "${CMAKE_COMMAND}" -E copy_if_different
            "${compile_naviprism_phase_reservoir_OUTPUT}"
            "$<TARGET_FILE_DIR:fsr4n10_harness>/naviprism_phase_reservoir.dxil"
    DEPENDS "${compile_naviprism_phase_reservoir_OUTPUT}"
    COMMENT "Copying NaviPRISM phase-reservoir DXIL to the harness"
    VERBATIM
)
add_dependencies(fsr4n10_harness compile_naviprism_phase_reservoir)

add_custom_target(generate_model_manifest
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tools/model/extract_manifest.py"
            --source "${CMAKE_CURRENT_SOURCE_DIR}/third_party/fidelityfx-fsr4-source"
            --lock "${CMAKE_CURRENT_SOURCE_DIR}/third_party/LOCK.json"
            --output "${CMAKE_CURRENT_SOURCE_DIR}/generated/manifests/upstream_inventory.json"
    DEPENDS
        "${CMAKE_CURRENT_SOURCE_DIR}/tools/model/extract_manifest.py"
        "${CMAKE_CURRENT_SOURCE_DIR}/third_party/LOCK.json"
    WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
    COMMENT "Inventorying the pinned FSR4 source and model inputs"
    VERBATIM
)

add_custom_target(generate_i8_pass_contracts
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tools/model/extract_pass_contracts.py"
            --source-root "${CMAKE_CURRENT_SOURCE_DIR}/third_party/fidelityfx-fsr4-source"
            --fsr4-root "${CMAKE_CURRENT_SOURCE_DIR}/third_party/fidelityfx-fsr4-source/Kits/FidelityFX/upscalers/fsr4"
            --lock "${CMAKE_CURRENT_SOURCE_DIR}/third_party/LOCK.json"
            --output "${CMAKE_CURRENT_SOURCE_DIR}/generated/manifests/i8_pass_contracts.json"
    DEPENDS
        "${CMAKE_CURRENT_SOURCE_DIR}/tools/model/extract_pass_contracts.py"
        "${CMAKE_CURRENT_SOURCE_DIR}/third_party/LOCK.json"
    WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
    COMMENT "Extracting upstream I8 pass/operator/tensor contracts from generated HLSL"
    VERBATIM
)

add_custom_target(audit_teacher_provider_schedule
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tools/teacher/audit_provider_schedule.py"
            --repo-root "${CMAKE_CURRENT_SOURCE_DIR}"
            --preset native
            --tier 1080
            --output "${CMAKE_CURRENT_BINARY_DIR}/teacher/provider_schedule_i8_native_1080.json"
    DEPENDS
        "${CMAKE_CURRENT_SOURCE_DIR}/tools/teacher/audit_provider_schedule.py"
        "${CMAKE_CURRENT_SOURCE_DIR}/third_party/LOCK.json"
    WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
    COMMENT "Auditing pinned FSR4 PRE/model/padding/POST provider scheduling"
    VERBATIM
)

option(FSR4N10_ENABLE_PASS_PREFIX_DIAGNOSTIC "Build temporary prefix-pass diagnostic into FSR4 provider" OFF)
option(FSR4N10_FORCE_GLOBAL_UAV_BARRIER "Diagnostic global UAV barrier after each backend compute dispatch" OFF)

option(FSR4N10_PASS11_BOUNDS_GUARD "Enable safe I8 <32,1> neural bounds guard in build overlay" OFF)
option(FSR4N10_FORCE_SCALAR_DOT4 "Use scalar signed-I8 dot4 fallback for Navi10 validation" OFF)
option(FSR4N10_STABLE_POST_MATH "Use overflow-stable but mathematically equivalent FSR4 POST tanh/sigmoid transforms" OFF)
set(FSR4N10_PROVIDER_DIAGNOSTIC_ARGS)
if(FSR4N10_FORCE_SCALAR_DOT4)
    list(APPEND FSR4N10_PROVIDER_DIAGNOSTIC_ARGS --scalar-dot4)
endif()
if(FSR4N10_STABLE_POST_MATH)
    list(APPEND FSR4N10_PROVIDER_DIAGNOSTIC_ARGS --stable-post-math)
endif()

if(FSR4N10_PASS11_BOUNDS_GUARD)
    list(APPEND FSR4N10_PROVIDER_DIAGNOSTIC_ARGS --pass11-bounds-guard)
endif()

add_custom_target(compile_provider_i8_native_1080
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tools/teacher/compile_provider_i8_native_1080.py"
            --repo-root "${CMAKE_CURRENT_SOURCE_DIR}"
            --output "${CMAKE_CURRENT_BINARY_DIR}/teacher/provider_i8_native_1080"
            ${FSR4N10_PROVIDER_DIAGNOSTIC_ARGS}
    BYPRODUCTS "${CMAKE_CURRENT_BINARY_DIR}/teacher/provider_i8_native_1080/manifest.json"
    DEPENDS
        "${CMAKE_CURRENT_SOURCE_DIR}/tools/teacher/compile_provider_i8_native_1080.py"
        "${CMAKE_CURRENT_SOURCE_DIR}/tools/teacher/fnb_bounds_overlay.py"
        "${CMAKE_CURRENT_SOURCE_DIR}/third_party/LOCK.json"
    WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
    COMMENT "Compiling pinned FSR4 I8 native/1080 provider PRE/model/padding/POST shader blobs"
    VERBATIM
)

set(FSR4N10_PROVIDER_SHADER_DIR "${CMAKE_CURRENT_BINARY_DIR}/teacher/provider_i8_native_1080")
set(FSR4N10_PROVIDER_INITIALIZER_CPP "${FSR4N10_PROVIDER_SHADER_DIR}/fsr4_model_v07_i8_native.cpp")
set_source_files_properties("${FSR4N10_PROVIDER_INITIALIZER_CPP}" PROPERTIES GENERATED TRUE)
set(FSR4N10_FIDELITYFX_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/third_party/fidelityfx-fsr4-source/Kits/FidelityFX")
file(READ "${CMAKE_CURRENT_SOURCE_DIR}/third_party/LOCK.json" FSR4N10_THIRD_PARTY_LOCK)
string(JSON FSR4N10_FSR4_SOURCE_COMMIT GET "${FSR4N10_THIRD_PARTY_LOCK}" fsr4Source actualCommit)
string(JSON FSR4N10_FSR3_SDK_COMMIT GET "${FSR4N10_THIRD_PARTY_LOCK}" currentSdk actualCommit)
execute_process(
    COMMAND git rev-parse HEAD
    WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
    OUTPUT_VARIABLE FSR4N10_BUILD_COMMIT
    OUTPUT_STRIP_TRAILING_WHITESPACE
    RESULT_VARIABLE FSR4N10_GIT_REV_PARSE_RESULT)
string(LENGTH "${FSR4N10_BUILD_COMMIT}" FSR4N10_BUILD_COMMIT_LENGTH)
if(NOT FSR4N10_GIT_REV_PARSE_RESULT EQUAL 0 OR
   NOT FSR4N10_BUILD_COMMIT MATCHES "^[0-9a-fA-F]+$" OR
   NOT FSR4N10_BUILD_COMMIT_LENGTH EQUAL 40)
    message(FATAL_ERROR "Could not read the repository commit for capture provenance")
endif()
set(FSR4N10_FIDELITYFX_COMPAT_DIR "${CMAKE_CURRENT_BINARY_DIR}/teacher/fidelityfx_build_compat")
set(FSR4N10_FIDELITYFX_PROVIDER_OVERLAY "${CMAKE_CURRENT_BINARY_DIR}/teacher/fidelityfx_provider_overlay")
file(MAKE_DIRECTORY
    "${FSR4N10_FIDELITYFX_PROVIDER_OVERLAY}/Kits/FidelityFX/upscalers/fsr4/dx12"
    "${FSR4N10_FIDELITYFX_PROVIDER_OVERLAY}/Kits/FidelityFX/api/internal")
set(FSR4N10_FIDELITYFX_PROVIDER_SOURCE
    "${FSR4N10_FIDELITYFX_ROOT}/upscalers/fsr4/dx12/ffx_provider_fsr4_dx12.cpp")
set(FSR4N10_FIDELITYFX_PROVIDER_OVERLAY_SOURCE
    "${FSR4N10_FIDELITYFX_PROVIDER_OVERLAY}/Kits/FidelityFX/upscalers/fsr4/dx12/ffx_provider_fsr4_dx12.cpp")
file(READ "${FSR4N10_FIDELITYFX_PROVIDER_SOURCE}" FSR4N10_FIDELITYFX_PROVIDER_OVERLAY_TEXT)
string(FIND "${FSR4N10_FIDELITYFX_PROVIDER_OVERLAY_TEXT}"
    "FFX_API_SURFACE_FORMAT_R16_UNORM, maxUpscaleSize->width, maxUpscaleSize->height"
    FSR4N10_DEBUG_RESOURCE_FORMAT_OFFSET)
if(FSR4N10_DEBUG_RESOURCE_FORMAT_OFFSET EQUAL -1)
    message(FATAL_ERROR "Pinned FSR4 provider debug-resource description changed; review capture overlay")
endif()
string(REPLACE
    "FFX_API_SURFACE_FORMAT_R16_UNORM, maxUpscaleSize->width, maxUpscaleSize->height"
    "FFX_API_SURFACE_FORMAT_R32G32B32A32_FLOAT, maxUpscaleSize->width * 5, maxUpscaleSize->height"
    FSR4N10_FIDELITYFX_PROVIDER_OVERLAY_TEXT
    "${FSR4N10_FIDELITYFX_PROVIDER_OVERLAY_TEXT}")
if(FSR4N10_ENABLE_PASS_PREFIX_DIAGNOSTIC)
    # Git may check out pinned third_party with Windows CRLF; normalize the
    # generated overlay before exact original-source ML-pass loop matching.
    string(REPLACE "\r\n" "\n" FSR4N10_FIDELITYFX_PROVIDER_OVERLAY_TEXT
        "${FSR4N10_FIDELITYFX_PROVIDER_OVERLAY_TEXT}")
    set(FSR4N10_ML_PASS_LOOP_ORIGINAL
        "        // ML passes\n        for (int i = 1; i < 13; ++i)\n        {\n")
    set(FSR4N10_ML_PASS_LOOP_DIAG
        "        // ML passes\n        const char* f4n10_last_text = std::getenv(\"FSR4N10_LAST_MODEL_PASS\");\n        const int f4n10_last_pass = f4n10_last_text ? std::atoi(f4n10_last_text) : -1;\n        for (int i = 1; i < 13; ++i)\n        {\n            if (f4n10_last_pass >= 0 && i > f4n10_last_pass)\n                break;\n")
    string(FIND "${FSR4N10_FIDELITYFX_PROVIDER_OVERLAY_TEXT}"
        "${FSR4N10_ML_PASS_LOOP_ORIGINAL}" FSR4N10_ML_LOOP_INDEX)
    if(FSR4N10_ML_LOOP_INDEX EQUAL -1)
        message(FATAL_ERROR "Pinned AMD FSR4 ML pass-loop anchor changed; refuse diagnostic injection")
    endif()
    string(REPLACE "${FSR4N10_ML_PASS_LOOP_ORIGINAL}" "${FSR4N10_ML_PASS_LOOP_DIAG}"
        FSR4N10_FIDELITYFX_PROVIDER_OVERLAY_TEXT
        "${FSR4N10_FIDELITYFX_PROVIDER_OVERLAY_TEXT}")
endif()
file(WRITE "${FSR4N10_FIDELITYFX_PROVIDER_OVERLAY_SOURCE}"
    "${FSR4N10_FIDELITYFX_PROVIDER_OVERLAY_TEXT}")
file(APPEND "${FSR4N10_FIDELITYFX_PROVIDER_OVERLAY_SOURCE}"
    "\nextern \"C\" FfxApiResource fsr4n10GetInternalResource(ffxContext* context, uint32_t resourceId, bool unorderedAccess)\n{\n"
    "    if (context == nullptr || *context == nullptr || resourceId >= FFX_FSR4UPSCALER_RESOURCE_IDENTIFIER_COUNT)\n"
    "        return FfxApiResource{};\n"
    "    auto* internalContext = reinterpret_cast<InternalFsr4Context*>(*context);\n"
    "    const FfxResourceInternal resource = unorderedAccess ? internalContext->uavResources[resourceId] : internalContext->srvResources[resourceId];\n"
    "    return internalContext->backendInterface.fpGetResource(&internalContext->backendInterface, resource);\n"
    "}\n")
configure_file(
    "${FSR4N10_FIDELITYFX_ROOT}/api/internal/ffx_watermark.h"
    "${FSR4N10_FIDELITYFX_PROVIDER_OVERLAY}/Kits/FidelityFX/api/internal/ffx_watermark.h"
    COPYONLY)
file(WRITE "${FSR4N10_FIDELITYFX_COMPAT_DIR}/pix3.h"
    "/* Build-only compatibility shim: tracing entry points are loaded dynamically by the backend. */\n#define PIX_COLOR(r, g, b) ((((r) & 0xff) << 16) | (((g) & 0xff) << 8) | ((b) & 0xff))\n")
file(WRITE "${FSR4N10_FIDELITYFX_PROVIDER_OVERLAY}/Kits/FidelityFX/api/internal/git_hash_branch.h"
    "#pragma once\n#define GIT_HASH \"${FSR4N10_FSR4_SOURCE_COMMIT}\"\n#define GIT_COMMIT_SUBJECT \"FSR4 Navi10 pinned provider source\"\n")
set(FSR4N10_FIDELITYFX_BACKEND_DIAGNOSTIC_SOURCE
    "${FSR4N10_FIDELITYFX_ROOT}/backend/dx12/ffx_dx12.cpp")
if(FSR4N10_FORCE_GLOBAL_UAV_BARRIER)
    set(FSR4N10_DX12_BACKEND_OVERLAY_DIR "${CMAKE_CURRENT_BINARY_DIR}/teacher/backend_diagnostic")
    file(MAKE_DIRECTORY "${FSR4N10_DX12_BACKEND_OVERLAY_DIR}")
    set(FSR4N10_FIDELITYFX_BACKEND_DIAGNOSTIC_SOURCE
        "${FSR4N10_DX12_BACKEND_OVERLAY_DIR}/ffx_dx12.cpp")
    file(READ "${FSR4N10_FIDELITYFX_ROOT}/backend/dx12/ffx_dx12.cpp" FSR4N10_DX12_TEXT)
    string(REPLACE "\r\n" "\n" FSR4N10_DX12_TEXT "${FSR4N10_DX12_TEXT}")
    # This source is relocated to a generated directory; repair only its three
    # relative includes, using existing target api/internal include directories.
    foreach(FSR4N10_RELATIVE_HEADER IN ITEMS ffx_interface.h ffx_util.h ffx_assert.h)
        string(REPLACE "\"../../api/internal/${FSR4N10_RELATIVE_HEADER}\""
                       "\"${FSR4N10_RELATIVE_HEADER}\""
               FSR4N10_DX12_TEXT "${FSR4N10_DX12_TEXT}")
    endforeach()
    set(FSR4N10_DX12_DISPATCH_ANCHOR
        "        dx12CommandList->Dispatch(job->computeJobDescriptor.dimensions[0], job->computeJobDescriptor.dimensions[1], job->computeJobDescriptor.dimensions[2]);")
    set(FSR4N10_DX12_DISPATCH_WITH_BARRIER
        "        dx12CommandList->Dispatch(job->computeJobDescriptor.dimensions[0], job->computeJobDescriptor.dimensions[1], job->computeJobDescriptor.dimensions[2]);\n        // FSR4-Navi10 diagnostic only: guarantee global UAV ordering after dispatch.\n        D3D12_RESOURCE_BARRIER f4n10_global_uav_barrier = {};\n        f4n10_global_uav_barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_UAV;\n        f4n10_global_uav_barrier.UAV.pResource = nullptr;\n        dx12CommandList->ResourceBarrier(1, &f4n10_global_uav_barrier);")
    string(FIND "${FSR4N10_DX12_TEXT}" "${FSR4N10_DX12_DISPATCH_ANCHOR}"
        FSR4N10_DX12_DISPATCH_POSITION)
    if(FSR4N10_DX12_DISPATCH_POSITION EQUAL -1)
        message(FATAL_ERROR "Pinned AMD backend dispatch anchor changed; cannot add UAV barrier")
    endif()
    string(REPLACE "${FSR4N10_DX12_DISPATCH_ANCHOR}" "${FSR4N10_DX12_DISPATCH_WITH_BARRIER}"
        FSR4N10_DX12_TEXT "${FSR4N10_DX12_TEXT}")
    file(WRITE "${FSR4N10_FIDELITYFX_BACKEND_DIAGNOSTIC_SOURCE}" "${FSR4N10_DX12_TEXT}")
endif()

add_library(fsr4n10_fsr4_teacher_provider STATIC
    src/teacher/provider_i8_native_1080_shader_selector.cpp
    src/teacher/provider_query_compat.cpp
    "${FSR4N10_FIDELITYFX_ROOT}/api/internal/dx12/amd_extensions.cpp"
    "${FSR4N10_FIDELITYFX_ROOT}/api/internal/ffx_assert.cpp"
    "${FSR4N10_FIDELITYFX_ROOT}/api/internal/ffx_message.cpp"
    "${FSR4N10_FIDELITYFX_ROOT}/api/internal/ffx_object_management.cpp"
    "${FSR4N10_FIDELITYFX_ROOT}/api/internal/ffx_watermark.cpp"
    "${FSR4N10_FIDELITYFX_ROOT}/backend/dx12/ffx_backends_dx12.cpp"
    "${FSR4N10_FIDELITYFX_BACKEND_DIAGNOSTIC_SOURCE}"
    "${FSR4N10_FIDELITYFX_PROVIDER_OVERLAY}/Kits/FidelityFX/upscalers/fsr4/dx12/ffx_provider_fsr4_dx12.cpp"
    "${FSR4N10_PROVIDER_INITIALIZER_CPP}"
)
add_dependencies(fsr4n10_fsr4_teacher_provider compile_provider_i8_native_1080)
target_include_directories(fsr4n10_fsr4_teacher_provider PRIVATE
    "${FSR4N10_FIDELITYFX_COMPAT_DIR}"
    "${FSR4N10_PROVIDER_SHADER_DIR}"
    "${FSR4N10_FIDELITYFX_ROOT}/api/include"
    "${FSR4N10_FIDELITYFX_ROOT}/api/include/dx12"
    "${FSR4N10_FIDELITYFX_ROOT}/api/internal"
    "${FSR4N10_FIDELITYFX_ROOT}/api/internal/dx12"
    "${FSR4N10_FIDELITYFX_ROOT}/api/internal/gpu"
    "${FSR4N10_FIDELITYFX_ROOT}/backend/dx12"
    "${FSR4N10_FIDELITYFX_ROOT}/upscalers/include"
    "${FSR4N10_FIDELITYFX_ROOT}/upscalers/fsr3/include"
    "${FSR4N10_FIDELITYFX_ROOT}/upscalers/fsr4/include"
    "${FSR4N10_FIDELITYFX_ROOT}/upscalers/fsr4/include/gpu"
    "${FSR4N10_FIDELITYFX_ROOT}/upscalers/fsr4/include/gpu/fsr4"
    "${FSR4N10_FIDELITYFX_ROOT}/upscalers/fsr4/internal"
    "${FSR4N10_FIDELITYFX_ROOT}/upscalers/fsr4/dx12"
)
target_compile_definitions(fsr4n10_fsr4_teacher_provider PRIVATE
    FFX_BACKEND_DX12
    FFX_UPSCALER
    FSR4_ENABLE_DOT4=1
    _WINDOWS
    NOMINMAX
)
target_link_libraries(fsr4n10_fsr4_teacher_provider PUBLIC d3d12 dxgi dxguid bcrypt user32)

set(FSR4N10_FSR3_SDK_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/third_party/fidelityfx-current/Kits/FidelityFX")
set(FSR4N10_FSR3_REFERENCE_ROOT "${CMAKE_CURRENT_BINARY_DIR}/fsr3_reference")
set(FSR4N10_FSR3_SHADER_OUTPUT "${FSR4N10_FSR3_REFERENCE_ROOT}/shaders")
set(FSR4N10_FSR3_SHADER_MANIFEST "${FSR4N10_FSR3_REFERENCE_ROOT}/manifest.json")
set(FSR4N10_FIDELITYFX_SC "${FSR4N10_FIDELITYFX_ROOT}/tools/ffx_sc/bin/FidelityFX_SC.exe")
file(GLOB FSR4N10_FSR3_SHADER_SOURCES CONFIGURE_DEPENDS
    "${FSR4N10_FSR3_SDK_ROOT}/upscalers/fsr3/internal/shaders/ffx_fsr3upscaler_*_pass.hlsl")
add_custom_command(
    OUTPUT "${FSR4N10_FSR3_SHADER_MANIFEST}"
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tools/shaders/compile_fsr3_reference.py"
            --sdk-root "${FSR4N10_FSR3_SDK_ROOT}"
            --compiler "${FSR4N10_FIDELITYFX_SC}"
            --source-commit "${FSR4N10_FSR3_SDK_COMMIT}"
            --output "${FSR4N10_FSR3_REFERENCE_ROOT}"
    DEPENDS
        "${CMAKE_CURRENT_SOURCE_DIR}/tools/shaders/compile_fsr3_reference.py"
        "${FSR4N10_FSR3_SDK_ROOT}/upscalers/fsr3/internal/ffx_fsr3upscaler_shaderblobs.cpp"
        "${FSR4N10_FSR3_SDK_ROOT}/upscalers/fsr3/include/gpu/fsr3upscaler/ffx_fsr3upscaler_accumulate.h"
        "${FSR4N10_FIDELITYFX_SC}"
        ${FSR4N10_FSR3_SHADER_SOURCES}
    COMMENT "Compiling pinned FidelityFX FSR3.1.5 shader permutations"
    VERBATIM
)
add_custom_target(compile_fsr3_reference_shaders DEPENDS "${FSR4N10_FSR3_SHADER_MANIFEST}")

set(FSR4N10_FSR3_PROVIDER_SOURCE
    "${FSR4N10_FSR3_SDK_ROOT}/upscalers/fsr3/internal/ffx_provider_fsr3upscale.cpp")
set(FSR4N10_FSR3_PROVIDER_OVERLAY_DIR "${FSR4N10_FSR3_REFERENCE_ROOT}/fidelityfx_provider")
set(FSR4N10_FSR3_PROVIDER_OVERLAY_SOURCE
    "${FSR4N10_FSR3_PROVIDER_OVERLAY_DIR}/ffx_provider_fsr3upscale.cpp")
file(MAKE_DIRECTORY "${FSR4N10_FSR3_PROVIDER_OVERLAY_DIR}")
file(READ "${FSR4N10_FSR3_PROVIDER_SOURCE}" FSR4N10_FSR3_PROVIDER_TEXT)
string(REPLACE
    "#include \"../../../api/internal/ffx_backends.h\""
    "#include <ffx_backends.h>"
    FSR4N10_FSR3_PROVIDER_TEXT "${FSR4N10_FSR3_PROVIDER_TEXT}")
string(REPLACE
    "#include \"../include/ffx_provider_fsr3upscale.h\""
    "#include <ffx_provider_fsr3upscale.h>"
    FSR4N10_FSR3_PROVIDER_TEXT "${FSR4N10_FSR3_PROVIDER_TEXT}")
string(REPLACE
    "#include \"../include/ffx_fsr3upscaler.h\""
    "#include <ffx_fsr3upscaler.h>"
    FSR4N10_FSR3_PROVIDER_TEXT "${FSR4N10_FSR3_PROVIDER_TEXT}")
string(REPLACE
    "#include \"../include/gpu/fsr3/ffx_fsr3_resources.h\""
    "#include <gpu/fsr3/ffx_fsr3_resources.h>"
    FSR4N10_FSR3_PROVIDER_TEXT "${FSR4N10_FSR3_PROVIDER_TEXT}")
file(WRITE "${FSR4N10_FSR3_PROVIDER_OVERLAY_SOURCE}" "${FSR4N10_FSR3_PROVIDER_TEXT}")

set(FSR4N10_FSR3_INTERNAL_OVERLAY "${FSR4N10_FSR3_REFERENCE_ROOT}/fidelityfx_internal")
file(MAKE_DIRECTORY "${FSR4N10_FSR3_INTERNAL_OVERLAY}")
set(FSR4N10_FSR3_UPSCALER_SOURCE "${FSR4N10_FSR3_SDK_ROOT}/upscalers/fsr3/internal/ffx_fsr3upscaler.cpp")
set(FSR4N10_FSR3_UPSCALER_OVERLAY_SOURCE "${FSR4N10_FSR3_INTERNAL_OVERLAY}/ffx_fsr3upscaler.cpp")
file(READ "${FSR4N10_FSR3_UPSCALER_SOURCE}" FSR4N10_FSR3_UPSCALER_TEXT)
foreach(FSR4N10_FSR3_INCLUDE_REPLACEMENT IN ITEMS
    "#include \"../include/ffx_fsr3upscaler.h\"|#include <ffx_fsr3upscaler.h>"
    "#include \"../../../api/internal/ffx_backends.h\"|#include <ffx_backends.h>"
    "#include \"../../../api/internal/gpu/ffx_core.h\"|#include <ffx_core.h>"
    "#include \"../../../api/internal/ffx_object_management.h\"|#include <ffx_object_management.h>"
    "#include \"../../../amdinternal/api/internal/git_hash_branch.h\"|#include <ffx_fsr3_git_hash_branch.h>"
    "#include \"../include/gpu/fsr1/ffx_fsr1.h\"|#include <gpu/fsr1/ffx_fsr1.h>"
    "#include \"../include/gpu/spd/ffx_spd.h\"|#include <gpu/spd/ffx_spd.h>"
    "#include \"../include/gpu/fsr3upscaler/ffx_fsr3upscaler_callbacks_hlsl.h\"|#include <gpu/fsr3upscaler/ffx_fsr3upscaler_callbacks_hlsl.h>"
    "#include \"../include/gpu/fsr3upscaler/ffx_fsr3upscaler_resources.h\"|#include <gpu/fsr3upscaler/ffx_fsr3upscaler_resources.h>"
    "#include \"../include/gpu/fsr3upscaler/ffx_fsr3upscaler_common.h\"|#include <gpu/fsr3upscaler/ffx_fsr3upscaler_common.h>")
    string(REPLACE "|" ";" FSR4N10_FSR3_INCLUDE_FIELDS "${FSR4N10_FSR3_INCLUDE_REPLACEMENT}")
    list(GET FSR4N10_FSR3_INCLUDE_FIELDS 0 FSR4N10_FSR3_INCLUDE_OLD)
    list(GET FSR4N10_FSR3_INCLUDE_FIELDS 1 FSR4N10_FSR3_INCLUDE_NEW)
    string(FIND "${FSR4N10_FSR3_UPSCALER_TEXT}" "${FSR4N10_FSR3_INCLUDE_OLD}" FSR4N10_FSR3_INCLUDE_OFFSET)
    if(FSR4N10_FSR3_INCLUDE_OFFSET EQUAL -1)
        message(FATAL_ERROR "Pinned FSR3 source include changed; review the local build overlay: ${FSR4N10_FSR3_INCLUDE_OLD}")
    endif()
    string(REPLACE "${FSR4N10_FSR3_INCLUDE_OLD}" "${FSR4N10_FSR3_INCLUDE_NEW}"
        FSR4N10_FSR3_UPSCALER_TEXT "${FSR4N10_FSR3_UPSCALER_TEXT}")
endforeach()
file(WRITE "${FSR4N10_FSR3_UPSCALER_OVERLAY_SOURCE}" "${FSR4N10_FSR3_UPSCALER_TEXT}")

set(FSR4N10_FSR3_SHADERBLOBS_SOURCE
    "${FSR4N10_FSR3_SDK_ROOT}/upscalers/fsr3/internal/ffx_fsr3upscaler_shaderblobs.cpp")
set(FSR4N10_FSR3_SHADERBLOBS_OVERLAY_SOURCE
    "${FSR4N10_FSR3_INTERNAL_OVERLAY}/ffx_fsr3upscaler_shaderblobs.cpp")
file(READ "${FSR4N10_FSR3_SHADERBLOBS_SOURCE}" FSR4N10_FSR3_SHADERBLOBS_TEXT)
string(REPLACE "#include \"../../../api/internal/ffx_util.h\"" "#include <ffx_util.h>"
    FSR4N10_FSR3_SHADERBLOBS_TEXT "${FSR4N10_FSR3_SHADERBLOBS_TEXT}")
set(FSR4N10_FSR3_LEGACY_BLOB_ADAPTER [=[#include "ffx_fsr3upscaler_private.h"

// The available pinned FidelityFX_SC emits reflection records without entryName.
// FSR3's selectors compile these shaders with -E CS, so adapt that record to the
// pinned SDK's FfxShaderBlob ABI with the actual compiled entry point.
#undef POPULATE_SHADER_BLOB_FFX
#define POPULATE_SHADER_BLOB_FFX(info, index) \
    { \
        info[index].blobData, \
        info[index].blobSize, \
        "CS", \
        info[index].numConstantBuffers, \
        info[index].numSRVTextures, \
        info[index].numUAVTextures, \
        info[index].numSRVBuffers, \
        info[index].numUAVBuffers, \
        info[index].numSamplers, \
        info[index].numRTAccelerationStructures, \
        info[index].constantBufferNames, \
        info[index].constantBufferBindings, \
        info[index].constantBufferCounts, \
        info[index].constantBufferSpaces, \
        info[index].srvTextureNames, \
        info[index].srvTextureBindings, \
        info[index].srvTextureCounts, \
        info[index].srvTextureSpaces, \
        info[index].uavTextureNames, \
        info[index].uavTextureBindings, \
        info[index].uavTextureCounts, \
        info[index].uavTextureSpaces, \
        info[index].srvBufferNames, \
        info[index].srvBufferBindings, \
        info[index].srvBufferCounts, \
        info[index].srvBufferSpaces, \
        info[index].uavBufferNames, \
        info[index].uavBufferBindings, \
        info[index].uavBufferCounts, \
        info[index].uavBufferSpaces, \
        info[index].samplerNames, \
        info[index].samplerBindings, \
        info[index].samplerCounts, \
        info[index].samplerSpaces, \
        info[index].rtAccelerationStructureNames, \
        info[index].rtAccelerationStructureBindings, \
        info[index].rtAccelerationStructureCounts, \
        info[index].rtAccelerationStructureSpaces \
    }
]=])
string(REPLACE "#include \"ffx_fsr3upscaler_private.h\""
    "${FSR4N10_FSR3_LEGACY_BLOB_ADAPTER}"
    FSR4N10_FSR3_SHADERBLOBS_TEXT "${FSR4N10_FSR3_SHADERBLOBS_TEXT}")
string(FIND "${FSR4N10_FSR3_SHADERBLOBS_TEXT}" "#include <ffx_util.h>" FSR4N10_FSR3_SHADERBLOBS_INCLUDE_OFFSET)
if(FSR4N10_FSR3_SHADERBLOBS_INCLUDE_OFFSET EQUAL -1)
    message(FATAL_ERROR "Pinned FSR3 shader selector include changed; review the local build overlay")
endif()
file(WRITE "${FSR4N10_FSR3_SHADERBLOBS_OVERLAY_SOURCE}" "${FSR4N10_FSR3_SHADERBLOBS_TEXT}")

set(FSR4N10_FSR3_PRIVATE_HEADER_SOURCE
    "${FSR4N10_FSR3_SDK_ROOT}/upscalers/fsr3/internal/ffx_fsr3upscaler_private.h")
set(FSR4N10_FSR3_PRIVATE_HEADER_OVERLAY
    "${FSR4N10_FSR3_INTERNAL_OVERLAY}/ffx_fsr3upscaler_private.h")
file(READ "${FSR4N10_FSR3_PRIVATE_HEADER_SOURCE}" FSR4N10_FSR3_PRIVATE_HEADER_TEXT)
string(REPLACE "#include \"../include/gpu/fsr3upscaler/ffx_fsr3upscaler_resources.h\""
    "#include <gpu/fsr3upscaler/ffx_fsr3upscaler_resources.h>"
    FSR4N10_FSR3_PRIVATE_HEADER_TEXT "${FSR4N10_FSR3_PRIVATE_HEADER_TEXT}")
string(REPLACE "#include \"../../../amdinternal/api/internal/ffx_watermark.h\""
    "#include <ffx_fsr3_watermark_compat.h>"
    FSR4N10_FSR3_PRIVATE_HEADER_TEXT "${FSR4N10_FSR3_PRIVATE_HEADER_TEXT}")
if(NOT FSR4N10_FSR3_PRIVATE_HEADER_TEXT MATCHES "ffx_fsr3_watermark_compat.h")
    message(FATAL_ERROR "Pinned FSR3 watermark include changed; review the local build overlay")
endif()
file(WRITE "${FSR4N10_FSR3_PRIVATE_HEADER_OVERLAY}" "${FSR4N10_FSR3_PRIVATE_HEADER_TEXT}")
file(WRITE "${FSR4N10_FSR3_INTERNAL_OVERLAY}/ffx_fsr3_watermark_compat.h" [=[
#pragma once
// The SDK tag omits its optional AMD-internal watermark module. This local
// no-op type keeps the default reference path buildable without altering FSR3
// reconstruction. The runtime rejects MLSR-WATERMARK because injection is unavailable.
class FfxWatermark {
public:
    template<typename Interface>
    FfxWatermark(Interface*, unsigned int) noexcept {}
    template<typename Resource, typename Message>
    void Dispatch(Resource&&, Message&&) noexcept {}
};
]=])
file(WRITE "${FSR4N10_FSR3_INTERNAL_OVERLAY}/ffx_fsr3_git_hash_branch.h"
    "#pragma once\n#define GIT_HASH \"${FSR4N10_FSR3_SDK_COMMIT}\"\n#define GIT_COMMIT_SUBJECT \"Pinned FSR3.1.5 reference\"\n")
file(APPEND "${FSR4N10_FSR3_PROVIDER_OVERLAY_SOURCE}" [=[
#include "ffx_fsr3upscaler_private.h"

extern "C" FfxApiResource fsr4n10Fsr3GetInternalResource(ffxContext* context, uint32_t resourceId, bool unorderedAccess)
{
    if (context == nullptr || *context == nullptr || resourceId >= FFX_FSR3UPSCALER_RESOURCE_IDENTIFIER_COUNT)
        return FfxApiResource{};
    auto* internalContext = reinterpret_cast<InternalFsr3UpscalerUContext*>(*context);
    auto* effectContext = reinterpret_cast<FfxFsr3UpscalerContext_Private*>(internalContext->context.data);
    const FfxResourceInternal resource = unorderedAccess ? effectContext->uavResources[resourceId] : effectContext->srvResources[resourceId];
    return internalContext->backendInterface.fpGetResource(&internalContext->backendInterface, resource);
}
]=])

add_executable(fsr4n10_fsr3_reference
    src/harness/fsr3_reference_main.cpp
    src/teacher/fsr3_reference_runtime.cpp
    "${FSR4N10_FSR3_SDK_ROOT}/api/internal/ffx_assert.cpp"
    "${FSR4N10_FSR3_SDK_ROOT}/api/internal/ffx_message.cpp"
    "${FSR4N10_FSR3_SDK_ROOT}/api/internal/ffx_object_management.cpp"
    "${FSR4N10_FSR3_SDK_ROOT}/backend/dx12/ffx_backends_dx12.cpp"
    "${FSR4N10_FSR3_SDK_ROOT}/backend/dx12/ffx_dx12.cpp"
    "${FSR4N10_FSR3_PROVIDER_OVERLAY_SOURCE}"
    "${FSR4N10_FSR3_UPSCALER_OVERLAY_SOURCE}"
    "${FSR4N10_FSR3_SHADERBLOBS_OVERLAY_SOURCE}"
)
add_dependencies(fsr4n10_fsr3_reference compile_fsr3_reference_shaders)
target_include_directories(fsr4n10_fsr3_reference PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}/include"
    "${FSR4N10_FIDELITYFX_COMPAT_DIR}"
    "${FSR4N10_FSR3_INTERNAL_OVERLAY}"
    "${FSR4N10_FSR3_PROVIDER_OVERLAY_DIR}"
    "${FSR4N10_FSR3_REFERENCE_ROOT}/ffx_sc_output"
    "${FSR4N10_FSR3_SDK_ROOT}/api/include"
    "${FSR4N10_FSR3_SDK_ROOT}/api/include/dx12"
    "${FSR4N10_FSR3_SDK_ROOT}/api/internal"
    "${FSR4N10_FSR3_SDK_ROOT}/api/internal/dx12"
    "${FSR4N10_FSR3_SDK_ROOT}/api/internal/gpu"
    "${FSR4N10_FSR3_SDK_ROOT}/backend/dx12"
    "${FSR4N10_FSR3_SDK_ROOT}/upscalers/include"
    "${FSR4N10_FSR3_SDK_ROOT}/upscalers/fsr3/include"
    "${FSR4N10_FSR3_SDK_ROOT}/upscalers/fsr3/include/gpu"
    "${FSR4N10_FSR3_SDK_ROOT}/upscalers/fsr3/internal"
)
target_compile_definitions(fsr4n10_fsr3_reference PRIVATE
    "FFX_BACKEND_DX12=0"
    FFX_UPSCALER
    _WINDOWS
    NOMINMAX
    "FSR4N10_FSR3_SDK_COMMIT=\"${FSR4N10_FSR3_SDK_COMMIT}\""
    "FSR4N10_BUILD_COMMIT=\"${FSR4N10_BUILD_COMMIT}\""
    "FSR4N10_BUILD_CONFIGURATION=\"$<CONFIG>\""
    "FSR4N10_FSR3_SHADER_MANIFEST=\"${FSR4N10_FSR3_SHADER_MANIFEST}\"")
target_link_libraries(fsr4n10_fsr3_reference PRIVATE fsr4n10_sequence bcrypt d3d12 dxgi dxguid user32)
fsr4n10_enable_warnings(fsr4n10_fsr3_reference)
target_compile_options(fsr4n10_fsr3_reference PRIVATE /wd4505 /wd4201 /wd4324)

add_library(fsr4n10_teacher_runtime STATIC src/teacher/gpu_teacher.cpp)
target_include_directories(fsr4n10_teacher_runtime PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}/include"
    "${FSR4N10_FIDELITYFX_ROOT}/api/include"
    "${FSR4N10_FIDELITYFX_ROOT}/api/include/dx12"
    "${FSR4N10_FIDELITYFX_ROOT}/api/internal"
    "${FSR4N10_FIDELITYFX_ROOT}/api/internal/dx12"
    "${FSR4N10_FIDELITYFX_ROOT}/backend/dx12"
    "${FSR4N10_FIDELITYFX_ROOT}/upscalers/include"
    "${FSR4N10_FIDELITYFX_ROOT}/upscalers/fsr3/include"
    "${FSR4N10_FIDELITYFX_ROOT}/upscalers/fsr4/include"
)
target_compile_definitions(fsr4n10_teacher_runtime PRIVATE
    FFX_BACKEND_DX12
    FFX_UPSCALER
    NOMINMAX
    "FSR4N10_FSR4_SOURCE_COMMIT=\"${FSR4N10_FSR4_SOURCE_COMMIT}\""
    "FSR4N10_BUILD_COMMIT=\"${FSR4N10_BUILD_COMMIT}\""
    "FSR4N10_BUILD_CONFIGURATION=\"$<CONFIG>\""
    "FSR4N10_PROVIDER_SHADER_MANIFEST=\"${FSR4N10_PROVIDER_SHADER_DIR}/manifest.json\"")
target_link_libraries(fsr4n10_teacher_runtime PUBLIC fsr4n10_fsr4_teacher_provider fsr4n10_sequence PRIVATE bcrypt d3d12 dxgi)
if(FSR4N10_ENABLE_PASS_PREFIX_DIAGNOSTIC)
    target_compile_definitions(fsr4n10_teacher_runtime PRIVATE FSR4N10_ENABLE_PASS_PREFIX_DIAGNOSTIC=1)
endif()
fsr4n10_enable_warnings(fsr4n10_teacher_runtime)
target_link_libraries(fsr4n10_harness PRIVATE fsr4n10_teacher_runtime)

add_custom_target(compile_reference_i8_native_1080
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tools/shaders/compile_reference_passes.py"
            --fsr4-root "${CMAKE_CURRENT_SOURCE_DIR}/third_party/fidelityfx-fsr4-source/Kits/FidelityFX/upscalers/fsr4"
            --dxc "${DXC_EXECUTABLE}"
            --output "${CMAKE_CURRENT_BINARY_DIR}/reference/i8"
            --preset native
            --tier 1080
    DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/tools/shaders/compile_reference_passes.py"
    COMMENT "Compiling pinned upstream FSR4 I8 native 1080p pass set"
    VERBATIM
)

add_custom_target(compile_reference_i8_all
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tools/shaders/compile_reference_passes.py"
            --fsr4-root "${CMAKE_CURRENT_SOURCE_DIR}/third_party/fidelityfx-fsr4-source/Kits/FidelityFX/upscalers/fsr4"
            --dxc "${DXC_EXECUTABLE}"
            --output "${CMAKE_CURRENT_BINARY_DIR}/reference/i8"
            --preset all
            --tier all
    DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/tools/shaders/compile_reference_passes.py"
    COMMENT "Compiling all pinned upstream FSR4 I8 presets and resolution tiers"
    VERBATIM
)

add_custom_target(generate_native_1080_fp16_parameter_pack
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tools/model/extract_fp16_weights.py"
            --fsr4-root "${CMAKE_CURRENT_SOURCE_DIR}/third_party/fidelityfx-fsr4-source/Kits/FidelityFX/upscalers/fsr4"
            --lock "${CMAKE_CURRENT_SOURCE_DIR}/third_party/LOCK.json"
            --output "${CMAKE_CURRENT_BINARY_DIR}/model/fp16"
            --preset native
            --tier 1080
    DEPENDS
        "${CMAKE_CURRENT_SOURCE_DIR}/tools/model/extract_fp16_weights.py"
        "${CMAKE_CURRENT_SOURCE_DIR}/third_party/LOCK.json"
    COMMENT "Extracting native/1080p FSR4 weights and biases to FP16"
    VERBATIM
)

add_custom_target(generate_fp16_parameter_packs_all
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tools/model/extract_fp16_weights.py"
            --fsr4-root "${CMAKE_CURRENT_SOURCE_DIR}/third_party/fidelityfx-fsr4-source/Kits/FidelityFX/upscalers/fsr4"
            --lock "${CMAKE_CURRENT_SOURCE_DIR}/third_party/LOCK.json"
            --output "${CMAKE_CURRENT_BINARY_DIR}/model/fp16"
            --preset all
            --tier all
    DEPENDS
        "${CMAKE_CURRENT_SOURCE_DIR}/tools/model/extract_fp16_weights.py"
        "${CMAKE_CURRENT_SOURCE_DIR}/third_party/LOCK.json"
    COMMENT "Extracting FP16 FSR4 parameter packs for all I8 presets and resolution tiers"
    VERBATIM
)

add_custom_target(generate_native_1080_model_pack
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tools/model/extract_fp16_weights.py"
            --fsr4-root "${CMAKE_CURRENT_SOURCE_DIR}/third_party/fidelityfx-fsr4-source/Kits/FidelityFX/upscalers/fsr4"
            --lock "${CMAKE_CURRENT_SOURCE_DIR}/third_party/LOCK.json"
            --output "${CMAKE_CURRENT_BINARY_DIR}/model/fp16"
            --preset native
            --tier 1080
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tools/model/build_model_packs.py"
            --index "${CMAKE_CURRENT_BINARY_DIR}/model/fp16/index.json"
    DEPENDS
        "${CMAKE_CURRENT_SOURCE_DIR}/tools/model/extract_fp16_weights.py"
        "${CMAKE_CURRENT_SOURCE_DIR}/tools/model/model_pack_format.py"
        "${CMAKE_CURRENT_SOURCE_DIR}/tools/model/build_model_packs.py"
        "${CMAKE_CURRENT_SOURCE_DIR}/third_party/LOCK.json"
    COMMENT "Generating the native/1080p versioned FSR4 parameter model pack"
    WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
    VERBATIM
)

add_custom_target(generate_fp16_model_packs_all
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tools/model/extract_fp16_weights.py"
            --fsr4-root "${CMAKE_CURRENT_SOURCE_DIR}/third_party/fidelityfx-fsr4-source/Kits/FidelityFX/upscalers/fsr4"
            --lock "${CMAKE_CURRENT_SOURCE_DIR}/third_party/LOCK.json"
            --output "${CMAKE_CURRENT_BINARY_DIR}/model/fp16"
            --preset all
            --tier all
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tools/model/build_model_packs.py"
            --index "${CMAKE_CURRENT_BINARY_DIR}/model/fp16/index.json"
    DEPENDS
        "${CMAKE_CURRENT_SOURCE_DIR}/tools/model/extract_fp16_weights.py"
        "${CMAKE_CURRENT_SOURCE_DIR}/tools/model/model_pack_format.py"
        "${CMAKE_CURRENT_SOURCE_DIR}/tools/model/build_model_packs.py"
        "${CMAKE_CURRENT_SOURCE_DIR}/third_party/LOCK.json"
    COMMENT "Generating versioned FSR4 FP16 parameter packs for all preset/tier combinations"
    WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
    VERBATIM
)

include(CTest)
if(BUILD_TESTING)
    add_test(
        NAME model_tools_unit_tests
        COMMAND "${Python3_EXECUTABLE}" -m unittest discover -s "${CMAKE_CURRENT_SOURCE_DIR}/tests" -v
    )
endif()
