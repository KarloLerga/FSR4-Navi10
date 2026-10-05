#include "fsr4n10/fsr3_reference.h"
#include "fsr4n10/sequence.h"

#include "ffx_api_dx12.h"
#include "ffx_dx12.h"
#include "gpu/fsr3upscaler/ffx_fsr3upscaler_resources.h"
#include "ffx_provider_fsr3upscale.h"
#include "ffx_upscale.h"

#include <Windows.h>
#include <bcrypt.h>
#include <d3d12.h>
#include <dxgi1_6.h>
#include <wrl/client.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <numeric>
#include <optional>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <system_error>
#include <unordered_set>
#include <vector>

#ifndef FSR4N10_FSR3_SDK_COMMIT
#error FSR4N10_FSR3_SDK_COMMIT must be supplied from third_party/LOCK.json
#endif
#ifndef FSR4N10_BUILD_COMMIT
#error FSR4N10_BUILD_COMMIT must be supplied by CMake
#endif
#ifndef FSR4N10_BUILD_CONFIGURATION
#error FSR4N10_BUILD_CONFIGURATION must be supplied by CMake
#endif
#ifndef FSR4N10_FSR3_SHADER_MANIFEST
#error FSR4N10_FSR3_SHADER_MANIFEST must identify the generated FSR3 shader manifest
#endif

extern "C" FfxApiResource fsr4n10Fsr3GetInternalResource(ffxContext* context, std::uint32_t resourceId,
                                                          bool unorderedAccess);

namespace fsr4n10 {
namespace {

using Microsoft::WRL::ComPtr;

constexpr std::uint32_t kFsr3ResourceDilatedMotionVectors = FFX_FSR3UPSCALER_RESOURCE_IDENTIFIER_DILATED_MOTION_VECTORS;
constexpr std::uint32_t kFsr3ResourceDilatedDepth = FFX_FSR3UPSCALER_RESOURCE_IDENTIFIER_DILATED_DEPTH;
constexpr std::uint32_t kFsr3ResourcePreviousNearestDepth = FFX_FSR3UPSCALER_RESOURCE_IDENTIFIER_RECONSTRUCTED_PREVIOUS_NEAREST_DEPTH;
constexpr std::uint32_t kFsr3ResourceInternalUpscaledColor = FFX_FSR3UPSCALER_RESOURCE_IDENTIFIER_INTERNAL_UPSCALED_COLOR;
constexpr std::uint32_t kFsr3ResourceAccumulation = FFX_FSR3UPSCALER_RESOURCE_IDENTIFIER_ACCUMULATION;
constexpr std::uint32_t kFsr3ResourceNewLocks = FFX_FSR3UPSCALER_RESOURCE_IDENTIFIER_NEW_LOCKS;
constexpr std::uint32_t kFsr3ResourceLumaHistory = FFX_FSR3UPSCALER_RESOURCE_IDENTIFIER_LUMA_HISTORY;
constexpr std::uint32_t kFsr3ResourceShadingChange = FFX_FSR3UPSCALER_RESOURCE_IDENTIFIER_SHADING_CHANGE;
constexpr std::uint32_t kFsr3ResourceLumaInstability = FFX_FSR3UPSCALER_RESOURCE_IDENTIFIER_LUMA_INSTABILITY;

void check_hr(HRESULT result, const char* operation) {
    if (FAILED(result)) {
        std::ostringstream message;
        message << operation << " failed (HRESULT 0x" << std::hex << static_cast<std::uint32_t>(result) << ')';
        throw std::system_error(static_cast<int>(result), std::system_category(), message.str());
    }
}

void check_ffx(ffxReturnCode_t result, const char* operation) {
    if (result != FFX_API_RETURN_OK) {
        std::ostringstream message;
        message << operation << " returned FidelityFX API error 0x" << std::hex << result;
        throw std::runtime_error(message.str());
    }
}

std::string json_escape(const std::string& value) {
    std::ostringstream output;
    for (unsigned char character : value) {
        switch (character) {
        case '"': output << "\\\""; break;
        case '\\': output << "\\\\"; break;
        case '\b': output << "\\b"; break;
        case '\f': output << "\\f"; break;
        case '\n': output << "\\n"; break;
        case '\r': output << "\\r"; break;
        case '\t': output << "\\t"; break;
        default:
            if (character < 0x20) {
                output << "\\u" << std::hex << std::setw(4) << std::setfill('0')
                       << static_cast<unsigned>(character);
            } else {
                output << static_cast<char>(character);
            }
        }
    }
    return output.str();
}

std::vector<std::byte> bytes_from_values(const std::vector<std::uint16_t>& values) {
    const auto* first = reinterpret_cast<const std::byte*>(values.data());
    return {first, first + values.size() * sizeof(std::uint16_t)};
}

std::vector<std::byte> bytes_from_values(const std::vector<float>& values) {
    const auto* first = reinterpret_cast<const std::byte*>(values.data());
    return {first, first + values.size() * sizeof(float)};
}

std::vector<std::byte> bytes_from_values(const std::vector<std::uint8_t>& values) {
    const auto* first = reinterpret_cast<const std::byte*>(values.data());
    return {first, first + values.size()};
}

std::string sha256_hex(const std::vector<std::byte>& data) {
    BCRYPT_ALG_HANDLE algorithm = nullptr;
    BCRYPT_HASH_HANDLE hash = nullptr;
    try {
        NTSTATUS status = BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0);
        if (status < 0) throw std::runtime_error("BCryptOpenAlgorithmProvider(SHA-256) failed");
        DWORD object_size = 0;
        DWORD result_size = 0;
        status = BCryptGetProperty(algorithm, BCRYPT_OBJECT_LENGTH,
                                   reinterpret_cast<PUCHAR>(&object_size), sizeof(object_size), &result_size, 0);
        if (status < 0) throw std::runtime_error("BCryptGetProperty(BCRYPT_OBJECT_LENGTH) failed");
        std::vector<UCHAR> object(object_size);
        status = BCryptCreateHash(algorithm, &hash, object.data(), object_size, nullptr, 0, 0);
        if (status < 0) throw std::runtime_error("BCryptCreateHash failed");
        std::size_t offset = 0;
        while (offset < data.size()) {
            const auto chunk = static_cast<ULONG>(std::min<std::size_t>(data.size() - offset, 0xffffffffULL));
            status = BCryptHashData(hash, reinterpret_cast<PUCHAR>(const_cast<std::byte*>(data.data() + offset)), chunk, 0);
            if (status < 0) throw std::runtime_error("BCryptHashData failed");
            offset += chunk;
        }
        std::array<UCHAR, 32> digest{};
        status = BCryptFinishHash(hash, digest.data(), static_cast<ULONG>(digest.size()), 0);
        if (status < 0) throw std::runtime_error("BCryptFinishHash failed");
        BCryptDestroyHash(hash);
        BCryptCloseAlgorithmProvider(algorithm, 0);
        std::ostringstream output;
        output << std::hex << std::setfill('0');
        for (UCHAR byte : digest) output << std::setw(2) << static_cast<unsigned>(byte);
        return output.str();
    } catch (...) {
        if (hash != nullptr) BCryptDestroyHash(hash);
        if (algorithm != nullptr) BCryptCloseAlgorithmProvider(algorithm, 0);
        throw;
    }
}

std::string sha256_hex(const std::string& data) {
    std::vector<std::byte> bytes(data.size());
    if (!data.empty()) std::memcpy(bytes.data(), data.data(), data.size());
    return sha256_hex(bytes);
}

std::vector<std::byte> read_binary_file(const std::filesystem::path& path) {
    std::ifstream input(path, std::ios::binary | std::ios::ate);
    if (!input) throw std::runtime_error("cannot read file: " + path.string());
    const auto end = input.tellg();
    if (end < 0) throw std::runtime_error("cannot determine file size: " + path.string());
    std::vector<std::byte> data(static_cast<std::size_t>(end));
    input.seekg(0, std::ios::beg);
    input.read(reinterpret_cast<char*>(data.data()), static_cast<std::streamsize>(data.size()));
    if (!input) throw std::runtime_error("failed reading file: " + path.string());
    return data;
}

void write_binary_file(const std::filesystem::path& path, const std::vector<std::byte>& data) {
    std::filesystem::create_directories(path.parent_path());
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    if (!output) throw std::runtime_error("cannot write capture array: " + path.string());
    output.write(reinterpret_cast<const char*>(data.data()), static_cast<std::streamsize>(data.size()));
    if (!output) throw std::runtime_error("failed writing capture array: " + path.string());
}

D3D12_HEAP_PROPERTIES heap_properties(D3D12_HEAP_TYPE type) {
    D3D12_HEAP_PROPERTIES properties{};
    properties.Type = type;
    properties.CreationNodeMask = 1;
    properties.VisibleNodeMask = 1;
    return properties;
}

ComPtr<ID3D12Resource> create_texture(ID3D12Device* device, std::uint32_t width, std::uint32_t height,
                                     DXGI_FORMAT format, D3D12_RESOURCE_STATES state,
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
    ComPtr<ID3D12Resource> resource;
    const auto properties = heap_properties(D3D12_HEAP_TYPE_DEFAULT);
    check_hr(device->CreateCommittedResource(&properties, D3D12_HEAP_FLAG_NONE, &description, state,
                                            nullptr, IID_PPV_ARGS(&resource)),
             "CreateCommittedResource(texture) failed");
    return resource;
}

ComPtr<ID3D12Resource> create_buffer(ID3D12Device* device, D3D12_HEAP_TYPE heap_type,
                                    D3D12_RESOURCE_STATES state, std::uint64_t byte_size) {
    D3D12_RESOURCE_DESC description{};
    description.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
    description.Width = byte_size;
    description.Height = 1;
    description.DepthOrArraySize = 1;
    description.MipLevels = 1;
    description.SampleDesc.Count = 1;
    description.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    ComPtr<ID3D12Resource> resource;
    const auto properties = heap_properties(heap_type);
    check_hr(device->CreateCommittedResource(&properties, D3D12_HEAP_FLAG_NONE, &description, state,
                                            nullptr, IID_PPV_ARGS(&resource)),
             "CreateCommittedResource(buffer) failed");
    return resource;
}

ComPtr<ID3D12Resource> upload_texture(ID3D12Device* device, ID3D12GraphicsCommandList* command_list,
                                      ID3D12Resource* destination, std::uint32_t width, std::uint32_t height,
                                      std::size_t bytes_per_pixel, const std::byte* source,
                                      std::size_t source_size) {
    const auto description = destination->GetDesc();
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};
    UINT rows = 0;
    UINT64 row_size = 0;
    UINT64 upload_size = 0;
    device->GetCopyableFootprints(&description, 0, 1, 0, &footprint, &rows, &row_size, &upload_size);
    const std::size_t source_row_bytes = static_cast<std::size_t>(width) * bytes_per_pixel;
    if (rows != height || row_size != source_row_bytes || source_size != source_row_bytes * height)
        throw std::runtime_error("upload texture layout does not match source dimensions");

