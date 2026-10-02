#include "fsr4n10/upstream_smoke.h"

#include <algorithm>
#include <array>
#include <bit>
#include <cctype>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace fsr4n10 {
namespace {

constexpr std::uint32_t kRenderWidth = 960;
constexpr std::uint32_t kRenderHeight = 540;
constexpr std::uint32_t kOutputWidth = 1920;
constexpr std::uint32_t kOutputHeight = 1080;
constexpr std::uint32_t kModelInputChannels = 8;

struct Rgb {
    float r;
    float g;
    float b;
};

struct Image {
    std::uint32_t width = 0;
    std::uint32_t height = 0;
    std::vector<Rgb> pixels;
};

struct TemporalState {
    std::vector<Rgb> history;
    std::vector<std::array<float, 4>> recurrent;
};

std::string read_ppm_token(std::istream& input) {
    for (;;) {
        const int next = input.peek();
        if (next == std::char_traits<char>::eof()) {
            throw std::runtime_error("unexpected end of PPM header");
        }
        if (std::isspace(static_cast<unsigned char>(next)) != 0) {
            input.get();
            continue;
        }
        if (next == '#') {
            input.ignore(std::numeric_limits<std::streamsize>::max(), '\n');
            continue;
        }
        break;
    }

    std::string token;
    while (input.good()) {
        const int next = input.peek();
        if (next == std::char_traits<char>::eof() || std::isspace(static_cast<unsigned char>(next)) != 0 || next == '#') {
            break;
        }
        token.push_back(static_cast<char>(input.get()));
    }
    if (token.empty()) {
        throw std::runtime_error("empty token in PPM header");
    }
    return token;
}

Image read_srgb_ppm(const std::filesystem::path& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        throw std::runtime_error("cannot open input PPM image: " + path.string());
    }
    if (read_ppm_token(input) != "P6") {
        throw std::runtime_error("input must be a binary PPM (P6) image");
    }
    const auto width = static_cast<std::uint32_t>(std::stoul(read_ppm_token(input)));
    const auto height = static_cast<std::uint32_t>(std::stoul(read_ppm_token(input)));
    const auto maximum = static_cast<std::uint32_t>(std::stoul(read_ppm_token(input)));
    if (width != kRenderWidth || height != kRenderHeight || maximum == 0 || maximum > 255) {
        throw std::runtime_error("input PPM must be 960x540 with maxval in [1, 255]");
    }

    const int separator = input.get();
    if (separator == std::char_traits<char>::eof() || std::isspace(static_cast<unsigned char>(separator)) == 0) {
        throw std::runtime_error("PPM maxval must be followed by whitespace");
    }
    if (separator == '\r' && input.peek() == '\n') {
        input.get();
    }

    const std::size_t pixel_count = static_cast<std::size_t>(width) * height;
    std::vector<unsigned char> rgb_bytes(pixel_count * 3);
    input.read(reinterpret_cast<char*>(rgb_bytes.data()), static_cast<std::streamsize>(rgb_bytes.size()));
    if (input.gcount() != static_cast<std::streamsize>(rgb_bytes.size())) {
        throw std::runtime_error("input PPM pixel data is truncated");
    }

    Image image{width, height, std::vector<Rgb>(pixel_count)};
    const float inverse_max = 1.0f / static_cast<float>(maximum);
    for (std::size_t index = 0; index < pixel_count; ++index) {
        image.pixels[index] = {
            static_cast<float>(rgb_bytes[index * 3]) * inverse_max,
            static_cast<float>(rgb_bytes[index * 3 + 1]) * inverse_max,
            static_cast<float>(rgb_bytes[index * 3 + 2]) * inverse_max,
        };
    }
    return image;
}

