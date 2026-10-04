#define NOMINMAX
#include "fsr4n10/naviprism.h"

#include <Windows.h>
#include <d3d12.h>
#include <dxgi1_6.h>
#include <bcrypt.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>
#include <system_error>
#include <vector>
#include <wrl/client.h>

namespace fsr4n10 {
namespace {

using Microsoft::WRL::ComPtr;

constexpr UINT kCaseCount = 4096;
constexpr UINT kSamplesPerChunk = 48;
constexpr UINT kChunkCount = 2;
constexpr UINT kSamplesPerCase = kSamplesPerChunk * kChunkCount;
constexpr UINT kWarmupCount = 5;
constexpr UINT kMeasuredCount = 20;
constexpr UINT kDispatchesPerSample = 32;
constexpr UINT kRunCount = kWarmupCount + kMeasuredCount;
constexpr UINT kAlgorithmCount = 3;
constexpr UINT kQueryCount = kAlgorithmCount * kRunCount * 2;
constexpr std::uint32_t kMaximumDifferencePerCall = 4U * 254U;
constexpr std::uint32_t kSafeCallsPerChunk = 48;

struct MsadInput {
    std::uint32_t reference;
    std::uint32_t source_low;
    std::uint32_t source_high;
    std::uint32_t padding;
};
static_assert(sizeof(MsadInput) == 16);

struct UInt4 {
    std::uint32_t x;
    std::uint32_t y;
    std::uint32_t z;
    std::uint32_t w;
};
static_assert(sizeof(UInt4) == 16);

struct Algorithm {
    const char* name;
    const wchar_t* shader;
};

constexpr std::array<Algorithm, kAlgorithmCount> kAlgorithms{{
    {"msad4", L"naviprism_msad4.dxil"},
    {"scalar_u8", L"naviprism_msad4_scalar.dxil"},
    {"fp16_difference_fp32_sum", L"naviprism_msad4_fp16.dxil"},
}};

void check_hr(HRESULT result, const char* operation) {
    if (FAILED(result)) {
        throw std::system_error(static_cast<int>(result), std::system_category(), operation);
    }
}

D3D12_HEAP_PROPERTIES heap_properties(D3D12_HEAP_TYPE type) {
    D3D12_HEAP_PROPERTIES result{};
    result.Type = type;
    result.CreationNodeMask = 1;
    result.VisibleNodeMask = 1;
    return result;
}

D3D12_RESOURCE_DESC buffer_description(
    std::uint64_t size,
    D3D12_RESOURCE_FLAGS flags = D3D12_RESOURCE_FLAG_NONE) {
    D3D12_RESOURCE_DESC result{};
    result.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
    result.Width = size;
    result.Height = 1;
    result.DepthOrArraySize = 1;
    result.MipLevels = 1;
    result.SampleDesc.Count = 1;
    result.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    result.Flags = flags;
    return result;
}

ComPtr<ID3D12Device> create_target_device() {
    ComPtr<IDXGIFactory6> factory;
    check_hr(CreateDXGIFactory2(0, IID_PPV_ARGS(&factory)), "CreateDXGIFactory2 failed");
    for (UINT index = 0;; ++index) {
        ComPtr<IDXGIAdapter1> adapter;
        const HRESULT enum_result = factory->EnumAdapters1(index, &adapter);
        if (enum_result == DXGI_ERROR_NOT_FOUND) break;
        check_hr(enum_result, "EnumAdapters1 failed");
        DXGI_ADAPTER_DESC1 description{};
        check_hr(adapter->GetDesc1(&description), "Read adapter description failed");
        if (description.VendorId != 0x1002 || description.DeviceId != 0x731F ||
            (description.Flags & DXGI_ADAPTER_FLAG_SOFTWARE) != 0) continue;
        ComPtr<ID3D12Device> device;
        check_hr(D3D12CreateDevice(adapter.Get(), D3D_FEATURE_LEVEL_11_0,
                                   IID_PPV_ARGS(&device)),
                 "RX 5700 XT does not expose a D3D12 device");
        return device;
    }
    throw std::runtime_error("RX 5700 XT (PCI 1002:731F) was not found");
}

std::filesystem::path executable_directory() {
    std::array<wchar_t, 32768> path{};
    const DWORD length = GetModuleFileNameW(nullptr, path.data(),
                                             static_cast<DWORD>(path.size()));
    if (length == 0 || length >= path.size()) {
        throw std::runtime_error("GetModuleFileNameW failed while locating NaviPRISM DXIL");
    }
    return std::filesystem::path(path.data()).parent_path();
}

std::vector<std::byte> read_shader(const std::filesystem::path& path) {
    std::ifstream file(path, std::ios::binary | std::ios::ate);
    if (!file) throw std::runtime_error("Cannot open NaviPRISM shader: " + path.string());
    const auto end = file.tellg();
    if (end <= 0) throw std::runtime_error("NaviPRISM shader is empty: " + path.string());
    std::vector<std::byte> data(static_cast<std::size_t>(end));
    file.seekg(0);
    file.read(reinterpret_cast<char*>(data.data()), static_cast<std::streamsize>(data.size()));
    if (!file) throw std::runtime_error("Failed to read NaviPRISM shader: " + path.string());
    return data;
}

std::string sha256_hex(const std::vector<std::byte>& data) {
    BCRYPT_ALG_HANDLE algorithm = nullptr;
    BCRYPT_HASH_HANDLE hash = nullptr;
    auto require = [](NTSTATUS status, const char* operation) {
        if (status < 0) throw std::runtime_error(operation);
    };
    require(BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0),
            "Open SHA-256 provider failed");
    struct AlgorithmCleanup {
        BCRYPT_ALG_HANDLE value;
        ~AlgorithmCleanup() { if (value) BCryptCloseAlgorithmProvider(value, 0); }
    } algorithm_cleanup{algorithm};
    ULONG object_size = 0;
    ULONG returned = 0;
    require(BCryptGetProperty(algorithm, BCRYPT_OBJECT_LENGTH,
                              reinterpret_cast<PUCHAR>(&object_size), sizeof(object_size),
                              &returned, 0), "Read SHA-256 object size failed");
    std::vector<UCHAR> object(object_size);
    std::array<UCHAR, 32> digest{};
    require(BCryptCreateHash(algorithm, &hash, object.data(), object_size, nullptr, 0, 0),
            "Create SHA-256 hash failed");
    struct HashCleanup {
        BCRYPT_HASH_HANDLE value;
        ~HashCleanup() { if (value) BCryptDestroyHash(value); }
    } hash_cleanup{hash};
    if (data.size() > std::numeric_limits<ULONG>::max()) {
        throw std::runtime_error("NaviPRISM DXIL is too large to hash");
    }
    require(BCryptHashData(hash,
                           reinterpret_cast<PUCHAR>(const_cast<std::byte*>(data.data())),
                           static_cast<ULONG>(data.size()), 0),
            "Hash NaviPRISM DXIL failed");
    require(BCryptFinishHash(hash, digest.data(), static_cast<ULONG>(digest.size()), 0),
            "Finish NaviPRISM DXIL hash failed");
    std::ostringstream result;
    result << std::hex << std::setfill('0');
    for (const UCHAR byte : digest) result << std::setw(2) << static_cast<unsigned>(byte);
    return result.str();
}

std::string target_driver_version() {
    ComPtr<IDXGIFactory6> factory;
    if (FAILED(CreateDXGIFactory2(0, IID_PPV_ARGS(&factory)))) return "unavailable";
    for (UINT index = 0;; ++index) {
        ComPtr<IDXGIAdapter1> adapter;
        const HRESULT enum_result = factory->EnumAdapters1(index, &adapter);
        if (enum_result == DXGI_ERROR_NOT_FOUND) break;
        if (FAILED(enum_result)) return "unavailable";
        DXGI_ADAPTER_DESC1 description{};
        if (FAILED(adapter->GetDesc1(&description)) || description.VendorId != 0x1002 ||
            description.DeviceId != 0x731F) continue;
        LARGE_INTEGER version{};
        if (FAILED(adapter->CheckInterfaceSupport(__uuidof(IDXGIDevice), &version))) {
            return "unavailable";
        }
        const auto packed = static_cast<std::uint64_t>(version.QuadPart);
        std::ostringstream result;
        result << ((packed >> 48) & 0xffffU) << '.' << ((packed >> 32) & 0xffffU) << '.'
               << ((packed >> 16) & 0xffffU) << '.' << (packed & 0xffffU);
        return result.str();
    }
    return "unavailable";
}

std::uint32_t packed_bytes(const std::array<std::uint8_t, 4>& bytes) {
    return static_cast<std::uint32_t>(bytes[0]) |
           (static_cast<std::uint32_t>(bytes[1]) << 8U) |
           (static_cast<std::uint32_t>(bytes[2]) << 16U) |
           (static_cast<std::uint32_t>(bytes[3]) << 24U);
}

std::uint32_t packed_source_byte(const MsadInput& input, unsigned index) {
    const std::uint32_t word = index < 4 ? input.source_low : input.source_high;
    const unsigned shift = (index & 3U) * 8U;
    return (word >> shift) & 0xffU;
}

UInt4 scalar_reference(const std::vector<MsadInput>& inputs, std::size_t base) {
    std::array<std::uint64_t, 4> total{};
    for (UINT chunk = 0; chunk < kChunkCount; ++chunk) {
        std::array<std::uint32_t, 4> partial{};
        for (UINT sample = 0; sample < kSamplesPerChunk; ++sample) {
            const auto& input = inputs[base + chunk * kSamplesPerChunk + sample];
            for (unsigned alignment = 0; alignment < 4; ++alignment) {
                for (unsigned ref_index = 0; ref_index < 4; ++ref_index) {
                    const std::uint32_t reference =
                        (input.reference >> (ref_index * 8U)) & 0xffU;
                    if (reference == 0) continue;
                    const std::uint32_t source =
                        packed_source_byte(input, alignment + ref_index);
                    partial[alignment] += reference > source
                        ? reference - source : source - reference;
                }
            }
        }
        for (unsigned lane = 0; lane < 4; ++lane) {
            if (partial[lane] > 65535U ||
                partial[lane] > kSafeCallsPerChunk * kMaximumDifferencePerCall) {
                throw std::runtime_error("NaviPRISM reference chunk exceeded the msad4 bound");
            }
            total[lane] += partial[lane];
        }
    }
    return {static_cast<std::uint32_t>(total[0]), static_cast<std::uint32_t>(total[1]),
            static_cast<std::uint32_t>(total[2]), static_cast<std::uint32_t>(total[3])};
}

std::vector<MsadInput> make_inputs() {
    std::vector<MsadInput> inputs(static_cast<std::size_t>(kCaseCount) * kSamplesPerCase);
    std::mt19937 random(0x4e415649U);
    std::uniform_int_distribution<unsigned> valid_byte(1, 255);
    std::uniform_int_distribution<unsigned> mask_choice(0, 7);
    for (UINT case_index = 0; case_index < kCaseCount; ++case_index) {
        for (UINT sample = 0; sample < kSamplesPerCase; ++sample) {
            auto& input = inputs[static_cast<std::size_t>(case_index) * kSamplesPerCase + sample];
            if (case_index == 0) {
                input = {0xffffffffU, 0x01010101U, 0x01010101U, 0};
                continue;
            }
            if (case_index == 1 && sample == 0) {
                input = {0xA100B2C3U, 0xD7B0C372U, 0x4F57C2A3U, 0};
                continue;
            }
            std::array<std::uint8_t, 4> reference{};
            std::array<std::uint8_t, 4> source_low{};
            std::array<std::uint8_t, 4> source_high{};
            for (unsigned index = 0; index < 4; ++index) {
                reference[index] = mask_choice(random) == 0
                    ? 0 : static_cast<std::uint8_t>(valid_byte(random));
                source_low[index] = static_cast<std::uint8_t>(valid_byte(random));
                source_high[index] = static_cast<std::uint8_t>(valid_byte(random));
            }
            input = {packed_bytes(reference), packed_bytes(source_low),
                     packed_bytes(source_high), 0};
        }
    }
    return inputs;
}

void create_buffer(ID3D12Device* device, D3D12_HEAP_TYPE heap_type,
                   std::uint64_t size, D3D12_RESOURCE_STATES state,
                   ComPtr<ID3D12Resource>& resource,
                   D3D12_RESOURCE_FLAGS flags = D3D12_RESOURCE_FLAG_NONE) {
    const auto heap = heap_properties(heap_type);
    const auto description = buffer_description(size, flags);
    check_hr(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &description,
                                              state, nullptr, IID_PPV_ARGS(&resource)),
             "Create NaviPRISM benchmark buffer failed");
}

std::vector<std::byte> read_module(const Algorithm& algorithm, std::string& hash) {
    auto bytes = read_shader(executable_directory() / algorithm.shader);
    hash = sha256_hex(bytes);
    return bytes;
}

struct TimingSummary {
    double minimum{};
    double median{};
    double p90{};
    double p95{};
};

TimingSummary summarize(std::vector<double> samples) {
    std::sort(samples.begin(), samples.end());
    const auto middle = samples.size() / 2;
    const double median = samples.size() % 2 == 0
        ? (samples[middle - 1] + samples[middle]) * 0.5 : samples[middle];
    return {samples.front(), median, samples[17], samples[18]};
}

struct SarmMotion {
    std::int32_t x;
    std::int32_t y;
};
static_assert(sizeof(SarmMotion) == 8);

struct SarmConstants {
    std::uint32_t image_width;
    std::uint32_t image_height;
    std::uint32_t tile_count_x;
    std::uint32_t tile_count_y;
};
static_assert(sizeof(SarmConstants) == 16);

struct SarmOutput {
    float residual_x;
    float residual_y;
    float refined_x;
    float refined_y;
    float confidence;
    std::uint32_t best_cost;
    std::uint32_t second_cost;
    std::uint32_t valid;
};
static_assert(sizeof(SarmOutput) == 32);

constexpr std::uint32_t kSarmWidth = 64;
constexpr std::uint32_t kSarmHeight = 48;
constexpr std::uint32_t kSarmPatchSize = 4;
constexpr int kSarmSearchX = 3;
constexpr int kSarmSearchY = 2;
constexpr std::uint32_t kSarmWarmupCount = 5;
constexpr std::uint32_t kSarmMeasuredCount = 20;
constexpr std::uint32_t kSarmDispatchesPerSample = 32;
constexpr std::uint32_t kSarmRunCount = kSarmWarmupCount + kSarmMeasuredCount;
constexpr std::uint32_t kSarmInvalidCost = std::numeric_limits<std::uint32_t>::max();

std::size_t sarm_cost_index(int dx, int dy) {
    return static_cast<std::size_t>(dy + kSarmSearchY) * (kSarmSearchX * 2 + 1)
        + static_cast<std::size_t>(dx + kSarmSearchX);
}

float sarm_quadratic_offset(std::uint32_t minus_cost,
                            std::uint32_t center_cost,
                            std::uint32_t plus_cost) {
    const float curvature = static_cast<float>(minus_cost)
        - 2.0F * static_cast<float>(center_cost) + static_cast<float>(plus_cost);
    if (curvature <= 1.0e-6F) return 0.0F;
    const float numerator = 0.5F
        * (static_cast<float>(minus_cost) - static_cast<float>(plus_cost));
    return (std::clamp)(numerator / curvature, -0.5F, 0.5F);
}

