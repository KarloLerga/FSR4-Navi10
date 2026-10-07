#pragma once
#include <filesystem>

namespace fsr4n10 {
int run_fsr4_post_gpu_oracle(const std::filesystem::path& case_path,
                             const std::filesystem::path& report_path);
}