    auto upload = create_buffer(device, D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ, upload_size);
    std::byte* mapped = nullptr;
    D3D12_RANGE no_cpu_reads{0, 0};
    check_hr(upload->Map(0, &no_cpu_reads, reinterpret_cast<void**>(&mapped)), "Map(upload texture) failed");
    for (std::uint32_t row = 0; row < height; ++row) {
        std::memcpy(mapped + footprint.Offset + static_cast<std::size_t>(row) * footprint.Footprint.RowPitch,
                    source + static_cast<std::size_t>(row) * source_row_bytes, source_row_bytes);
    }
    upload->Unmap(0, nullptr);
    D3D12_TEXTURE_COPY_LOCATION destination_location{};
    destination_location.pResource = destination;
    destination_location.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    D3D12_TEXTURE_COPY_LOCATION source_location{};
    source_location.pResource = upload.Get();
    source_location.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
    source_location.PlacedFootprint = footprint;
    command_list->CopyTextureRegion(&destination_location, 0, 0, 0, &source_location, nullptr);
    return upload;
}

struct TargetDevice {
    ComPtr<ID3D12Device> device;
    std::string adapter_name;
    std::string driver_version;
};

TargetDevice create_target_device() {
    ComPtr<IDXGIFactory6> factory;
    check_hr(CreateDXGIFactory2(0, IID_PPV_ARGS(&factory)), "CreateDXGIFactory2 failed");
    for (UINT index = 0;; ++index) {
        ComPtr<IDXGIAdapter1> adapter;
        const HRESULT result = factory->EnumAdapters1(index, &adapter);
        if (result == DXGI_ERROR_NOT_FOUND) break;
        check_hr(result, "IDXGIFactory6::EnumAdapters1 failed");
        DXGI_ADAPTER_DESC1 description{};
        check_hr(adapter->GetDesc1(&description), "IDXGIAdapter1::GetDesc1 failed");
        if (description.VendorId != 0x1002 || description.DeviceId != 0x731F ||
            (description.Flags & DXGI_ADAPTER_FLAG_SOFTWARE) != 0) continue;
        TargetDevice target;
        check_hr(D3D12CreateDevice(adapter.Get(), D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&target.device)),
                 "D3D12CreateDevice(RX 5700 XT) failed");
        const int length = WideCharToMultiByte(CP_UTF8, 0, description.Description, -1, nullptr, 0, nullptr, nullptr);
        if (length > 1) {
            target.adapter_name.resize(static_cast<std::size_t>(length));
            WideCharToMultiByte(CP_UTF8, 0, description.Description, -1, target.adapter_name.data(), length, nullptr, nullptr);
            target.adapter_name.pop_back();
        }
        LARGE_INTEGER driver_version{};
        if (SUCCEEDED(adapter->CheckInterfaceSupport(__uuidof(IDXGIDevice), &driver_version))) {
            std::ostringstream version;
            version << "0x" << std::hex << std::setfill('0') << std::setw(16)
                    << static_cast<std::uint64_t>(driver_version.QuadPart);
            target.driver_version = version.str();
        } else {
            target.driver_version = "unavailable";
        }
        return target;
    }
    throw std::runtime_error("RX 5700 XT (PCI 1002:731F) was not found");
}