SarmOutput sarm_scalar_reference(const std::vector<std::uint32_t>& current,
                                 const std::vector<std::uint32_t>& history,
                                 const SarmMotion& engine,
                                 std::uint32_t tile_x,
                                 std::uint32_t tile_y) {
    const int patch_x = static_cast<int>(tile_x * 8U) + 2;
    const int patch_y = static_cast<int>(tile_y * 8U) + 2;
    SarmOutput result{0.0F, 0.0F, static_cast<float>(engine.x),
                      static_cast<float>(engine.y), 0.0F,
                      kSarmInvalidCost, kSarmInvalidCost, 0};
    if (patch_x < 0 || patch_y < 0 ||
        patch_x + static_cast<int>(kSarmPatchSize) > static_cast<int>(kSarmWidth) ||
        patch_y + static_cast<int>(kSarmPatchSize) > static_cast<int>(kSarmHeight)) {
        return result;
    }

    std::uint32_t valid_samples = 0;
    for (std::uint32_t row = 0; row < kSarmPatchSize; ++row) {
        for (std::uint32_t column = 0; column < kSarmPatchSize; ++column) {
            const auto value = current[static_cast<std::size_t>(patch_y + static_cast<int>(row))
                * kSarmWidth + static_cast<std::size_t>(patch_x + static_cast<int>(column))]
                & 0xffU;
            if (value != 0) ++valid_samples;
        }
    }
    if (valid_samples == 0) return result;

    std::array<std::uint32_t, (kSarmSearchX * 2 + 1) * (kSarmSearchY * 2 + 1)> costs{};
    costs.fill(kSarmInvalidCost);
    for (int dy = -kSarmSearchY; dy <= kSarmSearchY; ++dy) {
        for (int dx = -kSarmSearchX; dx <= kSarmSearchX; ++dx) {
            const int source_x = patch_x + engine.x + dx;
            const int source_y = patch_y + engine.y + dy;
            if (source_x < 0 || source_y < 0 ||
                source_x + static_cast<int>(kSarmPatchSize) > static_cast<int>(kSarmWidth) ||
                source_y + static_cast<int>(kSarmPatchSize) > static_cast<int>(kSarmHeight)) {
                continue;
            }
            std::uint32_t cost = 0;
            for (std::uint32_t row = 0; row < kSarmPatchSize; ++row) {
                for (std::uint32_t column = 0; column < kSarmPatchSize; ++column) {
                    const auto reference = current[
                        static_cast<std::size_t>(patch_y + static_cast<int>(row)) * kSarmWidth
                        + static_cast<std::size_t>(patch_x + static_cast<int>(column))] & 0xffU;
                    if (reference == 0) continue;
                    const auto sample = history[
                        static_cast<std::size_t>(source_y + static_cast<int>(row)) * kSarmWidth
                        + static_cast<std::size_t>(source_x + static_cast<int>(column))] & 0xffU;
                    const auto difference = reference > sample
                        ? reference - sample : sample - reference;
                    cost += difference;
                }
            }
            costs[sarm_cost_index(dx, dy)] = cost;
        }
    }

    std::uint32_t best_cost = kSarmInvalidCost;
    std::uint32_t second_cost = kSarmInvalidCost;
    int best_dx = 0;
    int best_dy = 0;
    for (int dy = -kSarmSearchY; dy <= kSarmSearchY; ++dy) {
        for (int dx = -kSarmSearchX; dx <= kSarmSearchX; ++dx) {
            const auto cost = costs[sarm_cost_index(dx, dy)];
            if (cost < best_cost) {
                second_cost = best_cost;
                best_cost = cost;
                best_dx = dx;
                best_dy = dy;
            } else if (cost < second_cost) {
                second_cost = cost;
            }
        }
    }
    if (best_cost == kSarmInvalidCost) return result;
    if (second_cost == kSarmInvalidCost) second_cost = best_cost;

    const float uniqueness = static_cast<float>(second_cost - best_cost)
        / (std::max)(static_cast<float>(second_cost), 1.0F);
    const float quality = (std::clamp)(1.0F - static_cast<float>(best_cost)
        / (static_cast<float>(valid_samples) * 254.0F), 0.0F, 1.0F);
    float residual_x = static_cast<float>(best_dx);
    float residual_y = static_cast<float>(best_dy);
    if (uniqueness * quality > 0.0F) {
        if (best_dx > -kSarmSearchX && best_dx < kSarmSearchX) {
            const auto minus_cost = costs[sarm_cost_index(best_dx - 1, best_dy)];
            const auto plus_cost = costs[sarm_cost_index(best_dx + 1, best_dy)];
            if (minus_cost != kSarmInvalidCost && plus_cost != kSarmInvalidCost)
                residual_x += sarm_quadratic_offset(minus_cost, best_cost, plus_cost);
        }
        if (best_dy > -kSarmSearchY && best_dy < kSarmSearchY) {
            const auto minus_cost = costs[sarm_cost_index(best_dx, best_dy - 1)];
            const auto plus_cost = costs[sarm_cost_index(best_dx, best_dy + 1)];
            if (minus_cost != kSarmInvalidCost && plus_cost != kSarmInvalidCost)
                residual_y += sarm_quadratic_offset(minus_cost, best_cost, plus_cost);
        }
    }

    result.residual_x = residual_x;
    result.residual_y = residual_y;
    result.refined_x = static_cast<float>(engine.x) + residual_x;
    result.refined_y = static_cast<float>(engine.y) + residual_y;
    result.confidence = uniqueness * quality;
    result.best_cost = best_cost;
    result.second_cost = second_cost;
    result.valid = 1;
    return result;
}

struct ThfaConstants {
    std::uint32_t input_width;
    std::uint32_t input_height;
    std::uint32_t output_width;
    std::uint32_t output_height;
};
static_assert(sizeof(ThfaConstants) == 16);

struct ThfaFloat3 {
    float x;
    float y;
    float z;
};
static_assert(sizeof(ThfaFloat3) == 12);

constexpr std::uint32_t kThfaInputWidth = 16;
constexpr std::uint32_t kThfaInputHeight = 12;
constexpr std::uint32_t kThfaOutputWidth = kThfaInputWidth * 2;
constexpr std::uint32_t kThfaOutputHeight = kThfaInputHeight * 2;
constexpr std::uint32_t kThfaFeatureCount = 10;
constexpr std::uint32_t kThfaSpatialBuckets = 512;
constexpr std::uint32_t kThfaTemporalBuckets = 48;
constexpr std::uint32_t kThfaPhaseBuckets = 4;
constexpr std::uint32_t kThfaAlgorithmCount = 4;
constexpr std::uint32_t kThfaWarmupCount = 5;
constexpr std::uint32_t kThfaMeasuredCount = 20;
constexpr std::uint32_t kThfaDispatchesPerSample = 32;
constexpr std::uint32_t kThfaRunCount = kThfaWarmupCount + kThfaMeasuredCount;
constexpr std::uint32_t kThfaQueryCount = kThfaAlgorithmCount * kThfaRunCount * 2;

constexpr std::array<std::uint32_t, kThfaAlgorithmCount> kThfaTapCounts{4, 5, 8, 9};

std::array<float, 3> thfa_to_array(const ThfaFloat3& value) {
    return {value.x, value.y, value.z};
}

ThfaFloat3 thfa_lerp(const ThfaFloat3& a, const ThfaFloat3& b, float t) {
    return {a.x + (b.x - a.x) * t,
            a.y + (b.y - a.y) * t,
            a.z + (b.z - a.z) * t};
}

std::vector<ThfaFloat3> thfa_reference_filter(
    const std::vector<ThfaFloat3>& input,
    const std::vector<std::uint32_t>& spatial_descriptors,
    const std::vector<std::uint32_t>& temporal_descriptors,
    const std::vector<std::uint32_t>& phase_descriptors,
    const std::vector<float>& spatial_atlas,
    const std::vector<float>& temporal_atlas,
    const std::vector<float>& phase_atlas,
    std::uint32_t tap_count) {
    constexpr std::array<std::array<int, 2>, 9> offsets{{
        {{-1, -1}}, {{0, -1}}, {{1, -1}},
        {{-1, 0}}, {{0, 0}}, {{1, 0}},
        {{-1, 1}}, {{0, 1}}, {{1, 1}},
    }};
    auto sample = [&](int x, int y) -> const ThfaFloat3& {
        x = (std::clamp)(x, 0, static_cast<int>(kThfaInputWidth) - 1);
        y = (std::clamp)(y, 0, static_cast<int>(kThfaInputHeight) - 1);
        return input[static_cast<std::size_t>(y) * kThfaInputWidth
                     + static_cast<std::size_t>(x)];
    };
    auto tap_is_enabled = [tap_count](std::uint32_t tap) {
        if (tap_count == 4) return tap == 0 || tap == 2 || tap == 6 || tap == 8;
        if (tap_count == 5) return tap == 1 || tap == 3 || tap == 4 || tap == 5 || tap == 7;
        if (tap_count == 8) return tap != 4;
        return true;
    };

    std::vector<ThfaFloat3> output(static_cast<std::size_t>(kThfaOutputWidth)
                                   * kThfaOutputHeight);
    for (std::uint32_t y = 0; y < kThfaOutputHeight; ++y) {
        for (std::uint32_t x = 0; x < kThfaOutputWidth; ++x) {
            const float low_x = (static_cast<float>(x) + 0.5F) * 0.5F - 0.5F;
            const float low_y = (static_cast<float>(y) + 0.5F) * 0.5F - 0.5F;
            const int base_x = static_cast<int>(std::floor(low_x));
            const int base_y = static_cast<int>(std::floor(low_y));
            const float fraction_x = low_x - std::floor(low_x);
            const float fraction_y = low_y - std::floor(low_y);
            const auto top = thfa_lerp(sample(base_x, base_y), sample(base_x + 1, base_y),
                                       fraction_x);
            const auto bottom = thfa_lerp(sample(base_x, base_y + 1),
                                          sample(base_x + 1, base_y + 1), fraction_x);
            const auto baseline = thfa_lerp(top, bottom, fraction_y);
            const auto descriptor_x = static_cast<std::uint32_t>((std::clamp)(
                base_x, 0, static_cast<int>(kThfaInputWidth) - 1));
            const auto descriptor_y = static_cast<std::uint32_t>((std::clamp)(
                base_y, 0, static_cast<int>(kThfaInputHeight) - 1));
            const auto descriptor_index = static_cast<std::size_t>(descriptor_y)
                * kThfaInputWidth + descriptor_x;
            const auto spatial_base = spatial_descriptors[descriptor_index] * kThfaFeatureCount;
            const auto temporal_base = temporal_descriptors[descriptor_index] * kThfaFeatureCount;
            const auto phase_base = phase_descriptors[descriptor_index] * kThfaFeatureCount;
            std::array<float, 3> residual{};
            const float bias = spatial_atlas[spatial_base]
                + temporal_atlas[temporal_base] + phase_atlas[phase_base];
            residual.fill(bias);
            for (std::uint32_t tap = 0; tap < 9U; ++tap) {
                if (!tap_is_enabled(tap)) continue;
                const auto& local = sample(base_x + offsets[tap][0], base_y + offsets[tap][1]);
                const auto local_values = thfa_to_array(local);
                const auto base_values = thfa_to_array(baseline);
                const float weight = spatial_atlas[spatial_base + tap + 1]
                    + temporal_atlas[temporal_base + tap + 1]
                    + phase_atlas[phase_base + tap + 1];
                for (std::size_t channel = 0; channel < residual.size(); ++channel)
                    residual[channel] += (local_values[channel] - base_values[channel]) * weight;
            }
            output[static_cast<std::size_t>(y) * kThfaOutputWidth + x] = {
                baseline.x + residual[0], baseline.y + residual[1], baseline.z + residual[2]};
        }
    }
    return output;
}

struct RouterEvidenceGpu {
    float confidence;
    float disocclusion;
    std::uint32_t sarm_valid;
    std::uint32_t thin_detail;
    std::uint32_t reactive;
    std::uint32_t specular_risk;
    std::uint32_t history_valid;
    std::uint32_t force_reference;
};
static_assert(sizeof(RouterEvidenceGpu) == 32);

} // namespace

