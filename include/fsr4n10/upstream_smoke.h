#pragma once

#include <cstddef>
#include <filesystem>
#include <span>
#include <vector>

namespace fsr4n10 {

int run_upstream_pass0_smoke();
int run_upstream_i8_zero_model_smoke();
int run_upstream_i8_zero_model_benchmark();
std::vector<std::byte> run_upstream_i8_model(std::span<const std::byte> model_input);
int run_upstream_i8_image_smoke(const std::filesystem::path& input_path, const std::filesystem::path& output_path);

} // namespace fsr4n10
