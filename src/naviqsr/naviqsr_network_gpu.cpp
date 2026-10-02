#define NOMINMAX
#include "fsr4n10/naviqsr_gpu.h"

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>
#include <system_error>
#include <vector>
#include <wrl/client.h>

#include <Windows.h>
#include <d3d12.h>
#include <dxgi1_6.h>

namespace fsr4n10 {
namespace {

using Microsoft::WRL::ComPtr;

constexpr std::uint32_t kMaxLayers = 64;
constexpr UINT kGraphWarmups = 5;
constexpr UINT kGraphSamples = 20;
constexpr UINT kGraphRuns = kGraphWarmups + kGraphSamples;

#pragma pack(push, 1)
struct networkCaseHeader {
    char magic[8];
    std::uint32_t version;
    std::uint32_t width;
    std::uint32_t height;
    std::uint32_t input_channels;
    std::uint32_t width_channels;
    std::uint32_t hf_width;
    std::uint32_t layer_count;
    std::uint32_t packed_count;
    std::uint32_t features_count;
    std::uint32_t weights_count;
    std::uint32_t controls_count;
    std::uint32_t residual_count;
    std::uint32_t history_count;
    std::uint32_t output_count;
    std::uint32_t scale;
    std::uint32_t taps;
    float current_jitter_x;
    float current_jitter_y;
    float previous_jitter_x;
    float previous_jitter_y;
    float history_valid;
};

struct networkLayer {
    std::uint32_t operation;
    std::uint32_t source_a;
    std::uint32_t source_b;
    std::uint32_t output_id;
    std::uint32_t width;
    std::uint32_t height;
    std::uint32_t channels_a;
    std::uint32_t channels_b;
    std::uint32_t channels_out;
    std::uint32_t kernel;
    std::uint32_t weight_offset;
    std::uint32_t bias_offset;
    std::uint32_t relu;
    std::uint32_t residual;
};
#pragma pack(pop)
static_assert(sizeof(networkCaseHeader) == 92);
static_assert(sizeof(networkLayer) == 56);

struct networkCase {
    networkCaseHeader header{};
    std::vector<networkLayer> layers;
    std::vector<float> packed;
    std::vector<float> features;
    std::vector<std::uint16_t> weights;
    std::vector<float> reference_controls;
    std::vector<float> reference_residual;
    std::vector<float> history;
    std::vector<float> reference_output;
};

void check_hr(HRESULT result, const char* operation) {
    if (FAILED(result)) {
        throw std::system_error(static_cast<int>(result), std::system_category(), operation);
    }
}

D3D12_HEAP_PROPERTIES heap_properties(D3D12_HEAP_TYPE type) {
    D3D12_HEAP_PROPERTIES properties{};
    properties.Type = type;
    properties.CreationNodeMask = 1;
    properties.VisibleNodeMask = 1;
    return properties;
}

D3D12_RESOURCE_DESC buffer_description(std::uint64_t bytes,
                                      D3D12_RESOURCE_FLAGS flags = D3D12_RESOURCE_FLAG_NONE) {
    D3D12_RESOURCE_DESC description{};
    description.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
    description.Width = bytes;
    description.Height = 1;
    description.DepthOrArraySize = 1;
    description.MipLevels = 1;
    description.SampleDesc.Count = 1;
    description.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    description.Flags = flags;
    return description;
}

template<class T>
std::vector<T> read_array(std::istream& stream, std::size_t count, const char* name) {
    if (count > static_cast<std::size_t>((std::numeric_limits<std::streamsize>::max)()) / sizeof(T)) {
        throw std::runtime_error(std::string("NaviQSR network case array is too large: ") + name);
    }
    std::vector<T> values(count);
    const auto bytes = static_cast<std::streamsize>(count * sizeof(T));
    stream.read(reinterpret_cast<char*>(values.data()), bytes);
    if (stream.gcount() != bytes) {
        throw std::runtime_error(std::string("NaviQSR network case is truncated at ") + name);
    }
    return values;
}

struct Shape {
    std::uint32_t width;
    std::uint32_t height;
    std::uint32_t channels;
};

networkCase read_case(const std::filesystem::path& path) {
    std::error_code file_error;
    const auto file_size = std::filesystem::file_size(path, file_error);
    if (file_error || file_size > 128U * 1024U * 1024U) {
        throw std::runtime_error("NaviQSR network case is missing or exceeds the 128 MiB limit");
    }
    std::ifstream stream(path, std::ios::binary);
    if (!stream) throw std::runtime_error("cannot open NaviQSR network case: " + path.string());

    networkCase result{};
    stream.read(reinterpret_cast<char*>(&result.header), sizeof(result.header));
    if (stream.gcount() != static_cast<std::streamsize>(sizeof(result.header))) {
        throw std::runtime_error("NaviQSR network case header is truncated");
    }
    const auto& header = result.header;
    if (std::memcmp(header.magic, "NQSRFRM2", 8) != 0 || header.version != 2 ||
        header.width < 4 || header.height < 4 || (header.width & 1U) != 0 ||
        (header.height & 1U) != 0 || header.input_channels < 3 ||
        header.input_channels > 64 || header.width_channels < 4 ||
        header.width_channels > 256 || header.hf_width < 2 || header.hf_width > 128 ||
        header.scale < 2 || header.scale > 4 ||
        (header.taps != 4 && header.taps != 5 && header.taps != 8) ||
        !std::isfinite(header.current_jitter_x) || !std::isfinite(header.current_jitter_y) ||
        !std::isfinite(header.previous_jitter_x) || !std::isfinite(header.previous_jitter_y) ||
        !std::isfinite(header.history_valid) || header.history_valid < 0.0f ||
        header.history_valid > 1.0f ||
        header.layer_count < 6 || header.layer_count > kMaxLayers ||
        static_cast<std::uint64_t>(header.width) * header.height > 16U * 1024U * 1024U) {
        throw std::runtime_error("NaviQSR network case header values are invalid");
    }
    const std::size_t low_width = header.width / 2U;
    const std::size_t low_height = header.height / 2U;
    const std::size_t low_pixels = low_width * low_height;
    const std::size_t input_pixels = static_cast<std::size_t>(header.width) * header.height;
    const std::size_t expected_packed = static_cast<std::size_t>(header.input_channels) * 4U * low_pixels;
    const std::size_t expected_features = static_cast<std::size_t>(header.input_channels) * input_pixels;
    const std::size_t output_pixels = input_pixels * header.scale * header.scale;
    if (header.packed_count != expected_packed || header.features_count != expected_features ||
        header.weights_count == 0 || header.weights_count > 16U * 1024U * 1024U ||
        header.controls_count != 8U * low_pixels || header.residual_count != 3U * low_pixels ||
        header.history_count != 3U * output_pixels || header.output_count != 3U * output_pixels ||
        header.input_channels < 8) {
        throw std::runtime_error("NaviQSR network case tensor sizes do not match its dimensions");
    }
    const std::uint64_t expected_file_size = sizeof(networkCaseHeader)
        + static_cast<std::uint64_t>(header.layer_count) * sizeof(networkLayer)
        + static_cast<std::uint64_t>(header.packed_count) * sizeof(float)
        + static_cast<std::uint64_t>(header.features_count) * sizeof(float)
        + static_cast<std::uint64_t>(header.weights_count) * sizeof(std::uint16_t)
        + static_cast<std::uint64_t>(header.controls_count) * sizeof(float)
        + static_cast<std::uint64_t>(header.residual_count) * sizeof(float)
        + static_cast<std::uint64_t>(header.history_count) * sizeof(float)
        + static_cast<std::uint64_t>(header.output_count) * sizeof(float);
    if (expected_file_size != file_size) {
        throw std::runtime_error("NaviQSR network case byte size does not match its header");
    }

    result.layers = read_array<networkLayer>(stream, header.layer_count, "layer records");
    result.packed = read_array<float>(stream, header.packed_count, "packed input");
    result.features = read_array<float>(stream, header.features_count, "features");
    result.weights = read_array<std::uint16_t>(stream, header.weights_count, "FP16 weights");
    result.reference_controls = read_array<float>(stream, header.controls_count, "control reference");
    result.reference_residual = read_array<float>(stream, header.residual_count, "residual reference");
    result.history = read_array<float>(stream, header.history_count, "history input");
    result.reference_output = read_array<float>(stream, header.output_count, "RGB reference output");
    if (stream.peek() != std::char_traits<char>::eof()) {
        throw std::runtime_error("NaviQSR network case has unexpected trailing bytes");
    }

    for (const auto* values : {&result.packed, &result.features,
                               &result.reference_controls, &result.reference_residual,
                               &result.history, &result.reference_output}) {
        if (!std::all_of(values->begin(), values->end(),
                         [](float value) { return std::isfinite(value); })) {
            throw std::runtime_error("NaviQSR network case contains NaN or infinity");
        }
    }

    std::vector<Shape> sources{{static_cast<std::uint32_t>(low_width),
                                static_cast<std::uint32_t>(low_height),
                                header.input_channels * 4U},
                               {header.width, header.height, header.input_channels}};
    for (std::size_t index = 0; index < result.layers.size(); ++index) {
        const auto& layer = result.layers[index];
        if (layer.output_id != index || layer.channels_out == 0 ||
            layer.width == 0 || layer.height == 0 ||
            layer.width > header.width || layer.height > header.height ||
            layer.source_a >= sources.size() || layer.source_b >= sources.size() ||
            layer.width != sources[layer.source_a].width ||
            layer.height != sources[layer.source_a].height ||
            layer.channels_a != sources[layer.source_a].channels ||
            layer.width * static_cast<std::uint64_t>(layer.height) * layer.channels_out >
                65535U * 64U) {
            throw std::runtime_error("NaviQSR network layer has an invalid shape or source");
        }
        if (layer.operation == 0) {
            const std::uint64_t expected_weights = static_cast<std::uint64_t>(layer.channels_out)
                * layer.channels_a * layer.kernel * layer.kernel;
            if ((layer.kernel != 1 && layer.kernel != 3) || layer.channels_b != 0 ||
                layer.source_b != layer.source_a || layer.relu > 1 || layer.residual > 1 ||
                (layer.residual != 0 && layer.channels_a != layer.channels_out) ||
                expected_weights > header.weights_count ||
                layer.weight_offset + expected_weights > header.weights_count ||
                layer.bias_offset != layer.weight_offset + expected_weights ||
                layer.bias_offset + layer.channels_out > header.weights_count) {
                throw std::runtime_error("NaviQSR network convolution record is invalid");
            }
        } else if (layer.operation == 1) {
            if (layer.source_b >= sources.size() || layer.source_b == layer.source_a ||
                layer.channels_b != sources[layer.source_b].channels ||
                sources[layer.source_b].width != layer.width * 2U ||
                sources[layer.source_b].height != layer.height * 2U ||
                layer.channels_out != layer.channels_a + layer.channels_b ||
                layer.kernel != 0 || layer.weight_offset != 0 || layer.bias_offset != 0 ||
                layer.relu != 0 || layer.residual != 0) {
                throw std::runtime_error("NaviQSR network pool/concat record is invalid");
            }
        } else {
            throw std::runtime_error("NaviQSR network case uses an unknown layer operation");
        }
        sources.push_back({layer.width, layer.height, layer.channels_out});
    }
    if (result.layers[result.layers.size() - 2U].channels_out != 8 ||
        result.layers.back().channels_out != 3 ||
        result.layers[result.layers.size() - 2U].width != low_width ||
        result.layers[result.layers.size() - 2U].height != low_height ||
        result.layers.back().width != low_width || result.layers.back().height != low_height) {
        throw std::runtime_error("NaviQSR network case does not end in 8 control and 3 residual channels");
    }
    return result;
}

struct UploadedBuffer {
    ComPtr<ID3D12Resource> resource;
    ComPtr<ID3D12Resource> upload;
    std::uint64_t bytes{};
};

UploadedBuffer upload_buffer(ID3D12Device* device,
                             ID3D12GraphicsCommandList* command_list,
                             const void* data, std::size_t bytes) {
    if (bytes == 0) throw std::runtime_error("cannot upload an empty NaviQSR buffer");
    UploadedBuffer result{};
    result.bytes = bytes;
    const auto default_heap = heap_properties(D3D12_HEAP_TYPE_DEFAULT);
    const auto description = buffer_description(bytes);
    check_hr(device->CreateCommittedResource(&default_heap, D3D12_HEAP_FLAG_NONE,
                                              &description, D3D12_RESOURCE_STATE_COPY_DEST,
                                              nullptr, IID_PPV_ARGS(&result.resource)),
             "Create NaviQSR network input buffer failed");
    const auto upload_heap = heap_properties(D3D12_HEAP_TYPE_UPLOAD);
    const auto upload_description = buffer_description(bytes);
    check_hr(device->CreateCommittedResource(&upload_heap, D3D12_HEAP_FLAG_NONE,
                                              &upload_description, D3D12_RESOURCE_STATE_GENERIC_READ,
                                              nullptr, IID_PPV_ARGS(&result.upload)),
             "Create NaviQSR network upload buffer failed");
    void* mapped = nullptr;
    const D3D12_RANGE no_read{0, 0};
    check_hr(result.upload->Map(0, &no_read, &mapped), "Map NaviQSR network upload failed");
    std::memcpy(mapped, data, bytes);
    result.upload->Unmap(0, nullptr);
    command_list->CopyBufferRegion(result.resource.Get(), 0, result.upload.Get(), 0, bytes);
    D3D12_RESOURCE_BARRIER barrier{};
    barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    barrier.Transition.pResource = result.resource.Get();
    barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_COPY_DEST;
    barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
    command_list->ResourceBarrier(1, &barrier);
    return result;
}

ComPtr<ID3D12Resource> create_output_buffer(ID3D12Device* device, std::size_t bytes) {
    const auto heap = heap_properties(D3D12_HEAP_TYPE_DEFAULT);
    const auto description = buffer_description(bytes, D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS);
    ComPtr<ID3D12Resource> output;
    check_hr(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &description,
                                              D3D12_RESOURCE_STATE_UNORDERED_ACCESS, nullptr,
                                              IID_PPV_ARGS(&output)),
             "Create NaviQSR network output buffer failed");
    return output;
}

void create_structured_srv(ID3D12Device* device, ID3D12Resource* resource,
                           std::size_t bytes, std::uint32_t stride,
                           D3D12_CPU_DESCRIPTOR_HANDLE handle) {
    if (bytes % stride != 0 || bytes / stride > (std::numeric_limits<UINT>::max)()) {
        throw std::runtime_error("NaviQSR network SRV range is invalid");
    }
    D3D12_SHADER_RESOURCE_VIEW_DESC description{};
    description.Format = DXGI_FORMAT_UNKNOWN;
    description.ViewDimension = D3D12_SRV_DIMENSION_BUFFER;
    description.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
    description.Buffer.NumElements = static_cast<UINT>(bytes / stride);
    description.Buffer.StructureByteStride = stride;
    device->CreateShaderResourceView(resource, &description, handle);
}

void create_structured_uav(ID3D12Device* device, ID3D12Resource* resource,
                           std::size_t bytes, std::uint32_t stride,
                           D3D12_CPU_DESCRIPTOR_HANDLE handle) {
    if (bytes % stride != 0 || bytes / stride > (std::numeric_limits<UINT>::max)()) {
        throw std::runtime_error("NaviQSR network UAV range is invalid");
    }
    D3D12_UNORDERED_ACCESS_VIEW_DESC description{};
    description.Format = DXGI_FORMAT_UNKNOWN;
    description.ViewDimension = D3D12_UAV_DIMENSION_BUFFER;
    description.Buffer.NumElements = static_cast<UINT>(bytes / stride);
    description.Buffer.StructureByteStride = stride;
    device->CreateUnorderedAccessView(resource, nullptr, &description, handle);
}

void create_raw_srv(ID3D12Device* device, ID3D12Resource* resource,
                    std::size_t bytes, D3D12_CPU_DESCRIPTOR_HANDLE handle) {
    if (bytes == 0 || bytes % 4U != 0 || bytes / 4U > (std::numeric_limits<UINT>::max)()) {
        throw std::runtime_error("NaviQSR network raw weight SRV range is invalid");
    }
    D3D12_SHADER_RESOURCE_VIEW_DESC description{};
    description.Format = DXGI_FORMAT_R32_TYPELESS;
    description.ViewDimension = D3D12_SRV_DIMENSION_BUFFER;
    description.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
    description.Buffer.NumElements = static_cast<UINT>(bytes / 4U);
    description.Buffer.Flags = D3D12_BUFFER_SRV_FLAG_RAW;
    device->CreateShaderResourceView(resource, &description, handle);
}

ComPtr<ID3D12Device> create_target_device() {
    ComPtr<IDXGIFactory6> factory;
    check_hr(CreateDXGIFactory2(0, IID_PPV_ARGS(&factory)),
             "CreateDXGIFactory2 for NaviQSR network failed");
    for (UINT index = 0;; ++index) {
        ComPtr<IDXGIAdapter1> adapter;
        const HRESULT result = factory->EnumAdapters1(index, &adapter);
        if (result == DXGI_ERROR_NOT_FOUND) break;
        check_hr(result, "Enumerate adapter for NaviQSR network failed");
        DXGI_ADAPTER_DESC1 description{};
        check_hr(adapter->GetDesc1(&description), "Get NaviQSR network adapter description failed");
        if (description.VendorId != 0x1002 || description.DeviceId != 0x731F ||
            (description.Flags & DXGI_ADAPTER_FLAG_SOFTWARE) != 0) continue;
        ComPtr<ID3D12Device> device;
        check_hr(D3D12CreateDevice(adapter.Get(), D3D_FEATURE_LEVEL_11_0,
                                   IID_PPV_ARGS(&device)),
                 "Create RX 5700 XT D3D12 device for NaviQSR network failed");
        return device;
    }
    throw std::runtime_error("RX 5700 XT (PCI 1002:731F) was not found");
}

std::vector<std::byte> read_shader(const std::filesystem::path& path) {
    std::ifstream stream(path, std::ios::binary | std::ios::ate);
    if (!stream) throw std::runtime_error("cannot open NaviQSR network DXIL: " + path.string());
    const auto size = stream.tellg();
    if (size <= 0) throw std::runtime_error("NaviQSR network DXIL is empty");
    std::vector<std::byte> result(static_cast<std::size_t>(size));
    stream.seekg(0);
    stream.read(reinterpret_cast<char*>(result.data()), static_cast<std::streamsize>(result.size()));
    if (!stream) throw std::runtime_error("failed to read NaviQSR network DXIL");
    return result;
}

} // namespace