int benchmark_naviprism_msad4(const std::filesystem::path& report_path) {
    if (kSamplesPerChunk * kMaximumDifferencePerCall >= 65535U) {
        throw std::runtime_error("Configured msad4 accumulation chunk is not conservative");
    }

    const auto inputs = make_inputs();
    const auto expected = [&] {
        std::vector<UInt4> values(kCaseCount);
        for (UINT index = 0; index < kCaseCount; ++index) {
            values[index] = scalar_reference(inputs, static_cast<std::size_t>(index) * kSamplesPerCase);
        }
        return values;
    }();

    ComPtr<ID3D12Device> device = create_target_device();
    ComPtr<ID3D12CommandQueue> queue;
    D3D12_COMMAND_QUEUE_DESC queue_description{};
    queue_description.Type = D3D12_COMMAND_LIST_TYPE_COMPUTE;
    check_hr(device->CreateCommandQueue(&queue_description, IID_PPV_ARGS(&queue)),
             "Create NaviPRISM compute queue failed");
    ComPtr<ID3D12CommandAllocator> allocator;
    check_hr(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_COMPUTE,
                                             IID_PPV_ARGS(&allocator)),
             "Create NaviPRISM command allocator failed");
    ComPtr<ID3D12GraphicsCommandList> command_list;
    check_hr(device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_COMPUTE,
                                      allocator.Get(), nullptr, IID_PPV_ARGS(&command_list)),
             "Create NaviPRISM command list failed");

    const auto input_bytes = static_cast<std::uint64_t>(inputs.size() * sizeof(MsadInput));
    ComPtr<ID3D12Resource> input_buffer;
    create_buffer(device.Get(), D3D12_HEAP_TYPE_UPLOAD, input_bytes,
                  D3D12_RESOURCE_STATE_GENERIC_READ, input_buffer);
    void* input_mapping = nullptr;
    const D3D12_RANGE no_read{0, 0};
    check_hr(input_buffer->Map(0, &no_read, &input_mapping),
             "Map NaviPRISM input buffer failed");
    std::memcpy(input_mapping, inputs.data(), static_cast<std::size_t>(input_bytes));
    input_buffer->Unmap(0, nullptr);

    std::array<ComPtr<ID3D12Resource>, kAlgorithmCount> output_buffers{};
    std::array<ComPtr<ID3D12Resource>, kAlgorithmCount> output_readbacks{};
    const auto output_bytes = static_cast<std::uint64_t>(kCaseCount * sizeof(UInt4));
    for (UINT index = 0; index < kAlgorithmCount; ++index) {
        create_buffer(device.Get(), D3D12_HEAP_TYPE_DEFAULT, output_bytes,
                      D3D12_RESOURCE_STATE_UNORDERED_ACCESS, output_buffers[index],
                      D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS);
        create_buffer(device.Get(), D3D12_HEAP_TYPE_READBACK, output_bytes,
                      D3D12_RESOURCE_STATE_COPY_DEST, output_readbacks[index]);
    }

    D3D12_DESCRIPTOR_HEAP_DESC descriptor_description{};
    descriptor_description.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
    descriptor_description.NumDescriptors = 1 + kAlgorithmCount;
    descriptor_description.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
    ComPtr<ID3D12DescriptorHeap> descriptor_heap;
    check_hr(device->CreateDescriptorHeap(&descriptor_description,
                                         IID_PPV_ARGS(&descriptor_heap)),
             "Create NaviPRISM descriptor heap failed");
    const UINT descriptor_increment = device->GetDescriptorHandleIncrementSize(
        D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
    auto cpu_handle = descriptor_heap->GetCPUDescriptorHandleForHeapStart();
    D3D12_SHADER_RESOURCE_VIEW_DESC srv{};
    srv.Format = DXGI_FORMAT_UNKNOWN;
    srv.ViewDimension = D3D12_SRV_DIMENSION_BUFFER;
    srv.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
    srv.Buffer.NumElements = static_cast<UINT>(inputs.size());
    srv.Buffer.StructureByteStride = sizeof(MsadInput);
    device->CreateShaderResourceView(input_buffer.Get(), &srv, cpu_handle);
    cpu_handle.ptr += descriptor_increment;
    for (UINT index = 0; index < kAlgorithmCount; ++index) {
        D3D12_UNORDERED_ACCESS_VIEW_DESC uav{};
        uav.Format = DXGI_FORMAT_UNKNOWN;
        uav.ViewDimension = D3D12_UAV_DIMENSION_BUFFER;
        uav.Buffer.NumElements = kCaseCount;
        uav.Buffer.StructureByteStride = sizeof(UInt4);
        device->CreateUnorderedAccessView(output_buffers[index].Get(), nullptr, &uav, cpu_handle);
        cpu_handle.ptr += descriptor_increment;
    }

    D3D12_DESCRIPTOR_RANGE ranges[2]{};
    ranges[0].RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_SRV;
    ranges[0].NumDescriptors = 1;
    ranges[0].BaseShaderRegister = 0;
    ranges[0].OffsetInDescriptorsFromTableStart = D3D12_DESCRIPTOR_RANGE_OFFSET_APPEND;
    ranges[1].RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_UAV;
    ranges[1].NumDescriptors = 1;
    ranges[1].BaseShaderRegister = 0;
    ranges[1].OffsetInDescriptorsFromTableStart = D3D12_DESCRIPTOR_RANGE_OFFSET_APPEND;
    D3D12_ROOT_PARAMETER root_parameters[2]{};
    for (UINT index = 0; index < 2; ++index) {
        root_parameters[index].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
        root_parameters[index].DescriptorTable.NumDescriptorRanges = 1;
        root_parameters[index].DescriptorTable.pDescriptorRanges = &ranges[index];
        root_parameters[index].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
    }
    D3D12_ROOT_SIGNATURE_DESC root_description{};
    root_description.NumParameters = 2;
    root_description.pParameters = root_parameters;
    ComPtr<ID3DBlob> serialized_root;
    ComPtr<ID3DBlob> root_errors;
    check_hr(D3D12SerializeRootSignature(&root_description, D3D_ROOT_SIGNATURE_VERSION_1,
                                          &serialized_root, &root_errors),
             "Serialize NaviPRISM root signature failed");
    ComPtr<ID3D12RootSignature> root_signature;
    check_hr(device->CreateRootSignature(0, serialized_root->GetBufferPointer(),
                                          serialized_root->GetBufferSize(),
                                          IID_PPV_ARGS(&root_signature)),
             "Create NaviPRISM root signature failed");

    std::array<ComPtr<ID3D12PipelineState>, kAlgorithmCount> pipelines{};
    std::array<std::string, kAlgorithmCount> shader_hashes{};
    std::array<std::vector<std::byte>, kAlgorithmCount> shader_blobs{};
    for (UINT index = 0; index < kAlgorithmCount; ++index) {
        shader_blobs[index] = read_module(kAlgorithms[index], shader_hashes[index]);
        D3D12_COMPUTE_PIPELINE_STATE_DESC pso{};
        pso.pRootSignature = root_signature.Get();
        pso.CS.pShaderBytecode = shader_blobs[index].data();
        pso.CS.BytecodeLength = shader_blobs[index].size();
        check_hr(device->CreateComputePipelineState(&pso, IID_PPV_ARGS(&pipelines[index])),
                 "Create NaviPRISM compute PSO failed");
    }

    D3D12_QUERY_HEAP_DESC query_description{};
    query_description.Type = D3D12_QUERY_HEAP_TYPE_TIMESTAMP;
    query_description.Count = kQueryCount;
    ComPtr<ID3D12QueryHeap> queries;
    check_hr(device->CreateQueryHeap(&query_description, IID_PPV_ARGS(&queries)),
             "Create NaviPRISM timestamp query heap failed");
    ComPtr<ID3D12Resource> timestamp_readback;
    create_buffer(device.Get(), D3D12_HEAP_TYPE_READBACK,
                  kQueryCount * sizeof(std::uint64_t), D3D12_RESOURCE_STATE_COPY_DEST,
                  timestamp_readback);
    UINT64 timestamp_frequency = 0;
    check_hr(queue->GetTimestampFrequency(&timestamp_frequency),
             "Read NaviPRISM timestamp frequency failed");
    if (timestamp_frequency == 0) throw std::runtime_error("D3D12 timestamp frequency is zero");

    const auto gpu_start = descriptor_heap->GetGPUDescriptorHandleForHeapStart();
    for (UINT algorithm_index = 0; algorithm_index < kAlgorithmCount; ++algorithm_index) {
        command_list->SetPipelineState(pipelines[algorithm_index].Get());
        command_list->SetComputeRootSignature(root_signature.Get());
        command_list->SetDescriptorHeaps(1, descriptor_heap.GetAddressOf());
        command_list->SetComputeRootDescriptorTable(0, gpu_start);
        auto output_gpu = gpu_start;
        output_gpu.ptr += static_cast<UINT64>(algorithm_index + 1) * descriptor_increment;
        command_list->SetComputeRootDescriptorTable(1, output_gpu);
        for (UINT run = 0; run < kRunCount; ++run) {
            if (run != 0) {
                D3D12_RESOURCE_BARRIER barrier{};
                barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_UAV;
                barrier.UAV.pResource = output_buffers[algorithm_index].Get();
                command_list->ResourceBarrier(1, &barrier);
            }
            const UINT query_base = (algorithm_index * kRunCount + run) * 2;
            command_list->EndQuery(queries.Get(), D3D12_QUERY_TYPE_TIMESTAMP, query_base);
            for (UINT repeat = 0; repeat < kDispatchesPerSample; ++repeat) {
                command_list->Dispatch(kCaseCount / 64, 1, 1);
                if (repeat + 1 < kDispatchesPerSample) {
                    D3D12_RESOURCE_BARRIER barrier{};
                    barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_UAV;
                    barrier.UAV.pResource = output_buffers[algorithm_index].Get();
                    command_list->ResourceBarrier(1, &barrier);
                }
            }
            command_list->EndQuery(queries.Get(), D3D12_QUERY_TYPE_TIMESTAMP, query_base + 1);
        }
        D3D12_RESOURCE_BARRIER transition{};
        transition.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        transition.Transition.pResource = output_buffers[algorithm_index].Get();
        transition.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
        transition.Transition.StateBefore = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
        transition.Transition.StateAfter = D3D12_RESOURCE_STATE_COPY_SOURCE;
        command_list->ResourceBarrier(1, &transition);
        command_list->CopyBufferRegion(output_readbacks[algorithm_index].Get(), 0,
                                       output_buffers[algorithm_index].Get(), 0, output_bytes);
    }
    command_list->ResolveQueryData(queries.Get(), D3D12_QUERY_TYPE_TIMESTAMP,
                                   0, kQueryCount, timestamp_readback.Get(), 0);
    check_hr(command_list->Close(), "Close NaviPRISM command list failed");
    ID3D12CommandList* lists[]{command_list.Get()};
    queue->ExecuteCommandLists(1, lists);

    ComPtr<ID3D12Fence> fence;
    check_hr(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)),
             "Create NaviPRISM fence failed");
    check_hr(queue->Signal(fence.Get(), 1), "Signal NaviPRISM fence failed");
    if (fence->GetCompletedValue() < 1) {
        HANDLE event_handle = CreateEventW(nullptr, FALSE, FALSE, nullptr);
        if (!event_handle) throw std::runtime_error("CreateEventW failed");
        const HRESULT event_result = fence->SetEventOnCompletion(1, event_handle);
        if (FAILED(event_result)) {
            CloseHandle(event_handle);
            check_hr(event_result, "Set NaviPRISM fence event failed");
        }
        const DWORD wait_result = WaitForSingleObject(event_handle, 30000);
        CloseHandle(event_handle);
        if (wait_result != WAIT_OBJECT_0) {
            throw std::runtime_error("Timed out waiting for NaviPRISM GPU benchmark");
        }
    }

    std::vector<std::uint64_t> timestamp_values(kQueryCount);
    void* timestamp_mapping = nullptr;
    const D3D12_RANGE timestamp_range{0, timestamp_values.size() * sizeof(std::uint64_t)};
    check_hr(timestamp_readback->Map(0, &timestamp_range, &timestamp_mapping),
             "Map NaviPRISM timestamps failed");
    std::memcpy(timestamp_values.data(), timestamp_mapping,
                timestamp_values.size() * sizeof(std::uint64_t));
    timestamp_readback->Unmap(0, nullptr);

    std::array<std::vector<double>, kAlgorithmCount> timings{};
    for (UINT algorithm_index = 0; algorithm_index < kAlgorithmCount; ++algorithm_index) {
        for (UINT run = kWarmupCount; run < kRunCount; ++run) {
            const UINT query_base = (algorithm_index * kRunCount + run) * 2;
            const auto begin = timestamp_values[query_base];
            const auto end = timestamp_values[query_base + 1];
            if (end < begin) throw std::runtime_error("NaviPRISM timestamps are not monotonic");
            timings[algorithm_index].push_back(
                1.0e6 * static_cast<double>(end - begin) /
                (static_cast<double>(timestamp_frequency) * kDispatchesPerSample));
        }
    }

    std::array<double, kAlgorithmCount> max_errors{};
    for (UINT algorithm_index = 0; algorithm_index < kAlgorithmCount; ++algorithm_index) {
        void* output_mapping = nullptr;
        const D3D12_RANGE output_range{0, static_cast<SIZE_T>(output_bytes)};
        check_hr(output_readbacks[algorithm_index]->Map(0, &output_range, &output_mapping),
                 "Map NaviPRISM output failed");
        const auto* actual = static_cast<const UInt4*>(output_mapping);
        for (UINT case_index = 0; case_index < kCaseCount; ++case_index) {
            const std::array<std::uint32_t, 4> got{
                actual[case_index].x, actual[case_index].y,
                actual[case_index].z, actual[case_index].w};
            const std::array<std::uint32_t, 4> want{
                expected[case_index].x, expected[case_index].y,
                expected[case_index].z, expected[case_index].w};
            for (unsigned lane = 0; lane < 4; ++lane) {
                const auto error = got[lane] > want[lane] ? got[lane] - want[lane]
                                                          : want[lane] - got[lane];
                max_errors[algorithm_index] = (std::max)(max_errors[algorithm_index],
                                                          static_cast<double>(error));
                if (algorithm_index < 2 && error != 0) {
                    output_readbacks[algorithm_index]->Unmap(0, nullptr);
                    throw std::runtime_error(std::string(kAlgorithms[algorithm_index].name) +
                                             " differs from scalar reference");
                }
                if (algorithm_index == 2 && error != 0) {
                    output_readbacks[algorithm_index]->Unmap(0, nullptr);
                    throw std::runtime_error(
                        "FP16 byte difference with FP32 sum differs from integer reference");
                }
            }
        }
        output_readbacks[algorithm_index]->Unmap(0, nullptr);
    }

    std::array<TimingSummary, kAlgorithmCount> summaries{};
    for (UINT index = 0; index < kAlgorithmCount; ++index) {
        summaries[index] = summarize(timings[index]);
    }

    if (!report_path.parent_path().empty()) {
        std::filesystem::create_directories(report_path.parent_path());
    }
    std::ofstream report(report_path, std::ios::binary | std::ios::trunc);
    if (!report) throw std::runtime_error("Cannot write NaviPRISM report: " + report_path.string());
    report << std::fixed << std::setprecision(4)
           << "{\n  \"gpu\": \"AMD Radeon RX 5700 XT\",\n"
           << "  \"pci_id\": \"1002:731F\",\n"
           << "  \"driver\": \"" << target_driver_version() << "\",\n"
           << "  \"cases\": " << kCaseCount << ",\n"
           << "  \"samples_per_case\": " << kSamplesPerCase << ",\n"
           << "  \"warmup_samples\": " << kWarmupCount << ",\n"
           << "  \"measured_samples\": " << kMeasuredCount << ",\n"
           << "  \"dispatches_per_sample\": " << kDispatchesPerSample << ",\n"
           << "  \"accumulation_chunk_calls\": " << kSamplesPerChunk << ",\n"
           << "  \"timestamp_frequency_hz\": " << timestamp_frequency << ",\n"
           << "  \"modes\": [\n";
    for (UINT index = 0; index < kAlgorithmCount; ++index) {
        const auto& timing = summaries[index];
        report << "    {\"name\": \"" << kAlgorithms[index].name
               << "\", \"dxil_sha256\": \"" << shader_hashes[index]
               << "\", \"max_abs_error\": " << max_errors[index]
               << ", \"min_us\": " << timing.minimum
               << ", \"median_us\": " << timing.median
               << ", \"p90_us\": " << timing.p90
               << ", \"p95_us\": " << timing.p95
               << ", \"samples_us\": [";
        for (std::size_t sample = 0; sample < timings[index].size(); ++sample) {
            if (sample != 0) report << ", ";
            report << timings[index][sample];
        }
        report << "]}"
               << (index + 1 == kAlgorithmCount ? "\n" : ",\n");
    }
    report << "  ]\n}\n";
    if (!report) throw std::runtime_error("Failed while writing NaviPRISM JSON report");

    std::cout << "NaviPRISM msad4 validation passed on RX 5700 XT (PCI 1002:731F), driver "
              << target_driver_version() << ".\n"
              << "  " << kCaseCount << " cases x " << kSamplesPerCase
              << " calls; each SIMD accumulator is reset every " << kSamplesPerChunk
              << " calls, keeping the documented bound below 65535.\n"
              << "  " << kWarmupCount << " warmup + " << kMeasuredCount
              << " measured samples per mode, averaging " << kDispatchesPerSample
              << " back-to-back dispatches per sample; query brackets dispatches and their UAV ordering barriers.\n";
    for (UINT index = 0; index < kAlgorithmCount; ++index) {
        const auto& timing = summaries[index];
        std::cout << "  " << kAlgorithms[index].name << " max error " << max_errors[index]
                  << ", median " << timing.median << " us, p95 " << timing.p95 << " us, DXIL SHA-256 "
                  << shader_hashes[index] << ".\n";
    }
    std::cout << "  JSON report: " << report_path.string()
              << "; native instruction selection is determined by the separate RGA ISA dump.\n";
    return 0;
}

