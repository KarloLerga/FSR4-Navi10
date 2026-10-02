find_program(DXC_EXECUTABLE NAMES dxc dxc.exe)

if(DXC_EXECUTABLE)
    execute_process(
        COMMAND "${DXC_EXECUTABLE}" --version
        RESULT_VARIABLE DXC_VERSION_RESULT
        OUTPUT_VARIABLE DXC_VERSION_OUTPUT
        ERROR_VARIABLE DXC_VERSION_ERROR
        OUTPUT_STRIP_TRAILING_WHITESPACE
    )
    if(DXC_VERSION_RESULT EQUAL 0)
        string(STRIP "${DXC_VERSION_OUTPUT}\n${DXC_VERSION_ERROR}" DXC_VERSION)
        string(REGEX MATCH "[0-9]+\\.[0-9]+\\.[0-9]+(\\.[0-9]+)?" DXC_VERSION "${DXC_VERSION}")
    endif()
endif()

include(FindPackageHandleStandardArgs)
find_package_handle_standard_args(DXC
    REQUIRED_VARS DXC_EXECUTABLE
    VERSION_VAR DXC_VERSION
)
mark_as_advanced(DXC_EXECUTABLE)