class QueueWaiter {
public:
    explicit QueueWaiter(ID3D12Device* device) {
        check_hr(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence_)), "CreateFence failed");
        event_ = CreateEventW(nullptr, FALSE, FALSE, nullptr);
        if (event_ == nullptr) throw std::system_error(static_cast<int>(GetLastError()), std::system_category(), "CreateEventW failed");
    }
    ~QueueWaiter() { if (event_ != nullptr) CloseHandle(event_); }
    void wait(ID3D12CommandQueue* queue) {
        const UINT64 value = ++value_;
        check_hr(queue->Signal(fence_.Get(), value), "ID3D12CommandQueue::Signal failed");
        if (fence_->GetCompletedValue() >= value) return;
        check_hr(fence_->SetEventOnCompletion(value, event_), "ID3D12Fence::SetEventOnCompletion failed");
        if (WaitForSingleObject(event_, INFINITE) != WAIT_OBJECT_0)
            throw std::system_error(static_cast<int>(GetLastError()), std::system_category(), "WaitForSingleObject failed");
    }

private:
    ComPtr<ID3D12Fence> fence_;
    HANDLE event_ = nullptr;
    UINT64 value_ = 0;
};

class GpuDispatchTimer {
public:
    GpuDispatchTimer(ID3D12Device* device, ID3D12CommandQueue* queue) {
        check_hr(queue->GetTimestampFrequency(&frequency_), "ID3D12CommandQueue::GetTimestampFrequency failed");
        if (frequency_ == 0) throw std::runtime_error("D3D12 timestamp frequency is zero");
        D3D12_QUERY_HEAP_DESC query_description{};
        query_description.Type = D3D12_QUERY_HEAP_TYPE_TIMESTAMP;
        query_description.Count = 2;
        check_hr(device->CreateQueryHeap(&query_description, IID_PPV_ARGS(&query_heap_)),
                 "CreateQueryHeap(timestamp) failed");
        readback_ = create_buffer(device, D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST,
                                  sizeof(UINT64) * 2);
    }

    void begin(ID3D12GraphicsCommandList* command_list) const {
        command_list->EndQuery(query_heap_.Get(), D3D12_QUERY_TYPE_TIMESTAMP, 0);
    }

    void end_and_resolve(ID3D12GraphicsCommandList* command_list) const {
        command_list->EndQuery(query_heap_.Get(), D3D12_QUERY_TYPE_TIMESTAMP, 1);
        command_list->ResolveQueryData(query_heap_.Get(), D3D12_QUERY_TYPE_TIMESTAMP, 0, 2,
                                       readback_.Get(), 0);
    }

    [[nodiscard]] double elapsed_microseconds() const {
        void* mapped = nullptr;
        const D3D12_RANGE read_range{0, sizeof(UINT64) * 2};
        check_hr(readback_->Map(0, &read_range, &mapped), "Map(timestamp readback) failed");
        const auto* values = static_cast<const UINT64*>(mapped);
        const UINT64 start = values[0];
        const UINT64 end = values[1];
        const D3D12_RANGE no_writes{0, 0};
        readback_->Unmap(0, &no_writes);
        if (end < start) throw std::runtime_error("D3D12 timestamp query returned a negative interval");
        return static_cast<double>(end - start) * 1'000'000.0 / static_cast<double>(frequency_);
    }

    [[nodiscard]] UINT64 frequency() const noexcept { return frequency_; }

private:
    ComPtr<ID3D12QueryHeap> query_heap_;
    ComPtr<ID3D12Resource> readback_;
    UINT64 frequency_ = 0;
};

class Fsr3ProviderContext {
public:
    ~Fsr3ProviderContext() {
        if (value_ != nullptr) (void)ffxProvider_FSR3Upscale::GetInstance().DestroyContext(&value_, allocator_);
    }
    ffxContext* address() noexcept { return &value_; }
    Allocator& allocator() noexcept { return allocator_; }

private:
    ffxContext value_ = nullptr;
    Allocator allocator_{nullptr};
};

struct TextureReadbackRequest {
    ID3D12Resource* resource = nullptr;
    D3D12_RESOURCE_STATES initial_state = D3D12_RESOURCE_STATE_COMMON;
    std::size_t bytes_per_pixel = 0;
};

D3D12_RESOURCE_STATES dx12_state_from_ffx(std::uint32_t state) {
    switch (state) {
    case FFX_API_RESOURCE_STATE_COMMON: return D3D12_RESOURCE_STATE_COMMON;
    case FFX_API_RESOURCE_STATE_UNORDERED_ACCESS: return D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
    case FFX_API_RESOURCE_STATE_COMPUTE_READ: return D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
    case FFX_API_RESOURCE_STATE_PIXEL_COMPUTE_READ:
        return D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE | D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
    case FFX_API_RESOURCE_STATE_COPY_SRC: return D3D12_RESOURCE_STATE_COPY_SOURCE;
    case FFX_API_RESOURCE_STATE_COPY_DEST: return D3D12_RESOURCE_STATE_COPY_DEST;
    case FFX_API_RESOURCE_STATE_GENERIC_READ: return D3D12_RESOURCE_STATE_GENERIC_READ;
    default: throw std::runtime_error("unsupported FSR3 internal resource state for readback");
    }
}