std::uint16_t float_to_half(float value) noexcept {
    const std::uint32_t bits = std::bit_cast<std::uint32_t>(value);
    const std::uint16_t sign = static_cast<std::uint16_t>((bits >> 16U) & 0x8000U);
    const std::uint32_t exponent = (bits >> 23U) & 0xffU;
    const std::uint32_t mantissa = bits & 0x7fffffU;

    if (exponent == 0xffU) {
        return static_cast<std::uint16_t>(sign | (mantissa == 0 ? 0x7c00U : 0x7e00U));
    }

    const int half_exponent = static_cast<int>(exponent) - 127 + 15;
    if (half_exponent >= 31) {
        return static_cast<std::uint16_t>(sign | 0x7c00U);
    }
    if (half_exponent <= 0) {
        if (half_exponent < -10) {
            return sign;
        }
        const std::uint32_t significand = mantissa | 0x800000U;
        const unsigned shift = static_cast<unsigned>(14 - half_exponent);
        std::uint32_t rounded = significand >> shift;
        const std::uint32_t remainder = significand & ((1U << shift) - 1U);
        const std::uint32_t midpoint = 1U << (shift - 1U);
        if (remainder > midpoint || (remainder == midpoint && (rounded & 1U) != 0)) {
            ++rounded;
        }
        return static_cast<std::uint16_t>(sign | rounded);
    }

    std::uint32_t rounded_mantissa = mantissa >> 13U;
    const std::uint32_t remainder = mantissa & 0x1fffU;
    if (remainder > 0x1000U || (remainder == 0x1000U && (rounded_mantissa & 1U) != 0)) {
        ++rounded_mantissa;
    }
    std::uint32_t output_exponent = static_cast<std::uint32_t>(half_exponent);
    if (rounded_mantissa == 0x400U) {
        rounded_mantissa = 0;
        ++output_exponent;
        if (output_exponent >= 31U) {
            return static_cast<std::uint16_t>(sign | 0x7c00U);
        }
    }
    return static_cast<std::uint16_t>(sign | (output_exponent << 10U) | rounded_mantissa);
}

float half_to_float(std::uint16_t value) noexcept {
    const float sign = (value & 0x8000U) != 0 ? -1.0f : 1.0f;
    const std::uint32_t exponent = (value >> 10U) & 0x1fU;
    const std::uint32_t mantissa = value & 0x03ffU;
    if (exponent == 0) {
        return sign * std::ldexp(static_cast<float>(mantissa), -24);
    }
    if (exponent == 0x1fU) {
        return mantissa == 0 ? sign * std::numeric_limits<float>::infinity()
                             : std::numeric_limits<float>::quiet_NaN();
    }
    return sign * std::ldexp(static_cast<float>(1024U + mantissa), static_cast<int>(exponent) - 25);
}

float round_half(float value) noexcept {
    return half_to_float(float_to_half(value));
}

float remove_srgb(float value) {
    return value < 0.04045f ? value / 12.92f : std::pow((value + 0.055f) / 1.055f, 2.4f);
}

float apply_srgb(float value) {
    return value < 0.0031308f ? 12.92f * value : 1.055f * std::pow(value, 1.0f / 2.4f) - 0.055f;
}

Rgb apply_mu_law_srgb(Rgb encoded_color) {
    const auto tone = [](float channel) {
        const float linear = remove_srgb(channel);
        return std::max(0.1174f * std::log(1.0f + 150.0f * linear), 0.0f);
    };
    return {tone(encoded_color.r), tone(encoded_color.g), tone(encoded_color.b)};
}

Rgb remove_mu_law_to_srgb(Rgb color) {
    const auto inverse_tone = [](float channel) {
        const float linear = std::max((std::exp(8.51788f * channel) - 1.0f) / 150.0f, 0.0f);
        return std::clamp(apply_srgb(linear), 0.0f, 1.0f);
    };
    return {inverse_tone(color.r), inverse_tone(color.g), inverse_tone(color.b)};
}

