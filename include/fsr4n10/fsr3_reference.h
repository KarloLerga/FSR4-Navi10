#pragma once

#include <filesystem>

namespace fsr4n10 {

int run_fsr3_reference_sequence(const std::filesystem::path& sequence_path,
                               const std::filesystem::path& report_path,
                               const std::filesystem::path& capture_root = {});

} // namespace fsr4n10
