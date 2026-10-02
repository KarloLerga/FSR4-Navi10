function(fsr4n10_enable_warnings target)
    if(MSVC)
        target_compile_options(${target} PRIVATE
            /W4
            /WX
            /permissive-
            /EHsc
            /Zc:__cplusplus
            /utf-8
        )
    endif()
endfunction()