int validate_naviprism_sarm(const std::filesystem::path& report_path) {
    constexpr std::uint32_t tile_stride = 8;
    const std::uint32_t tile_count_x = (kSarmWidth + tile_stride - 1) / tile_stride;
    const std::uint32_t tile_count_y = (kSarmHeight + tile_stride - 1) / tile_stride;
    const std::uint32_t tile_count = tile_count_x * tile_count_y;
    std::mt19937 random(0x5341524dU);
    std::uniform_int_distribution<std::uint32_t> luma(1, 255);
    std::vector<std::uint32_t> history(static_cast<std::size_t>(kSarmWidth) * kSarmHeight);
    std::vector<std::uint32_t> current(history.size());
    std::vector<SarmMotion> engine_motion(tile_count, SarmMotion{1, 0});
    for (auto& value : history) value = luma(random);
    for (std::uint32_t y = 0; y < kSarmHeight; ++y) {
        for (std::uint32_t x = 0; x < kSarmWidth; ++x) {
            const auto sx = static_cast<int>(x) + 2;
            const auto sy = static_cast<int>(y) - 1;
            current[static_cast<std::size_t>(y) * kSarmWidth + x] =
                sx >= 0 && sy >= 0 && sx < static_cast<int>(kSarmWidth)
                    && sy < static_cast<int>(kSarmHeight)
                ? history[static_cast<std::size_t>(sy) * kSarmWidth
                          + static_cast<std::size_t>(sx)]
                : luma(random);
        }
    }

    std::vector<SarmOutput> expected(tile_count);
    for (std::uint32_t tile_y = 0; tile_y < tile_count_y; ++tile_y) {
        for (std::uint32_t tile_x = 0; tile_x < tile_count_x; ++tile_x) {
            const auto index = static_cast<std::size_t>(tile_y) * tile_count_x + tile_x;
            expected[index] = sarm_scalar_reference(
                current, history, engine_motion[index], tile_x, tile_y);
        }
    }

    ComPtr<ID3D12Device> device = create_target_device();
    ComPtr<ID3D12CommandQueue> queue;
    D3D12_COMMAND_QUEUE_DESC queue_description{};
    queue_description.Type = D3D12_COMMAND_LIST_TYPE_COMPUTE;
    check_hr(device->CreateCommandQueue(&queue_description, IID_PPV_ARGS(&queue)),
             "Create NaviPRISM SARM compute queue failed");
    ComPtr<ID3D12CommandAllocator> allocator;
    check_hr(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_COMPUTE,
                                             IID_PPV_ARGS(&allocator)),
             "Create NaviPRISM SARM allocator failed");
    ComPtr<ID3D12GraphicsCommandList> command_list;
    check_hr(device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_COMPUTE,
                                      allocator.Get(), nullptr, IID_PPV_ARGS(&command_list)),
             "Create NaviPRISM SARM command list failed");

    auto upload_data = [&](const void* source, std::uint64_t size,
                           ComPtr<ID3D12Resource>& destination, const char* label) {
        create_buffer(device.Get(), D3D12_HEAP_TYPE_UPLOAD, size,
                      D3D12_RESOURCE_STATE_GENERIC_READ, destination);
        void* mapping = nullptr;
        const D3D12_RANGE no_read{0, 0};
        check_hr(destination->Map(0, &no_read, &mapping), label);
        std::memcpy(mapping, source, static_cast<std::size_t>(size));
        destination->Unmap(0, nullptr);
    };

    ComPtr<ID3D12Resource> current_buffer;
    ComPtr<ID3D12Resource> history_buffer;
    ComPtr<ID3D12Resource> motion_buffer;
    ComPtr<ID3D12Resource> constants_buffer;
    upload_data(current.data(), current.size() * sizeof(current[0]), current_buffer,
                "Map NaviPRISM SARM current luma failed");
    upload_data(history.data(), history.size() * sizeof(history[0]), history_buffer,
                "Map NaviPRISM SARM history luma failed");
    upload_data(engine_motion.data(), engine_motion.size() * sizeof(engine_motion[0]),
                motion_buffer, "Map NaviPRISM SARM engine motion failed");
    const SarmConstants constants{kSarmWidth, kSarmHeight, tile_count_x, tile_count_y};
    std::array<std::byte, 256> constants_upload{};
    std::memcpy(constants_upload.data(), &constants, sizeof(constants));
    upload_data(constants_upload.data(), constants_upload.size(), constants_buffer,
                "Map NaviPRISM SARM constants failed");

    const auto output_bytes = static_cast<std::uint64_t>(tile_count) * sizeof(SarmOutput);
    ComPtr<ID3D12Resource> output_buffer;
    ComPtr<ID3D12Resource> output_readback;
    create_buffer(device.Get(), D3D12_HEAP_TYPE_DEFAULT, output_bytes,
                  D3D12_RESOURCE_STATE_UNORDERED_ACCESS, output_buffer,
                  D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS);
    create_buffer(device.Get(), D3D12_HEAP_TYPE_READBACK, output_bytes,
                  D3D12_RESOURCE_STATE_COPY_DEST, output_readback);

    D3D12_DESCRIPTOR_HEAP_DESC descriptor_description{};
    descriptor_description.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
    descriptor_description.NumDescriptors = 4;
    descriptor_description.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
    ComPtr<ID3D12DescriptorHeap> descriptor_heap;
    check_hr(device->CreateDescriptorHeap(&descriptor_description,
                                         IID_PPV_ARGS(&descriptor_heap)),
             "Create NaviPRISM SARM descriptor heap failed");
    const UINT descriptor_increment = device->GetDescriptorHandleIncrementSize(
        D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
    auto cpu_handle = descriptor_heap->GetCPUDescriptorHandleForHeapStart();
    auto create_structured_srv = [&](ID3D12Resource* resource,
                                     UINT element_count, UINT stride) {
        D3D12_SHADER_RESOURCE_VIEW_DESC srv{};
        srv.Format = DXGI_FORMAT_UNKNOWN;
        srv.ViewDimension = D3D12_SRV_DIMENSION_BUFFER;
        srv.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
        srv.Buffer.NumElements = element_count;
        srv.Buffer.StructureByteStride = stride;
        device->CreateShaderResourceView(resource, &srv, cpu_handle);
        cpu_handle.ptr += descriptor_increment;
    };
    create_structured_srv(current_buffer.Get(), static_cast<UINT>(current.size()), sizeof(std::uint32_t));
    create_structured_srv(history_buffer.Get(), static_cast<UINT>(history.size()), sizeof(std::uint32_t));
    create_structured_srv(motion_buffer.Get(), tile_count, sizeof(SarmMotion));
    D3D12_UNORDERED_ACCESS_VIEW_DESC uav{};
    uav.Format = DXGI_FORMAT_UNKNOWN;
    uav.ViewDimension = D3D12_UAV_DIMENSION_BUFFER;
    uav.Buffer.NumElements = tile_count;
    uav.Buffer.StructureByteStride = sizeof(SarmOutput);
    device->CreateUnorderedAccessView(output_buffer.Get(), nullptr, &uav, cpu_handle);

    std::array<D3D12_DESCRIPTOR_RANGE, 4> ranges{};
    for (UINT index = 0; index < 3; ++index) {
        ranges[index].RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_SRV;
        ranges[index].NumDescriptors = 1;
        ranges[index].BaseShaderRegister = index;
        ranges[index].OffsetInDescriptorsFromTableStart = 0;
    }
    ranges[3].RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_UAV;
    ranges[3].NumDescriptors = 1;
    ranges[3].BaseShaderRegister = 0;
    ranges[3].OffsetInDescriptorsFromTableStart = 0;
    std::array<D3D12_ROOT_PARAMETER, 5> root_parameters{};
    for (UINT index = 0; index < 3; ++index) {
        root_parameters[index].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
        root_parameters[index].DescriptorTable.NumDescriptorRanges = 1;
        root_parameters[index].DescriptorTable.pDescriptorRanges = &ranges[index];
        root_parameters[index].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
    }
    root_parameters[3].ParameterType = D3D12_ROOT_PARAMETER_TYPE_CBV;
    root_parameters[3].Descriptor.ShaderRegister = 0;
    root_parameters[3].Descriptor.RegisterSpace = 0;
    root_parameters[3].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
    root_parameters[4].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
    root_parameters[4].DescriptorTable.NumDescriptorRanges = 1;
    root_parameters[4].DescriptorTable.pDescriptorRanges = &ranges[3];
    root_parameters[4].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
    D3D12_ROOT_SIGNATURE_DESC root_description{};
    root_description.NumParameters = static_cast<UINT>(root_parameters.size());
    root_description.pParameters = root_parameters.data();
    ComPtr<ID3DBlob> serialized_root;
    ComPtr<ID3DBlob> root_errors;
    check_hr(D3D12SerializeRootSignature(&root_description, D3D_ROOT_SIGNATURE_VERSION_1,
                                         &serialized_root, &root_errors),
             "Serialize NaviPRISM SARM root signature failed");
    ComPtr<ID3D12RootSignature> root_signature;
    check_hr(device->CreateRootSignature(0, serialized_root->GetBufferPointer(),
                                          serialized_root->GetBufferSize(),
                                          IID_PPV_ARGS(&root_signature)),
             "Create NaviPRISM SARM root signature failed");

    const auto shader_path = executable_directory() / L"naviprism_sarm_residual.dxil";
    auto shader = read_shader(shader_path);
    const auto shader_hash = sha256_hex(shader);
    D3D12_COMPUTE_PIPELINE_STATE_DESC pipeline_description{};
    pipeline_description.pRootSignature = root_signature.Get();
    pipeline_description.CS.pShaderBytecode = shader.data();
    pipeline_description.CS.BytecodeLength = shader.size();
    ComPtr<ID3D12PipelineState> pipeline;
    check_hr(device->CreateComputePipelineState(&pipeline_description, IID_PPV_ARGS(&pipeline)),
             "Create NaviPRISM SARM compute pipeline failed");

    D3D12_QUERY_HEAP_DESC query_description{};
    query_description.Type = D3D12_QUERY_HEAP_TYPE_TIMESTAMP;
    query_description.Count = kSarmRunCount * 2;
    ComPtr<ID3D12QueryHeap> queries;
    check_hr(device->CreateQueryHeap(&query_description, IID_PPV_ARGS(&queries)),
             "Create NaviPRISM SARM timestamp heap failed");
    ComPtr<ID3D12Resource> timestamp_readback;
    create_buffer(device.Get(), D3D12_HEAP_TYPE_READBACK,
                  query_description.Count * sizeof(std::uint64_t),
                  D3D12_RESOURCE_STATE_COPY_DEST, timestamp_readback);
    UINT64 timestamp_frequency = 0;
    check_hr(queue->GetTimestampFrequency(&timestamp_frequency),
             "Read NaviPRISM SARM timestamp frequency failed");
    if (timestamp_frequency == 0) throw std::runtime_error("D3D12 timestamp frequency is zero");

    command_list->SetPipelineState(pipeline.Get());
    command_list->SetComputeRootSignature(root_signature.Get());
    ID3D12DescriptorHeap* heaps[]{descriptor_heap.Get()};
    command_list->SetDescriptorHeaps(1, heaps);
    auto gpu_handle = descriptor_heap->GetGPUDescriptorHandleForHeapStart();
    for (UINT index = 0; index < 3; ++index) {
        auto handle = gpu_handle;
        handle.ptr += static_cast<UINT64>(index) * descriptor_increment;
        command_list->SetComputeRootDescriptorTable(index, handle);
    }
    command_list->SetComputeRootConstantBufferView(3, constants_buffer->GetGPUVirtualAddress());
    auto output_handle = gpu_handle;
    output_handle.ptr += 3ULL * descriptor_increment;
    command_list->SetComputeRootDescriptorTable(4, output_handle);
    for (UINT run = 0; run < kSarmRunCount; ++run) {
        if (run != 0) {
            D3D12_RESOURCE_BARRIER barrier{};
            barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_UAV;
            barrier.UAV.pResource = output_buffer.Get();
            command_list->ResourceBarrier(1, &barrier);
        }
        command_list->EndQuery(queries.Get(), D3D12_QUERY_TYPE_TIMESTAMP, run * 2);
        for (UINT repeat = 0; repeat < kSarmDispatchesPerSample; ++repeat) {
            command_list->Dispatch((tile_count_x + 7) / 8, (tile_count_y + 7) / 8, 1);
            if (repeat + 1 < kSarmDispatchesPerSample) {
                D3D12_RESOURCE_BARRIER barrier{};
                barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_UAV;
                barrier.UAV.pResource = output_buffer.Get();
                command_list->ResourceBarrier(1, &barrier);
            }
        }
        command_list->EndQuery(queries.Get(), D3D12_QUERY_TYPE_TIMESTAMP, run * 2 + 1);
    }
    D3D12_RESOURCE_BARRIER transition{};
    transition.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    transition.Transition.pResource = output_buffer.Get();
    transition.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    transition.Transition.StateBefore = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
    transition.Transition.StateAfter = D3D12_RESOURCE_STATE_COPY_SOURCE;
    command_list->ResourceBarrier(1, &transition);
    command_list->CopyBufferRegion(output_readback.Get(), 0, output_buffer.Get(), 0, output_bytes);
    command_list->ResolveQueryData(queries.Get(), D3D12_QUERY_TYPE_TIMESTAMP,
                                   0, kSarmRunCount * 2, timestamp_readback.Get(), 0);
    check_hr(command_list->Close(), "Close NaviPRISM SARM command list failed");
    ID3D12CommandList* lists[]{command_list.Get()};
    queue->ExecuteCommandLists(1, lists);

    ComPtr<ID3D12Fence> fence;
    check_hr(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)),
             "Create NaviPRISM SARM fence failed");
    check_hr(queue->Signal(fence.Get(), 1), "Signal NaviPRISM SARM fence failed");
    if (fence->GetCompletedValue() < 1) {
        HANDLE event_handle = CreateEventW(nullptr, FALSE, FALSE, nullptr);
        if (!event_handle) throw std::runtime_error("CreateEventW failed for NaviPRISM SARM");
        const HRESULT event_result = fence->SetEventOnCompletion(1, event_handle);
        if (FAILED(event_result)) {
            CloseHandle(event_handle);
            check_hr(event_result, "Set NaviPRISM SARM fence event failed");
        }
        const DWORD wait_result = WaitForSingleObject(event_handle, 30000);
        CloseHandle(event_handle);
        if (wait_result != WAIT_OBJECT_0)
            throw std::runtime_error("Timed out waiting for NaviPRISM SARM GPU dispatch");
    }

    std::vector<std::uint64_t> timestamp_values(kSarmRunCount * 2);
    void* timestamp_mapping = nullptr;
    const D3D12_RANGE timestamp_range{0, timestamp_values.size() * sizeof(std::uint64_t)};
    check_hr(timestamp_readback->Map(0, &timestamp_range, &timestamp_mapping),
             "Map NaviPRISM SARM timestamps failed");
    std::memcpy(timestamp_values.data(), timestamp_mapping,
                timestamp_values.size() * sizeof(std::uint64_t));
    timestamp_readback->Unmap(0, nullptr);
    std::vector<double> timings;
    for (UINT run = kSarmWarmupCount; run < kSarmRunCount; ++run) {
        const auto begin = timestamp_values[run * 2];
        const auto end = timestamp_values[run * 2 + 1];
        if (end < begin) throw std::runtime_error("NaviPRISM SARM timestamps are not monotonic");
        timings.push_back(1.0e6 * static_cast<double>(end - begin)
                          / (static_cast<double>(timestamp_frequency)
                             * kSarmDispatchesPerSample));
    }
    const auto timing_summary = summarize(timings);

    void* output_mapping = nullptr;
    const D3D12_RANGE output_range{0, static_cast<SIZE_T>(output_bytes)};
    check_hr(output_readback->Map(0, &output_range, &output_mapping),
             "Map NaviPRISM SARM outputs failed");
    const auto* actual = static_cast<const SarmOutput*>(output_mapping);
    float max_motion_error = 0.0F;
    float max_confidence_error = 0.0F;
    std::uint32_t valid_tiles = 0;
    for (std::uint32_t index = 0; index < tile_count; ++index) {
        const auto& got = actual[index];
        const auto& want = expected[index];
        if (got.valid != want.valid || got.best_cost != want.best_cost ||
            got.second_cost != want.second_cost) {
            output_readback->Unmap(0, nullptr);
            throw std::runtime_error("NaviPRISM SARM GPU costs differ from scalar reference");
        }
        const float motion_error = (std::max)(
            std::abs(got.residual_x - want.residual_x),
            std::abs(got.residual_y - want.residual_y));
        const float confidence_error = std::abs(got.confidence - want.confidence);
        max_motion_error = (std::max)(max_motion_error, motion_error);
        max_confidence_error = (std::max)(max_confidence_error, confidence_error);
        if (motion_error > 0.002F || confidence_error > 1.0e-5F ||
            std::abs(got.refined_x - want.refined_x) > 0.002F ||
            std::abs(got.refined_y - want.refined_y) > 0.002F) {
            output_readback->Unmap(0, nullptr);
            throw std::runtime_error("NaviPRISM SARM GPU motion differs from scalar reference");
        }
        valid_tiles += got.valid;
    }
    output_readback->Unmap(0, nullptr);

    if (!report_path.parent_path().empty())
        std::filesystem::create_directories(report_path.parent_path());
    std::ofstream report(report_path, std::ios::binary | std::ios::trunc);
    if (!report) throw std::runtime_error("Cannot write NaviPRISM SARM report: " + report_path.string());
    report << std::fixed << std::setprecision(6)
           << "{\n  \"gpu\": \"AMD Radeon RX 5700 XT\",\n"
           << "  \"pci_id\": \"1002:731F\",\n"
           << "  \"driver\": \"" << target_driver_version() << "\",\n"
           << "  \"shader_sha256\": \"" << shader_hash << "\",\n"
           << "  \"resolution\": [" << kSarmWidth << ", " << kSarmHeight << "],\n"
           << "  \"tiles\": [" << tile_count_x << ", " << tile_count_y << "],\n"
           << "  \"patch\": [" << kSarmPatchSize << ", " << kSarmPatchSize << "],\n"
           << "  \"search\": {\"dx\": [-3, 3], \"dy\": [-2, 2]},\n"
           << "  \"expected_translation\": [1, -1],\n"
           << "  \"valid_tiles\": " << valid_tiles << ",\n"
           << "  \"max_motion_error_px\": " << max_motion_error << ",\n"
           << "  \"max_confidence_error\": " << max_confidence_error << ",\n"
           << "  \"warmup_samples\": " << kSarmWarmupCount << ",\n"
           << "  \"measured_samples\": " << kSarmMeasuredCount << ",\n"
           << "  \"dispatches_per_sample\": " << kSarmDispatchesPerSample << ",\n"
           << "  \"timestamp_frequency_hz\": " << timestamp_frequency << ",\n"
           << "  \"min_us\": " << timing_summary.minimum << ",\n"
           << "  \"median_us\": " << timing_summary.median << ",\n"
           << "  \"p90_us\": " << timing_summary.p90 << ",\n"
           << "  \"p95_us\": " << timing_summary.p95 << ",\n"
           << "  \"samples_us\": [";
    for (std::size_t sample = 0; sample < timings.size(); ++sample) {
        if (sample != 0) report << ", ";
        report << timings[sample];
    }
    report << "]\n}\n";
    if (!report) throw std::runtime_error("Failed while writing NaviPRISM SARM report");

    std::cout << "NaviPRISM SARM GPU/reference validation passed on RX 5700 XT.\n"
              << "  " << valid_tiles << "/" << tile_count
              << " tiles valid; maximum motion error " << max_motion_error
              << " px; maximum confidence error " << max_confidence_error << ".\n"
              << "  Median dispatch " << timing_summary.median << " us, p95 "
              << timing_summary.p95 << " us; each sample averages "
              << kSarmDispatchesPerSample << " dispatches and ordering barriers.\n"
              << "  JSON report: " << report_path.string() << "; shader SHA-256 "
              << shader_hash << ".\n";
    return 0;
}

