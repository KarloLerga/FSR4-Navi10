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
)
target_link_libraries(fsr4n10_harness PRIVATE fsr4n10_core)
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
