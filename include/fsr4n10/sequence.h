#pragma once

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <memory>
#include <string>
#include <vector>

namespace fsr4n10 {

struct SequenceMetadata {
    std::string sequence_id;
    std::string preset;
    std::string source_kind;
    std::string source_hash;
    std::string sequence_hash;
    std::uint64_t seed = 0;
    std::uint32_t render_width = 0;
    std::uint32_t render_height = 0;
    std::uint32_t output_width = 0;
    std::uint32_t output_height = 0;
    std::uint32_t scale_numerator = 0;
    std::uint32_t scale_denominator = 0;
    std::uint32_t frame_count = 0;
    std::uint32_t motion_convention_id = 0;
    bool reversed_depth = false;
};

struct SequenceFrameMetadata {
    std::uint32_t frame_index = 0;
    float frame_time_delta_ms = 0.0f;
    float jitter_x = 0.0f;
    float jitter_y = 0.0f;
    float previous_jitter_x = 0.0f;
    float previous_jitter_y = 0.0f;
    float exposure = 1.0f;
    float pre_exposure = 1.0f;
    bool reset = false;
    bool camera_cut = false;
    bool reactive_mask_valid = false;
    bool transparency_composition_mask_valid = false;
};

struct SequenceFrame {
    SequenceFrameMetadata metadata;
    std::vector<std::uint16_t> color_rgba_half;
    std::vector<float> depth;
    std::vector<std::uint16_t> motion_vectors_half;
    std::vector<std::uint8_t> reactive_mask;
    std::vector<std::uint8_t> transparency_composition_mask;
};

class F4Sequence final {
public:
    static F4Sequence open(const std::filesystem::path& path);

    F4Sequence(F4Sequence&&) noexcept;
    F4Sequence& operator=(F4Sequence&&) noexcept;
    F4Sequence(const F4Sequence&) = delete;
    F4Sequence& operator=(const F4Sequence&) = delete;
    ~F4Sequence();

    [[nodiscard]] const SequenceMetadata& metadata() const noexcept;
    [[nodiscard]] const SequenceFrameMetadata& frame_metadata(std::uint32_t frame_index) const;
    [[nodiscard]] SequenceFrame read_frame(std::uint32_t frame_index);

private:
    struct Impl;
    explicit F4Sequence(std::unique_ptr<Impl> implementation) noexcept;
    std::unique_ptr<Impl> implementation_;
};

[[nodiscard]] std::string sequence_frame_input_sha256(const SequenceFrame& frame);

} // namespace fsr4n10