int validate_naviprism_thfa(const std::filesystem::path& report_path) {
    const auto input_count = static_cast<std::size_t>(kThfaInputWidth) * kThfaInputHeight;
    const auto output_count = static_cast<std::size_t>(kThfaOutputWidth) * kThfaOutputHeight;
    std::mt19937 random(0x54484641U);
    std::uniform_real_distribution<float> color_distribution(-0.25F, 1.25F);
    std::uniform_real_distribution<float> coefficient_distribution(-0.02F, 0.02F);
    std::uniform_int_distribution<std::uint32_t> spatial_distribution(0, kThfaSpatialBuckets - 1);
    std::uniform_int_distribution<std::uint32_t> temporal_distribution(0, kThfaTemporalBuckets - 1);
    std::uniform_int_distribution<std::uint32_t> phase_distribution(0, kThfaPhaseBuckets - 1);

    std::vector<ThfaFloat3> input(input_count);
    std::vector<std::uint32_t> spatial_descriptors(input_count);
    std::vector<std::uint32_t> temporal_descriptors(input_count);
    std::vector<std::uint32_t> phase_descriptors(input_count);
    for (std::size_t index = 0; index < input_count; ++index) {
        input[index] = {color_distribution(random), color_distribution(random),
                        color_distribution(random)};
        spatial_descriptors[index] = spatial_distribution(random);
        temporal_descriptors[index] = temporal_distribution(random);
        phase_descriptors[index] = phase_distribution(random);
    }
    std::vector<float> spatial_atlas(kThfaSpatialBuckets * kThfaFeatureCount);
    std::vector<float> temporal_atlas(kThfaTemporalBuckets * kThfaFeatureCount);
    std::vector<float> phase_atlas(kThfaPhaseBuckets * kThfaFeatureCount);
    for (auto& value : spatial_atlas) value = coefficient_distribution(random);
    for (auto& value : temporal_atlas) value = coefficient_distribution(random);
    for (auto& value : phase_atlas) value = coefficient_distribution(random);
    const auto constants = ThfaConstants{
        kThfaInputWidth, kThfaInputHeight, kThfaOutputWidth, kThfaOutputHeight};
    std::array<std::byte, 256> constants_upload{};
    std::memcpy(constants_upload.data(), &constants, sizeof(constants));

    std::array<std::vector<ThfaFloat3>, kThfaAlgorithmCount> expected{};
    for (std::uint32_t index = 0; index < kThfaAlgorithmCount; ++index) {
        expected[index] = thfa_reference_filter(
            input, spatial_descriptors, temporal_descriptors, phase_descriptors,
            spatial_atlas, temporal_atlas, phase_atlas, kThfaTapCounts[index]);
    }

    ComPtr<ID3D12Device> device = create_target_device();
    ComPtr<ID3D12CommandQueue> queue;
    D3D12_COMMAND_QUEUE_DESC queue_description{};
    queue_description.Type = D3D12_COMMAND_LIST_TYPE_COMPUTE;
    check_hr(device->CreateCommandQueue(&queue_description, IID_PPV_ARGS(&queue)),
             "Create NaviPRISM THFA compute queue failed");
    ComPtr<ID3D12CommandAllocator> allocator;
    check_hr(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_COMPUTE,
                                             IID_PPV_ARGS(&allocator)),
             "Create NaviPRISM THFA allocator failed");
    ComPtr<ID3D12GraphicsCommandList> command_list;
    check_hr(device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_COMPUTE,
                                      allocator.Get(), nullptr, IID_PPV_ARGS(&command_list)),
             "Create NaviPRISM THFA command list failed");

    auto upload_data = [&](const void* source, std::uint64_t size,
                           ComPtr<ID3D12Resource>& destination, const char* label) {
        create_buffer(device.Get(), D3D12_HEAP_TYPE_UPLOAD, size,
                      D3D12_RESOURCE_STATE_GENERIC_READ, destination);
        void* mapping = nullptr;
        const D3D12_RANGE no_read{0, 0};
        check_hr(destination->Map(0, &no_read, &mapping), label);
        std::memcpy(mapping, source, static_cast<std::size_t>(size));
        destination->Unmap(0, nullptr);
    };
    std::array<ComPtr<ID3D12Resource>, 7> input_buffers{};
    upload_data(input.data(), input.size() * sizeof(input[0]), input_buffers[0],
                "Map NaviPRISM THFA current color failed");
    upload_data(spatial_descriptors.data(), spatial_descriptors.size() * sizeof(std::uint32_t),
                input_buffers[1], "Map NaviPRISM THFA spatial descriptors failed");
    upload_data(temporal_descriptors.data(), temporal_descriptors.size() * sizeof(std::uint32_t),
                input_buffers[2], "Map NaviPRISM THFA temporal descriptors failed");
    upload_data(phase_descriptors.data(), phase_descriptors.size() * sizeof(std::uint32_t),
                input_buffers[3], "Map NaviPRISM THFA phase descriptors failed");
    upload_data(spatial_atlas.data(), spatial_atlas.size() * sizeof(float), input_buffers[4],
                "Map NaviPRISM THFA spatial atlas failed");
    upload_data(temporal_atlas.data(), temporal_atlas.size() * sizeof(float), input_buffers[5],
                "Map NaviPRISM THFA temporal atlas failed");
    upload_data(phase_atlas.data(), phase_atlas.size() * sizeof(float), input_buffers[6],
                "Map NaviPRISM THFA phase atlas failed");
    ComPtr<ID3D12Resource> constants_buffer;
    upload_data(constants_upload.data(), constants_upload.size(), constants_buffer,
                "Map NaviPRISM THFA constants failed");

    std::array<ComPtr<ID3D12Resource>, kThfaAlgorithmCount> output_buffers{};
    std::array<ComPtr<ID3D12Resource>, kThfaAlgorithmCount> output_readbacks{};
    const auto output_bytes = static_cast<std::uint64_t>(output_count * sizeof(ThfaFloat3));
    for (std::uint32_t index = 0; index < kThfaAlgorithmCount; ++index) {
        create_buffer(device.Get(), D3D12_HEAP_TYPE_DEFAULT, output_bytes,
                      D3D12_RESOURCE_STATE_UNORDERED_ACCESS, output_buffers[index],
                      D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS);
        create_buffer(device.Get(), D3D12_HEAP_TYPE_READBACK, output_bytes,
                      D3D12_RESOURCE_STATE_COPY_DEST, output_readbacks[index]);
    }

    D3D12_DESCRIPTOR_HEAP_DESC descriptor_description{};
    descriptor_description.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
    descriptor_description.NumDescriptors = 7 + kThfaAlgorithmCount;
    descriptor_description.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
    ComPtr<ID3D12DescriptorHeap> descriptor_heap;
    check_hr(device->CreateDescriptorHeap(&descriptor_description,
                                         IID_PPV_ARGS(&descriptor_heap)),
             "Create NaviPRISM THFA descriptor heap failed");
    const UINT descriptor_increment = device->GetDescriptorHandleIncrementSize(
        D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
    auto cpu_handle = descriptor_heap->GetCPUDescriptorHandleForHeapStart();
    const std::array<UINT, 7> element_counts{
        static_cast<UINT>(input_count), static_cast<UINT>(input_count),
        static_cast<UINT>(input_count), static_cast<UINT>(input_count),
        kThfaSpatialBuckets * kThfaFeatureCount,
        kThfaTemporalBuckets * kThfaFeatureCount,
        kThfaPhaseBuckets * kThfaFeatureCount};
    const std::array<UINT, 7> structure_strides{
        sizeof(ThfaFloat3), sizeof(std::uint32_t), sizeof(std::uint32_t),
        sizeof(std::uint32_t), sizeof(float), sizeof(float), sizeof(float)};
    for (UINT index = 0; index < 7; ++index) {
        D3D12_SHADER_RESOURCE_VIEW_DESC srv{};
        srv.Format = DXGI_FORMAT_UNKNOWN;
        srv.ViewDimension = D3D12_SRV_DIMENSION_BUFFER;
        srv.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
        srv.Buffer.NumElements = element_counts[index];
        srv.Buffer.StructureByteStride = structure_strides[index];
        device->CreateShaderResourceView(input_buffers[index].Get(), &srv, cpu_handle);
        cpu_handle.ptr += descriptor_increment;
    }
    for (UINT index = 0; index < kThfaAlgorithmCount; ++index) {
        D3D12_UNORDERED_ACCESS_VIEW_DESC uav{};
        uav.Format = DXGI_FORMAT_UNKNOWN;
        uav.ViewDimension = D3D12_UAV_DIMENSION_BUFFER;
        uav.Buffer.NumElements = static_cast<UINT>(output_count);
        uav.Buffer.StructureByteStride = sizeof(ThfaFloat3);
        device->CreateUnorderedAccessView(output_buffers[index].Get(), nullptr,
                                           &uav, cpu_handle);
        cpu_handle.ptr += descriptor_increment;
    }

    std::array<D3D12_DESCRIPTOR_RANGE, 8> ranges{};
    for (UINT index = 0; index < 7; ++index) {
        ranges[index].RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_SRV;
        ranges[index].NumDescriptors = 1;
        ranges[index].BaseShaderRegister = index;
        ranges[index].OffsetInDescriptorsFromTableStart = 0;
    }
    ranges[7].RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_UAV;
    ranges[7].NumDescriptors = 1;
    ranges[7].BaseShaderRegister = 0;
    ranges[7].OffsetInDescriptorsFromTableStart = 0;
    std::array<D3D12_ROOT_PARAMETER, 9> root_parameters{};
    for (UINT index = 0; index < 7; ++index) {
        root_parameters[index].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
        root_parameters[index].DescriptorTable.NumDescriptorRanges = 1;
        root_parameters[index].DescriptorTable.pDescriptorRanges = &ranges[index];
        root_parameters[index].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
    }
    root_parameters[7].ParameterType = D3D12_ROOT_PARAMETER_TYPE_CBV;
    root_parameters[7].Descriptor.ShaderRegister = 0;
    root_parameters[7].Descriptor.RegisterSpace = 0;
    root_parameters[7].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
    root_parameters[8].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
    root_parameters[8].DescriptorTable.NumDescriptorRanges = 1;
    root_parameters[8].DescriptorTable.pDescriptorRanges = &ranges[7];
    root_parameters[8].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
    D3D12_ROOT_SIGNATURE_DESC root_description{};
    root_description.NumParameters = static_cast<UINT>(root_parameters.size());
    root_description.pParameters = root_parameters.data();
    ComPtr<ID3DBlob> serialized_root;
    ComPtr<ID3DBlob> root_errors;
    check_hr(D3D12SerializeRootSignature(&root_description, D3D_ROOT_SIGNATURE_VERSION_1,
                                         &serialized_root, &root_errors),
             "Serialize NaviPRISM THFA root signature failed");
    ComPtr<ID3D12RootSignature> root_signature;
    check_hr(device->CreateRootSignature(0, serialized_root->GetBufferPointer(),
                                          serialized_root->GetBufferSize(),
                                          IID_PPV_ARGS(&root_signature)),
             "Create NaviPRISM THFA root signature failed");

    std::array<ComPtr<ID3D12PipelineState>, kThfaAlgorithmCount> pipelines{};
    std::array<std::vector<std::byte>, kThfaAlgorithmCount> shader_blobs{};
    std::array<std::string, kThfaAlgorithmCount> shader_hashes{};
    for (std::uint32_t index = 0; index < kThfaAlgorithmCount; ++index) {
        const std::wstring shader_name = L"naviprism_thfa_"
            + std::to_wstring(kThfaTapCounts[index]) + L"tap.dxil";
        shader_blobs[index] = read_shader(executable_directory() / shader_name);
        shader_hashes[index] = sha256_hex(shader_blobs[index]);
        D3D12_COMPUTE_PIPELINE_STATE_DESC pipeline_description{};
        pipeline_description.pRootSignature = root_signature.Get();
        pipeline_description.CS.pShaderBytecode = shader_blobs[index].data();
        pipeline_description.CS.BytecodeLength = shader_blobs[index].size();
        check_hr(device->CreateComputePipelineState(&pipeline_description,
                                                     IID_PPV_ARGS(&pipelines[index])),
                 "Create NaviPRISM THFA compute pipeline failed");
    }

    D3D12_QUERY_HEAP_DESC query_description{};
    query_description.Type = D3D12_QUERY_HEAP_TYPE_TIMESTAMP;
    query_description.Count = kThfaQueryCount;
    ComPtr<ID3D12QueryHeap> queries;
    check_hr(device->CreateQueryHeap(&query_description, IID_PPV_ARGS(&queries)),
             "Create NaviPRISM THFA timestamp heap failed");
    ComPtr<ID3D12Resource> timestamp_readback;
    create_buffer(device.Get(), D3D12_HEAP_TYPE_READBACK,
                  kThfaQueryCount * sizeof(std::uint64_t),
                  D3D12_RESOURCE_STATE_COPY_DEST, timestamp_readback);
    UINT64 timestamp_frequency = 0;
    check_hr(queue->GetTimestampFrequency(&timestamp_frequency),
             "Read NaviPRISM THFA timestamp frequency failed");
    if (timestamp_frequency == 0) throw std::runtime_error("D3D12 timestamp frequency is zero");

    const auto gpu_base = descriptor_heap->GetGPUDescriptorHandleForHeapStart();
    for (UINT algorithm = 0; algorithm < kThfaAlgorithmCount; ++algorithm) {
        command_list->SetPipelineState(pipelines[algorithm].Get());
        command_list->SetComputeRootSignature(root_signature.Get());
        ID3D12DescriptorHeap* heaps[]{descriptor_heap.Get()};
        command_list->SetDescriptorHeaps(1, heaps);
        for (UINT root = 0; root < 7; ++root) {
            auto handle = gpu_base;
            handle.ptr += static_cast<UINT64>(root) * descriptor_increment;
            command_list->SetComputeRootDescriptorTable(root, handle);
        }
        command_list->SetComputeRootConstantBufferView(7,
                                                       constants_buffer->GetGPUVirtualAddress());
        auto output_handle = gpu_base;
        output_handle.ptr += static_cast<UINT64>(7 + algorithm) * descriptor_increment;
        command_list->SetComputeRootDescriptorTable(8, output_handle);
        for (UINT run = 0; run < kThfaRunCount; ++run) {
            if (run != 0) {
                D3D12_RESOURCE_BARRIER barrier{};
                barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_UAV;
                barrier.UAV.pResource = output_buffers[algorithm].Get();
                command_list->ResourceBarrier(1, &barrier);
            }
            const UINT query_base = (algorithm * kThfaRunCount + run) * 2;
            command_list->EndQuery(queries.Get(), D3D12_QUERY_TYPE_TIMESTAMP, query_base);
            for (UINT repeat = 0; repeat < kThfaDispatchesPerSample; ++repeat) {
                command_list->Dispatch((kThfaOutputWidth + 7) / 8,
                                       (kThfaOutputHeight + 7) / 8, 1);
                if (repeat + 1 < kThfaDispatchesPerSample) {
                    D3D12_RESOURCE_BARRIER barrier{};
                    barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_UAV;
                    barrier.UAV.pResource = output_buffers[algorithm].Get();
                    command_list->ResourceBarrier(1, &barrier);
                }
            }
            command_list->EndQuery(queries.Get(), D3D12_QUERY_TYPE_TIMESTAMP, query_base + 1);
        }
        D3D12_RESOURCE_BARRIER transition{};
        transition.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        transition.Transition.pResource = output_buffers[algorithm].Get();
        transition.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
        transition.Transition.StateBefore = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
        transition.Transition.StateAfter = D3D12_RESOURCE_STATE_COPY_SOURCE;
        command_list->ResourceBarrier(1, &transition);
        command_list->CopyBufferRegion(output_readbacks[algorithm].Get(), 0,
                                       output_buffers[algorithm].Get(), 0, output_bytes);
    }
    command_list->ResolveQueryData(queries.Get(), D3D12_QUERY_TYPE_TIMESTAMP,
                                   0, kThfaQueryCount, timestamp_readback.Get(), 0);
    check_hr(command_list->Close(), "Close NaviPRISM THFA command list failed");
    ID3D12CommandList* lists[]{command_list.Get()};
    queue->ExecuteCommandLists(1, lists);
    ComPtr<ID3D12Fence> fence;
    check_hr(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)),
             "Create NaviPRISM THFA fence failed");
    check_hr(queue->Signal(fence.Get(), 1), "Signal NaviPRISM THFA fence failed");
    if (fence->GetCompletedValue() < 1) {
        HANDLE event_handle = CreateEventW(nullptr, FALSE, FALSE, nullptr);
        if (!event_handle) throw std::runtime_error("CreateEventW failed for NaviPRISM THFA");
        const HRESULT event_result = fence->SetEventOnCompletion(1, event_handle);
        if (FAILED(event_result)) {
            CloseHandle(event_handle);
            check_hr(event_result, "Set NaviPRISM THFA fence event failed");
        }
        const DWORD wait_result = WaitForSingleObject(event_handle, 30000);
        CloseHandle(event_handle);
        if (wait_result != WAIT_OBJECT_0)
            throw std::runtime_error("Timed out waiting for NaviPRISM THFA GPU dispatch");
    }

    std::vector<std::uint64_t> timestamp_values(kThfaQueryCount);
    void* timestamp_mapping = nullptr;
    const D3D12_RANGE timestamp_range{0, timestamp_values.size() * sizeof(std::uint64_t)};
    check_hr(timestamp_readback->Map(0, &timestamp_range, &timestamp_mapping),
             "Map NaviPRISM THFA timestamps failed");
    std::memcpy(timestamp_values.data(), timestamp_mapping,
                timestamp_values.size() * sizeof(std::uint64_t));
    timestamp_readback->Unmap(0, nullptr);
    std::array<std::vector<double>, kThfaAlgorithmCount> timings{};
    for (UINT algorithm = 0; algorithm < kThfaAlgorithmCount; ++algorithm) {
        for (UINT run = kThfaWarmupCount; run < kThfaRunCount; ++run) {
            const UINT query_base = (algorithm * kThfaRunCount + run) * 2;
            const auto begin = timestamp_values[query_base];
            const auto end = timestamp_values[query_base + 1];
            if (end < begin) throw std::runtime_error("NaviPRISM THFA timestamps are not monotonic");
            timings[algorithm].push_back(1.0e6 * static_cast<double>(end - begin)
                                         / (static_cast<double>(timestamp_frequency)
                                            * kThfaDispatchesPerSample));
        }
    }

    std::array<TimingSummary, kThfaAlgorithmCount> timing_summaries{};
    std::array<float, kThfaAlgorithmCount> max_errors{};
    for (UINT algorithm = 0; algorithm < kThfaAlgorithmCount; ++algorithm) {
        timing_summaries[algorithm] = summarize(timings[algorithm]);
        void* output_mapping = nullptr;
        const D3D12_RANGE output_range{0, static_cast<SIZE_T>(output_bytes)};
        check_hr(output_readbacks[algorithm]->Map(0, &output_range, &output_mapping),
                 "Map NaviPRISM THFA output failed");
        const auto* actual = static_cast<const ThfaFloat3*>(output_mapping);
        for (std::size_t index = 0; index < output_count; ++index) {
            const float error_x = std::abs(actual[index].x - expected[algorithm][index].x);
            const float error_y = std::abs(actual[index].y - expected[algorithm][index].y);
            const float error_z = std::abs(actual[index].z - expected[algorithm][index].z);
            max_errors[algorithm] = (std::max)(max_errors[algorithm],
                                               (std::max)({error_x, error_y, error_z}));
        }
        output_readbacks[algorithm]->Unmap(0, nullptr);
        if (max_errors[algorithm] > 2.0e-5F)
            throw std::runtime_error("NaviPRISM THFA GPU output differs from scalar reference");
    }

    if (!report_path.parent_path().empty())
        std::filesystem::create_directories(report_path.parent_path());
    std::ofstream report(report_path, std::ios::binary | std::ios::trunc);
    if (!report) throw std::runtime_error("Cannot write NaviPRISM THFA report: " + report_path.string());
    report << std::fixed << std::setprecision(6)
           << "{\n  \"gpu\": \"AMD Radeon RX 5700 XT\",\n"
           << "  \"pci_id\": \"1002:731F\",\n"
           << "  \"driver\": \"" << target_driver_version() << "\",\n"
           << "  \"input_resolution\": [" << kThfaInputWidth << ", " << kThfaInputHeight << "],\n"
           << "  \"output_resolution\": [" << kThfaOutputWidth << ", " << kThfaOutputHeight << "],\n"
           << "  \"warmup_samples\": " << kThfaWarmupCount << ",\n"
           << "  \"measured_samples\": " << kThfaMeasuredCount << ",\n"
           << "  \"dispatches_per_sample\": " << kThfaDispatchesPerSample << ",\n"
           << "  \"timestamp_frequency_hz\": " << timestamp_frequency << ",\n"
           << "  \"modes\": [\n";
    for (UINT algorithm = 0; algorithm < kThfaAlgorithmCount; ++algorithm) {
        const auto& summary = timing_summaries[algorithm];
        report << "    {\"tap_count\": " << kThfaTapCounts[algorithm]
               << ", \"shader_sha256\": \"" << shader_hashes[algorithm]
               << "\", \"max_abs_error\": " << max_errors[algorithm]
               << ", \"min_us\": " << summary.minimum
               << ", \"median_us\": " << summary.median
               << ", \"p90_us\": " << summary.p90
               << ", \"p95_us\": " << summary.p95 << ", \"samples_us\": [";
        for (std::size_t sample = 0; sample < timings[algorithm].size(); ++sample) {
            if (sample != 0) report << ", ";
            report << timings[algorithm][sample];
        }
        report << "]}" << (algorithm + 1 == kThfaAlgorithmCount ? "\n" : ",\n");
    }
    report << "  ]\n}\n";
    if (!report) throw std::runtime_error("Failed while writing NaviPRISM THFA report");

    std::cout << "NaviPRISM THFA GPU/reference validation passed on RX 5700 XT.\n"
              << "  2x output; bilinear baseline plus direct residual atlas; each timing sample averages "
              << kThfaDispatchesPerSample << " dispatches and ordering barriers.\n";
    for (UINT algorithm = 0; algorithm < kThfaAlgorithmCount; ++algorithm) {
        std::cout << "  " << kThfaTapCounts[algorithm] << " taps: max error "
                  << max_errors[algorithm] << ", median " << timing_summaries[algorithm].median
                  << " us, p95 " << timing_summaries[algorithm].p95
                  << " us, shader SHA-256 " << shader_hashes[algorithm] << ".\n";
    }
    std::cout << "  JSON report: " << report_path.string() << ".\n";
    return 0;
}