std::vector<std::vector<std::byte>> read_textures(
    ID3D12Device* device, ID3D12CommandQueue* queue,
    ID3D12GraphicsCommandList* command_list, QueueWaiter& waiter,
    const std::vector<TextureReadbackRequest>& requests) {
    struct PendingReadback {
        ComPtr<ID3D12Resource> buffer;
        D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};
        UINT rows = 0;
        UINT64 row_size = 0;
        UINT64 total_size = 0;
    };
    std::vector<PendingReadback> pending(requests.size());
    for (std::size_t index = 0; index < requests.size(); ++index) {
        const auto& request = requests[index];
        if (request.resource == nullptr || request.bytes_per_pixel == 0)
            throw std::runtime_error("invalid texture readback request");
        const auto description = request.resource->GetDesc();
        device->GetCopyableFootprints(&description, 0, 1, 0, &pending[index].footprint,
                                      &pending[index].rows, &pending[index].row_size, &pending[index].total_size);
        if (pending[index].rows != description.Height || pending[index].row_size != description.Width * request.bytes_per_pixel)
            throw std::runtime_error("unexpected FSR3 resource readback layout");
        pending[index].buffer = create_buffer(device, D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST,
                                              pending[index].total_size);
        if (request.initial_state != D3D12_RESOURCE_STATE_COPY_SOURCE) {
            D3D12_RESOURCE_BARRIER to_copy{};
            to_copy.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
            to_copy.Transition.pResource = request.resource;
            to_copy.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
            to_copy.Transition.StateBefore = request.initial_state;
            to_copy.Transition.StateAfter = D3D12_RESOURCE_STATE_COPY_SOURCE;
            command_list->ResourceBarrier(1, &to_copy);
        }
        D3D12_TEXTURE_COPY_LOCATION source{};
        source.pResource = request.resource;
        source.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        D3D12_TEXTURE_COPY_LOCATION destination{};
        destination.pResource = pending[index].buffer.Get();
        destination.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
        destination.PlacedFootprint = pending[index].footprint;
        command_list->CopyTextureRegion(&destination, 0, 0, 0, &source, nullptr);
        if (request.initial_state != D3D12_RESOURCE_STATE_COPY_SOURCE) {
            D3D12_RESOURCE_BARRIER restore{};
            restore.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
            restore.Transition.pResource = request.resource;
            restore.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
            restore.Transition.StateBefore = D3D12_RESOURCE_STATE_COPY_SOURCE;
            restore.Transition.StateAfter = request.initial_state;
            command_list->ResourceBarrier(1, &restore);
        }
    }
    check_hr(command_list->Close(), "ID3D12GraphicsCommandList::Close(readback) failed");
    ID3D12CommandList* lists[]{command_list};
    queue->ExecuteCommandLists(1, lists);
    waiter.wait(queue);

    std::vector<std::vector<std::byte>> results(requests.size());
    for (std::size_t index = 0; index < requests.size(); ++index) {
        auto& item = pending[index];
        auto& packed = results[index];
        packed.resize(static_cast<std::size_t>(item.row_size) * item.rows);
        void* mapped = nullptr;
        D3D12_RANGE read_range{0, static_cast<SIZE_T>(item.total_size)};
        check_hr(item.buffer->Map(0, &read_range, &mapped), "Map(texture readback) failed");
        for (std::uint32_t row = 0; row < item.rows; ++row) {
            std::memcpy(packed.data() + static_cast<std::size_t>(row) * item.row_size,
                        static_cast<const std::byte*>(mapped) + static_cast<std::size_t>(row) * item.footprint.Footprint.RowPitch,
                        static_cast<std::size_t>(item.row_size));
        }
        const D3D12_RANGE no_writes{0, 0};
        item.buffer->Unmap(0, &no_writes);
    }
    return results;
}

struct TargetFormat {
    const char* dtype;
    std::uint32_t channels;
    std::size_t bytes_per_pixel;
};

TargetFormat target_format(DXGI_FORMAT format) {
    switch (format) {
    case DXGI_FORMAT_R8_UNORM: return {"|u1", 1, 1};
    case DXGI_FORMAT_R8G8_UNORM: return {"|u1", 2, 2};
    case DXGI_FORMAT_R8G8B8A8_UNORM: return {"|u1", 4, 4};
    case DXGI_FORMAT_R16_FLOAT: return {"<f2", 1, 2};
    case DXGI_FORMAT_R16G16_FLOAT: return {"<f2", 2, 4};
    case DXGI_FORMAT_R16G16B16A16_FLOAT: return {"<f2", 4, 8};
    case DXGI_FORMAT_R32_FLOAT: return {"<f4", 1, 4};
    case DXGI_FORMAT_R32G32_FLOAT: return {"<f4", 2, 8};
    case DXGI_FORMAT_R32G32B32A32_FLOAT: return {"<f4", 4, 16};
    case DXGI_FORMAT_R32_UINT: return {"<u4", 1, 4};
    default: throw std::runtime_error("unsupported FSR3 tap texture format " + std::to_string(format));
    }
}

struct CapturedTexture {
    std::string name;
    ID3D12Resource* texture = nullptr;
    D3D12_RESOURCE_STATES state = D3D12_RESOURCE_STATE_COMMON;
    std::uint32_t width = 0;
    std::uint32_t height = 0;
    TargetFormat format{};
};

CapturedTexture capture_texture(std::string name, ID3D12Resource* texture, D3D12_RESOURCE_STATES state) {
    const auto description = texture->GetDesc();
    const auto format = target_format(description.Format);
    return {std::move(name), texture, state, static_cast<std::uint32_t>(description.Width),
            description.Height, format};
}

void add_fsr3_tap(ffxContext* context, std::uint32_t id, const char* name,
                  std::vector<CapturedTexture>& captures,
                  std::unordered_set<ID3D12Resource*>& seen) {
    FfxApiResource resource = fsr4n10Fsr3GetInternalResource(context, id, true);
    if (resource.resource == nullptr) return;
    auto* texture = static_cast<ID3D12Resource*>(resource.resource);
    if (!seen.insert(texture).second) return;
    captures.push_back(capture_texture(name, texture, dx12_state_from_ffx(resource.state)));
}

struct Fsr3UploadInputs {
    ComPtr<ID3D12Resource> color;
    ComPtr<ID3D12Resource> depth;
    ComPtr<ID3D12Resource> motion;
    ComPtr<ID3D12Resource> exposure;
    ComPtr<ID3D12Resource> reactive;
    ComPtr<ID3D12Resource> transparency;
    std::array<D3D12_RESOURCE_STATES, 6> states{
        D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_COPY_DEST,
        D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_COPY_DEST,
        D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_COPY_DEST};
};

