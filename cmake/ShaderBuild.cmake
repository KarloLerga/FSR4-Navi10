function(fsr4n10_compile_hlsl target source entry_point output profile)
    set(compile_args
        -T "${profile}"
        -HV 2021
        -O3
        -enable-16bit-types
        -E "${entry_point}"
        -Fo "${output}"
        ${ARGN}
    )

    add_custom_command(
        OUTPUT "${output}"
        COMMAND "${CMAKE_COMMAND}" -E make_directory "${CMAKE_CURRENT_BINARY_DIR}/generated-shaders"
        COMMAND "${DXC_EXECUTABLE}" ${compile_args} "${source}"
        DEPENDS "${source}"
        COMMENT "DXC ${profile}: ${source} (${entry_point})"
        VERBATIM
    )
    set(FSR4N10_COMPILED_SHADER "${output}" PARENT_SCOPE)
    set(${target}_OUTPUT "${output}" PARENT_SCOPE)
endfunction()