int validate_naviprism_router(const std::filesystem::path& report_path) {
    constexpr std::uint32_t tile_count = 8;
    constexpr std::uint32_t route_count = 5;
    const std::array<RouterEvidenceGpu, tile_count> evidence{{
        {0.95F, 0.00F, 1, 0, 0, 0, 1, 0}, // EASY
        {0.75F, 0.00F, 1, 0, 0, 0, 1, 0}, // MEDIUM
        {0.90F, 0.00F, 1, 1, 0, 0, 1, 0}, // HARD: thin detail
        {0.10F, 0.00F, 1, 0, 0, 0, 1, 0}, // VERY_HARD: ambiguous motion
        {0.00F, 0.00F, 1, 0, 0, 0, 1, 1}, // REFERENCE: explicit override
        {0.90F, 0.80F, 1, 0, 0, 0, 1, 0}, // VERY_HARD: disocclusion
        {0.90F, 0.00F, 1, 0, 1, 0, 1, 0}, // HARD: reactive
        {0.70F, 0.00F, 1, 0, 0, 0, 1, 0}, // MEDIUM
    }};
    constexpr std::array<std::uint32_t, tile_count> expected_routes{
        0, 1, 2, 3, 4, 3, 2, 1};
    constexpr std::array<std::uint32_t, route_count> expected_counts{1, 2, 2, 2, 1};

    ComPtr<ID3D12Device> device = create_target_device();
    ComPtr<ID3D12CommandQueue> queue;
    D3D12_COMMAND_QUEUE_DESC queue_description{};
    queue_description.Type = D3D12_COMMAND_LIST_TYPE_COMPUTE;
    check_hr(device->CreateCommandQueue(&queue_description, IID_PPV_ARGS(&queue)),
             "Create NaviPRISM router compute queue failed");
    ComPtr<ID3D12CommandAllocator> allocator;
    check_hr(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_COMPUTE,
                                             IID_PPV_ARGS(&allocator)),
             "Create NaviPRISM router allocator failed");
    ComPtr<ID3D12GraphicsCommandList> command_list;
    check_hr(device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_COMPUTE,
                                      allocator.Get(), nullptr, IID_PPV_ARGS(&command_list)),
             "Create NaviPRISM router command list failed");

    auto upload_data = [&](const void* source, std::uint64_t size,
                           ComPtr<ID3D12Resource>& destination, const char* label) {
        create_buffer(device.Get(), D3D12_HEAP_TYPE_UPLOAD, size,
                      D3D12_RESOURCE_STATE_GENERIC_READ, destination);
        void* mapping = nullptr;
        const D3D12_RANGE no_read{0, 0};
        check_hr(destination->Map(0, &no_read, &mapping), label);
        std::memcpy(mapping, source, static_cast<std::size_t>(size));
        destination->Unmap(0, nullptr);
    };
    ComPtr<ID3D12Resource> evidence_buffer;
    upload_data(evidence.data(), sizeof(evidence), evidence_buffer,
                "Map NaviPRISM router evidence failed");
    const std::uint32_t tile_count_constant = tile_count;
    std::array<std::byte, 256> constants_upload{};
    std::memcpy(constants_upload.data(), &tile_count_constant, sizeof(tile_count_constant));
    ComPtr<ID3D12Resource> constants_buffer;
    upload_data(constants_upload.data(), constants_upload.size(), constants_buffer,
                "Map NaviPRISM router constants failed");

    const std::array<std::uint32_t, route_count> zero_counts{};
    ComPtr<ID3D12Resource> counter_upload;
    upload_data(zero_counts.data(), sizeof(zero_counts), counter_upload,
                "Map NaviPRISM router zero counters failed");
    std::array<ComPtr<ID3D12Resource>, 4> outputs{};
    std::array<ComPtr<ID3D12Resource>, 4> readbacks{};
    const std::array<std::uint64_t, 4> output_sizes{
        tile_count * sizeof(std::uint32_t), tile_count * sizeof(std::uint32_t),
        tile_count * sizeof(std::uint32_t), route_count * sizeof(std::uint32_t)};
    for (std::size_t index = 0; index < outputs.size(); ++index) {
        const auto initial_state = index == 3 ? D3D12_RESOURCE_STATE_COPY_DEST
                                              : D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
        create_buffer(device.Get(), D3D12_HEAP_TYPE_DEFAULT, output_sizes[index],
                      initial_state, outputs[index], D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS);
        create_buffer(device.Get(), D3D12_HEAP_TYPE_READBACK, output_sizes[index],
                      D3D12_RESOURCE_STATE_COPY_DEST, readbacks[index]);
    }

    D3D12_DESCRIPTOR_HEAP_DESC descriptor_description{};
    descriptor_description.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
    descriptor_description.NumDescriptors = 5;
    descriptor_description.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
    ComPtr<ID3D12DescriptorHeap> descriptor_heap;
    check_hr(device->CreateDescriptorHeap(&descriptor_description,
                                         IID_PPV_ARGS(&descriptor_heap)),
             "Create NaviPRISM router descriptor heap failed");
    const UINT descriptor_increment = device->GetDescriptorHandleIncrementSize(
        D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
    auto cpu_handle = descriptor_heap->GetCPUDescriptorHandleForHeapStart();
    D3D12_SHADER_RESOURCE_VIEW_DESC srv{};
    srv.Format = DXGI_FORMAT_UNKNOWN;
    srv.ViewDimension = D3D12_SRV_DIMENSION_BUFFER;
    srv.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
    srv.Buffer.NumElements = tile_count;
    srv.Buffer.StructureByteStride = sizeof(RouterEvidenceGpu);
    device->CreateShaderResourceView(evidence_buffer.Get(), &srv, cpu_handle);
    cpu_handle.ptr += descriptor_increment;
    for (UINT index = 0; index < outputs.size(); ++index) {
        D3D12_UNORDERED_ACCESS_VIEW_DESC uav{};
        uav.Format = DXGI_FORMAT_UNKNOWN;
        uav.ViewDimension = D3D12_UAV_DIMENSION_BUFFER;
        uav.Buffer.NumElements = index == 3 ? route_count : tile_count;
        uav.Buffer.StructureByteStride = sizeof(std::uint32_t);
        device->CreateUnorderedAccessView(outputs[index].Get(), nullptr, &uav, cpu_handle);
        cpu_handle.ptr += descriptor_increment;
    }

    std::array<D3D12_DESCRIPTOR_RANGE, 5> ranges{};
    ranges[0].RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_SRV;
    ranges[0].NumDescriptors = 1;
    ranges[0].BaseShaderRegister = 0;
    ranges[0].OffsetInDescriptorsFromTableStart = 0;
    for (UINT index = 1; index < ranges.size(); ++index) {
        ranges[index].RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_UAV;
        ranges[index].NumDescriptors = 1;
        ranges[index].BaseShaderRegister = index - 1;
        ranges[index].OffsetInDescriptorsFromTableStart = 0;
    }
    std::array<D3D12_ROOT_PARAMETER, 6> root_parameters{};
    root_parameters[0].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
    root_parameters[0].DescriptorTable.NumDescriptorRanges = 1;
    root_parameters[0].DescriptorTable.pDescriptorRanges = &ranges[0];
    root_parameters[0].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
    root_parameters[1].ParameterType = D3D12_ROOT_PARAMETER_TYPE_CBV;
    root_parameters[1].Descriptor.ShaderRegister = 0;
    root_parameters[1].Descriptor.RegisterSpace = 0;
    root_parameters[1].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
    for (UINT index = 0; index < 4; ++index) {
        root_parameters[index + 2].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
        root_parameters[index + 2].DescriptorTable.NumDescriptorRanges = 1;
        root_parameters[index + 2].DescriptorTable.pDescriptorRanges = &ranges[index + 1];
        root_parameters[index + 2].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
    }
    D3D12_ROOT_SIGNATURE_DESC root_description{};
    root_description.NumParameters = static_cast<UINT>(root_parameters.size());
    root_description.pParameters = root_parameters.data();
    ComPtr<ID3DBlob> serialized_root;
    ComPtr<ID3DBlob> root_errors;
    check_hr(D3D12SerializeRootSignature(&root_description, D3D_ROOT_SIGNATURE_VERSION_1,
                                         &serialized_root, &root_errors),
             "Serialize NaviPRISM router root signature failed");
    ComPtr<ID3D12RootSignature> root_signature;
    check_hr(device->CreateRootSignature(0, serialized_root->GetBufferPointer(),
                                          serialized_root->GetBufferSize(),
                                          IID_PPV_ARGS(&root_signature)),
             "Create NaviPRISM router root signature failed");

    const auto shader_path = executable_directory() / L"naviprism_quality_router.dxil";
    auto shader = read_shader(shader_path);
    const auto shader_hash = sha256_hex(shader);
    D3D12_COMPUTE_PIPELINE_STATE_DESC pipeline_description{};
    pipeline_description.pRootSignature = root_signature.Get();
    pipeline_description.CS.pShaderBytecode = shader.data();
    pipeline_description.CS.BytecodeLength = shader.size();
    ComPtr<ID3D12PipelineState> pipeline;
    check_hr(device->CreateComputePipelineState(&pipeline_description, IID_PPV_ARGS(&pipeline)),
             "Create NaviPRISM router pipeline failed");

    command_list->CopyBufferRegion(outputs[3].Get(), 0, counter_upload.Get(), 0,
                                   output_sizes[3]);
    D3D12_RESOURCE_BARRIER counter_transition{};
    counter_transition.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    counter_transition.Transition.pResource = outputs[3].Get();
    counter_transition.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    counter_transition.Transition.StateBefore = D3D12_RESOURCE_STATE_COPY_DEST;
    counter_transition.Transition.StateAfter = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
    command_list->ResourceBarrier(1, &counter_transition);

    command_list->SetPipelineState(pipeline.Get());
    command_list->SetComputeRootSignature(root_signature.Get());
    ID3D12DescriptorHeap* heaps[]{descriptor_heap.Get()};
    command_list->SetDescriptorHeaps(1, heaps);
    const auto gpu_base = descriptor_heap->GetGPUDescriptorHandleForHeapStart();
    auto input_handle = gpu_base;
    command_list->SetComputeRootDescriptorTable(0, input_handle);
    command_list->SetComputeRootConstantBufferView(1, constants_buffer->GetGPUVirtualAddress());
    for (UINT index = 0; index < 4; ++index) {
        auto handle = gpu_base;
        handle.ptr += static_cast<UINT64>(index + 1) * descriptor_increment;
        command_list->SetComputeRootDescriptorTable(index + 2, handle);
    }
    command_list->Dispatch(1, 1, 1);

    for (std::size_t index = 0; index < outputs.size(); ++index) {
        D3D12_RESOURCE_BARRIER transition{};
        transition.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        transition.Transition.pResource = outputs[index].Get();
        transition.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
        transition.Transition.StateBefore = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
        transition.Transition.StateAfter = D3D12_RESOURCE_STATE_COPY_SOURCE;
        command_list->ResourceBarrier(1, &transition);
        command_list->CopyBufferRegion(readbacks[index].Get(), 0,
                                       outputs[index].Get(), 0, output_sizes[index]);
    }
    check_hr(command_list->Close(), "Close NaviPRISM router command list failed");
    ID3D12CommandList* lists[]{command_list.Get()};
    queue->ExecuteCommandLists(1, lists);
    ComPtr<ID3D12Fence> fence;
    check_hr(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)),
             "Create NaviPRISM router fence failed");
    check_hr(queue->Signal(fence.Get(), 1), "Signal NaviPRISM router fence failed");
    if (fence->GetCompletedValue() < 1) {
        HANDLE event_handle = CreateEventW(nullptr, FALSE, FALSE, nullptr);
        if (!event_handle) throw std::runtime_error("CreateEventW failed for NaviPRISM router");
        const HRESULT event_result = fence->SetEventOnCompletion(1, event_handle);
        if (FAILED(event_result)) {
            CloseHandle(event_handle);
            check_hr(event_result, "Set NaviPRISM router fence event failed");
        }
        const DWORD wait_result = WaitForSingleObject(event_handle, 30000);
        CloseHandle(event_handle);
        if (wait_result != WAIT_OBJECT_0)
            throw std::runtime_error("Timed out waiting for NaviPRISM router validation");
    }

    std::array<std::vector<std::uint32_t>, 4> actual{};
    for (std::size_t index = 0; index < readbacks.size(); ++index) {
        const auto elements = static_cast<std::size_t>(output_sizes[index] / sizeof(std::uint32_t));
        actual[index].resize(elements);
        void* mapping = nullptr;
        const D3D12_RANGE range{0, static_cast<SIZE_T>(output_sizes[index])};
        check_hr(readbacks[index]->Map(0, &range, &mapping),
                 "Map NaviPRISM router output failed");
        std::memcpy(actual[index].data(), mapping, static_cast<std::size_t>(output_sizes[index]));
        readbacks[index]->Unmap(0, nullptr);
    }
    if (!std::equal(expected_routes.begin(), expected_routes.end(), actual[0].begin()) ||
        !std::equal(expected_counts.begin(), expected_counts.end(), actual[3].begin())) {
        throw std::runtime_error("NaviPRISM GPU router decisions/counters differ from reference");
    }
    std::vector<std::uint32_t> hard_tiles(actual[1].begin(),
                                          actual[1].begin() + actual[3][2]);
    std::vector<std::uint32_t> very_hard_tiles(actual[2].begin(),
                                               actual[2].begin() + actual[3][3]);
    std::sort(hard_tiles.begin(), hard_tiles.end());
    std::sort(very_hard_tiles.begin(), very_hard_tiles.end());
    if (hard_tiles != std::vector<std::uint32_t>{2, 6} ||
        very_hard_tiles != std::vector<std::uint32_t>{3, 5}) {
        throw std::runtime_error("NaviPRISM GPU router compacted tile lists are incorrect");
    }

    if (!report_path.parent_path().empty())
        std::filesystem::create_directories(report_path.parent_path());
    std::ofstream report(report_path, std::ios::binary | std::ios::trunc);
    if (!report) throw std::runtime_error("Cannot write NaviPRISM router report: " + report_path.string());
    report << "{\n  \"gpu\": \"AMD Radeon RX 5700 XT\",\n"
           << "  \"pci_id\": \"1002:731F\",\n"
           << "  \"shader_sha256\": \"" << shader_hash << "\",\n"
           << "  \"tiles\": " << tile_count << ",\n"
           << "  \"route_counts\": [";
    for (std::size_t index = 0; index < actual[3].size(); ++index) {
        if (index != 0) report << ", ";
        report << actual[3][index];
    }
    report << "],\n  \"hard_tiles\": [";
    for (std::size_t index = 0; index < hard_tiles.size(); ++index) {
        if (index != 0) report << ", ";
        report << hard_tiles[index];
    }
    report << "],\n  \"very_hard_tiles\": [";
    for (std::size_t index = 0; index < very_hard_tiles.size(); ++index) {
        if (index != 0) report << ", ";
        report << very_hard_tiles[index];
    }
    report << "]\n}\n";
    if (!report) throw std::runtime_error("Failed while writing NaviPRISM router report");
    std::cout << "NaviPRISM router GPU/reference validation passed on RX 5700 XT.\n"
              << "  Route counts EASY/MEDIUM/HARD/VERY_HARD/REFERENCE: 1/2/2/2/1.\n"
              << "  Compacted HARD tiles: 2,6; VERY_HARD tiles: 3,5.\n"
              << "  JSON report: " << report_path.string() << "; shader SHA-256 "
              << shader_hash << ".\n";
    return 0;
}