Rgb rgb_to_ycbcr(Rgb color) {
    constexpr float ka = 0.2126f;
    constexpr float kb = 0.7152f;
    constexpr float kc = 0.0722f;
    constexpr float kd = 1.8556f;
    constexpr float ke = 1.5748f;
    const float y = color.r * ka + color.g * kb + color.b * kc;
    return {y, (color.b - y) / kd, (color.r - y) / ke};
}

float gaussian_weight(float distance, float upscale_factor) {
    constexpr float exponent_factor = -0.5f / (0.47f * 0.47f);
    const float scaled_distance = upscale_factor * distance;
    return std::exp(scaled_distance * scaled_distance * exponent_factor);
}

Rgb load_input(const Image& image, int x, int y) {
    const int max_x = static_cast<int>(image.width) - 1;
    const int max_y = static_cast<int>(image.height) - 1;
    const auto sx = static_cast<std::uint32_t>(std::clamp(x, 0, max_x));
    const auto sy = static_cast<std::uint32_t>(std::clamp(y, 0, max_y));
    return image.pixels[static_cast<std::size_t>(sy) * image.width + sx];
}

struct UpscaledInput {
    Rgb color;
    float alpha;
};

UpscaledInput upscale_input(const Image& image, std::uint32_t x, std::uint32_t y) {
    constexpr float scale = 2.0f;
    constexpr float inverse_scale = 0.5f;
    const float input_x = -0.5f + inverse_scale / 2.0f + static_cast<float>(x) * inverse_scale;
    const float input_y = -0.5f + inverse_scale / 2.0f + static_cast<float>(y) * inverse_scale;
    const int left = static_cast<int>(std::floor(input_x));
    const int top = static_cast<int>(std::floor(input_y));
    const float wx0 = gaussian_weight(std::abs(static_cast<float>(left) - input_x), scale);
    const float wx1 = gaussian_weight(std::abs(static_cast<float>(left + 1) - input_x), scale);
    const float wy0 = gaussian_weight(std::abs(static_cast<float>(top) - input_y), scale);
    const float wy1 = gaussian_weight(std::abs(static_cast<float>(top + 1) - input_y), scale);
    const std::array<float, 4> weights{wx0 * wy0, wx1 * wy0, wx0 * wy1, wx1 * wy1};
    const std::array<Rgb, 4> samples{
        apply_mu_law_srgb(load_input(image, left, top)),
        apply_mu_law_srgb(load_input(image, left + 1, top)),
        apply_mu_law_srgb(load_input(image, left, top + 1)),
        apply_mu_law_srgb(load_input(image, left + 1, top + 1)),
    };
    Rgb result{};
    float sum = 0.0f;
    float center_weight = 0.0f;
    for (std::size_t index = 0; index < weights.size(); ++index) {
        result.r += weights[index] * samples[index].r;
        result.g += weights[index] * samples[index].g;
        result.b += weights[index] * samples[index].b;
        sum += weights[index];
        center_weight = std::max(center_weight, weights[index]);
    }
    if (sum <= 0.0f) {
        throw std::runtime_error("input upscaler produced zero sample weight");
    }
    const float inverse_sum = 1.0f / sum;
    return {{result.r * inverse_sum, result.g * inverse_sum, result.b * inverse_sum}, center_weight};
}