void upload_frame_inputs(ID3D12Device* device, ID3D12CommandQueue* queue,
                         ID3D12CommandAllocator* allocator, ID3D12GraphicsCommandList* command_list,
                         QueueWaiter& waiter, Fsr3UploadInputs& inputs,
                         const SequenceFrame& frame, std::uint32_t width, std::uint32_t height) {
    check_hr(allocator->Reset(), "ID3D12CommandAllocator::Reset(before input upload) failed");
    check_hr(command_list->Reset(allocator, nullptr), "ID3D12GraphicsCommandList::Reset(before input upload) failed");
    struct Upload {
        ID3D12Resource* resource;
        std::size_t index;
        std::uint32_t width;
        std::uint32_t height;
        std::size_t pixel_bytes;
        const std::byte* data;
        std::size_t size;
    };
    const float exposure_value = frame.metadata.exposure;
    const std::array<Upload, 6> possible{{
        {inputs.color.Get(), 0, width, height, 8, reinterpret_cast<const std::byte*>(frame.color_rgba_half.data()), frame.color_rgba_half.size() * 2},
        {inputs.depth.Get(), 1, width, height, 4, reinterpret_cast<const std::byte*>(frame.depth.data()), frame.depth.size() * 4},
        {inputs.motion.Get(), 2, width, height, 4, reinterpret_cast<const std::byte*>(frame.motion_vectors_half.data()), frame.motion_vectors_half.size() * 2},
        {inputs.exposure.Get(), 3, 1, 1, 4, reinterpret_cast<const std::byte*>(&exposure_value), sizeof(exposure_value)},
        {inputs.reactive.Get(), 4, width, height, 1, reinterpret_cast<const std::byte*>(frame.reactive_mask.data()), frame.reactive_mask.size()},
        {inputs.transparency.Get(), 5, width, height, 1, reinterpret_cast<const std::byte*>(frame.transparency_composition_mask.data()), frame.transparency_composition_mask.size()},
    }};
    std::vector<Upload> uploads;
    std::vector<ComPtr<ID3D12Resource>> upload_buffers;
    uploads.reserve(possible.size());
    upload_buffers.reserve(possible.size());
    for (const auto& upload : possible) {
        if ((upload.index == 4 && !frame.metadata.reactive_mask_valid) ||
            (upload.index == 5 && !frame.metadata.transparency_composition_mask_valid)) continue;
        if (inputs.states[upload.index] != D3D12_RESOURCE_STATE_COPY_DEST) {
            D3D12_RESOURCE_BARRIER to_copy{};
            to_copy.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
            to_copy.Transition.pResource = upload.resource;
            to_copy.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
            to_copy.Transition.StateBefore = inputs.states[upload.index];
            to_copy.Transition.StateAfter = D3D12_RESOURCE_STATE_COPY_DEST;
            command_list->ResourceBarrier(1, &to_copy);
        }
        upload_buffers.push_back(upload_texture(device, command_list, upload.resource, upload.width, upload.height,
                                               upload.pixel_bytes, upload.data, upload.size));
        uploads.push_back(upload);
    }
    for (const auto& upload : uploads) {
        D3D12_RESOURCE_BARRIER to_read{};
        to_read.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        to_read.Transition.pResource = upload.resource;
        to_read.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
        to_read.Transition.StateBefore = D3D12_RESOURCE_STATE_COPY_DEST;
        to_read.Transition.StateAfter = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
        command_list->ResourceBarrier(1, &to_read);
        inputs.states[upload.index] = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
    }
    check_hr(command_list->Close(), "ID3D12GraphicsCommandList::Close(input upload) failed");
    ID3D12CommandList* lists[]{command_list};
    queue->ExecuteCommandLists(1, lists);
    waiter.wait(queue);
}

struct CaptureDescriptor {
    std::string name;
    std::string dtype;
    std::uint32_t width = 0;
    std::uint32_t height = 0;
    std::uint32_t channels = 0;
    std::string file;
};

CaptureDescriptor write_capture_array(const std::filesystem::path& arrays_dir,
                                      const std::string& name, const std::string& dtype,
                                      std::uint32_t width, std::uint32_t height,
                                      std::uint32_t channels, const std::vector<std::byte>& bytes) {
    const std::string file = "arrays/" + name + ".raw";
    write_binary_file(arrays_dir / (name + ".raw"), bytes);
    return {name, dtype, width, height, channels, file};
}

void write_capture_manifest(const std::filesystem::path& path, const SequenceMetadata& sequence,
                            const SequenceFrame& frame, const TargetDevice& target,
                            const std::string& input_hash, const std::string& shader_manifest_hash,
                            const std::vector<CaptureDescriptor>& arrays) {
    std::ofstream manifest(path, std::ios::binary | std::ios::trunc);
    if (!manifest) throw std::runtime_error("cannot write FSR3 capture manifest: " + path.string());
    manifest << std::setprecision(9)
             << "{\n"
             << "  \"schema\": \"f4n10.fsr3-aligned-capture.v1\",\n"
             << "  \"metadata\": {\n"
             << "    \"sequence_id\": \"" << json_escape(sequence.sequence_id) << "\",\n"
             << "    \"source_kind\": \"" << json_escape(sequence.source_kind) << "\",\n"
             << "    \"source_hash\": \"" << sequence.source_hash << "\",\n"
             << "    \"sequence_hash\": \"" << sequence.sequence_hash << "\",\n"
             << "    \"input_frame_sha256\": \"" << input_hash << "\",\n"
             << "    \"frame_index\": " << frame.metadata.frame_index << ",\n"
             << "    \"preset\": \"" << json_escape(sequence.preset) << "\",\n"
             << "    \"render_size\": [" << sequence.render_width << ", " << sequence.render_height << "],\n"
             << "    \"output_size\": [" << sequence.output_width << ", " << sequence.output_height << "],\n"
             << "    \"jitter_current\": [" << frame.metadata.jitter_x << ", " << frame.metadata.jitter_y << "],\n"
             << "    \"jitter_previous\": [" << frame.metadata.previous_jitter_x << ", " << frame.metadata.previous_jitter_y << "],\n"
             << "    \"frame_time_delta_ms\": " << frame.metadata.frame_time_delta_ms << ",\n"
             << "    \"exposure\": " << frame.metadata.exposure << ",\n"
             << "    \"pre_exposure\": " << frame.metadata.pre_exposure << ",\n"
             << "    \"reset\": " << (frame.metadata.reset ? "true" : "false") << ",\n"
             << "    \"camera_cut\": " << (frame.metadata.camera_cut ? "true" : "false") << ",\n"
             << "    \"motion_vector_convention\": \"current_to_previous_render_pixels_unjittered\",\n"
             << "    \"fsr3_version\": \"3.1.5\",\n"
             << "    \"fsr3_sdk_commit\": \"" << FSR4N10_FSR3_SDK_COMMIT << "\",\n"
             << "    \"shader_manifest_sha256\": \"" << shader_manifest_hash << "\",\n"
             << "    \"build_commit\": \"" << FSR4N10_BUILD_COMMIT << "\",\n"
             << "    \"build_mode\": \"" << FSR4N10_BUILD_CONFIGURATION << "\",\n"
             << "    \"camera_profile\": {\"near\": 0.1, \"far\": 1000.0, \"vertical_fov_radians\": 1.0, \"view_space_to_meters\": 1.0},\n"
             << "    \"camera_profile_origin\": \"fixed harness values; f4seq v2 does not encode camera projection parameters\",\n"
             << "    \"capture_origin\": \"" << json_escape(sequence.source_kind) << "_fsr3_reference_gpu_capture\",\n"
             << "    \"gpu_name\": \"" << json_escape(target.adapter_name) << "\",\n"
             << "    \"driver_version\": \"" << json_escape(target.driver_version) << "\"\n"
             << "  },\n"
             << "  \"validity\": {\n"
             << "    \"reactive_mask\": " << (frame.metadata.reactive_mask_valid ? "true" : "false") << ",\n"
             << "    \"transparency_composition_mask\": "
             << (frame.metadata.transparency_composition_mask_valid ? "true" : "false") << "\n"
             << "  },\n"
             << "  \"arrays\": {\n";
    for (std::size_t index = 0; index < arrays.size(); ++index) {
        const auto& array = arrays[index];
        manifest << "    \"" << array.name << "\": {\"file\": \"" << array.file
                 << "\", \"dtype\": \"" << array.dtype << "\", \"shape\": ["
                 << array.height << ", " << array.width << ", " << array.channels << "]}"
                 << (index + 1 == arrays.size() ? "\n" : ",\n");
    }
    manifest << "  }\n}\n";
    if (!manifest) throw std::runtime_error("failed writing FSR3 capture manifest: " + path.string());
}

} // namespace