namespace {

constexpr std::uint32_t kPhrWidth = 13;
constexpr std::uint32_t kPhrHeight = 9;
constexpr std::uint32_t kPhrPhaseCount = 4;
constexpr std::uint32_t kPhrCurrentPhase = 2;
constexpr std::uint32_t kPhrResetPhase = 1;
constexpr std::uint32_t kPhrMaximumAge = 6;
constexpr float kPhrDepthThreshold = 0.02F;
constexpr float kPhrConfidenceDecay = 0.98F;
constexpr UINT kPhrWarmupCount = 5;
constexpr UINT kPhrMeasuredCount = 20;
constexpr UINT kPhrRunCount = kPhrWarmupCount + kPhrMeasuredCount;
constexpr UINT kPhrDispatchesPerSample = 32;
constexpr UINT kPhrModeCount = 2;
constexpr UINT kPhrQueryCount = kPhrModeCount * kPhrRunCount * 2;

struct PhrEntry {
    float color[3];
    float confidence;
    std::uint32_t age;
    float depth;
    std::uint32_t valid;
};
static_assert(sizeof(PhrEntry) == 28);

struct PhrFloat2 { float x; float y; };
static_assert(sizeof(PhrFloat2) == 8);

struct PhrFloat4 { float x; float y; float z; float w; };
static_assert(sizeof(PhrFloat4) == 16);

struct PhrConstants {
    std::uint32_t width;
    std::uint32_t height;
    std::uint32_t current_phase;
    std::uint32_t reset_history;
    float depth_threshold;
    float confidence_decay;
    std::uint32_t maximum_age;
    std::uint32_t padding;
};
static_assert(sizeof(PhrConstants) == 32);

std::vector<PhrEntry> phr_scalar_reference(
    const std::vector<PhrEntry>& previous,
    const std::vector<PhrFloat2>& motion,
    const std::vector<float>& depth,
    const std::vector<std::uint32_t>& validity,
    const std::vector<PhrFloat4>& current_color_confidence,
    std::uint32_t current_phase,
    bool reset_history) {
    const std::size_t pixel_count = static_cast<std::size_t>(kPhrWidth) * kPhrHeight;
    std::vector<PhrEntry> output(pixel_count * kPhrPhaseCount);
    for (std::size_t pixel = 0; pixel < pixel_count; ++pixel) {
        const auto& mv = motion[pixel];
        const float current_depth = depth[pixel];
        const bool map_valid = validity[pixel] != 0 && std::isfinite(current_depth)
            && std::isfinite(mv.x) && std::isfinite(mv.y);
        int previous_x = -1;
        int previous_y = -1;
        if (map_valid) {
            const float rounded_x = std::floor(mv.x + 0.5F);
            const float rounded_y = std::floor(mv.y + 0.5F);
            if (rounded_x >= 0.0F && rounded_y >= 0.0F &&
                rounded_x < static_cast<float>(kPhrWidth) &&
                rounded_y < static_cast<float>(kPhrHeight)) {
                previous_x = static_cast<int>(rounded_x);
                previous_y = static_cast<int>(rounded_y);
            }
        }
        const bool previous_valid = previous_x >= 0 && previous_y >= 0;
        for (std::uint32_t phase = 0; phase < kPhrPhaseCount; ++phase) {
            PhrEntry result{};
            if (!reset_history && map_valid && previous_valid) {
                const auto source_pixel = static_cast<std::size_t>(previous_y) * kPhrWidth
                    + static_cast<std::size_t>(previous_x);
                const auto& old = previous[static_cast<std::size_t>(phase) * pixel_count
                                           + source_pixel];
                if (old.valid != 0 && std::isfinite(old.depth) &&
                    std::abs(old.depth - current_depth) <= kPhrDepthThreshold) {
                    result = old;
                    result.confidence = old.confidence * kPhrConfidenceDecay;
                    result.age = old.age >= kPhrMaximumAge
                        ? kPhrMaximumAge : old.age + 1;
                    result.depth = current_depth;
                    result.valid = result.confidence > 0.0F ? 1U : 0U;
                }
            }

            if (phase == current_phase) {
                result = {};
                const auto& current = current_color_confidence[pixel];
                const bool color_valid = std::isfinite(current.x) &&
                    std::isfinite(current.y) && std::isfinite(current.z) &&
                    std::isfinite(current.w) && current.w >= 0.0F && current.w <= 1.0F;
                if (map_valid && color_valid) {
                    result.color[0] = current.x;
                    result.color[1] = current.y;
                    result.color[2] = current.z;
                    result.confidence = current.w;
                    result.age = 0;
                    result.depth = current_depth;
                    result.valid = 1;
                }
            }
            output[static_cast<std::size_t>(phase) * pixel_count + pixel] = result;
        }
    }
    return output;
}

} // namespace