int run_naviqsr_network_gpu_smoke(const std::filesystem::path& case_path) {
    const auto network_case = read_case(case_path);
    const auto& header = network_case.header;
    ComPtr<ID3D12Device> device = create_target_device();
    ComPtr<ID3D12CommandQueue> queue;
    D3D12_COMMAND_QUEUE_DESC queue_description{};
    queue_description.Type = D3D12_COMMAND_LIST_TYPE_COMPUTE;
    check_hr(device->CreateCommandQueue(&queue_description, IID_PPV_ARGS(&queue)),
             "Create NaviQSR network compute queue failed");
    ComPtr<ID3D12CommandAllocator> allocator;
    check_hr(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_COMPUTE,
                                             IID_PPV_ARGS(&allocator)),
             "Create NaviQSR network command allocator failed");
    ComPtr<ID3D12GraphicsCommandList> command_list;
    check_hr(device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_COMPUTE,
                                      allocator.Get(), nullptr, IID_PPV_ARGS(&command_list)),
             "Create NaviQSR network command list failed");

    auto packed = upload_buffer(device.Get(), command_list.Get(), network_case.packed.data(),
                                network_case.packed.size() * sizeof(float));
    auto features = upload_buffer(device.Get(), command_list.Get(), network_case.features.data(),
                                  network_case.features.size() * sizeof(float));
    auto weights = upload_buffer(device.Get(), command_list.Get(), network_case.weights.data(),
                                 network_case.weights.size() * sizeof(std::uint16_t));
    auto history = upload_buffer(device.Get(), command_list.Get(), network_case.history.data(),
                                 network_case.history.size() * sizeof(float));

    std::vector<ComPtr<ID3D12Resource>> outputs;
    std::vector<std::size_t> output_bytes;
    outputs.reserve(network_case.layers.size());
    output_bytes.reserve(network_case.layers.size());
    for (const auto& layer : network_case.layers) {
        const std::size_t bytes = static_cast<std::size_t>(layer.width) * layer.height
                                * layer.channels_out * sizeof(float);
        output_bytes.push_back(bytes);
        outputs.push_back(create_output_buffer(device.Get(), bytes));
    }
    const std::size_t controls_index = network_case.layers.size() - 2U;
    const std::size_t residual_index = network_case.layers.size() - 1U;
    const std::size_t frame_output_bytes = network_case.reference_output.size() * sizeof(float);
    auto frame_output = create_output_buffer(device.Get(), frame_output_bytes);

    D3D12_DESCRIPTOR_HEAP_DESC descriptor_description{};
    descriptor_description.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
    descriptor_description.NumDescriptors = static_cast<UINT>(network_case.layers.size() * 4U);
    descriptor_description.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
    ComPtr<ID3D12DescriptorHeap> descriptor_heap;
    check_hr(device->CreateDescriptorHeap(&descriptor_description,
                                         IID_PPV_ARGS(&descriptor_heap)),
             "Create NaviQSR network descriptor heap failed");
    const UINT descriptor_increment = device->GetDescriptorHandleIncrementSize(
        D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);

    auto source_resource = [&](std::uint32_t source) -> ID3D12Resource* {
        if (source == 0) return packed.resource.Get();
        if (source == 1) return features.resource.Get();
        return outputs.at(source - 2U).Get();
    };
    auto source_bytes = [&](std::uint32_t source) -> std::size_t {
        if (source == 0) return packed.bytes;
        if (source == 1) return features.bytes;
        return output_bytes.at(source - 2U);
    };

    auto cpu_handle = descriptor_heap->GetCPUDescriptorHandleForHeapStart();
    for (std::size_t index = 0; index < network_case.layers.size(); ++index) {
        const auto& layer = network_case.layers[index];
        create_structured_srv(device.Get(), source_resource(layer.source_a),
                              source_bytes(layer.source_a), sizeof(float), cpu_handle);
        cpu_handle.ptr += descriptor_increment;
        create_structured_srv(device.Get(), source_resource(layer.source_b),
                              source_bytes(layer.source_b), sizeof(float), cpu_handle);
        cpu_handle.ptr += descriptor_increment;
        create_raw_srv(device.Get(), weights.resource.Get(), weights.bytes, cpu_handle);
        cpu_handle.ptr += descriptor_increment;
        create_structured_uav(device.Get(), outputs[index].Get(), output_bytes[index],
                              sizeof(float), cpu_handle);
        cpu_handle.ptr += descriptor_increment;
    }

    D3D12_DESCRIPTOR_RANGE srv_range{};
    srv_range.RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_SRV;
    srv_range.NumDescriptors = 3;
    srv_range.BaseShaderRegister = 0;
    srv_range.OffsetInDescriptorsFromTableStart = D3D12_DESCRIPTOR_RANGE_OFFSET_APPEND;
    D3D12_DESCRIPTOR_RANGE uav_range{};
    uav_range.RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_UAV;
    uav_range.NumDescriptors = 1;
    uav_range.BaseShaderRegister = 0;
    uav_range.OffsetInDescriptorsFromTableStart = D3D12_DESCRIPTOR_RANGE_OFFSET_APPEND;
    std::array<D3D12_ROOT_PARAMETER, 3> root_parameters{};
    root_parameters[0].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
    root_parameters[0].DescriptorTable.NumDescriptorRanges = 1;
    root_parameters[0].DescriptorTable.pDescriptorRanges = &srv_range;
    root_parameters[0].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
    root_parameters[1].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
    root_parameters[1].DescriptorTable.NumDescriptorRanges = 1;
    root_parameters[1].DescriptorTable.pDescriptorRanges = &uav_range;
    root_parameters[1].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
    root_parameters[2].ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
    root_parameters[2].Constants.Num32BitValues = 14;
    root_parameters[2].Constants.ShaderRegister = 0;
    root_parameters[2].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
    D3D12_ROOT_SIGNATURE_DESC root_description{};
    root_description.NumParameters = static_cast<UINT>(root_parameters.size());
    root_description.pParameters = root_parameters.data();
    ComPtr<ID3DBlob> serialized_root;
    ComPtr<ID3DBlob> root_errors;
    check_hr(D3D12SerializeRootSignature(&root_description, D3D_ROOT_SIGNATURE_VERSION_1,
                                          &serialized_root, &root_errors),
             "Serialize NaviQSR network root signature failed");
    ComPtr<ID3D12RootSignature> root_signature;
    check_hr(device->CreateRootSignature(0, serialized_root->GetBufferPointer(),
                                         serialized_root->GetBufferSize(),
                                         IID_PPV_ARGS(&root_signature)),
             "Create NaviQSR network root signature failed");

    std::array<wchar_t, 32768> executable_path{};
    const DWORD path_length = GetModuleFileNameW(nullptr, executable_path.data(),
                                                 static_cast<DWORD>(executable_path.size()));
    if (path_length == 0 || path_length >= static_cast<DWORD>(executable_path.size())) {
        throw std::system_error(static_cast<int>(GetLastError()), std::system_category(),
                                "GetModuleFileNameW for NaviQSR network failed");
    }
    const auto shader_path = std::filesystem::path(executable_path.data()).parent_path()
                           / L"naviqsr_network_conv.dxil";
    const auto shader = read_shader(shader_path);
    D3D12_COMPUTE_PIPELINE_STATE_DESC pipeline_description{};
    pipeline_description.pRootSignature = root_signature.Get();
    pipeline_description.CS = {shader.data(), shader.size()};
    ComPtr<ID3D12PipelineState> pipeline;
    check_hr(device->CreateComputePipelineState(&pipeline_description, IID_PPV_ARGS(&pipeline)),
             "Create NaviQSR network convolution pipeline failed");

    D3D12_DESCRIPTOR_HEAP_DESC analytic_heap_description{};
    analytic_heap_description.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
    analytic_heap_description.NumDescriptors = 5;
    analytic_heap_description.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
    ComPtr<ID3D12DescriptorHeap> analytic_heap;
    check_hr(device->CreateDescriptorHeap(&analytic_heap_description,
                                         IID_PPV_ARGS(&analytic_heap)),
             "Create NaviQSR integrated analytic descriptor heap failed");
    auto analytic_cpu = analytic_heap->GetCPUDescriptorHandleForHeapStart();
    create_structured_srv(device.Get(), features.resource.Get(), features.bytes,
                          sizeof(float), analytic_cpu);
    analytic_cpu.ptr += descriptor_increment;
    create_structured_srv(device.Get(), outputs[controls_index].Get(),
                          output_bytes[controls_index], sizeof(float), analytic_cpu);
    analytic_cpu.ptr += descriptor_increment;
    create_structured_srv(device.Get(), outputs[residual_index].Get(),
                          output_bytes[residual_index], sizeof(float), analytic_cpu);
    analytic_cpu.ptr += descriptor_increment;
    create_structured_srv(device.Get(), history.resource.Get(), history.bytes,
                          sizeof(float), analytic_cpu);
    analytic_cpu.ptr += descriptor_increment;
    create_structured_uav(device.Get(), frame_output.Get(), frame_output_bytes,
                          sizeof(float), analytic_cpu);

    D3D12_DESCRIPTOR_RANGE analytic_srv_range{};
    analytic_srv_range.RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_SRV;
    analytic_srv_range.NumDescriptors = 4;
    analytic_srv_range.BaseShaderRegister = 0;
    analytic_srv_range.OffsetInDescriptorsFromTableStart = D3D12_DESCRIPTOR_RANGE_OFFSET_APPEND;
    D3D12_DESCRIPTOR_RANGE analytic_uav_range{};
    analytic_uav_range.RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_UAV;
    analytic_uav_range.NumDescriptors = 1;
    analytic_uav_range.BaseShaderRegister = 0;
    analytic_uav_range.OffsetInDescriptorsFromTableStart = D3D12_DESCRIPTOR_RANGE_OFFSET_APPEND;
    std::array<D3D12_ROOT_PARAMETER, 3> analytic_root_parameters{};
    analytic_root_parameters[0].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
    analytic_root_parameters[0].DescriptorTable.NumDescriptorRanges = 1;
    analytic_root_parameters[0].DescriptorTable.pDescriptorRanges = &analytic_srv_range;
    analytic_root_parameters[0].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
    analytic_root_parameters[1].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
    analytic_root_parameters[1].DescriptorTable.NumDescriptorRanges = 1;
    analytic_root_parameters[1].DescriptorTable.pDescriptorRanges = &analytic_uav_range;
    analytic_root_parameters[1].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
    analytic_root_parameters[2].ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
    analytic_root_parameters[2].Constants.Num32BitValues = 12;
    analytic_root_parameters[2].Constants.ShaderRegister = 0;
    analytic_root_parameters[2].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
    D3D12_ROOT_SIGNATURE_DESC analytic_root_description{};
    analytic_root_description.NumParameters = static_cast<UINT>(analytic_root_parameters.size());
    analytic_root_description.pParameters = analytic_root_parameters.data();
    ComPtr<ID3DBlob> analytic_serialized_root;
    ComPtr<ID3DBlob> analytic_root_errors;
    check_hr(D3D12SerializeRootSignature(&analytic_root_description,
                                          D3D_ROOT_SIGNATURE_VERSION_1,
                                          &analytic_serialized_root, &analytic_root_errors),
             "Serialize NaviQSR integrated analytic root signature failed");
    ComPtr<ID3D12RootSignature> analytic_root_signature;
    check_hr(device->CreateRootSignature(0, analytic_serialized_root->GetBufferPointer(),
                                         analytic_serialized_root->GetBufferSize(),
                                         IID_PPV_ARGS(&analytic_root_signature)),
             "Create NaviQSR integrated analytic root signature failed");
    const std::wstring analytic_shader_name = L"naviqsr_network_analytic_"
        + std::to_wstring(header.taps) + L"tap.dxil";
    const auto analytic_shader_path = std::filesystem::path(executable_path.data()).parent_path()
                                    / analytic_shader_name;
    const auto analytic_shader = read_shader(analytic_shader_path);
    D3D12_COMPUTE_PIPELINE_STATE_DESC analytic_pipeline_description{};
    analytic_pipeline_description.pRootSignature = analytic_root_signature.Get();
    analytic_pipeline_description.CS = {analytic_shader.data(), analytic_shader.size()};
    ComPtr<ID3D12PipelineState> analytic_pipeline;
    check_hr(device->CreateComputePipelineState(&analytic_pipeline_description,
                                                IID_PPV_ARGS(&analytic_pipeline)),
             "Create NaviQSR integrated analytic pipeline failed");

    D3D12_QUERY_HEAP_DESC query_description{};
    query_description.Type = D3D12_QUERY_HEAP_TYPE_TIMESTAMP;
    query_description.Count = kGraphRuns * 3U;
    ComPtr<ID3D12QueryHeap> timestamp_queries;
    check_hr(device->CreateQueryHeap(&query_description, IID_PPV_ARGS(&timestamp_queries)),
             "Create NaviQSR network timestamp query heap failed");
    const auto timestamp_buffer_description = buffer_description(
        static_cast<std::uint64_t>(query_description.Count) * sizeof(std::uint64_t));
    const auto timestamp_readback_heap = heap_properties(D3D12_HEAP_TYPE_READBACK);
    ComPtr<ID3D12Resource> timestamp_readback;
    check_hr(device->CreateCommittedResource(&timestamp_readback_heap, D3D12_HEAP_FLAG_NONE,
                                              &timestamp_buffer_description,
                                              D3D12_RESOURCE_STATE_COPY_DEST, nullptr,
                                              IID_PPV_ARGS(&timestamp_readback)),
             "Create NaviQSR network timestamp readback failed");
    UINT64 timestamp_frequency = 0;
    check_hr(queue->GetTimestampFrequency(&timestamp_frequency),
             "Get NaviQSR network timestamp frequency failed");
    if (timestamp_frequency == 0) {
        throw std::runtime_error("NaviQSR network queue returned zero timestamp frequency");
    }

    ID3D12DescriptorHeap* network_heaps[] = {descriptor_heap.Get()};
    ID3D12DescriptorHeap* analytic_heaps[] = {analytic_heap.Get()};
    const auto gpu_start = descriptor_heap->GetGPUDescriptorHandleForHeapStart();
    const auto analytic_gpu_start = analytic_heap->GetGPUDescriptorHandleForHeapStart();
    for (UINT run = 0; run < kGraphRuns; ++run) {
        if (run != 0) {
            for (const auto& output : outputs) {
                D3D12_RESOURCE_BARRIER reset_barrier{};
                reset_barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
                reset_barrier.Transition.pResource = output.Get();
                reset_barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
                reset_barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
                reset_barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
                command_list->ResourceBarrier(1, &reset_barrier);
            }
            D3D12_RESOURCE_BARRIER frame_reset{};
            frame_reset.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
            frame_reset.Transition.pResource = frame_output.Get();
            frame_reset.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
            frame_reset.Transition.StateBefore = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
            frame_reset.Transition.StateAfter = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
            command_list->ResourceBarrier(1, &frame_reset);
        }
        command_list->SetDescriptorHeaps(1, network_heaps);
        command_list->SetComputeRootSignature(root_signature.Get());
        command_list->SetPipelineState(pipeline.Get());
        command_list->EndQuery(timestamp_queries.Get(), D3D12_QUERY_TYPE_TIMESTAMP, run * 3U);
        for (std::size_t index = 0; index < network_case.layers.size(); ++index) {
            const auto& layer = network_case.layers[index];
            D3D12_GPU_DESCRIPTOR_HANDLE srv_handle = gpu_start;
            srv_handle.ptr += static_cast<UINT64>(index * 4U) * descriptor_increment;
            D3D12_GPU_DESCRIPTOR_HANDLE uav_handle = srv_handle;
            uav_handle.ptr += static_cast<UINT64>(3U) * descriptor_increment;
            command_list->SetComputeRootDescriptorTable(0, srv_handle);
            command_list->SetComputeRootDescriptorTable(1, uav_handle);
            const std::array<std::uint32_t, 14> constants{
                layer.operation, layer.width, layer.height, layer.channels_a,
                layer.channels_b, layer.channels_out, layer.kernel,
                layer.weight_offset, layer.bias_offset, layer.relu, layer.residual,
                0U, layer.operation == 1 ? layer.width * 2U : layer.width,
                layer.operation == 1 ? layer.height * 2U : layer.height};
            command_list->SetComputeRoot32BitConstants(2, static_cast<UINT>(constants.size()),
                                                        constants.data(), 0);
            const std::uint64_t element_count = static_cast<std::uint64_t>(layer.width)
                                              * layer.height * layer.channels_out;
            command_list->Dispatch(static_cast<UINT>((element_count + 63U) / 64U), 1, 1);
            D3D12_RESOURCE_BARRIER barrier{};
            barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
            barrier.Transition.pResource = outputs[index].Get();
            barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
            barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
            barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
            command_list->ResourceBarrier(1, &barrier);
        }
        command_list->EndQuery(timestamp_queries.Get(), D3D12_QUERY_TYPE_TIMESTAMP,
                               run * 3U + 1U);

        command_list->SetDescriptorHeaps(1, analytic_heaps);
        command_list->SetComputeRootSignature(analytic_root_signature.Get());
        command_list->SetPipelineState(analytic_pipeline.Get());
        D3D12_GPU_DESCRIPTOR_HANDLE analytic_uav = analytic_gpu_start;
        analytic_uav.ptr += static_cast<UINT64>(4U) * descriptor_increment;
        command_list->SetComputeRootDescriptorTable(0, analytic_gpu_start);
        command_list->SetComputeRootDescriptorTable(1, analytic_uav);
        const std::array<std::uint32_t, 12> analytic_constants{
            header.width, header.height, header.scale,
            header.width * header.scale, header.height * header.scale,
            header.taps, std::bit_cast<std::uint32_t>(header.history_valid), 0U,
            std::bit_cast<std::uint32_t>(header.current_jitter_x),
            std::bit_cast<std::uint32_t>(header.current_jitter_y),
            std::bit_cast<std::uint32_t>(header.previous_jitter_x),
            std::bit_cast<std::uint32_t>(header.previous_jitter_y)};
        command_list->SetComputeRoot32BitConstants(2,
            static_cast<UINT>(analytic_constants.size()), analytic_constants.data(), 0);
        const std::uint64_t output_pixels = static_cast<std::uint64_t>(header.width)
            * header.height * header.scale * header.scale;
        command_list->Dispatch(static_cast<UINT>((output_pixels + 63U) / 64U), 1, 1);
        D3D12_RESOURCE_BARRIER analytic_output_barrier{};
        analytic_output_barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        analytic_output_barrier.Transition.pResource = frame_output.Get();
        analytic_output_barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
        analytic_output_barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
        analytic_output_barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
        command_list->ResourceBarrier(1, &analytic_output_barrier);
        command_list->EndQuery(timestamp_queries.Get(), D3D12_QUERY_TYPE_TIMESTAMP,
                               run * 3U + 2U);
    }

    auto transition_to_copy = [&](ID3D12Resource* resource) {
        D3D12_RESOURCE_BARRIER barrier{};
        barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        barrier.Transition.pResource = resource;
        barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
        barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
        barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_COPY_SOURCE;
        command_list->ResourceBarrier(1, &barrier);
    };
    transition_to_copy(outputs[controls_index].Get());
    transition_to_copy(outputs[residual_index].Get());
    transition_to_copy(frame_output.Get());
    const std::uint64_t control_bytes = network_case.reference_controls.size() * sizeof(float);
    const std::uint64_t residual_bytes = network_case.reference_residual.size() * sizeof(float);
    const std::uint64_t frame_bytes = network_case.reference_output.size() * sizeof(float);
    const std::uint64_t readback_bytes = control_bytes + residual_bytes + frame_bytes;
    const auto readback_heap = heap_properties(D3D12_HEAP_TYPE_READBACK);
    const auto readback_description = buffer_description(readback_bytes);
    ComPtr<ID3D12Resource> readback;
    check_hr(device->CreateCommittedResource(&readback_heap, D3D12_HEAP_FLAG_NONE,
                                              &readback_description,
                                              D3D12_RESOURCE_STATE_COPY_DEST, nullptr,
                                              IID_PPV_ARGS(&readback)),
             "Create NaviQSR network readback failed");
    command_list->CopyBufferRegion(readback.Get(), 0, outputs[controls_index].Get(), 0,
                                   control_bytes);
    command_list->CopyBufferRegion(readback.Get(), control_bytes,
                                   outputs[residual_index].Get(), 0, residual_bytes);
    command_list->CopyBufferRegion(readback.Get(), control_bytes + residual_bytes,
                                   frame_output.Get(), 0, frame_bytes);
    command_list->ResolveQueryData(timestamp_queries.Get(), D3D12_QUERY_TYPE_TIMESTAMP,
                                   0, query_description.Count, timestamp_readback.Get(), 0);
    check_hr(command_list->Close(), "Close NaviQSR network command list failed");

    ID3D12CommandList* command_lists[] = {command_list.Get()};
    queue->ExecuteCommandLists(1, command_lists);
    ComPtr<ID3D12Fence> fence;
    check_hr(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)),
             "Create NaviQSR network fence failed");
    check_hr(queue->Signal(fence.Get(), 1), "Signal NaviQSR network fence failed");
    HANDLE event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    if (event == nullptr) {
        throw std::system_error(static_cast<int>(GetLastError()), std::system_category(),
                                "Create NaviQSR network fence event failed");
    }
    const auto close_event = std::unique_ptr<void, decltype(&CloseHandle)>(event, &CloseHandle);
    check_hr(fence->SetEventOnCompletion(1, event),
             "Set NaviQSR network fence event failed");
    if (WaitForSingleObject(event, 30000) != WAIT_OBJECT_0) {
        throw std::runtime_error("Timed out waiting for NaviQSR network GPU inference");
    }

    std::array<std::uint64_t, kGraphRuns * 3U> timestamps{};
    void* timestamp_mapped = nullptr;
    const D3D12_RANGE timestamp_range{0, sizeof(timestamps)};
    check_hr(timestamp_readback->Map(0, &timestamp_range, &timestamp_mapped),
             "Map NaviQSR network timestamps failed");
    std::memcpy(timestamps.data(), timestamp_mapped, sizeof(timestamps));
    timestamp_readback->Unmap(0, nullptr);
    std::vector<double> network_times_us;
    std::vector<double> frame_times_us;
    network_times_us.reserve(kGraphSamples);
    frame_times_us.reserve(kGraphSamples);
    for (UINT run = kGraphWarmups; run < kGraphRuns; ++run) {
        const auto begin = timestamps[run * 3U];
        const auto network_end = timestamps[run * 3U + 1U];
        const auto frame_end = timestamps[run * 3U + 2U];
        if (network_end < begin || frame_end < network_end) {
            throw std::runtime_error("NaviQSR GPU frame timestamps are not monotonic");
        }
        network_times_us.push_back(1.0e6 * static_cast<double>(network_end - begin)
                                   / static_cast<double>(timestamp_frequency));
        frame_times_us.push_back(1.0e6 * static_cast<double>(frame_end - begin)
                                 / static_cast<double>(timestamp_frequency));
    }
    auto summarize = [](std::vector<double>& values) {
        std::sort(values.begin(), values.end());
        return std::array<double, 4>{values.front(), (values[9] + values[10]) * 0.5,
                                     values[17], values[18]};
    };
    const auto network_timing = summarize(network_times_us);
    const auto frame_timing = summarize(frame_times_us);

    void* mapped = nullptr;
    const D3D12_RANGE read_range{0, static_cast<SIZE_T>(readback_bytes)};
    check_hr(readback->Map(0, &read_range, &mapped), "Map NaviQSR network output failed");
    const auto* actual = static_cast<const float*>(mapped);
    std::vector<float> actual_controls(actual, actual + network_case.reference_controls.size());
    std::vector<float> actual_residual(actual + network_case.reference_controls.size(),
                                       actual + network_case.reference_controls.size()
                                           + network_case.reference_residual.size());
    const auto image_begin = actual + network_case.reference_controls.size()
                           + network_case.reference_residual.size();
    std::vector<float> actual_image(image_begin,
                                    image_begin + network_case.reference_output.size());
    readback->Unmap(0, nullptr);

    auto measure_error = [&](const std::vector<float>& actual_values,
                             const std::vector<float>& expected_values,
                             const char* name) {
        float maximum_error = 0.0f;
        double error_sum = 0.0;
        for (std::size_t index = 0; index < actual_values.size(); ++index) {
            if (!std::isfinite(actual_values[index])) {
                throw std::runtime_error(std::string("NaviQSR GPU output contains NaN or infinity: ")
                                         + name);
            }
            const float error = std::abs(actual_values[index] - expected_values[index]);
            maximum_error = (std::max)(maximum_error, error);
            error_sum += error;
        }
        return std::array<double, 2>{maximum_error,
            error_sum / static_cast<double>(actual_values.size())};
    };
    const auto control_error = measure_error(actual_controls,
                                             network_case.reference_controls, "controls");
    const auto residual_error = measure_error(actual_residual,
                                              network_case.reference_residual, "residual");
    const auto image_error = measure_error(actual_image,
                                           network_case.reference_output, "RGB output");
    if (control_error[0] > 5.0e-3 || control_error[1] > 1.0e-3 ||
        residual_error[0] > 5.0e-3 || residual_error[1] > 1.0e-3 ||
        image_error[0] > 5.5e-3 || image_error[1] > 2.5e-3) {
        const auto debug_path = std::filesystem::path(case_path.string() + ".gpu.f32");
        std::ofstream debug(debug_path, std::ios::binary);
        debug.write(reinterpret_cast<const char*>(actual_controls.data()),
                    static_cast<std::streamsize>(actual_controls.size() * sizeof(float)));
        debug.write(reinterpret_cast<const char*>(actual_residual.data()),
                    static_cast<std::streamsize>(actual_residual.size() * sizeof(float)));
        debug.write(reinterpret_cast<const char*>(actual_image.data()),
                    static_cast<std::streamsize>(actual_image.size() * sizeof(float)));
        throw std::runtime_error("NaviQSR network/AKR GPU reference gate failed; image max/mean abs error=" +
                                 std::to_string(image_error[0]) + "/" +
                                 std::to_string(image_error[1]));
    }

    std::cout << "NaviQSR network+AKR GPU frame passed on RX 5700 XT (PCI 1002:731F): "
              << header.width << 'x' << header.height << " LR input -> "
              << header.width * header.scale << 'x' << header.height * header.scale
              << ", taps " << header.taps << ", " << network_case.layers.size()
              << " network GPU layers.\n"
              << "  controls max/mean abs error " << control_error[0] << '/' << control_error[1]
              << ", residual " << residual_error[0] << '/' << residual_error[1]
              << ", RGB " << image_error[0] << '/' << image_error[1] << ".\n"
              << "  network weights/biases: " << header.weights_count
              << " FP16 values; activations and accumulation are FP32.\n"
              << "  network-only timing min/median/p90/p95: " << network_timing[0] << '/'
              << network_timing[1] << '/' << network_timing[2] << '/' << network_timing[3]
              << " us\n"
              << "  network+AKR timing min/median/p90/p95: " << frame_timing[0] << '/'
              << frame_timing[1] << '/' << frame_timing[2] << '/' << frame_timing[3]
              << " us; uploads, CPU preprocessing, PSO creation, wait, and readback excluded.\n";
    return 0;
}

} // namespace fsr4n10
