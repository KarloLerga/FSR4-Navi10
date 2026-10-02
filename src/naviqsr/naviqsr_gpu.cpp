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
#include <iomanip>
#include <iostream>
#include <limits>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <system_error>
#include <vector>
#include <wrl/client.h>

#include <Windows.h>
#include <bcrypt.h>
#include <d3d12.h>
#include <dxgi1_6.h>

namespace fsr4n10 {
namespace {

using Microsoft::WRL::ComPtr;

constexpr UINT kWarmupDispatches = 5;
constexpr UINT kMeasuredDispatches = 20;
constexpr UINT kTotalDispatches = kWarmupDispatches + kMeasuredDispatches;

std::string sha256_hex(const std::vector<std::byte>& data) {
    struct AlgorithmGuard {
        BCRYPT_ALG_HANDLE value{};
        ~AlgorithmGuard() { if (value != nullptr) BCryptCloseAlgorithmProvider(value, 0); }
    } algorithm;
    struct HashGuard {
        BCRYPT_HASH_HANDLE value{};
        ~HashGuard() { if (value != nullptr) BCryptDestroyHash(value); }
    } hash;

    auto require_success = [](NTSTATUS status, const char* operation) {
        if (status < 0) {
            throw std::runtime_error(std::string(operation) + " (NTSTATUS " +
                                     std::to_string(status) + ")");
        }
    };
    require_success(BCryptOpenAlgorithmProvider(&algorithm.value, BCRYPT_SHA256_ALGORITHM,
                                                nullptr, 0),
                    "Open SHA-256 provider failed");
    ULONG object_size = 0;
    ULONG property_size = 0;
    require_success(BCryptGetProperty(algorithm.value, BCRYPT_OBJECT_LENGTH,
                                      reinterpret_cast<PUCHAR>(&object_size), sizeof(object_size),
                                      &property_size, 0),
                    "Read SHA-256 object size failed");
    std::vector<UCHAR> object(object_size);
    std::array<UCHAR, 32> digest{};
    require_success(BCryptCreateHash(algorithm.value, &hash.value, object.data(), object_size,
                                     nullptr, 0, 0),
                    "Create SHA-256 hash failed");
    if (data.size() > std::numeric_limits<ULONG>::max()) {
        throw std::runtime_error("Shader bytecode is too large to hash");
    }
    require_success(BCryptHashData(hash.value,
                                   reinterpret_cast<PUCHAR>(const_cast<std::byte*>(data.data())),
                                   static_cast<ULONG>(data.size()), 0),
                    "Hash shader bytecode failed");
    require_success(BCryptFinishHash(hash.value, digest.data(),
                                     static_cast<ULONG>(digest.size()), 0),
                    "Finish shader SHA-256 failed");
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
        const HRESULT result = factory->EnumAdapters1(index, &adapter);
        if (result == DXGI_ERROR_NOT_FOUND) break;
        if (FAILED(result)) return "unavailable";
        DXGI_ADAPTER_DESC1 description{};
        if (FAILED(adapter->GetDesc1(&description)) || description.VendorId != 0x1002 ||
            description.DeviceId != 0x731F) continue;
        LARGE_INTEGER version{};
        if (FAILED(adapter->CheckInterfaceSupport(__uuidof(IDXGIDevice), &version))) {
            return "unavailable";
        }
        const auto packed = static_cast<std::uint64_t>(version.QuadPart);
        std::ostringstream text;
        text << ((packed >> 48) & 0xffffU) << '.' << ((packed >> 32) & 0xffffU) << '.'
             << ((packed >> 16) & 0xffffU) << '.' << (packed & 0xffffU);
        return text.str();
    }
    return "unavailable";
}

#pragma pack(push, 1)
struct GpuCaseHeader {
    char magic[8];
    std::uint32_t version;
    std::uint32_t width;
    std::uint32_t height;
    std::uint32_t scale;
    std::uint32_t taps;
    float current_jitter_x;
    float current_jitter_y;
    float previous_jitter_x;
    float previous_jitter_y;
};
#pragma pack(pop)
static_assert(sizeof(GpuCaseHeader) == 44);

struct Float2 {
    float x;
    float y;
};
static_assert(sizeof(Float2) == 8);

struct Float3 {
    float x;
    float y;
    float z;
};
static_assert(sizeof(Float3) == 12);

struct Float4 {
    float x;
    float y;
    float z;
    float w;
};
static_assert(sizeof(Float4) == 16);

struct GpuCase {
    GpuCaseHeader header{};
    std::vector<Float4> current;
    std::vector<Float4> controls0;
    std::vector<Float4> controls1;
    std::vector<Float4> residual;
    std::vector<Float4> history;
    std::vector<Float2> motion;
    std::vector<Float4> masks;
    std::vector<Float3> reference;
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

D3D12_RESOURCE_DESC buffer_description(std::uint64_t bytes) {
    D3D12_RESOURCE_DESC description{};
    description.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
    description.Width = bytes;
    description.Height = 1;
    description.DepthOrArraySize = 1;
    description.MipLevels = 1;
    description.SampleDesc.Count = 1;
    description.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    return description;
}

D3D12_RESOURCE_DESC texture_description(std::uint32_t width, std::uint32_t height,
                                        DXGI_FORMAT format,
                                        D3D12_RESOURCE_FLAGS flags = D3D12_RESOURCE_FLAG_NONE) {
    D3D12_RESOURCE_DESC description{};
    description.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    description.Width = width;
    description.Height = height;
    description.DepthOrArraySize = 1;
    description.MipLevels = 1;
    description.Format = format;
    description.SampleDesc.Count = 1;
    description.Layout = D3D12_TEXTURE_LAYOUT_UNKNOWN;
    description.Flags = flags;
    return description;
}

ComPtr<ID3D12Device> create_target_device() {
    ComPtr<IDXGIFactory6> factory;
    check_hr(CreateDXGIFactory2(0, IID_PPV_ARGS(&factory)), "CreateDXGIFactory2 failed");
    for (UINT index = 0;; ++index) {
        ComPtr<IDXGIAdapter1> adapter;
        const HRESULT enumerate_result = factory->EnumAdapters1(index, &adapter);
        if (enumerate_result == DXGI_ERROR_NOT_FOUND) {
            break;
        }
        check_hr(enumerate_result, "IDXGIFactory6::EnumAdapters1 failed");
        DXGI_ADAPTER_DESC1 description{};
        check_hr(adapter->GetDesc1(&description), "IDXGIAdapter1::GetDesc1 failed");
        if (description.VendorId != 0x1002 || description.DeviceId != 0x731F ||
            (description.Flags & DXGI_ADAPTER_FLAG_SOFTWARE) != 0) {
            continue;
        }
        ComPtr<ID3D12Device> device;
        check_hr(D3D12CreateDevice(adapter.Get(), D3D_FEATURE_LEVEL_11_0,
                                   IID_PPV_ARGS(&device)),
                 "RX 5700 XT does not expose a D3D12 device");
        return device;
    }
    throw std::runtime_error("RX 5700 XT (PCI 1002:731F) was not found");
}

std::vector<std::byte> read_shader(const std::filesystem::path& path) {
    std::ifstream file(path, std::ios::binary | std::ios::ate);
    if (!file) {
        throw std::runtime_error("cannot open NaviQSR analytic shader: " + path.string());
    }
    const auto size = file.tellg();
    if (size <= 0) {
        throw std::runtime_error("NaviQSR analytic shader is empty: " + path.string());
    }
    std::vector<std::byte> bytes(static_cast<std::size_t>(size));
    file.seekg(0);
    file.read(reinterpret_cast<char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
    if (!file) {
        throw std::runtime_error("failed to read NaviQSR analytic shader: " + path.string());
    }
    return bytes;
}

template<class T>
std::vector<T> read_array(std::istream& stream, std::size_t count, const char* name) {
    if (count > static_cast<std::size_t>((std::numeric_limits<std::streamsize>::max)()) / sizeof(T)) {
        throw std::runtime_error(std::string("GPU case array is too large: ") + name);
    }
    std::vector<T> values(count);
    const auto bytes = static_cast<std::streamsize>(count * sizeof(T));
    stream.read(reinterpret_cast<char*>(values.data()), bytes);
    if (stream.gcount() != bytes) {
        throw std::runtime_error(std::string("GPU case is truncated while reading ") + name);
    }
    return values;
}

GpuCase read_case(const std::filesystem::path& path) {
    std::ifstream stream(path, std::ios::binary);
    if (!stream) {
        throw std::runtime_error("cannot open NaviQSR GPU case: " + path.string());
    }
    GpuCase gpu_case{};
    stream.read(reinterpret_cast<char*>(&gpu_case.header), sizeof(gpu_case.header));
    if (stream.gcount() != static_cast<std::streamsize>(sizeof(gpu_case.header))) {
        throw std::runtime_error("NaviQSR GPU case header is truncated");
    }
    const auto& header = gpu_case.header;
    if (std::memcmp(header.magic, "NQSRCASE", 8) != 0 || header.version != 1 ||
        header.width < 2 || header.height < 2 || header.scale < 2 || header.scale > 4 ||
        (header.width % 2) != 0 || (header.height % 2) != 0 ||
        (header.taps != 4 && header.taps != 5 && header.taps != 8)) {
        throw std::runtime_error("unsupported or invalid NaviQSR GPU case header");
    }
    const std::uint64_t output_width = static_cast<std::uint64_t>(header.width) * header.scale;
    const std::uint64_t output_height = static_cast<std::uint64_t>(header.height) * header.scale;
    if (output_width > 8192 || output_height > 8192 ||
        output_width * output_height > 16U * 1024U * 1024U) {
        throw std::runtime_error("NaviQSR GPU case exceeds the smoke harness size limit");
    }
    const std::size_t input_pixels = static_cast<std::size_t>(header.width) * header.height;
    const std::size_t control_pixels = static_cast<std::size_t>(header.width / 2) * (header.height / 2);
    const std::size_t output_pixels = input_pixels * header.scale * header.scale;
    gpu_case.current = read_array<Float4>(stream, input_pixels, "current color");
    gpu_case.controls0 = read_array<Float4>(stream, control_pixels, "control map 0");
    gpu_case.controls1 = read_array<Float4>(stream, control_pixels, "control map 1");
    gpu_case.residual = read_array<Float4>(stream, control_pixels, "residual map");
    gpu_case.history = read_array<Float4>(stream, output_pixels, "history");
    gpu_case.motion = read_array<Float2>(stream, input_pixels, "motion");
    gpu_case.masks = read_array<Float4>(stream, input_pixels, "masks");
    gpu_case.reference = read_array<Float3>(stream, output_pixels, "CPU reference output");
    if (stream.peek() != std::char_traits<char>::eof()) {
        throw std::runtime_error("NaviQSR GPU case has unexpected trailing bytes");
    }
    return gpu_case;
}

struct UploadedTexture {
    ComPtr<ID3D12Resource> resource;
    ComPtr<ID3D12Resource> upload;
};

template<class T>
UploadedTexture upload_texture(ID3D12Device* device, ID3D12GraphicsCommandList* command_list,
                               std::uint32_t width, std::uint32_t height, DXGI_FORMAT format,
                               const std::vector<T>& pixels, std::uint32_t bytes_per_pixel) {
    const auto texture_desc = texture_description(width, height, format);
    UploadedTexture texture{};
    const auto default_heap = heap_properties(D3D12_HEAP_TYPE_DEFAULT);
    check_hr(device->CreateCommittedResource(&default_heap, D3D12_HEAP_FLAG_NONE,
                                              &texture_desc, D3D12_RESOURCE_STATE_COPY_DEST,
                                              nullptr, IID_PPV_ARGS(&texture.resource)),
             "Create NaviQSR input texture failed");
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};
    UINT row_count = 0;
    UINT64 row_size = 0;
    UINT64 upload_size = 0;
    device->GetCopyableFootprints(&texture_desc, 0, 1, 0, &footprint,
                                  &row_count, &row_size, &upload_size);
    if (row_count != height || row_size != static_cast<UINT64>(width) * bytes_per_pixel ||
        pixels.size() * sizeof(T) != row_size * height) {
        throw std::runtime_error("NaviQSR texture source layout does not match its dimensions");
    }
    const auto upload_heap = heap_properties(D3D12_HEAP_TYPE_UPLOAD);
    const auto upload_desc = buffer_description(upload_size);
    check_hr(device->CreateCommittedResource(&upload_heap, D3D12_HEAP_FLAG_NONE,
                                              &upload_desc, D3D12_RESOURCE_STATE_GENERIC_READ,
                                              nullptr, IID_PPV_ARGS(&texture.upload)),
             "Create NaviQSR texture upload buffer failed");
    void* mapped = nullptr;
    const D3D12_RANGE no_read{0, 0};
    check_hr(texture.upload->Map(0, &no_read, &mapped), "Map NaviQSR upload buffer failed");
    const auto* source = reinterpret_cast<const std::byte*>(pixels.data());
    auto* destination = static_cast<std::byte*>(mapped) + footprint.Offset;
    for (UINT row = 0; row < row_count; ++row) {
        std::memcpy(destination + static_cast<std::size_t>(row) * footprint.Footprint.RowPitch,
                    source + static_cast<std::size_t>(row) * static_cast<std::size_t>(row_size),
                    static_cast<std::size_t>(row_size));
    }
    texture.upload->Unmap(0, nullptr);
    D3D12_TEXTURE_COPY_LOCATION source_location{};
    source_location.pResource = texture.upload.Get();
    source_location.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
    source_location.PlacedFootprint = footprint;
    D3D12_TEXTURE_COPY_LOCATION destination_location{};
    destination_location.pResource = texture.resource.Get();
    destination_location.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    destination_location.SubresourceIndex = 0;
    command_list->CopyTextureRegion(&destination_location, 0, 0, 0, &source_location, nullptr);
    D3D12_RESOURCE_BARRIER barrier{};
    barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    barrier.Transition.pResource = texture.resource.Get();
    barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_COPY_DEST;
    barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
    command_list->ResourceBarrier(1, &barrier);
    return texture;
}

void create_texture_srv(ID3D12Device* device, ID3D12Resource* resource,
                        DXGI_FORMAT format, D3D12_CPU_DESCRIPTOR_HANDLE handle) {
    D3D12_SHADER_RESOURCE_VIEW_DESC description{};
    description.Format = format;
    description.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D;
    description.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
    description.Texture2D.MipLevels = 1;
    device->CreateShaderResourceView(resource, &description, handle);
}

} // namespace

int run_naviqsr_analytic_gpu_smoke(const std::filesystem::path& case_path) {
    const auto gpu_case = read_case(case_path);
    const std::uint32_t input_width = gpu_case.header.width;
    const std::uint32_t input_height = gpu_case.header.height;
    const std::uint32_t output_width = input_width * gpu_case.header.scale;
    const std::uint32_t output_height = input_height * gpu_case.header.scale;
    const std::uint32_t control_width = input_width / 2;
    const std::uint32_t control_height = input_height / 2;
    ComPtr<ID3D12Device> device = create_target_device();

    ComPtr<ID3D12CommandQueue> queue;
    D3D12_COMMAND_QUEUE_DESC queue_desc{};
    queue_desc.Type = D3D12_COMMAND_LIST_TYPE_COMPUTE;
    check_hr(device->CreateCommandQueue(&queue_desc, IID_PPV_ARGS(&queue)),
             "Create NaviQSR compute queue failed");
    ComPtr<ID3D12CommandAllocator> allocator;
    check_hr(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_COMPUTE,
                                             IID_PPV_ARGS(&allocator)),
             "Create NaviQSR command allocator failed");
    ComPtr<ID3D12GraphicsCommandList> command_list;
    check_hr(device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_COMPUTE,
                                      allocator.Get(), nullptr, IID_PPV_ARGS(&command_list)),
             "Create NaviQSR command list failed");

    std::array<UploadedTexture, 7> inputs{};
    inputs[0] = upload_texture(device.Get(), command_list.Get(), input_width, input_height,
                               DXGI_FORMAT_R32G32B32A32_FLOAT, gpu_case.current, sizeof(Float4));
    inputs[1] = upload_texture(device.Get(), command_list.Get(), control_width, control_height,
                               DXGI_FORMAT_R32G32B32A32_FLOAT, gpu_case.controls0, sizeof(Float4));
    inputs[2] = upload_texture(device.Get(), command_list.Get(), control_width, control_height,
                               DXGI_FORMAT_R32G32B32A32_FLOAT, gpu_case.controls1, sizeof(Float4));
    inputs[3] = upload_texture(device.Get(), command_list.Get(), control_width, control_height,
                               DXGI_FORMAT_R32G32B32A32_FLOAT, gpu_case.residual, sizeof(Float4));
    inputs[4] = upload_texture(device.Get(), command_list.Get(), output_width, output_height,
                               DXGI_FORMAT_R32G32B32A32_FLOAT, gpu_case.history, sizeof(Float4));
    inputs[5] = upload_texture(device.Get(), command_list.Get(), input_width, input_height,
                               DXGI_FORMAT_R32G32_FLOAT, gpu_case.motion, sizeof(Float2));
    inputs[6] = upload_texture(device.Get(), command_list.Get(), input_width, input_height,
                               DXGI_FORMAT_R32G32B32A32_FLOAT, gpu_case.masks, sizeof(Float4));

    const auto output_desc = texture_description(output_width, output_height,
                                                 DXGI_FORMAT_R32G32B32A32_FLOAT,
                                                 D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS);
    ComPtr<ID3D12Resource> output_texture;
    const auto default_heap = heap_properties(D3D12_HEAP_TYPE_DEFAULT);
    check_hr(device->CreateCommittedResource(&default_heap, D3D12_HEAP_FLAG_NONE,
                                              &output_desc, D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
                                              nullptr, IID_PPV_ARGS(&output_texture)),
             "Create NaviQSR output texture failed");

    D3D12_DESCRIPTOR_HEAP_DESC heap_desc{};
    heap_desc.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
    heap_desc.NumDescriptors = 8;
    heap_desc.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
    ComPtr<ID3D12DescriptorHeap> descriptor_heap;
    check_hr(device->CreateDescriptorHeap(&heap_desc, IID_PPV_ARGS(&descriptor_heap)),
             "Create NaviQSR descriptor heap failed");
    const UINT descriptor_increment = device->GetDescriptorHandleIncrementSize(
        D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
    auto cpu_handle = descriptor_heap->GetCPUDescriptorHandleForHeapStart();
    const std::array<DXGI_FORMAT, 7> input_formats{
        DXGI_FORMAT_R32G32B32A32_FLOAT, DXGI_FORMAT_R32G32B32A32_FLOAT,
        DXGI_FORMAT_R32G32B32A32_FLOAT, DXGI_FORMAT_R32G32B32A32_FLOAT,
        DXGI_FORMAT_R32G32B32A32_FLOAT, DXGI_FORMAT_R32G32_FLOAT,
        DXGI_FORMAT_R32G32B32A32_FLOAT};
    for (UINT index = 0; index < inputs.size(); ++index) {
        create_texture_srv(device.Get(), inputs[index].resource.Get(), input_formats[index], cpu_handle);
        cpu_handle.ptr += descriptor_increment;
    }
    const auto cpu_uav = cpu_handle;
    D3D12_UNORDERED_ACCESS_VIEW_DESC uav_desc{};
    uav_desc.Format = DXGI_FORMAT_R32G32B32A32_FLOAT;
    uav_desc.ViewDimension = D3D12_UAV_DIMENSION_TEXTURE2D;
    device->CreateUnorderedAccessView(output_texture.Get(), nullptr, &uav_desc, cpu_uav);

    D3D12_DESCRIPTOR_RANGE ranges[2]{};
    ranges[0].RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_SRV;
    ranges[0].NumDescriptors = static_cast<UINT>(inputs.size());
    ranges[0].BaseShaderRegister = 0;
    ranges[0].OffsetInDescriptorsFromTableStart = D3D12_DESCRIPTOR_RANGE_OFFSET_APPEND;
    ranges[1].RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_UAV;
    ranges[1].NumDescriptors = 1;
    ranges[1].BaseShaderRegister = 0;
    ranges[1].OffsetInDescriptorsFromTableStart = D3D12_DESCRIPTOR_RANGE_OFFSET_APPEND;
    D3D12_ROOT_PARAMETER root_parameters[3]{};
    root_parameters[0].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
    root_parameters[0].DescriptorTable.NumDescriptorRanges = 1;
    root_parameters[0].DescriptorTable.pDescriptorRanges = &ranges[0];
    root_parameters[0].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
    root_parameters[1].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
    root_parameters[1].DescriptorTable.NumDescriptorRanges = 1;
    root_parameters[1].DescriptorTable.pDescriptorRanges = &ranges[1];
    root_parameters[1].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
    root_parameters[2].ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
    root_parameters[2].Constants.Num32BitValues = 8;
    root_parameters[2].Constants.ShaderRegister = 0;
    root_parameters[2].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;

    D3D12_STATIC_SAMPLER_DESC sampler{};
    sampler.Filter = D3D12_FILTER_MIN_MAG_LINEAR_MIP_POINT;
    sampler.AddressU = D3D12_TEXTURE_ADDRESS_MODE_CLAMP;
    sampler.AddressV = D3D12_TEXTURE_ADDRESS_MODE_CLAMP;
    sampler.AddressW = D3D12_TEXTURE_ADDRESS_MODE_CLAMP;
    sampler.MipLODBias = 0.0f;
    sampler.MaxAnisotropy = 1;
    sampler.ComparisonFunc = D3D12_COMPARISON_FUNC_ALWAYS;
    sampler.BorderColor = D3D12_STATIC_BORDER_COLOR_TRANSPARENT_BLACK;
    sampler.MinLOD = 0.0f;
    sampler.MaxLOD = D3D12_FLOAT32_MAX;
    sampler.ShaderRegister = 0;
    sampler.ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;

    D3D12_ROOT_SIGNATURE_DESC root_desc{};
    root_desc.NumParameters = 3;
    root_desc.pParameters = root_parameters;
    root_desc.NumStaticSamplers = 1;
    root_desc.pStaticSamplers = &sampler;
    root_desc.Flags = D3D12_ROOT_SIGNATURE_FLAG_NONE;
    ComPtr<ID3DBlob> serialized_root;
    ComPtr<ID3DBlob> root_errors;
    check_hr(D3D12SerializeRootSignature(&root_desc, D3D_ROOT_SIGNATURE_VERSION_1,
                                          &serialized_root, &root_errors),
             "Serialize NaviQSR root signature failed");
    ComPtr<ID3D12RootSignature> root_signature;
    check_hr(device->CreateRootSignature(0, serialized_root->GetBufferPointer(),
                                          serialized_root->GetBufferSize(),
                                          IID_PPV_ARGS(&root_signature)),
             "Create NaviQSR root signature failed");

    std::array<wchar_t, 32768> executable_path{};
    const DWORD path_length = GetModuleFileNameW(nullptr, executable_path.data(),
                                                 static_cast<DWORD>(executable_path.size()));
    if (path_length == 0 || path_length >= static_cast<DWORD>(executable_path.size())) {
        throw std::system_error(static_cast<int>(GetLastError()), std::system_category(),
                                "GetModuleFileNameW failed");
    }
    const std::wstring shader_name = L"naviqsr_akr_" +
        std::to_wstring(gpu_case.header.taps) + L"tap.dxil";
    const auto shader_path = std::filesystem::path(executable_path.data()).parent_path() / shader_name;
    const auto shader = read_shader(shader_path);
    D3D12_COMPUTE_PIPELINE_STATE_DESC pipeline_desc{};
    pipeline_desc.pRootSignature = root_signature.Get();
    pipeline_desc.CS = {shader.data(), shader.size()};
    ComPtr<ID3D12PipelineState> pipeline;
    check_hr(device->CreateComputePipelineState(&pipeline_desc, IID_PPV_ARGS(&pipeline)),
             "Create NaviQSR analytic PSO failed");

    D3D12_PLACED_SUBRESOURCE_FOOTPRINT output_footprint{};
    UINT output_rows = 0;
    UINT64 output_row_size = 0;
    UINT64 readback_bytes = 0;
    device->GetCopyableFootprints(&output_desc, 0, 1, 0, &output_footprint,
                                  &output_rows, &output_row_size, &readback_bytes);
    if (output_rows != output_height ||
        output_row_size != static_cast<UINT64>(output_width) * sizeof(Float4)) {
        throw std::runtime_error("NaviQSR output texture footprint is unexpected");
    }
    const auto readback_desc = buffer_description(readback_bytes);
    const auto readback_heap = heap_properties(D3D12_HEAP_TYPE_READBACK);
    ComPtr<ID3D12Resource> readback;
    check_hr(device->CreateCommittedResource(&readback_heap, D3D12_HEAP_FLAG_NONE,
                                              &readback_desc, D3D12_RESOURCE_STATE_COPY_DEST,
                                              nullptr, IID_PPV_ARGS(&readback)),
             "Create NaviQSR readback buffer failed");

    D3D12_QUERY_HEAP_DESC query_desc{};
    query_desc.Type = D3D12_QUERY_HEAP_TYPE_TIMESTAMP;
    query_desc.Count = kTotalDispatches * 2U;
    ComPtr<ID3D12QueryHeap> timestamp_queries;
    check_hr(device->CreateQueryHeap(&query_desc, IID_PPV_ARGS(&timestamp_queries)),
             "Create NaviQSR timestamp query heap failed");
    const auto timestamp_readback_desc = buffer_description(
        static_cast<std::uint64_t>(query_desc.Count) * sizeof(std::uint64_t));
    ComPtr<ID3D12Resource> timestamp_readback;
    check_hr(device->CreateCommittedResource(&readback_heap, D3D12_HEAP_FLAG_NONE,
                                              &timestamp_readback_desc,
                                              D3D12_RESOURCE_STATE_COPY_DEST, nullptr,
                                              IID_PPV_ARGS(&timestamp_readback)),
             "Create NaviQSR timestamp readback buffer failed");
    UINT64 timestamp_frequency = 0;
    check_hr(queue->GetTimestampFrequency(&timestamp_frequency),
             "Get NaviQSR compute timestamp frequency failed");
    if (timestamp_frequency == 0) {
        throw std::runtime_error("NaviQSR compute queue returned a zero timestamp frequency");
    }

    ID3D12DescriptorHeap* heaps[] = {descriptor_heap.Get()};
    command_list->SetDescriptorHeaps(1, heaps);
    command_list->SetComputeRootSignature(root_signature.Get());
    command_list->SetPipelineState(pipeline.Get());
    const auto gpu_start = descriptor_heap->GetGPUDescriptorHandleForHeapStart();
    D3D12_GPU_DESCRIPTOR_HANDLE gpu_uav = gpu_start;
    gpu_uav.ptr += static_cast<UINT64>(inputs.size()) * descriptor_increment;
    command_list->SetComputeRootDescriptorTable(0, gpu_start);
    command_list->SetComputeRootDescriptorTable(1, gpu_uav);
    const std::array<std::uint32_t, 8> constants{
        input_width, input_height, output_width, output_height,
        std::bit_cast<std::uint32_t>(gpu_case.header.current_jitter_x),
        std::bit_cast<std::uint32_t>(gpu_case.header.current_jitter_y),
        std::bit_cast<std::uint32_t>(gpu_case.header.previous_jitter_x),
        std::bit_cast<std::uint32_t>(gpu_case.header.previous_jitter_y)};
    command_list->SetComputeRoot32BitConstants(2, static_cast<UINT>(constants.size()),
                                                constants.data(), 0);
    for (UINT iteration = 0; iteration < kTotalDispatches; ++iteration) {
        if (iteration != 0) {
            D3D12_RESOURCE_BARRIER ordering_barrier{};
            ordering_barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_UAV;
            ordering_barrier.UAV.pResource = output_texture.Get();
            command_list->ResourceBarrier(1, &ordering_barrier);
        }
        command_list->EndQuery(timestamp_queries.Get(), D3D12_QUERY_TYPE_TIMESTAMP,
                               iteration * 2U);
        command_list->Dispatch((output_width + 7U) / 8U, (output_height + 7U) / 8U, 1);
        command_list->EndQuery(timestamp_queries.Get(), D3D12_QUERY_TYPE_TIMESTAMP,
                               iteration * 2U + 1U);
    }
    D3D12_RESOURCE_BARRIER output_barrier{};
    output_barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    output_barrier.Transition.pResource = output_texture.Get();
    output_barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    output_barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
    output_barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_COPY_SOURCE;
    command_list->ResourceBarrier(1, &output_barrier);
    D3D12_TEXTURE_COPY_LOCATION readback_location{};
    readback_location.pResource = readback.Get();
    readback_location.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
    readback_location.PlacedFootprint = output_footprint;
    D3D12_TEXTURE_COPY_LOCATION output_location{};
    output_location.pResource = output_texture.Get();
    output_location.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    output_location.SubresourceIndex = 0;
    command_list->CopyTextureRegion(&readback_location, 0, 0, 0, &output_location, nullptr);
    command_list->ResolveQueryData(timestamp_queries.Get(), D3D12_QUERY_TYPE_TIMESTAMP,
                                   0, query_desc.Count, timestamp_readback.Get(), 0);
    check_hr(command_list->Close(), "Close NaviQSR command list failed");

    ID3D12CommandList* command_lists[] = {command_list.Get()};
    queue->ExecuteCommandLists(1, command_lists);
    ComPtr<ID3D12Fence> fence;
    check_hr(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)),
             "Create NaviQSR fence failed");
    check_hr(queue->Signal(fence.Get(), 1), "Signal NaviQSR fence failed");
    HANDLE fence_event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    if (fence_event == nullptr) {
        throw std::system_error(static_cast<int>(GetLastError()), std::system_category(),
                                "Create NaviQSR fence event failed");
    }
    const auto close_event = std::unique_ptr<void, decltype(&CloseHandle)>(fence_event, &CloseHandle);
    check_hr(fence->SetEventOnCompletion(1, fence_event),
             "Set NaviQSR fence event failed");
    if (WaitForSingleObject(fence_event, 30000) != WAIT_OBJECT_0) {
        throw std::runtime_error("Timed out waiting for the NaviQSR analytic GPU dispatch");
    }

    std::array<std::uint64_t, kTotalDispatches * 2U> timestamps{};
    void* timestamp_mapped = nullptr;
    const D3D12_RANGE timestamp_range{0, sizeof(timestamps)};
    check_hr(timestamp_readback->Map(0, &timestamp_range, &timestamp_mapped),
             "Map NaviQSR timestamps failed");
    std::memcpy(timestamps.data(), timestamp_mapped, sizeof(timestamps));
    timestamp_readback->Unmap(0, nullptr);
    std::vector<double> dispatch_times_us;
    dispatch_times_us.reserve(kMeasuredDispatches);
    for (UINT iteration = kWarmupDispatches; iteration < kTotalDispatches; ++iteration) {
        const auto begin = timestamps[iteration * 2U];
        const auto end = timestamps[iteration * 2U + 1U];
        if (end < begin) throw std::runtime_error("NaviQSR timestamps are not monotonic");
        dispatch_times_us.push_back(1.0e6 * static_cast<double>(end - begin) /
                                    static_cast<double>(timestamp_frequency));
    }
    std::sort(dispatch_times_us.begin(), dispatch_times_us.end());
    const auto median_us = (dispatch_times_us[9] + dispatch_times_us[10]) * 0.5;
    const auto p90_us = dispatch_times_us[17];
    const auto p95_us = dispatch_times_us[18];

    void* mapped = nullptr;
    const D3D12_RANGE read_range{0, static_cast<SIZE_T>(readback_bytes)};
    check_hr(readback->Map(0, &read_range, &mapped), "Map NaviQSR output readback failed");
    const auto* bytes = static_cast<const std::byte*>(mapped) + output_footprint.Offset;
    double absolute_error_sum = 0.0;
    float maximum_error = 0.0f;
    std::size_t maximum_error_index = 0;
    std::size_t finite_values = 0;
    std::vector<Float3> actual_output(static_cast<std::size_t>(output_width) * output_height);
    for (UINT row = 0; row < output_height; ++row) {
        const auto* row_data = reinterpret_cast<const Float4*>(
            bytes + static_cast<std::size_t>(row) * output_footprint.Footprint.RowPitch);
        for (UINT column = 0; column < output_width; ++column) {
            const std::size_t index = static_cast<std::size_t>(row) * output_width + column;
            const std::array<float, 3> actual{row_data[column].x, row_data[column].y, row_data[column].z};
            const auto& expected = gpu_case.reference[index];
            actual_output[index] = {actual[0], actual[1], actual[2]};
            const std::array<float, 3> target{expected.x, expected.y, expected.z};
            for (std::size_t channel = 0; channel < actual.size(); ++channel) {
                if (!std::isfinite(actual[channel])) {
                    readback->Unmap(0, nullptr);
                    throw std::runtime_error("NaviQSR analytic GPU output contains NaN or infinity");
                }
                const float error = std::abs(actual[channel] - target[channel]);
                absolute_error_sum += error;
                if (error > maximum_error) {
                    maximum_error = error;
                    maximum_error_index = index;
                }
                ++finite_values;
            }
        }
    }
    const D3D12_RANGE no_write{0, 0};
    readback->Unmap(0, &no_write);
    const double mean_absolute_error = absolute_error_sum / static_cast<double>(finite_values);
    if (maximum_error > 5.5e-3f || mean_absolute_error > 2.5e-3) {
        const auto debug_path = std::filesystem::path(case_path.string() + ".gpu.f32");
        std::ofstream debug_output(debug_path, std::ios::binary);
        debug_output.write(reinterpret_cast<const char*>(actual_output.data()),
                           static_cast<std::streamsize>(actual_output.size() * sizeof(Float3)));
        throw std::runtime_error("NaviQSR GPU analytic result exceeds its texture-sampling error gate; max abs error=" +
                                 std::to_string(maximum_error) + ", mean abs error=" +
                                 std::to_string(mean_absolute_error) + ", max pixel=(" +
                                 std::to_string(maximum_error_index % output_width) + "," +
                                 std::to_string(maximum_error_index / output_width) + ")");
    }
    std::cout << "NaviQSR AKR GPU/reference check passed on RX 5700 XT: "
              << gpu_case.header.taps << " taps, " << output_width << 'x' << output_height
              << ", max abs error " << maximum_error << ", mean abs error "
              << mean_absolute_error << ".\n"
              << "  isolated dispatch: " << kWarmupDispatches << " warmup + "
              << kMeasuredDispatches << " measured; min/median/p90/p95 "
              << dispatch_times_us.front() << '/' << median_us << '/'
              << p90_us << '/' << p95_us << " us\n"
              << "  GPU PCI 1002:731F, driver " << target_driver_version()
              << ", DXIL SHA-256 " << sha256_hex(shader) << "\n"
              << "  network convolutions still ran in the PyTorch reference path.\n";
    return 0;
}

} // namespace fsr4n10