int validate_naviprism_phase_reservoir(const std::filesystem::path& report_path) {
    const std::size_t pixel_count = static_cast<std::size_t>(kPhrWidth) * kPhrHeight;
    const std::size_t entry_count = pixel_count * kPhrPhaseCount;
    std::vector<PhrEntry> previous(entry_count);
    std::vector<PhrFloat2> motion(pixel_count);
    std::vector<float> depth(pixel_count);
    std::vector<std::uint32_t> validity(pixel_count);
    std::vector<PhrFloat4> current_color_confidence(pixel_count);
    const float nan = std::numeric_limits<float>::quiet_NaN();
    for (std::size_t pixel = 0; pixel < pixel_count; ++pixel) {
        const auto x = static_cast<std::uint32_t>(pixel % kPhrWidth);
        const auto y = static_cast<std::uint32_t>(pixel / kPhrWidth);
        depth[pixel] = 1.0F + 0.01F * static_cast<float>(pixel % 5);
        validity[pixel] = pixel % 9 == 0 ? 0U : 1U;
        const int dx = static_cast<int>((pixel * 3) % 7) - 3;
        const int dy = static_cast<int>((pixel * 5) % 5) - 2;
        const float fraction_x = pixel % 2 == 0 ? 0.49F : 0.51F;
        const float fraction_y = pixel % 3 == 0 ? 0.49F : 0.51F;
        motion[pixel] = {static_cast<float>(static_cast<int>(x) + dx) + fraction_x,
                         static_cast<float>(static_cast<int>(y) + dy) + fraction_y};
        if (pixel % 29 == 0) motion[pixel].x = -32.0F;
        if (pixel % 37 == 0) motion[pixel].y = nan;
        if (pixel % 43 == 0) depth[pixel] = nan;

        const float base = static_cast<float>(pixel % 17) * 0.025F;
        current_color_confidence[pixel] = {
            0.10F + base, 0.20F + base * 0.5F, 0.30F + base * 0.25F,
            static_cast<float>(pixel % 5) * 0.25F};
        if (pixel % 31 == 0) current_color_confidence[pixel].y = nan;

        for (std::uint32_t phase = 0; phase < kPhrPhaseCount; ++phase) {
            auto& entry = previous[static_cast<std::size_t>(phase) * pixel_count + pixel];
            entry.color[0] = 0.01F * static_cast<float>(pixel + phase);
            entry.color[1] = 0.02F * static_cast<float>((pixel + 2 * phase) % 19);
            entry.color[2] = 0.03F * static_cast<float>((pixel + phase) % 13);
            entry.confidence = (pixel + phase) % 8 == 0
                ? 0.0F : 0.125F * static_cast<float>(1 + ((pixel + phase) % 7));
            entry.age = static_cast<std::uint32_t>((pixel + phase) % 11);
            entry.depth = depth[pixel];
            if ((pixel + 2 * phase) % 6 == 0) entry.depth += 0.12F;
            entry.valid = (pixel + phase) % 7 == 0 ? 0U : 1U;
        }
    }

    const std::array<std::vector<PhrEntry>, kPhrModeCount> expected{
        phr_scalar_reference(previous, motion, depth, validity,
                             current_color_confidence, kPhrCurrentPhase, false),
        phr_scalar_reference(previous, motion, depth, validity,
                             current_color_confidence, kPhrResetPhase, true),
    };
    const std::array<PhrConstants, kPhrModeCount> constants{{
        {kPhrWidth, kPhrHeight, kPhrCurrentPhase, 0,
         kPhrDepthThreshold, kPhrConfidenceDecay, kPhrMaximumAge, 0},
        {kPhrWidth, kPhrHeight, kPhrResetPhase, 1,
         kPhrDepthThreshold, kPhrConfidenceDecay, kPhrMaximumAge, 0},
    }};

    ComPtr<ID3D12Device> device = create_target_device();
    ComPtr<ID3D12CommandQueue> queue;
    D3D12_COMMAND_QUEUE_DESC queue_description{};
    queue_description.Type = D3D12_COMMAND_LIST_TYPE_COMPUTE;
    check_hr(device->CreateCommandQueue(&queue_description, IID_PPV_ARGS(&queue)),
             "Create NaviPRISM phase-reservoir compute queue failed");
    UINT64 timestamp_frequency = 0;
    check_hr(queue->GetTimestampFrequency(&timestamp_frequency),
             "Read NaviPRISM phase-reservoir timestamp frequency failed");

    auto upload = [&](const void* source, std::uint64_t size,
                      ComPtr<ID3D12Resource>& resource, const char* operation) {
        create_buffer(device.Get(), D3D12_HEAP_TYPE_UPLOAD, size,
                      D3D12_RESOURCE_STATE_GENERIC_READ, resource);
        void* mapping = nullptr;
        const D3D12_RANGE no_read{0, 0};
        check_hr(resource->Map(0, &no_read, &mapping), operation);
        std::memcpy(mapping, source, static_cast<std::size_t>(size));
        resource->Unmap(0, nullptr);
    };

    std::array<ComPtr<ID3D12Resource>, 5> input_resources{};
    upload(previous.data(), previous.size() * sizeof(PhrEntry), input_resources[0],
           "Map NaviPRISM phase-reservoir history failed");
    upload(motion.data(), motion.size() * sizeof(PhrFloat2), input_resources[1],
           "Map NaviPRISM phase-reservoir motion failed");
    upload(depth.data(), depth.size() * sizeof(float), input_resources[2],
           "Map NaviPRISM phase-reservoir depth failed");
    upload(validity.data(), validity.size() * sizeof(std::uint32_t), input_resources[3],
           "Map NaviPRISM phase-reservoir validity failed");
    upload(current_color_confidence.data(),
           current_color_confidence.size() * sizeof(PhrFloat4), input_resources[4],
           "Map NaviPRISM phase-reservoir current colors failed");

    std::array<ComPtr<ID3D12Resource>, kPhrModeCount> constants_resources{};
    for (std::size_t mode = 0; mode < constants_resources.size(); ++mode) {
        std::array<std::byte, 256> padded{};
        std::memcpy(padded.data(), &constants[mode], sizeof(PhrConstants));
        upload(padded.data(), padded.size(), constants_resources[mode],
               "Map NaviPRISM phase-reservoir constants failed");
    }

    const auto output_bytes = static_cast<std::uint64_t>(entry_count * sizeof(PhrEntry));
    std::array<ComPtr<ID3D12Resource>, kPhrModeCount> outputs{};
    std::array<ComPtr<ID3D12Resource>, kPhrModeCount> readbacks{};
    for (std::size_t mode = 0; mode < outputs.size(); ++mode) {
        create_buffer(device.Get(), D3D12_HEAP_TYPE_DEFAULT, output_bytes,
                      D3D12_RESOURCE_STATE_UNORDERED_ACCESS, outputs[mode],
                      D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS);
        create_buffer(device.Get(), D3D12_HEAP_TYPE_READBACK, output_bytes,
                      D3D12_RESOURCE_STATE_COPY_DEST, readbacks[mode]);
    }

    D3D12_DESCRIPTOR_HEAP_DESC heap_description{};
    heap_description.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
    heap_description.NumDescriptors = static_cast<UINT>(input_resources.size());
    heap_description.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
    ComPtr<ID3D12DescriptorHeap> descriptor_heap;
    check_hr(device->CreateDescriptorHeap(&heap_description, IID_PPV_ARGS(&descriptor_heap)),
             "Create NaviPRISM phase-reservoir descriptor heap failed");
    const std::array<UINT, 5> element_counts{
        static_cast<UINT>(previous.size()), static_cast<UINT>(motion.size()),
        static_cast<UINT>(depth.size()), static_cast<UINT>(validity.size()),
        static_cast<UINT>(current_color_confidence.size())};
    const std::array<UINT, 5> strides{
        sizeof(PhrEntry), sizeof(PhrFloat2), sizeof(float), sizeof(std::uint32_t),
        sizeof(PhrFloat4)};
    auto cpu_descriptor = descriptor_heap->GetCPUDescriptorHandleForHeapStart();
    const UINT descriptor_increment = device->GetDescriptorHandleIncrementSize(
        D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
    for (UINT index = 0; index < input_resources.size(); ++index) {
        D3D12_SHADER_RESOURCE_VIEW_DESC srv{};
        srv.Format = DXGI_FORMAT_UNKNOWN;
        srv.ViewDimension = D3D12_SRV_DIMENSION_BUFFER;
        srv.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
        srv.Buffer.NumElements = element_counts[index];
        srv.Buffer.StructureByteStride = strides[index];
        device->CreateShaderResourceView(input_resources[index].Get(), &srv, cpu_descriptor);
        cpu_descriptor.ptr += descriptor_increment;
    }

    D3D12_DESCRIPTOR_RANGE srv_range{};
    srv_range.RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_SRV;
    srv_range.NumDescriptors = static_cast<UINT>(input_resources.size());
    srv_range.BaseShaderRegister = 0;
    srv_range.OffsetInDescriptorsFromTableStart = D3D12_DESCRIPTOR_RANGE_OFFSET_APPEND;
    std::array<D3D12_ROOT_PARAMETER, 3> root_parameters{};
    root_parameters[0].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
    root_parameters[0].DescriptorTable.NumDescriptorRanges = 1;
    root_parameters[0].DescriptorTable.pDescriptorRanges = &srv_range;
    root_parameters[0].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
    root_parameters[1].ParameterType = D3D12_ROOT_PARAMETER_TYPE_CBV;
    root_parameters[1].Descriptor.ShaderRegister = 0;
    root_parameters[1].Descriptor.RegisterSpace = 0;
    root_parameters[1].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
    root_parameters[2].ParameterType = D3D12_ROOT_PARAMETER_TYPE_UAV;
    root_parameters[2].Descriptor.ShaderRegister = 0;
    root_parameters[2].Descriptor.RegisterSpace = 0;
    root_parameters[2].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
    D3D12_ROOT_SIGNATURE_DESC root_description{};
    root_description.NumParameters = static_cast<UINT>(root_parameters.size());
    root_description.pParameters = root_parameters.data();
    ComPtr<ID3DBlob> serialized_root;
    ComPtr<ID3DBlob> root_errors;
    check_hr(D3D12SerializeRootSignature(&root_description, D3D_ROOT_SIGNATURE_VERSION_1,
                                          &serialized_root, &root_errors),
             "Serialize NaviPRISM phase-reservoir root signature failed");
    ComPtr<ID3D12RootSignature> root_signature;
    check_hr(device->CreateRootSignature(0, serialized_root->GetBufferPointer(),
                                          serialized_root->GetBufferSize(),
                                          IID_PPV_ARGS(&root_signature)),
             "Create NaviPRISM phase-reservoir root signature failed");

    const auto shader_path = executable_directory() / L"naviprism_phase_reservoir.dxil";
    auto shader = read_shader(shader_path);
    const auto shader_hash = sha256_hex(shader);
    D3D12_COMPUTE_PIPELINE_STATE_DESC pipeline_description{};
    pipeline_description.pRootSignature = root_signature.Get();
    pipeline_description.CS.pShaderBytecode = shader.data();
    pipeline_description.CS.BytecodeLength = shader.size();
    ComPtr<ID3D12PipelineState> pipeline;
    check_hr(device->CreateComputePipelineState(&pipeline_description, IID_PPV_ARGS(&pipeline)),
             "Create NaviPRISM phase-reservoir pipeline failed");

    ComPtr<ID3D12CommandAllocator> allocator;
    check_hr(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_COMPUTE,
                                             IID_PPV_ARGS(&allocator)),
             "Create NaviPRISM phase-reservoir allocator failed");
    ComPtr<ID3D12GraphicsCommandList> command_list;
    check_hr(device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_COMPUTE,
                                       allocator.Get(), nullptr,
                                       IID_PPV_ARGS(&command_list)),
             "Create NaviPRISM phase-reservoir command list failed");

    D3D12_QUERY_HEAP_DESC query_description{};
    query_description.Type = D3D12_QUERY_HEAP_TYPE_TIMESTAMP;
    query_description.Count = kPhrQueryCount;
    ComPtr<ID3D12QueryHeap> queries;
    check_hr(device->CreateQueryHeap(&query_description, IID_PPV_ARGS(&queries)),
             "Create NaviPRISM phase-reservoir query heap failed");
    ComPtr<ID3D12Resource> timestamp_readback;
    create_buffer(device.Get(), D3D12_HEAP_TYPE_READBACK,
                  kPhrQueryCount * sizeof(std::uint64_t),
                  D3D12_RESOURCE_STATE_COPY_DEST, timestamp_readback);

    command_list->SetPipelineState(pipeline.Get());
    command_list->SetComputeRootSignature(root_signature.Get());
    ID3D12DescriptorHeap* heaps[]{descriptor_heap.Get()};
    command_list->SetDescriptorHeaps(1, heaps);
    command_list->SetComputeRootDescriptorTable(
        0, descriptor_heap->GetGPUDescriptorHandleForHeapStart());
    const UINT groups_x = static_cast<UINT>((pixel_count + 63) / 64);
    for (UINT mode = 0; mode < kPhrModeCount; ++mode) {
        command_list->SetComputeRootConstantBufferView(
            1, constants_resources[mode]->GetGPUVirtualAddress());
        command_list->SetComputeRootUnorderedAccessView(
            2, outputs[mode]->GetGPUVirtualAddress());
        for (UINT run = 0; run < kPhrRunCount; ++run) {
            if (run != 0) {
                D3D12_RESOURCE_BARRIER barrier{};
                barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_UAV;
                barrier.UAV.pResource = outputs[mode].Get();
                command_list->ResourceBarrier(1, &barrier);
            }
            const UINT query = (mode * kPhrRunCount + run) * 2;
            command_list->EndQuery(queries.Get(), D3D12_QUERY_TYPE_TIMESTAMP, query);
            for (UINT repeat = 0; repeat < kPhrDispatchesPerSample; ++repeat) {
                command_list->Dispatch(groups_x, 1, 1);
                if (repeat + 1 < kPhrDispatchesPerSample) {
                    D3D12_RESOURCE_BARRIER barrier{};
                    barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_UAV;
                    barrier.UAV.pResource = outputs[mode].Get();
                    command_list->ResourceBarrier(1, &barrier);
                }
            }
            command_list->EndQuery(queries.Get(), D3D12_QUERY_TYPE_TIMESTAMP, query + 1);
        }
        D3D12_RESOURCE_BARRIER transition{};
        transition.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        transition.Transition.pResource = outputs[mode].Get();
        transition.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
        transition.Transition.StateBefore = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
        transition.Transition.StateAfter = D3D12_RESOURCE_STATE_COPY_SOURCE;
        command_list->ResourceBarrier(1, &transition);
        command_list->CopyBufferRegion(readbacks[mode].Get(), 0, outputs[mode].Get(),
                                       0, output_bytes);
    }
    command_list->ResolveQueryData(queries.Get(), D3D12_QUERY_TYPE_TIMESTAMP,
                                   0, kPhrQueryCount, timestamp_readback.Get(), 0);
    check_hr(command_list->Close(), "Close NaviPRISM phase-reservoir command list failed");
    ID3D12CommandList* lists[]{command_list.Get()};
    queue->ExecuteCommandLists(1, lists);

    ComPtr<ID3D12Fence> fence;
    check_hr(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)),
             "Create NaviPRISM phase-reservoir fence failed");
    check_hr(queue->Signal(fence.Get(), 1), "Signal NaviPRISM phase-reservoir fence failed");
    if (fence->GetCompletedValue() < 1) {
        HANDLE event_handle = CreateEventW(nullptr, FALSE, FALSE, nullptr);
        if (!event_handle) throw std::runtime_error("CreateEventW failed for NaviPRISM phase reservoir");
        const HRESULT event_result = fence->SetEventOnCompletion(1, event_handle);
        if (FAILED(event_result)) {
            CloseHandle(event_handle);
            check_hr(event_result, "Set NaviPRISM phase-reservoir fence event failed");
        }
        const DWORD wait_result = WaitForSingleObject(event_handle, 30000);
        CloseHandle(event_handle);
        if (wait_result != WAIT_OBJECT_0)
            throw std::runtime_error("Timed out waiting for NaviPRISM phase-reservoir dispatch");
    }

    std::array<std::vector<double>, kPhrModeCount> timings{};
    std::vector<std::uint64_t> timestamp_values(kPhrQueryCount);
    void* timestamp_mapping = nullptr;
    const D3D12_RANGE timestamp_range{0, timestamp_values.size() * sizeof(std::uint64_t)};
    check_hr(timestamp_readback->Map(0, &timestamp_range, &timestamp_mapping),
             "Map NaviPRISM phase-reservoir timestamps failed");
    std::memcpy(timestamp_values.data(), timestamp_mapping,
                timestamp_values.size() * sizeof(std::uint64_t));
    timestamp_readback->Unmap(0, nullptr);
    std::array<TimingSummary, kPhrModeCount> timing_summaries{};
    for (UINT mode = 0; mode < kPhrModeCount; ++mode) {
        for (UINT run = kPhrWarmupCount; run < kPhrRunCount; ++run) {
            const UINT query = (mode * kPhrRunCount + run) * 2;
            const auto begin = timestamp_values[query];
            const auto end = timestamp_values[query + 1];
            if (end < begin)
                throw std::runtime_error("NaviPRISM phase-reservoir timestamps are not monotonic");
            timings[mode].push_back(1.0e6 * static_cast<double>(end - begin)
                / (static_cast<double>(timestamp_frequency) * kPhrDispatchesPerSample));
        }
        timing_summaries[mode] = summarize(timings[mode]);
    }

    std::array<float, kPhrModeCount> max_color_error{};
    std::array<float, kPhrModeCount> max_confidence_error{};
    std::array<float, kPhrModeCount> max_depth_error{};
    std::array<std::uint32_t, kPhrModeCount> valid_entries{};
    for (UINT mode = 0; mode < kPhrModeCount; ++mode) {
        void* mapping = nullptr;
        const D3D12_RANGE output_range{0, static_cast<SIZE_T>(output_bytes)};
        check_hr(readbacks[mode]->Map(0, &output_range, &mapping),
                 "Map NaviPRISM phase-reservoir output failed");
        const auto* actual = static_cast<const PhrEntry*>(mapping);
        for (std::size_t index = 0; index < entry_count; ++index) {
            const auto& got = actual[index];
            const auto& want = expected[mode][index];
            if (got.valid != want.valid || got.age != want.age) {
                readbacks[mode]->Unmap(0, nullptr);
                throw std::runtime_error("NaviPRISM phase-reservoir validity/age differs from reference");
            }
            for (std::size_t channel = 0; channel < 3; ++channel) {
                max_color_error[mode] = (std::max)(max_color_error[mode],
                    std::abs(got.color[channel] - want.color[channel]));
            }
            max_confidence_error[mode] = (std::max)(max_confidence_error[mode],
                std::abs(got.confidence - want.confidence));
            max_depth_error[mode] = (std::max)(max_depth_error[mode],
                std::abs(got.depth - want.depth));
            if (got.valid != 0) ++valid_entries[mode];
        }
        readbacks[mode]->Unmap(0, nullptr);
        if (max_color_error[mode] > 1.0e-6F ||
            max_confidence_error[mode] > 1.0e-6F ||
            max_depth_error[mode] > 1.0e-6F) {
            throw std::runtime_error("NaviPRISM phase-reservoir GPU values differ from reference");
        }
    }

    if (!report_path.parent_path().empty())
        std::filesystem::create_directories(report_path.parent_path());
    std::ofstream report(report_path, std::ios::binary | std::ios::trunc);
    if (!report) throw std::runtime_error("Cannot write NaviPRISM phase-reservoir report: "
                                          + report_path.string());
    report << std::fixed << std::setprecision(6)
           << "{\n  \"gpu\": \"AMD Radeon RX 5700 XT\",\n"
           << "  \"pci_id\": \"1002:731F\",\n"
           << "  \"driver\": \"" << target_driver_version() << "\",\n"
           << "  \"shader_sha256\": \"" << shader_hash << "\",\n"
           << "  \"resolution\": [" << kPhrWidth << ", " << kPhrHeight << "],\n"
           << "  \"phase_count\": " << kPhrPhaseCount << ",\n"
           << "  \"color_samples_match_2x_hr_history\": true,\n"
           << "  \"reservoir_bytes\": " << output_bytes << ",\n"
           << "  \"warmup_samples\": " << kPhrWarmupCount << ",\n"
           << "  \"measured_samples\": " << kPhrMeasuredCount << ",\n"
           << "  \"dispatches_per_sample\": " << kPhrDispatchesPerSample << ",\n"
           << "  \"timestamp_frequency_hz\": " << timestamp_frequency << ",\n"
           << "  \"scenarios\": [\n";
    for (UINT mode = 0; mode < kPhrModeCount; ++mode) {
        report << "    {\"name\": \"" << (mode == 0 ? "reproject_update" : "scene_reset")
               << "\", \"reset\": " << (mode == 0 ? "false" : "true")
               << ", \"current_phase\": "
               << (mode == 0 ? kPhrCurrentPhase : kPhrResetPhase)
               << ", \"valid_entries\": " << valid_entries[mode]
               << ", \"max_color_error\": " << max_color_error[mode]
               << ", \"max_confidence_error\": " << max_confidence_error[mode]
               << ", \"max_depth_error\": " << max_depth_error[mode]
               << ", \"min_us\": " << timing_summaries[mode].minimum
               << ", \"median_us\": " << timing_summaries[mode].median
               << ", \"p90_us\": " << timing_summaries[mode].p90
               << ", \"p95_us\": " << timing_summaries[mode].p95
               << ", \"samples_us\": [";
        for (std::size_t sample = 0; sample < timings[mode].size(); ++sample) {
            if (sample != 0) report << ", ";
            report << timings[mode][sample];
        }
        report << "]}" << (mode + 1 == kPhrModeCount ? "\n" : ",\n");
    }
    report << "  ]\n}\n";
    if (!report) throw std::runtime_error("Failed while writing NaviPRISM phase-reservoir report");
    std::cout << "NaviPRISM phase-reservoir GPU/reference validation passed on RX 5700 XT.\n"
              << "  Reprojection/update valid entries: " << valid_entries[0]
              << "; reset/update valid entries: " << valid_entries[1] << ".\n"
              << "  Max RGB/confidence/depth errors: " << max_color_error[0] << "/"
              << max_confidence_error[0] << "/" << max_depth_error[0] << ".\n"
              << "  Reproject median " << timing_summaries[0].median << " us; reset median "
              << timing_summaries[1].median << " us for 13x9 input and 32 averaged dispatches.\n"
              << "  JSON report: " << report_path.string() << "; shader SHA-256 "
              << shader_hash << ".\n";
    return 0;
}

} // namespace fsr4n10