int run_fsr3_reference_sequence(const std::filesystem::path& sequence_path,
                                const std::filesystem::path& report_path,
                                const std::filesystem::path& capture_root) {
    F4Sequence sequence = F4Sequence::open(sequence_path);
    const SequenceMetadata metadata = sequence.metadata();
    std::size_t watermark_environment_size = 0;
    getenv_s(&watermark_environment_size, nullptr, 0, "MLSR-WATERMARK");
    if (watermark_environment_size != 0) {
        throw std::runtime_error("this pinned FSR3 reference target excludes the optional AMD-internal watermark module; unset MLSR-WATERMARK");
    }
    if (metadata.reversed_depth || metadata.motion_convention_id != 1) {
        throw std::runtime_error("FSR3 reference requires forward depth and unjittered current-to-previous render-pixel motion vectors");
    }
    const std::uint32_t render_width = metadata.render_width;
    const std::uint32_t render_height = metadata.render_height;
    const std::uint32_t output_width = metadata.output_width;
    const std::uint32_t output_height = metadata.output_height;
    const std::size_t output_bytes = static_cast<std::size_t>(output_width) * output_height * 8;
    const std::string shader_manifest_data = [&] {
        const auto bytes = read_binary_file(FSR4N10_FSR3_SHADER_MANIFEST);
        return std::string(reinterpret_cast<const char*>(bytes.data()), bytes.size());
    }();
    const std::string shader_manifest_hash = sha256_hex(shader_manifest_data);

    TargetDevice target = create_target_device();
    D3D12_COMMAND_QUEUE_DESC queue_description{};
    queue_description.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
    ComPtr<ID3D12CommandQueue> queue;
    check_hr(target.device->CreateCommandQueue(&queue_description, IID_PPV_ARGS(&queue)), "CreateCommandQueue failed");
    ComPtr<ID3D12CommandAllocator> allocator;
    check_hr(target.device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&allocator)),
             "CreateCommandAllocator failed");
    ComPtr<ID3D12GraphicsCommandList> command_list;
    check_hr(target.device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, allocator.Get(), nullptr,
                                              IID_PPV_ARGS(&command_list)), "CreateCommandList failed");
    check_hr(command_list->Close(), "Close(initial command list) failed");
    QueueWaiter waiter(target.device.Get());
    GpuDispatchTimer gpu_timer(target.device.Get(), queue.Get());

    Fsr3UploadInputs inputs;
    inputs.color = create_texture(target.device.Get(), render_width, render_height, DXGI_FORMAT_R16G16B16A16_FLOAT,
                                  D3D12_RESOURCE_STATE_COPY_DEST);
    inputs.depth = create_texture(target.device.Get(), render_width, render_height, DXGI_FORMAT_R32_FLOAT,
                                  D3D12_RESOURCE_STATE_COPY_DEST);
    inputs.motion = create_texture(target.device.Get(), render_width, render_height, DXGI_FORMAT_R16G16_FLOAT,
                                   D3D12_RESOURCE_STATE_COPY_DEST);
    inputs.exposure = create_texture(target.device.Get(), 1, 1, DXGI_FORMAT_R32_FLOAT,
                                     D3D12_RESOURCE_STATE_COPY_DEST);
    inputs.reactive = create_texture(target.device.Get(), render_width, render_height, DXGI_FORMAT_R8_UNORM,
                                     D3D12_RESOURCE_STATE_COPY_DEST);
    inputs.transparency = create_texture(target.device.Get(), render_width, render_height, DXGI_FORMAT_R8_UNORM,
                                         D3D12_RESOURCE_STATE_COPY_DEST);
    auto instrumented_output = create_texture(target.device.Get(), output_width, output_height,
                                               DXGI_FORMAT_R16G16B16A16_FLOAT,
                                               D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
                                               D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS);
    auto reference_output = create_texture(target.device.Get(), output_width, output_height,
                                            DXGI_FORMAT_R16G16B16A16_FLOAT,
                                            D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
                                            D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS);

    ffxCreateBackendDX12Desc backend_description{};
    backend_description.header.type = FFX_API_CREATE_CONTEXT_DESC_TYPE_BACKEND_DX12;
    backend_description.device = target.device.Get();
    ffxCreateContextDescUpscale context_description{};
    context_description.header.type = FFX_API_CREATE_CONTEXT_DESC_TYPE_UPSCALE;
    context_description.header.pNext = &backend_description.header;
    context_description.maxRenderSize = {render_width, render_height};
    context_description.maxUpscaleSize = {output_width, output_height};
    context_description.flags = FFX_UPSCALE_ENABLE_HIGH_DYNAMIC_RANGE;
    Fsr3ProviderContext instrumented_context;
    check_ffx(ffxProvider_FSR3Upscale::GetInstance().CreateContext(
                  instrumented_context.address(), &context_description.header, instrumented_context.allocator()),
              "FSR3 instrumented CreateContext");
    Fsr3ProviderContext reference_context;
    check_ffx(ffxProvider_FSR3Upscale::GetInstance().CreateContext(
                  reference_context.address(), &context_description.header, reference_context.allocator()),
              "FSR3 reference CreateContext");

    ffxDispatchDescUpscale dispatch{};
    dispatch.header.type = FFX_API_DISPATCH_DESC_TYPE_UPSCALE;
    dispatch.color = ffxApiGetResourceDX12(inputs.color.Get(), FFX_API_RESOURCE_STATE_COMPUTE_READ);
    dispatch.depth = ffxApiGetResourceDX12(inputs.depth.Get(), FFX_API_RESOURCE_STATE_COMPUTE_READ);
    dispatch.motionVectors = ffxApiGetResourceDX12(inputs.motion.Get(), FFX_API_RESOURCE_STATE_COMPUTE_READ);
    dispatch.exposure = ffxApiGetResourceDX12(inputs.exposure.Get(), FFX_API_RESOURCE_STATE_COMPUTE_READ);
    dispatch.motionVectorScale = {1.0f, 1.0f};
    dispatch.renderSize = {render_width, render_height};
    dispatch.upscaleSize = {output_width, output_height};
    dispatch.enableSharpening = false;
    dispatch.sharpness = 0.0f;
    dispatch.cameraNear = 0.1f;
    dispatch.cameraFar = 1000.0f;
    dispatch.cameraFovAngleVertical = 1.0f;
    dispatch.viewSpaceToMetersFactor = 1.0f;

    std::set<std::uint32_t> audit_frames;
    if (!capture_root.empty()) {
        audit_frames.insert(0);
        audit_frames.insert(metadata.frame_count - 1);
        for (std::uint32_t index = 0; index < metadata.frame_count; ++index) {
            const auto& frame = sequence.frame_metadata(index);
            if (frame.camera_cut || frame.reset) audit_frames.insert(index);
        }
    }

    std::vector<std::string> frame_reports;
    frame_reports.reserve(metadata.frame_count);
    std::vector<double> reference_gpu_times;
    std::vector<double> steady_state_gpu_times;
    reference_gpu_times.reserve(metadata.frame_count);
    steady_state_gpu_times.reserve(metadata.frame_count);
    bool all_match = true;
    for (std::uint32_t frame_index = 0; frame_index < metadata.frame_count; ++frame_index) {
        SequenceFrame frame = sequence.read_frame(frame_index);
        upload_frame_inputs(target.device.Get(), queue.Get(), allocator.Get(), command_list.Get(), waiter,
                           inputs, frame, render_width, render_height);
        const std::string input_hash = sequence_frame_input_sha256(frame);
        const bool audit = audit_frames.contains(frame_index);
        double reference_gpu_time_us = 0.0;

        const auto run_dispatch = [&](Fsr3ProviderContext& context, ID3D12Resource* output_texture,
                                      bool instrumented_provider, bool capture_taps) {
            check_hr(allocator->Reset(), "ID3D12CommandAllocator::Reset(before FSR3 dispatch) failed");
            check_hr(command_list->Reset(allocator.Get(), nullptr), "ID3D12GraphicsCommandList::Reset(before FSR3 dispatch) failed");
            dispatch.commandList = ffxGetCommandListDX12(command_list.Get());
            dispatch.output = ffxApiGetResourceDX12(output_texture, FFX_API_RESOURCE_STATE_UNORDERED_ACCESS);
            dispatch.jitterOffset = {frame.metadata.jitter_x, frame.metadata.jitter_y};
            dispatch.frameTimeDelta = frame.metadata.frame_time_delta_ms;
            dispatch.preExposure = frame.metadata.pre_exposure;
            dispatch.reset = frame.metadata.reset;
            dispatch.reactive = frame.metadata.reactive_mask_valid
                ? ffxApiGetResourceDX12(inputs.reactive.Get(), FFX_API_RESOURCE_STATE_COMPUTE_READ)
                : FfxApiResource{};
            dispatch.transparencyAndComposition = frame.metadata.transparency_composition_mask_valid
                ? ffxApiGetResourceDX12(inputs.transparency.Get(), FFX_API_RESOURCE_STATE_COMPUTE_READ)
                : FfxApiResource{};
            if (!instrumented_provider) gpu_timer.begin(command_list.Get());
            check_ffx(ffxProvider_FSR3Upscale::GetInstance().Dispatch(context.address(), &dispatch.header),
                      instrumented_provider ? "FSR3 instrumented Dispatch" : "FSR3 reference Dispatch");
            if (!instrumented_provider) gpu_timer.end_and_resolve(command_list.Get());

            std::vector<CapturedTexture> textures;
            textures.push_back(capture_texture("final_output", output_texture,
                                               D3D12_RESOURCE_STATE_UNORDERED_ACCESS));
            if (capture_taps) {
                std::unordered_set<ID3D12Resource*> seen{output_texture};
                add_fsr3_tap(context.address(), kFsr3ResourceDilatedMotionVectors, "dilated_motion_vectors", textures, seen);
                add_fsr3_tap(context.address(), kFsr3ResourceDilatedDepth, "dilated_depth", textures, seen);
                add_fsr3_tap(context.address(), kFsr3ResourcePreviousNearestDepth, "reconstructed_previous_nearest_depth", textures, seen);
                add_fsr3_tap(context.address(), kFsr3ResourceInternalUpscaledColor, "internal_upscaled_color_after_accumulate", textures, seen);
                add_fsr3_tap(context.address(), kFsr3ResourceAccumulation, "accumulation_state", textures, seen);
                add_fsr3_tap(context.address(), kFsr3ResourceNewLocks, "new_locks", textures, seen);
                add_fsr3_tap(context.address(), kFsr3ResourceLumaHistory, "luma_history", textures, seen);
                add_fsr3_tap(context.address(), kFsr3ResourceShadingChange, "shading_change", textures, seen);
                add_fsr3_tap(context.address(), kFsr3ResourceLumaInstability, "luma_instability_or_shared_intermediate", textures, seen);
            }
            std::vector<TextureReadbackRequest> requests;
            requests.reserve(textures.size());
            for (const auto& texture : textures)
                requests.push_back({texture.texture, texture.state, texture.format.bytes_per_pixel});
            auto data = read_textures(target.device.Get(), queue.Get(), command_list.Get(), waiter, requests);
            if (data.size() != textures.size() || data.front().size() != output_bytes)
                throw std::runtime_error("FSR3 output readback has an unexpected size");
            if (!instrumented_provider) reference_gpu_time_us = gpu_timer.elapsed_microseconds();
            return std::pair{std::move(textures), std::move(data)};
        };

        auto instrumented = run_dispatch(instrumented_context, instrumented_output.Get(), true, audit);
        auto reference = run_dispatch(reference_context, reference_output.Get(), false, false);
        reference_gpu_times.push_back(reference_gpu_time_us);
        if (frame_index != 0 && !frame.metadata.reset && !frame.metadata.camera_cut)
            steady_state_gpu_times.push_back(reference_gpu_time_us);
        const bool matches = instrumented.second.front() == reference.second.front();
        all_match = all_match && matches;
        if (!matches) {
            std::ostringstream error;
            error << "FSR3 instrumented/reference outputs differ on frame " << frame_index
                  << " (input SHA-256 " << input_hash << ')';
            throw std::runtime_error(error.str());
        }
        const std::string output_hash = sha256_hex(instrumented.second.front());
        std::string capture_manifest;
        if (audit) {
            const auto frame_root = capture_root / ("frame_" + std::to_string(frame_index));
            const auto arrays_dir = frame_root / "arrays";
            std::vector<CaptureDescriptor> descriptors;
            descriptors.push_back(write_capture_array(arrays_dir, "input_color", "<f2", render_width,
                                                       render_height, 4, bytes_from_values(frame.color_rgba_half)));
            descriptors.push_back(write_capture_array(arrays_dir, "depth", "<f4", render_width,
                                                       render_height, 1, bytes_from_values(frame.depth)));
            descriptors.push_back(write_capture_array(arrays_dir, "motion_vectors", "<f2", render_width,
                                                       render_height, 2, bytes_from_values(frame.motion_vectors_half)));
            if (frame.metadata.reactive_mask_valid) {
                descriptors.push_back(write_capture_array(arrays_dir, "reactive_mask", "|u1", render_width,
                                                           render_height, 1, bytes_from_values(frame.reactive_mask)));
            }
            if (frame.metadata.transparency_composition_mask_valid) {
                descriptors.push_back(write_capture_array(arrays_dir, "transparency_composition_mask", "|u1", render_width,
                                                           render_height, 1, bytes_from_values(frame.transparency_composition_mask)));
            }
            for (std::size_t index = 0; index < instrumented.first.size(); ++index) {
                const auto& texture = instrumented.first[index];
                descriptors.push_back(write_capture_array(arrays_dir, texture.name, texture.format.dtype,
                                                           texture.width, texture.height, texture.format.channels,
                                                           instrumented.second[index]));
            }
            const auto manifest_path = frame_root / "manifest.json";
            write_capture_manifest(manifest_path, metadata, frame, target, input_hash,
                                   shader_manifest_hash, descriptors);
            capture_manifest = manifest_path.string();
        }

        std::ostringstream frame_json;
        frame_json << "    {\"frame_index\": " << frame_index
                   << ", \"reset\": " << (frame.metadata.reset ? "true" : "false")
                   << ", \"camera_cut\": " << (frame.metadata.camera_cut ? "true" : "false")
                   << ", \"input_frame_sha256\": \"" << input_hash << '\"'
                   << ", \"instrumented_output_sha256\": \"" << output_hash << '\"'
                   << ", \"reference_output_sha256\": \"" << sha256_hex(reference.second.front()) << '\"'
                   << ", \"reference_gpu_dispatch_us\": " << std::setprecision(9) << reference_gpu_time_us
                   << ", \"instrumented_reference_match\": true";
        if (!capture_manifest.empty()) frame_json << ", \"capture_manifest\": \"" << json_escape(capture_manifest) << '\"';
        frame_json << '}';
        frame_reports.push_back(frame_json.str());
    }

    if (!report_path.parent_path().empty()) std::filesystem::create_directories(report_path.parent_path());
    std::ofstream report(report_path, std::ios::binary | std::ios::trunc);
    if (!report) throw std::runtime_error("cannot write FSR3 sequence report: " + report_path.string());
    const auto mean = [](const std::vector<double>& values) {
        if (values.empty()) return 0.0;
        return std::accumulate(values.begin(), values.end(), 0.0) / static_cast<double>(values.size());
    };
    const auto percentile = [](std::vector<double> values, double fraction) {
        if (values.empty()) return 0.0;
        std::sort(values.begin(), values.end());
        const auto rank = static_cast<std::size_t>(std::ceil(fraction * static_cast<double>(values.size())));
        return values[std::max<std::size_t>(1, rank) - 1];
    };
    report << "{\n"
           << "  \"schema\": \"f4n10.fsr3-reference-sequence.v1\",\n"
           << "  \"provider\": \"FidelityFX FSR3 Upscaler 3.1.5\",\n"
           << "  \"sdk_commit\": \"" << FSR4N10_FSR3_SDK_COMMIT << "\",\n"
           << "  \"shader_manifest\": \"" << json_escape(FSR4N10_FSR3_SHADER_MANIFEST) << "\",\n"
           << "  \"shader_manifest_sha256\": \"" << shader_manifest_hash << "\",\n"
           << "  \"build_commit\": \"" << FSR4N10_BUILD_COMMIT << "\",\n"
           << "  \"build_mode\": \"" << FSR4N10_BUILD_CONFIGURATION << "\",\n"
           << "  \"gpu_name\": \"" << json_escape(target.adapter_name) << "\",\n"
           << "  \"driver_version\": \"" << json_escape(target.driver_version) << "\",\n"
           << "  \"sequence\": {\"id\": \"" << json_escape(metadata.sequence_id)
           << "\", \"source_kind\": \"" << json_escape(metadata.source_kind)
           << "\", \"source_hash\": \"" << metadata.source_hash
           << "\", \"sequence_hash\": \"" << metadata.sequence_hash
           << "\", \"frame_count\": " << metadata.frame_count
           << ", \"render_size\": [" << render_width << ", " << render_height
           << "], \"output_size\": [" << output_width << ", " << output_height
           << "], \"motion_vector_convention\": \"current_to_previous_render_pixels_unjittered\"},\n"
           << "  \"dispatch\": {\"hdr_linear_color\": true, \"jitter_cancellation\": false, \"depth_inverted\": false, "
           << "\"sharpening\": false, \"watermark_injection_enabled\": false, \"camera_near\": 0.1, \"camera_far\": 1000.0, "
           << "\"camera_fov_vertical_radians\": 1.0, \"view_space_to_meters_factor\": 1.0},\n"
           << "  \"gpu_timing\": {\"source\": \"D3D12 timestamp queries around non-instrumented FSR3 provider Dispatch\", "
           << "\"scope\": \"provider GPU work only; excludes input upload, output readback, CPU and packaging\", "
           << "\"timestamp_frequency_hz\": " << gpu_timer.frequency()
           << ", \"all_frames_mean_us\": " << mean(reference_gpu_times)
           << ", \"steady_state_excludes_first_reset_and_cuts\": true"
           << ", \"steady_state_frame_count\": " << steady_state_gpu_times.size()
           << ", \"steady_state_mean_us\": " << mean(steady_state_gpu_times)
           << ", \"steady_state_p50_us\": " << percentile(steady_state_gpu_times, 0.50)
           << ", \"steady_state_p95_us\": " << percentile(steady_state_gpu_times, 0.95) << "},\n"
           << "  \"validation\": {\"instrumented_reference_outputs_match\": " << (all_match ? "true" : "false")
           << ", \"gpu_timing_recorded\": true, \"quality_claimed\": false},\n"
           << "  \"frames\": [\n";
    for (std::size_t index = 0; index < frame_reports.size(); ++index)
        report << frame_reports[index] << (index + 1 == frame_reports.size() ? "\n" : ",\n");
    report << "  ]\n}\n";
    if (!report) throw std::runtime_error("failed writing FSR3 sequence report: " + report_path.string());

    std::cout << "Pinned FSR3.1.5 completed " << metadata.frame_count << " stateful frame dispatches on "
              << target.adapter_name << "; instrumented/ordinary output equality: " << (all_match ? "yes" : "no") << ".\n"
              << "Input source kind: " << metadata.source_kind
              << "; fixed camera profile is recorded because f4seq v2 does not contain projection values.\n"
              << "No quality or performance claim is made by this validation run.\n"
              << "Report: " << report_path.string() << ".\n";
    return 0;
}

} // namespace fsr4n10
