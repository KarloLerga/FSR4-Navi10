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
    src/harness/upstream_pass0_smoke.cpp
    src/harness/frame_pipeline.cpp
    src/naviqsr/naviqsr_gpu.cpp
    src/naviqsr/naviqsr_network_gpu.cpp
    src/naviprism/msad4_validation.cpp
)
target_link_libraries(fsr4n10_harness PRIVATE fsr4n10_core bcrypt)
fsr4n10_enable_warnings(fsr4n10_harness)

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

add_custom_target(compile_provider_i8_native_1080
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tools/teacher/compile_provider_i8_native_1080.py"
            --repo-root "${CMAKE_CURRENT_SOURCE_DIR}"
            --output "${CMAKE_CURRENT_BINARY_DIR}/teacher/provider_i8_native_1080"
    BYPRODUCTS "${CMAKE_CURRENT_BINARY_DIR}/teacher/provider_i8_native_1080/manifest.json"
    DEPENDS
        "${CMAKE_CURRENT_SOURCE_DIR}/tools/teacher/compile_provider_i8_native_1080.py"
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
    "/* Build-only include shim. The pinned backend declares its two PIX function pointer types locally and loads them dynamically; no PIX header declarations are used. */\n")
file(WRITE "${FSR4N10_FIDELITYFX_PROVIDER_OVERLAY}/Kits/FidelityFX/api/internal/git_hash_branch.h"
    "#pragma once\n#define GIT_HASH \"${FSR4N10_FSR4_SOURCE_COMMIT}\"\n#define GIT_COMMIT_SUBJECT \"FSR4 Navi10 pinned provider source\"\n")
add_library(fsr4n10_fsr4_teacher_provider STATIC
    src/teacher/provider_i8_native_1080_shader_selector.cpp
    src/teacher/provider_query_compat.cpp
    "${FSR4N10_FIDELITYFX_ROOT}/api/internal/dx12/amd_extensions.cpp"
    "${FSR4N10_FIDELITYFX_ROOT}/api/internal/ffx_assert.cpp"
    "${FSR4N10_FIDELITYFX_ROOT}/api/internal/ffx_message.cpp"
    "${FSR4N10_FIDELITYFX_ROOT}/api/internal/ffx_object_management.cpp"
    "${FSR4N10_FIDELITYFX_ROOT}/api/internal/ffx_watermark.cpp"
    "${FSR4N10_FIDELITYFX_ROOT}/backend/dx12/ffx_backends_dx12.cpp"
    "${FSR4N10_FIDELITYFX_ROOT}/backend/dx12/ffx_dx12.cpp"
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
    NOMINMAX
)
target_link_libraries(fsr4n10_fsr4_teacher_provider PUBLIC d3d12 dxgi dxguid bcrypt user32)

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
target_link_libraries(fsr4n10_teacher_runtime PUBLIC fsr4n10_fsr4_teacher_provider PRIVATE bcrypt d3d12 dxgi)
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
