#pragma once

#include <filesystem>

namespace fsr4n10 {

int benchmark_naviprism_msad4(const std::filesystem::path& report_path);
int validate_naviprism_sarm(const std::filesystem::path& report_path);
int validate_naviprism_thfa(const std::filesystem::path& report_path);
int validate_naviprism_router(const std::filesystem::path& report_path);
int validate_naviprism_phase_reservoir(const std::filesystem::path& report_path);

} // namespace fsr4n10
