find_program(RGA_EXECUTABLE
    NAMES rga rga.exe
    HINTS "${CMAKE_SOURCE_DIR}/.tools/rga"
)

include(FindPackageHandleStandardArgs)
find_package_handle_standard_args(RGA REQUIRED_VARS RGA_EXECUTABLE)
mark_as_advanced(RGA_EXECUTABLE)