std::vector<std::uint16_t> make_frame_features(
    const Image& image,
    bool reset,
    const TemporalState& previous,
    std::vector<Rgb>& reprojected_color) {
    const std::size_t pixel_count = static_cast<std::size_t>(kOutputWidth) * kOutputHeight;
    if (!reset && (previous.history.size() != pixel_count || previous.recurrent.size() != pixel_count)) {
        throw std::runtime_error("temporal history is missing or has an unexpected size");
    }
    std::vector<std::uint16_t> features(pixel_count * kModelInputChannels, 0);
    reprojected_color.resize(pixel_count);
    for (std::uint32_t y = 0; y < kOutputHeight; ++y) {
        for (std::uint32_t x = 0; x < kOutputWidth; ++x) {
            const std::size_t pixel_index = static_cast<std::size_t>(y) * kOutputWidth + x;
            const UpscaledInput current = upscale_input(image, x, y);
            Rgb history = current.color;
            std::array<float, 4> recurrent{};
            if (!reset) {
                history = previous.history[pixel_index];
                recurrent = previous.recurrent[pixel_index];
                history.r = std::max(history.r, 0.0f);
                history.g = std::max(history.g, 0.0f);
                history.b = std::max(history.b, 0.0f);
                const float temporal_weight = current.alpha * 0.1f;
                history = {
                    temporal_weight * current.color.r + (1.0f - temporal_weight) * history.r,
                    temporal_weight * current.color.g + (1.0f - temporal_weight) * history.g,
                    temporal_weight * current.color.b + (1.0f - temporal_weight) * history.b,
                };
            }
            reprojected_color[pixel_index] = {round_half(history.r), round_half(history.g), round_half(history.b)};
            const Rgb input_ycbcr = rgb_to_ycbcr(current.color);
            const Rgb history_ycbcr = rgb_to_ycbcr(history);
            const float cb_delta = input_ycbcr.g - history_ycbcr.g;
            const float cr_delta = input_ycbcr.b - history_ycbcr.b;
            const float chroma_distance = std::sqrt(cb_delta * cb_delta + cr_delta * cr_delta + 1e-6f);
            const std::size_t feature = pixel_index * kModelInputChannels;

            const float network_luma = round_half(input_ycbcr.r);
            features[feature] = float_to_half(round_half(2.0f * network_luma - 1.0f));
            features[feature + 1] = features[feature];
            features[feature + 2] = float_to_half(round_half(chroma_distance));
            for (std::size_t channel = 0; channel < recurrent.size(); ++channel) {
                const float network_recurrent = round_half(recurrent[channel]);
                features[feature + 3 + channel] = float_to_half(round_half(2.0f * network_recurrent - 1.0f));
            }
            features[feature + 7] = float_to_half(0.0f);
        }
    }
    return features;
}

float sigmoid(float value) {
    if (value >= 0.0f) {
        const float e = std::exp(-value);
        return 1.0f / (1.0f + e);
    }
    const float e = std::exp(value);
    return e / (1.0f + e);
}

std::uint8_t to_byte(float value) {
    return static_cast<std::uint8_t>(std::clamp(std::lround(std::clamp(value, 0.0f, 1.0f) * 255.0f), 0L, 255L));
}

void write_bmp(const std::filesystem::path& path, std::span<const Rgb> pixels) {
    constexpr std::uint32_t header_bytes = 54;
    const std::uint32_t row_bytes = kOutputWidth * 3;
    const std::uint32_t row_stride = (row_bytes + 3U) & ~3U;
    const std::uint32_t pixel_bytes = row_stride * kOutputHeight;
    const std::uint32_t file_bytes = header_bytes + pixel_bytes;
    std::array<std::byte, header_bytes> header{};
    const auto write_u16 = [&header](std::size_t offset, std::uint16_t value) {
        header[offset] = static_cast<std::byte>(value & 0xffU);
        header[offset + 1] = static_cast<std::byte>(value >> 8U);
    };
    const auto write_u32 = [&header](std::size_t offset, std::uint32_t value) {
        for (std::size_t byte = 0; byte < 4; ++byte) {
            header[offset + byte] = static_cast<std::byte>((value >> (byte * 8U)) & 0xffU);
        }
    };
    header[0] = std::byte{'B'};
    header[1] = std::byte{'M'};
    write_u32(2, file_bytes);
    write_u32(10, header_bytes);
    write_u32(14, 40);
    write_u32(18, kOutputWidth);
    write_u32(22, static_cast<std::uint32_t>(-static_cast<std::int32_t>(kOutputHeight)));
    write_u16(26, 1);
    write_u16(28, 24);
    write_u32(34, pixel_bytes);
    write_u32(38, 2835);
    write_u32(42, 2835);

    std::ofstream output(path, std::ios::binary);
    if (!output) {
        throw std::runtime_error("cannot create output BMP image: " + path.string());
    }
    output.write(reinterpret_cast<const char*>(header.data()), static_cast<std::streamsize>(header.size()));
    std::vector<std::byte> row(row_stride, std::byte{0});
    for (std::uint32_t y = 0; y < kOutputHeight; ++y) {
        for (std::uint32_t x = 0; x < kOutputWidth; ++x) {
            const Rgb color = pixels[static_cast<std::size_t>(y) * kOutputWidth + x];
            const std::size_t offset = static_cast<std::size_t>(x) * 3;
            row[offset] = static_cast<std::byte>(to_byte(color.b));
            row[offset + 1] = static_cast<std::byte>(to_byte(color.g));
            row[offset + 2] = static_cast<std::byte>(to_byte(color.r));
        }
        output.write(reinterpret_cast<const char*>(row.data()), static_cast<std::streamsize>(row.size()));
    }
    if (!output) {
        throw std::runtime_error("failed writing output BMP image: " + path.string());
    }
}

struct FrameOutput {
    std::vector<Rgb> image;
    TemporalState state;
};

FrameOutput make_output_image(const Image& image, std::span<const std::byte> model_output, std::span<const Rgb> reprojected_color) {
    const std::size_t expected_bytes = static_cast<std::size_t>(kOutputWidth) * kOutputHeight * kModelInputChannels * 2;
    if (model_output.size() != expected_bytes || reprojected_color.size() != static_cast<std::size_t>(kOutputWidth) * kOutputHeight) {
        throw std::runtime_error("model output tensor has an unexpected size");
    }
    FrameOutput output;
    output.image.resize(static_cast<std::size_t>(kOutputWidth) * kOutputHeight);
    output.state.history.resize(static_cast<std::size_t>(kOutputWidth) * kOutputHeight);
    output.state.recurrent.resize(static_cast<std::size_t>(kOutputWidth) * kOutputHeight);
    constexpr float scale = 2.0f;
    constexpr float inverse_scale = 0.5f;
    constexpr float origin_offset = -0.25f;
    constexpr int kernel_radius = 1;
    const auto read_feature = [model_output](std::size_t pixel_index, std::size_t channel) {
        const std::size_t offset = (pixel_index * kModelInputChannels + channel) * 2;
        const std::uint16_t bits = static_cast<std::uint16_t>(std::to_integer<std::uint8_t>(model_output[offset])) |
                                   static_cast<std::uint16_t>(std::to_integer<std::uint8_t>(model_output[offset + 1]) << 8U);
        return half_to_float(bits);
    };

    for (std::uint32_t y = 0; y < kOutputHeight; ++y) {
        for (std::uint32_t x = 0; x < kOutputWidth; ++x) {
            const std::size_t pixel_index = static_cast<std::size_t>(y) * kOutputWidth + x;
            const std::array<float, 4> model_parameters{
                read_feature(pixel_index, 0),
                read_feature(pixel_index, 1),
                read_feature(pixel_index, 2),
                read_feature(pixel_index, 3),
            };
            const float correlation = std::tanh(model_parameters[0]);
            const float scale_x = 2.0f / (1.0f + std::exp(-model_parameters[1]));
            const float scale_y = 2.0f / (1.0f + std::exp(-model_parameters[2]));
            const float scale_x2 = scale_x * scale_x;
            const float scale_y2 = scale_y * scale_y;
            const float scale_xy = scale_x * scale_y;

            const float input_x = origin_offset + static_cast<float>(x) * inverse_scale;
            const float input_y = origin_offset + static_cast<float>(y) * inverse_scale;
            const int center_x = static_cast<int>(std::nearbyint(input_x));
            const int center_y = static_cast<int>(std::nearbyint(input_y));
            Rgb upscaled_color{};
            float total_weight = 0.0f;
            for (int dy = 0; dy < 3; ++dy) {
                const int sample_y = center_y + dy - kernel_radius;
                const float distance_y = (static_cast<float>(sample_y) - input_y) * scale;
                const float distance_y2 = distance_y * distance_y;
                for (int dx = 0; dx < 3; ++dx) {
                    const int sample_x = center_x + dx - kernel_radius;
                    const float distance_x = (static_cast<float>(sample_x) - input_x) * scale;
                    const float distance_x2 = distance_x * distance_x;
                    const float exponent = (-0.5f / (0.47f * 0.47f)) *
                                           (distance_x2 * scale_x2 + 2.0f * correlation * (distance_x * distance_y) * scale_xy +
                                            distance_y2 * scale_y2);
                    const float weight = std::exp(exponent);
                    const Rgb sample = apply_mu_law_srgb(load_input(image, sample_x, sample_y));
                    upscaled_color.r += sample.r * weight;
                    upscaled_color.g += sample.g * weight;
                    upscaled_color.b += sample.b * weight;
                    total_weight += weight;
                }
            }
            if (!(total_weight > 0.0f) || !std::isfinite(total_weight)) {
                throw std::runtime_error(
                    "post-filter generated an invalid weight sum at (" + std::to_string(x) + "," +
                    std::to_string(y) + "): params=" + std::to_string(model_parameters[0]) + "," +
                    std::to_string(model_parameters[1]) + "," + std::to_string(model_parameters[2]) + "," +
                    std::to_string(model_parameters[3]) + ", corr=" + std::to_string(correlation) +
                    ", scales=" + std::to_string(scale_x) + "," + std::to_string(scale_y) +
                    ", weight=" + std::to_string(total_weight));
            }
            const float inverse_total = 1.0f / total_weight;
            upscaled_color.r *= inverse_total;
            upscaled_color.g *= inverse_total;
            upscaled_color.b *= inverse_total;
            const float blending = sigmoid(model_parameters[3]);
            const Rgb history = reprojected_color[pixel_index];
            const Rgb model_color{
                upscaled_color.r * (1.0f - blending) + history.r * blending,
                upscaled_color.g * (1.0f - blending) + history.g * blending,
                upscaled_color.b * (1.0f - blending) + history.b * blending,
            };
            output.image[pixel_index] = remove_mu_law_to_srgb(model_color);
            output.state.history[pixel_index] = {
                round_half(model_color.r), round_half(model_color.g), round_half(model_color.b)};
            output.state.recurrent[pixel_index] = {
                round_half(sigmoid(read_feature(pixel_index, 4))),
                round_half(sigmoid(read_feature(pixel_index, 5))),
                round_half(sigmoid(read_feature(pixel_index, 6))),
                round_half(sigmoid(read_feature(pixel_index, 7))),
            };
        }
    }
    return output;
}

} // namespace

int run_upstream_i8_image_smoke(const std::filesystem::path& input_path, const std::filesystem::path& output_path) {
    const Image input = read_srgb_ppm(input_path);
    TemporalState previous{};
    FrameOutput output{};
    for (std::uint32_t frame = 0; frame < 2; ++frame) {
        std::vector<Rgb> reprojected_color;
        const auto model_input = make_frame_features(input, frame == 0, previous, reprojected_color);
        const auto model_input_bytes = std::as_bytes(std::span<const std::uint16_t>(model_input));
        const auto model_output = run_upstream_i8_model(model_input_bytes);
        output = make_output_image(input, model_output, reprojected_color);
        previous = output.state;
    }
    write_bmp(output_path, std::span<const Rgb>(output.image));
    std::cout << "Wrote " << kOutputWidth << 'x' << kOutputHeight << " RGB output to " << output_path.string() << ". "
              << "The I8 neural passes ran on the RX 5700 XT; source-derived preprocessing and postprocessing ran on the CPU. "
              << "This static two-frame sequence resets history on frame one and reuses recurrent state on frame two. "
              << "It has not been compared with AMD's reference output.\n";
    return 0;
}

} // namespace fsr4n10
