#include "fsr4n10/gpu_teacher.h"
#include "fsr4n10/sequence.h"

#include "ffx_api_dx12.h"
#include "ffx_dx12.h"
#include "ffx_provider_fsr4.h"
#include "ffx_upscale.h"

#include <Windows.h>
#include <bcrypt.h>
#include <d3d12.h>
#include <dxgi1_6.h>
#include <wrl/client.h>

#include <array>
#include <algorithm>
#include <bit>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <numeric>
#include <sstream>
#include <set>
#include <stdexcept>
#include <string>
#include <system_error>
#include <vector>

#ifndef FSR4N10_FSR4_SOURCE_COMMIT
#error FSR4N10_FSR4_SOURCE_COMMIT must be supplied from third_party/LOCK.json
#endif
#ifndef FSR4N10_BUILD_COMMIT
#error FSR4N10_BUILD_COMMIT must be supplied from the repository HEAD
#endif
#ifndef FSR4N10_BUILD_CONFIGURATION
#error FSR4N10_BUILD_CONFIGURATION must be supplied by the active CMake configuration
#endif
#ifndef FSR4N10_PROVIDER_SHADER_MANIFEST
#error FSR4N10_PROVIDER_SHADER_MANIFEST must identify the generated shader manifest
#endif

extern "C" FfxApiResource fsr4n10GetInternalResource(ffxContext* context, std::uint32_t resourceId,
                                                      bool unorderedAccess);

namespace fsr4n10 {
namespace {

using Microsoft::WRL::ComPtr;

constexpr std::uint32_t kWidth = 1920;
constexpr std::uint32_t kHeight = 1080;
constexpr std::size_t kOutputBytesPerPixel = 8;
// Resource IDs come from the pinned provider's FfxFsr4UpscalerResourceIdentifier enum.
constexpr std::uint32_t kFsr4ResourceRecurrent = 13;
constexpr std::uint32_t kFsr4ResourceHistoryReprojected = 15;
constexpr std::uint32_t kFsr4ResourceDebugInformation = 23;

void check_hr(HRESULT result, const char* operation) {
    if (FAILED(result)) {
        std::ostringstream message;
        message << operation << " failed (HRESULT 0x" << std::hex << static_cast<std::uint32_t>(result) << ")";
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

D3D12_HEAP_PROPERTIES heap_properties(D3D12_HEAP_TYPE type) {
    D3D12_HEAP_PROPERTIES properties{};
    properties.Type = type;
    properties.CreationNodeMask = 1;
    properties.VisibleNodeMask = 1;
    return properties;
}

ComPtr<ID3D12Resource> create_texture(
    ID3D12Device* device,
    std::uint32_t width,
    std::uint32_t height,
    DXGI_FORMAT format,
    D3D12_RESOURCE_STATES state,
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
    check_hr(device->CreateCommittedResource(
                 &properties,
                 D3D12_HEAP_FLAG_NONE,
                 &description,
                 state,
                 nullptr,
                 IID_PPV_ARGS(&resource)),
             "CreateCommittedResource(texture) failed");
    return resource;
}

ComPtr<ID3D12Resource> create_buffer(
    ID3D12Device* device,
    D3D12_HEAP_TYPE heap_type,
    D3D12_RESOURCE_STATES state,
    std::uint64_t byte_size) {
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
    check_hr(device->CreateCommittedResource(
                 &properties,
                 D3D12_HEAP_FLAG_NONE,
                 &description,
                 state,
                 nullptr,
                 IID_PPV_ARGS(&resource)),
             "CreateCommittedResource(buffer) failed");
    return resource;
}

ComPtr<ID3D12Resource> upload_texture(
    ID3D12Device* device,
    ID3D12GraphicsCommandList* command_list,
    ID3D12Resource* destination,
    std::uint32_t width,
    std::uint32_t height,
    std::size_t bytes_per_pixel,
    const std::byte* source,
    std::size_t source_size) {
    const auto description = destination->GetDesc();
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};
    UINT rows = 0;
    UINT64 row_size = 0;
    UINT64 upload_size = 0;
    device->GetCopyableFootprints(&description, 0, 1, 0, &footprint, &rows, &row_size, &upload_size);
    const std::size_t source_row_bytes = static_cast<std::size_t>(width) * bytes_per_pixel;
    if (rows != height || row_size != source_row_bytes || source_size != source_row_bytes * height) {
        throw std::runtime_error("upload texture layout does not match source dimensions");
    }

    auto upload = create_buffer(device, D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ, upload_size);
    std::byte* mapped = nullptr;
    D3D12_RANGE no_cpu_reads{0, 0};
    check_hr(upload->Map(0, &no_cpu_reads, reinterpret_cast<void**>(&mapped)), "Map(upload texture) failed");
    for (std::uint32_t row = 0; row < height; ++row) {
        std::memcpy(
            mapped + footprint.Offset + static_cast<std::size_t>(row) * footprint.Footprint.RowPitch,
            source + static_cast<std::size_t>(row) * source_row_bytes,
            source_row_bytes);
    }
    upload->Unmap(0, nullptr);

    D3D12_TEXTURE_COPY_LOCATION destination_location{};
    destination_location.pResource = destination;
    destination_location.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    destination_location.SubresourceIndex = 0;
    D3D12_TEXTURE_COPY_LOCATION source_location{};
    source_location.pResource = upload.Get();
    source_location.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
    source_location.PlacedFootprint = footprint;
    command_list->CopyTextureRegion(&destination_location, 0, 0, 0, &source_location, nullptr);
    return upload;
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

std::string sha256_hex(const std::vector<std::byte>& data) {
    BCRYPT_ALG_HANDLE algorithm = nullptr;
    BCRYPT_HASH_HANDLE hash = nullptr;
    try {
        NTSTATUS status = BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0);
        if (status < 0) {
            throw std::runtime_error("BCryptOpenAlgorithmProvider(SHA-256) failed");
        }
        DWORD object_size = 0;
        DWORD result_size = 0;
        status = BCryptGetProperty(algorithm, BCRYPT_OBJECT_LENGTH,
                                   reinterpret_cast<PUCHAR>(&object_size), sizeof(object_size), &result_size, 0);
        if (status < 0) {
            throw std::runtime_error("BCryptGetProperty(BCRYPT_OBJECT_LENGTH) failed");
        }
        std::vector<UCHAR> object(object_size);
        status = BCryptCreateHash(algorithm, &hash, object.data(), object_size, nullptr, 0, 0);
        if (status < 0) {
            throw std::runtime_error("BCryptCreateHash failed");
        }
        if (!data.empty()) {
            status = BCryptHashData(hash, reinterpret_cast<PUCHAR>(const_cast<std::byte*>(data.data())),
                                    static_cast<ULONG>(data.size()), 0);
            if (status < 0) {
                throw std::runtime_error("BCryptHashData failed");
            }
        }
        std::array<UCHAR, 32> digest{};
        status = BCryptFinishHash(hash, digest.data(), static_cast<ULONG>(digest.size()), 0);
        if (status < 0) {
            throw std::runtime_error("BCryptFinishHash failed");
        }
        BCryptDestroyHash(hash);
        BCryptCloseAlgorithmProvider(algorithm, 0);
        std::ostringstream output;
        output << std::hex << std::setfill('0');
        for (UCHAR byte : digest) {
            output << std::setw(2) << static_cast<unsigned>(byte);
        }
        return output.str();
    } catch (...) {
        if (hash != nullptr) {
            BCryptDestroyHash(hash);
        }
        if (algorithm != nullptr) {
            BCryptCloseAlgorithmProvider(algorithm, 0);
        }
        throw;
    }
}

bool all_half_values_are_finite(const std::vector<std::byte>& data) noexcept {
    if (data.size() % sizeof(std::uint16_t) != 0) {
        return false;
    }
    for (std::size_t offset = 0; offset < data.size(); offset += sizeof(std::uint16_t)) {
        std::uint16_t value = 0;
        std::memcpy(&value, data.data() + offset, sizeof(value));
        if ((value & 0x7c00U) == 0x7c00U) {
            return false;
        }
    }
    return true;
}

bool all_float_values_are_finite(const std::vector<std::byte>& data) noexcept {
    if (data.size() % sizeof(float) != 0) {
        return false;
    }
    for (std::size_t offset = 0; offset < data.size(); offset += sizeof(float)) {
        float value = 0.0f;
        std::memcpy(&value, data.data() + offset, sizeof(value));
        if (!std::isfinite(value)) {
            return false;
        }
    }
    return true;
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
                output << "\\u" << std::hex << std::setw(4) << std::setfill('0') << static_cast<unsigned>(character);
            } else {
                output << static_cast<char>(character);
            }
        }
    }
    return output.str();
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
        if (event_ == nullptr) {
            throw std::system_error(static_cast<int>(GetLastError()), std::system_category(), "CreateEventW failed");
        }
    }
    ~QueueWaiter() {
        if (event_ != nullptr) {
            CloseHandle(event_);
        }
    }
    void wait(ID3D12CommandQueue* queue) {
        const UINT64 value = ++value_;
        check_hr(queue->Signal(fence_.Get(), value), "ID3D12CommandQueue::Signal failed");
        if (fence_->GetCompletedValue() < value) {
            check_hr(fence_->SetEventOnCompletion(value, event_), "ID3D12Fence::SetEventOnCompletion failed");
            const DWORD wait_result = WaitForSingleObject(event_, INFINITE);
            if (wait_result != WAIT_OBJECT_0) {
                throw std::system_error(static_cast<int>(GetLastError()), std::system_category(), "WaitForSingleObject failed");
            }
        }
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
        if (frequency_ == 0) {
            throw std::runtime_error("D3D12 timestamp frequency is zero");
        }
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
        if (end < start) {
            throw std::runtime_error("D3D12 timestamp query returned a negative interval");
        }
        return static_cast<double>(end - start) * 1'000'000.0 / static_cast<double>(frequency_);
    }

    [[nodiscard]] UINT64 frequency() const noexcept { return frequency_; }

private:
    ComPtr<ID3D12QueryHeap> query_heap_;
    ComPtr<ID3D12Resource> readback_;
    UINT64 frequency_ = 0;
};

class ProviderContext {
public:
    ~ProviderContext() {
        if (value_ != nullptr) {
            (void)ffxProvider_FSR4::Instance.DestroyContext(&value_, allocator_);
        }
    }
    ffxContext* address() noexcept { return &value_; }
    ffxContext get() const noexcept { return value_; }
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
    default: throw std::runtime_error("unsupported FidelityFX internal resource state for readback");
    }
}

std::vector<std::vector<std::byte>> read_textures(
    ID3D12Device* device,
    ID3D12CommandQueue* queue,
    ID3D12CommandAllocator* allocator,
    ID3D12GraphicsCommandList* command_list,
    QueueWaiter& waiter,
    const std::vector<TextureReadbackRequest>& requests,
    bool command_list_contains_dispatch) {
    if (requests.empty()) {
        return {};
    }
    if (!command_list_contains_dispatch) {
        check_hr(allocator->Reset(), "ID3D12CommandAllocator::Reset(before readback) failed");
        check_hr(command_list->Reset(allocator, nullptr), "ID3D12GraphicsCommandList::Reset(before readback) failed");
    }

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
        if (request.resource == nullptr || request.bytes_per_pixel == 0) {
            throw std::runtime_error("invalid texture readback request");
        }
        const auto description = request.resource->GetDesc();
        device->GetCopyableFootprints(&description, 0, 1, 0, &pending[index].footprint,
                                      &pending[index].rows, &pending[index].row_size, &pending[index].total_size);
        if (pending[index].rows != description.Height ||
            pending[index].row_size != description.Width * request.bytes_per_pixel) {
            throw std::runtime_error("unexpected internal texture readback layout");
        }
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

        D3D12_TEXTURE_COPY_LOCATION source_location{};
        source_location.pResource = request.resource;
        source_location.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        source_location.SubresourceIndex = 0;
        D3D12_TEXTURE_COPY_LOCATION destination_location{};
        destination_location.pResource = pending[index].buffer.Get();
        destination_location.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
        destination_location.PlacedFootprint = pending[index].footprint;
        command_list->CopyTextureRegion(&destination_location, 0, 0, 0, &source_location, nullptr);

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
    ID3D12CommandList* command_lists[]{command_list};
    queue->ExecuteCommandLists(1, command_lists);
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
        D3D12_RANGE no_writes{0, 0};
        item.buffer->Unmap(0, &no_writes);
    }
    return results;
}

FfxApiResource get_provider_resource(ffxContext* context, std::uint32_t resource_id, bool unordered_access) {
    FfxApiResource resource = fsr4n10GetInternalResource(context, resource_id, unordered_access);
    if (resource.resource == nullptr) {
        throw std::runtime_error("FSR4 provider did not expose the requested capture resource");
    }
    return resource;
}

std::vector<std::byte> extract_rgba16_rgb(const std::vector<std::byte>& rgba, std::size_t pixels) {
    constexpr std::size_t input_pixel_bytes = 4 * sizeof(std::uint16_t);
    constexpr std::size_t output_pixel_bytes = 3 * sizeof(std::uint16_t);
    if (rgba.size() != pixels * input_pixel_bytes) {
        throw std::runtime_error("RGBA16F capture array has an unexpected size");
    }
    std::vector<std::byte> rgb(pixels * output_pixel_bytes);
    for (std::size_t pixel = 0; pixel < pixels; ++pixel) {
        std::memcpy(rgb.data() + pixel * output_pixel_bytes,
                    rgba.data() + pixel * input_pixel_bytes,
                    output_pixel_bytes);
    }
    return rgb;
}

std::vector<std::byte> extract_rgba32_region(
    const std::vector<std::byte>& data,
    std::uint32_t region,
    std::uint32_t texture_width,
    std::uint32_t width,
    std::uint32_t height,
    std::uint32_t output_channels) {
    constexpr std::size_t rgba_bytes = 4 * sizeof(float);
    if (output_channels == 0 || output_channels > 4 || texture_width < (region + 1) * width ||
        data.size() != static_cast<std::size_t>(texture_width) * height * rgba_bytes) {
        throw std::runtime_error("RGBA32F capture bank has an unexpected shape");
    }
    const std::size_t output_scalar_bytes = output_channels * sizeof(float);
    std::vector<std::byte> output(static_cast<std::size_t>(width) * height * output_scalar_bytes);
    for (std::uint32_t y = 0; y < height; ++y) {
        for (std::uint32_t x = 0; x < width; ++x) {
            const std::size_t source_pixel = static_cast<std::size_t>(y) * texture_width + region * width + x;
            const std::size_t target_pixel = static_cast<std::size_t>(y) * width + x;
            std::memcpy(output.data() + target_pixel * output_scalar_bytes,
                        data.data() + source_pixel * rgba_bytes,
                        output_scalar_bytes);
        }
    }
    return output;
}

std::vector<std::byte> extract_semantic_channels(
    const std::vector<std::byte>& data,
    std::uint32_t texture_width,
    std::uint32_t width,
    std::uint32_t height) {
    constexpr std::size_t rgba_bytes = 4 * sizeof(float);
    if (texture_width < 3 * width || data.size() != static_cast<std::size_t>(texture_width) * height * rgba_bytes) {
        throw std::runtime_error("semantic-channel capture banks have an unexpected shape");
    }
    std::vector<std::byte> output(static_cast<std::size_t>(width) * height * 7 * sizeof(float));
    for (std::uint32_t y = 0; y < height; ++y) {
        for (std::uint32_t x = 0; x < width; ++x) {
            const std::size_t first_pixel = static_cast<std::size_t>(y) * texture_width + width + x;
            const std::size_t second_pixel = static_cast<std::size_t>(y) * texture_width + width * 2 + x;
            std::array<float, 4> first{};
            std::array<float, 4> second{};
            std::memcpy(first.data(), data.data() + first_pixel * rgba_bytes, rgba_bytes);
            std::memcpy(second.data(), data.data() + second_pixel * rgba_bytes, rgba_bytes);
            const std::array<float, 7> values{
                first[0], first[1], first[2], first[3], second[0], second[1], second[2]};
            const std::size_t target_pixel = static_cast<std::size_t>(y) * width + x;
            std::memcpy(output.data() + target_pixel * values.size() * sizeof(float),
                        values.data(), values.size() * sizeof(float));
        }
    }
    return output;
}

std::vector<std::byte> bytes_from_half_rgba(const std::vector<std::uint16_t>& rgba) {
    const auto* first = reinterpret_cast<const std::byte*>(rgba.data());
    return {first, first + rgba.size() * sizeof(std::uint16_t)};
}

template <typename T>
std::vector<std::byte> bytes_from_values(const std::vector<T>& values) {
    const auto* first = reinterpret_cast<const std::byte*>(values.data());
    return {first, first + values.size() * sizeof(T)};
}

void write_binary_file(const std::filesystem::path& path, const std::vector<std::byte>& data) {
    std::filesystem::create_directories(path.parent_path());
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    if (!output) {
        throw std::runtime_error("cannot write capture array: " + path.string());
    }
    output.write(reinterpret_cast<const char*>(data.data()), static_cast<std::streamsize>(data.size()));
    if (!output) {
        throw std::runtime_error("failed writing capture array: " + path.string());
    }
}

std::vector<std::byte> read_binary_file(const std::filesystem::path& path) {
    std::ifstream input(path, std::ios::binary | std::ios::ate);
    if (!input) {
        throw std::runtime_error("cannot read capture provenance file: " + path.string());
    }
    const auto end = input.tellg();
    if (end < 0) {
        throw std::runtime_error("cannot determine capture provenance file size: " + path.string());
    }
    std::vector<std::byte> data(static_cast<std::size_t>(end));
    input.seekg(0, std::ios::beg);
    input.read(reinterpret_cast<char*>(data.data()), static_cast<std::streamsize>(data.size()));
    if (!input) {
        throw std::runtime_error("failed reading capture provenance file: " + path.string());
    }
    return data;
}

void write_capture_manifest(
    const std::filesystem::path& manifest_path,
    const TargetDevice& target,
    const std::vector<std::byte>& input_hash_bytes,
    const std::string& shader_manifest_hash) {
    const auto sequence_hash = sha256_hex(input_hash_bytes);
    std::ofstream manifest(manifest_path, std::ios::binary | std::ios::trunc);
    if (!manifest) {
        throw std::runtime_error("cannot write teacher capture manifest: " + manifest_path.string());
    }
    manifest << std::setprecision(9)
             << "{\n"
             << "  \"schema\": \"f4n10.teacher.capture.v1\",\n"
             << "  \"metadata\": {\n"
             << "    \"sequence_id\": \"synthetic-gradient-checkerboard\",\n"
             << "    \"frame_index\": 0,\n"
             << "    \"preset\": \"native\",\n"
             << "    \"render_width\": " << kWidth << ",\n"
             << "    \"render_height\": " << kHeight << ",\n"
             << "    \"output_width\": " << kWidth << ",\n"
             << "    \"output_height\": " << kHeight << ",\n"
             << "    \"jitter_current\": [0.0, 0.0],\n"
             << "    \"jitter_previous\": [0.0, 0.0],\n"
             << "    \"exposure\": 1.0,\n"
             << "    \"pre_exposure\": 1.0,\n"
             << "    \"reset\": true,\n"
             << "    \"motion_convention\": \"zero vectors; direction is immaterial for this synthetic frame\",\n"
             << "    \"source_commit\": \"" << FSR4N10_FSR4_SOURCE_COMMIT << "\",\n"
             << "    \"source_hash\": \"" << sequence_hash << "\",\n"
             << "    \"sequence_hash\": \"" << sequence_hash << "\",\n"
             << "    \"shader_hashes\": {\"provider_shader_manifest\": \"" << shader_manifest_hash << "\"},\n"
             << "    \"build_commit\": \"" << FSR4N10_BUILD_COMMIT << "\",\n"
             << "    \"build_mode\": \"" << FSR4N10_BUILD_CONFIGURATION << "\",\n"
             << "    \"capture_origin\": \"synthetic_gpu_provider_capture\",\n"
             << "    \"physical_control_transform\": \"capture-only stable tanh/sigmoid equivalent; does not feed reconstruction\",\n"
             << "    \"gpu_name\": \"" << json_escape(target.adapter_name) << "\",\n"
             << "    \"driver_version\": \"" << json_escape(target.driver_version) << "\"\n"
             << "  },\n"
             << "  \"validity\": {\n"
             << "    \"input_color\": true,\n"
             << "    \"depth\": true,\n"
             << "    \"motion_vectors\": true,\n"
             << "    \"reactive_mask\": false,\n"
             << "    \"transparency_composition_mask\": false\n"
             << "  },\n"
             << "  \"arrays\": {\n"
             << "    \"input_color\": {\"file\": \"arrays/input_color.raw\", \"dtype\": \"<f2\", \"shape\": [1080, 1920, 3]},\n"
             << "    \"depth\": {\"file\": \"arrays/depth.raw\", \"dtype\": \"<f4\", \"shape\": [1080, 1920, 1]},\n"
             << "    \"motion_vectors\": {\"file\": \"arrays/motion_vectors.raw\", \"dtype\": \"<f2\", \"shape\": [1080, 1920, 2]},\n"
             << "    \"current_reconstruction_source\": {\"file\": \"arrays/current_reconstruction_source.raw\", \"dtype\": \"<f4\", \"shape\": [1080, 1920, 3]},\n"
             << "    \"reprojected_history\": {\"file\": \"arrays/reprojected_history.raw\", \"dtype\": \"<f2\", \"shape\": [1080, 1920, 3]},\n"
             << "    \"model_input_semantic_channels\": {\"file\": \"arrays/model_input_semantic_channels.raw\", \"dtype\": \"<f4\", \"shape\": [1080, 1920, 7]},\n"
             << "    \"raw_model_parameters\": {\"file\": \"arrays/raw_model_parameters.raw\", \"dtype\": \"<f4\", \"shape\": [1080, 1920, 4]},\n"
             << "    \"physical_controls\": {\"file\": \"arrays/physical_controls.raw\", \"dtype\": \"<f4\", \"shape\": [1080, 1920, 4]},\n"
             << "    \"recurrent_state\": {\"file\": \"arrays/recurrent_state.raw\", \"dtype\": \"|u1\", \"shape\": [1080, 1920, 4]},\n"
             << "    \"final_rgb\": {\"file\": \"arrays/final_rgb.raw\", \"dtype\": \"<f2\", \"shape\": [1080, 1920, 3]}\n"
             << "  }\n"
             << "}\n";
    if (!manifest) {
        throw std::runtime_error("failed writing teacher capture manifest: " + manifest_path.string());
    }
}

std::filesystem::path write_synthetic_teacher_capture(
    const std::filesystem::path& report_path,
    const TargetDevice& target,
    const std::vector<std::uint16_t>& input_color,
    const std::vector<float>& depth,
    const std::vector<std::uint16_t>& motion,
    const std::vector<std::byte>& output_rgba16,
    const std::vector<std::byte>& debug_rgba32,
    const std::vector<std::byte>& recurrent_rgba8,
    const std::vector<std::byte>& reprojected_history_rgba16,
    std::uint32_t debug_width) {
    const auto pixels = static_cast<std::size_t>(kWidth) * kHeight;
    const auto input_rgba_bytes = bytes_from_half_rgba(input_color);
    const auto depth_bytes = bytes_from_values(depth);
    const auto motion_bytes = bytes_from_values(motion);
    std::vector<std::byte> input_hash_bytes;
    input_hash_bytes.reserve(input_rgba_bytes.size() + depth_bytes.size() + motion_bytes.size());
    input_hash_bytes.insert(input_hash_bytes.end(), input_rgba_bytes.begin(), input_rgba_bytes.end());
    input_hash_bytes.insert(input_hash_bytes.end(), depth_bytes.begin(), depth_bytes.end());
    input_hash_bytes.insert(input_hash_bytes.end(), motion_bytes.begin(), motion_bytes.end());

    const auto input_rgb = extract_rgba16_rgb(input_rgba_bytes, pixels);
    const auto final_rgb = extract_rgba16_rgb(output_rgba16, pixels);
    const auto history_rgb = extract_rgba16_rgb(reprojected_history_rgba16, pixels);
    const auto current_rgb = extract_rgba32_region(debug_rgba32, 0, debug_width, kWidth, kHeight, 3);
    const auto semantic = extract_semantic_channels(debug_rgba32, debug_width, kWidth, kHeight);
    const auto raw_parameters = extract_rgba32_region(debug_rgba32, 3, debug_width, kWidth, kHeight, 4);
    const auto physical_controls = extract_rgba32_region(debug_rgba32, 4, debug_width, kWidth, kHeight, 4);
    const bool recurrent_size_valid = recurrent_rgba8.size() == pixels * 4;
    const bool final_rgb_finite = all_half_values_are_finite(final_rgb);
    const bool history_finite = all_half_values_are_finite(history_rgb);
    const bool current_finite = all_float_values_are_finite(current_rgb);
    const bool semantic_finite = all_float_values_are_finite(semantic);
    const bool parameters_finite = all_float_values_are_finite(raw_parameters);
    const bool controls_finite = all_float_values_are_finite(physical_controls);
    if (!recurrent_size_valid || !final_rgb_finite || !history_finite || !current_finite ||
        !semantic_finite || !parameters_finite || !controls_finite) {
        std::ostringstream error;
        std::size_t first_invalid_control = physical_controls.size();
        float invalid_control_value = 0.0f;
        for (std::size_t offset = 0; offset + sizeof(float) <= physical_controls.size(); offset += sizeof(float)) {
            float value = 0.0f;
            std::memcpy(&value, physical_controls.data() + offset, sizeof(value));
            if (!std::isfinite(value)) {
                first_invalid_control = offset / sizeof(float);
                invalid_control_value = value;
                break;
            }
        }
        error << "captured provider arrays invalid: recurrent_size=" << recurrent_rgba8.size()
              << '/' << pixels * 4 << ", final_rgb_finite=" << final_rgb_finite
              << ", history_finite=" << history_finite << ", current_finite=" << current_finite
              << ", semantic_finite=" << semantic_finite << ", parameters_finite=" << parameters_finite
              << ", controls_finite=" << controls_finite;
        if (!controls_finite) {
            error << ", first_invalid_control_pixel=" << first_invalid_control / 4
                  << ", channel=" << first_invalid_control % 4 << ", value=" << invalid_control_value;
            const std::size_t parameter_offset = (first_invalid_control / 4) * 4 * sizeof(float);
            std::array<float, 4> parameters_at_pixel{};
            std::memcpy(parameters_at_pixel.data(), raw_parameters.data() + parameter_offset,
                        sizeof(parameters_at_pixel));
            error << ", parameters_at_pixel=[" << parameters_at_pixel[0] << ',' << parameters_at_pixel[1]
                  << ',' << parameters_at_pixel[2] << ',' << parameters_at_pixel[3] << ']';
        }
        throw std::runtime_error(error.str());
    }

    std::filesystem::path capture_root = report_path.parent_path() /
        (report_path.stem().string() + "_capture") / "frame_0000";
    const auto arrays_dir = capture_root / "arrays";
    write_binary_file(arrays_dir / "input_color.raw", input_rgb);
    write_binary_file(arrays_dir / "depth.raw", depth_bytes);
    write_binary_file(arrays_dir / "motion_vectors.raw", motion_bytes);
    write_binary_file(arrays_dir / "current_reconstruction_source.raw", current_rgb);
    write_binary_file(arrays_dir / "reprojected_history.raw", history_rgb);
    write_binary_file(arrays_dir / "model_input_semantic_channels.raw", semantic);
    write_binary_file(arrays_dir / "raw_model_parameters.raw", raw_parameters);
    write_binary_file(arrays_dir / "physical_controls.raw", physical_controls);
    write_binary_file(arrays_dir / "recurrent_state.raw", recurrent_rgba8);
    write_binary_file(arrays_dir / "final_rgb.raw", final_rgb);

    const auto shader_manifest = read_binary_file(FSR4N10_PROVIDER_SHADER_MANIFEST);
    write_capture_manifest(capture_root / "manifest.json", target, input_hash_bytes, sha256_hex(shader_manifest));
    return capture_root;
}

} // namespace

int run_fsr4_provider_smoke(const std::filesystem::path& report_path) {
    std::size_t wmma_environment_size = 0;
    getenv_s(&wmma_environment_size, nullptr, 0, "MLSR-WMMA");
    if (wmma_environment_size != 0) {
        throw std::runtime_error("unset MLSR-WMMA before this native/1080 I8-only provider smoke");
    }
    std::size_t watermark_environment_size = 0;
    getenv_s(&watermark_environment_size, nullptr, 0, "MLSR-WATERMARK");
    if (watermark_environment_size != 0) {
        throw std::runtime_error("unset MLSR-WATERMARK so the provider smoke output stays deterministic");
    }

    auto target = create_target_device();
    ComPtr<ID3D12CommandQueue> queue;
    D3D12_COMMAND_QUEUE_DESC queue_desc{};
    queue_desc.Type = D3D12_COMMAND_LIST_TYPE_COMPUTE;
    check_hr(target.device->CreateCommandQueue(&queue_desc, IID_PPV_ARGS(&queue)), "CreateCommandQueue failed");
    ComPtr<ID3D12CommandAllocator> allocator;
    check_hr(target.device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_COMPUTE, IID_PPV_ARGS(&allocator)),
             "CreateCommandAllocator failed");
    ComPtr<ID3D12GraphicsCommandList> command_list;
    check_hr(target.device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_COMPUTE, allocator.Get(), nullptr,
                                              IID_PPV_ARGS(&command_list)),
             "CreateCommandList failed");
    QueueWaiter waiter(target.device.Get());

    const std::size_t pixels = static_cast<std::size_t>(kWidth) * kHeight;
    std::vector<std::uint16_t> color(pixels * 4);
    std::vector<std::uint16_t> motion(pixels * 2, 0);
    std::vector<float> depth(pixels, 0.5f);
    for (std::uint32_t y = 0; y < kHeight; ++y) {
        for (std::uint32_t x = 0; x < kWidth; ++x) {
            const std::size_t index = static_cast<std::size_t>(y) * kWidth + x;
            const float checker = ((x / 16U + y / 16U) & 1U) != 0 ? 0.75f : 0.25f;
            color[index * 4 + 0] = float_to_half(static_cast<float>(x) / static_cast<float>(kWidth - 1));
            color[index * 4 + 1] = float_to_half(static_cast<float>(y) / static_cast<float>(kHeight - 1));
            color[index * 4 + 2] = float_to_half(checker);
            color[index * 4 + 3] = float_to_half(1.0f);
        }
    }

    auto color_texture = create_texture(target.device.Get(), kWidth, kHeight, DXGI_FORMAT_R16G16B16A16_FLOAT,
                                        D3D12_RESOURCE_STATE_COPY_DEST);
    auto depth_texture = create_texture(target.device.Get(), kWidth, kHeight, DXGI_FORMAT_R32_FLOAT,
                                        D3D12_RESOURCE_STATE_COPY_DEST);
    auto motion_texture = create_texture(target.device.Get(), kWidth, kHeight, DXGI_FORMAT_R16G16_FLOAT,
                                         D3D12_RESOURCE_STATE_COPY_DEST);
    auto output_texture = create_texture(target.device.Get(), kWidth, kHeight, DXGI_FORMAT_R16G16B16A16_FLOAT,
                                         D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
                                         D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS);

    std::vector<ComPtr<ID3D12Resource>> uploads;
    uploads.push_back(upload_texture(target.device.Get(), command_list.Get(), color_texture.Get(), kWidth, kHeight,
                                     4 * sizeof(std::uint16_t), reinterpret_cast<const std::byte*>(color.data()),
                                     color.size() * sizeof(std::uint16_t)));
    uploads.push_back(upload_texture(target.device.Get(), command_list.Get(), depth_texture.Get(), kWidth, kHeight,
                                     sizeof(float), reinterpret_cast<const std::byte*>(depth.data()),
                                     depth.size() * sizeof(float)));
    uploads.push_back(upload_texture(target.device.Get(), command_list.Get(), motion_texture.Get(), kWidth, kHeight,
                                     2 * sizeof(std::uint16_t), reinterpret_cast<const std::byte*>(motion.data()),
                                     motion.size() * sizeof(std::uint16_t)));
    std::array<D3D12_RESOURCE_BARRIER, 3> to_read{};
    const std::array<ID3D12Resource*, 3> input_resources{color_texture.Get(), depth_texture.Get(), motion_texture.Get()};
    for (std::size_t index = 0; index < to_read.size(); ++index) {
        to_read[index].Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        to_read[index].Transition.pResource = input_resources[index];
        to_read[index].Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
        to_read[index].Transition.StateBefore = D3D12_RESOURCE_STATE_COPY_DEST;
        to_read[index].Transition.StateAfter = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
    }
    command_list->ResourceBarrier(static_cast<UINT>(to_read.size()), to_read.data());
    check_hr(command_list->Close(), "ID3D12GraphicsCommandList::Close(upload) failed");
    ID3D12CommandList* upload_lists[]{command_list.Get()};
    queue->ExecuteCommandLists(1, upload_lists);
    waiter.wait(queue.Get());

    ffxCreateBackendDX12Desc backend_desc{};
    backend_desc.header.type = FFX_API_CREATE_CONTEXT_DESC_TYPE_BACKEND_DX12;
    backend_desc.header.pNext = nullptr;
    backend_desc.device = target.device.Get();
    ffxCreateContextDescUpscale context_desc{};
    context_desc.header.type = FFX_API_CREATE_CONTEXT_DESC_TYPE_UPSCALE;
    context_desc.header.pNext = &backend_desc.header;
    context_desc.maxRenderSize = {kWidth, kHeight};
    context_desc.maxUpscaleSize = {kWidth, kHeight};
    ProviderContext instrumented_context;
    context_desc.flags = FFX_UPSCALE_ENABLE_DEBUG_VISUALIZATION;
    check_ffx(ffxProvider_FSR4::Instance.CreateContext(
                  instrumented_context.address(), &context_desc.header, instrumented_context.allocator()),
              "FSR4 instrumented provider CreateContext");
    ProviderContext reference_context;
    context_desc.flags = 0;
    check_ffx(ffxProvider_FSR4::Instance.CreateContext(
                  reference_context.address(), &context_desc.header, reference_context.allocator()),
              "FSR4 reference provider CreateContext");

    const auto color_resource = ffxApiGetResourceDX12(color_texture.Get(), FFX_API_RESOURCE_STATE_COMPUTE_READ);
    const auto depth_resource = ffxApiGetResourceDX12(depth_texture.Get(), FFX_API_RESOURCE_STATE_COMPUTE_READ);
    const auto motion_resource = ffxApiGetResourceDX12(motion_texture.Get(), FFX_API_RESOURCE_STATE_COMPUTE_READ);
    const auto output_resource = ffxApiGetResourceDX12(output_texture.Get(), FFX_API_RESOURCE_STATE_UNORDERED_ACCESS);
    ffxDispatchDescUpscale dispatch{};
    dispatch.header.type = FFX_API_DISPATCH_DESC_TYPE_UPSCALE;
    dispatch.commandList = ffxGetCommandListDX12(command_list.Get());
    dispatch.color = color_resource;
    dispatch.depth = depth_resource;
    dispatch.motionVectors = motion_resource;
    dispatch.output = output_resource;
    dispatch.jitterOffset = {0.0f, 0.0f};
    dispatch.motionVectorScale = {1.0f, 1.0f};
    dispatch.renderSize = {kWidth, kHeight};
    dispatch.upscaleSize = {kWidth, kHeight};
    dispatch.enableSharpening = false;
    dispatch.sharpness = 0.0f;
    dispatch.frameTimeDelta = 16.6667f;
    dispatch.preExposure = 1.0f;
    dispatch.reset = true;
    dispatch.cameraNear = 0.1f;
    dispatch.cameraFar = 1000.0f;
    dispatch.cameraFovAngleVertical = 1.0f;
    dispatch.viewSpaceToMetersFactor = 1.0f;
    dispatch.flags = 0;

    const auto capture_one_dispatch = [&]() {
        check_hr(allocator->Reset(), "ID3D12CommandAllocator::Reset(before instrumented dispatch) failed");
        check_hr(command_list->Reset(allocator.Get(), nullptr), "ID3D12GraphicsCommandList::Reset(before instrumented dispatch) failed");
        dispatch.commandList = ffxGetCommandListDX12(command_list.Get());
        dispatch.reset = true;
        check_ffx(ffxProvider_FSR4::Instance.Dispatch(instrumented_context.address(), &dispatch.header),
                  "FSR4 instrumented provider Dispatch");

        const auto debug_resource = get_provider_resource(
            instrumented_context.address(), kFsr4ResourceDebugInformation, true);
        const auto recurrent_resource = get_provider_resource(
            instrumented_context.address(), kFsr4ResourceRecurrent, true);
        const auto history_resource = get_provider_resource(
            instrumented_context.address(), kFsr4ResourceHistoryReprojected, true);
        auto* debug_texture = static_cast<ID3D12Resource*>(debug_resource.resource);
        auto* recurrent_texture = static_cast<ID3D12Resource*>(recurrent_resource.resource);
        auto* history_texture = static_cast<ID3D12Resource*>(history_resource.resource);
        const auto debug_desc = debug_texture->GetDesc();
        const auto recurrent_desc = recurrent_texture->GetDesc();
        const auto history_desc = history_texture->GetDesc();
        if (debug_desc.Width != kWidth * 5 || debug_desc.Height != kHeight ||
            debug_desc.Format != DXGI_FORMAT_R32G32B32A32_FLOAT ||
            recurrent_desc.Width != kWidth || recurrent_desc.Height != kHeight ||
            recurrent_desc.Format != DXGI_FORMAT_R8G8B8A8_UNORM ||
            history_desc.Width != kWidth || history_desc.Height != kHeight ||
            history_desc.Format != DXGI_FORMAT_R16G16B16A16_FLOAT) {
            throw std::runtime_error("FSR4 provider capture resource dimensions or formats changed");
        }
        const std::vector<TextureReadbackRequest> requests{
            {output_texture.Get(), D3D12_RESOURCE_STATE_UNORDERED_ACCESS, kOutputBytesPerPixel},
            {debug_texture, dx12_state_from_ffx(debug_resource.state), 4 * sizeof(float)},
            {recurrent_texture, dx12_state_from_ffx(recurrent_resource.state), 4},
            {history_texture, dx12_state_from_ffx(history_resource.state), kOutputBytesPerPixel},
        };
        return read_textures(target.device.Get(), queue.Get(), allocator.Get(), command_list.Get(), waiter,
                             requests, true);
    };

    auto instrumented_output_one = capture_one_dispatch();
    const std::string instrumented_hash_one = sha256_hex(instrumented_output_one[0]);
    const std::string parameter_hash_one = sha256_hex(extract_rgba32_region(
        instrumented_output_one[1], 3, kWidth * 5, kWidth, kHeight, 4));
    const std::string control_hash_one = sha256_hex(extract_rgba32_region(
        instrumented_output_one[1], 4, kWidth * 5, kWidth, kHeight, 4));
    const std::string recurrent_hash_one = sha256_hex(instrumented_output_one[2]);

    check_hr(allocator->Reset(), "ID3D12CommandAllocator::Reset(before reference dispatch) failed");
    check_hr(command_list->Reset(allocator.Get(), nullptr), "ID3D12GraphicsCommandList::Reset(before reference dispatch) failed");
    dispatch.commandList = ffxGetCommandListDX12(command_list.Get());
    check_ffx(ffxProvider_FSR4::Instance.Dispatch(reference_context.address(), &dispatch.header),
              "FSR4 reference provider Dispatch");
    const auto reference_output = read_textures(
        target.device.Get(), queue.Get(), allocator.Get(), command_list.Get(), waiter,
        {{output_texture.Get(), D3D12_RESOURCE_STATE_UNORDERED_ACCESS, kOutputBytesPerPixel}}, true);

    auto instrumented_output_two = capture_one_dispatch();
    const std::string instrumented_hash_two = sha256_hex(instrumented_output_two[0]);
    const std::string parameter_hash_two = sha256_hex(extract_rgba32_region(
        instrumented_output_two[1], 3, kWidth * 5, kWidth, kHeight, 4));
    const std::string control_hash_two = sha256_hex(extract_rgba32_region(
        instrumented_output_two[1], 4, kWidth * 5, kWidth, kHeight, 4));
    const std::string recurrent_hash_two = sha256_hex(instrumented_output_two[2]);

    const std::string reference_hash = sha256_hex(reference_output[0]);
    const bool instrumentation_matches = instrumented_hash_one == reference_hash;
    const bool deterministic_output = instrumented_hash_one == instrumented_hash_two;
    const bool deterministic_taps = parameter_hash_one == parameter_hash_two &&
                                    control_hash_one == control_hash_two &&
                                    recurrent_hash_one == recurrent_hash_two &&
                                    instrumented_output_one[1] == instrumented_output_two[1] &&
                                    instrumented_output_one[2] == instrumented_output_two[2] &&
                                    instrumented_output_one[3] == instrumented_output_two[3];
    const bool finite_output = all_half_values_are_finite(instrumented_output_one[0]) &&
                               all_half_values_are_finite(reference_output[0]);
    if (!finite_output || !deterministic_output || !deterministic_taps || !instrumentation_matches) {
        std::ostringstream message;
        message << "instrumented provider validation failed: finite=" << finite_output
                << ", rgb_match=" << instrumentation_matches
                << ", repeat_rgb=" << deterministic_output
                << ", repeat_taps=" << deterministic_taps
                << ", instrumented_rgb_sha256=" << instrumented_hash_one
                << ", reference_rgb_sha256=" << reference_hash
                << ", repeat_rgb_sha256=" << instrumented_hash_two;
        throw std::runtime_error(message.str());
    }

    const auto capture_root = write_synthetic_teacher_capture(
        report_path, target, color, depth, motion, instrumented_output_one[0], instrumented_output_one[1],
        instrumented_output_one[2], instrumented_output_one[3], kWidth * 5);
    if (!report_path.parent_path().empty()) {
        std::filesystem::create_directories(report_path.parent_path());
    }
    std::ofstream report(report_path, std::ios::binary | std::ios::trunc);
    if (!report) {
        throw std::runtime_error("cannot write provider smoke report: " + report_path.string());
    }
    report << "{\n"
           << "  \"schema\": \"f4n10.fsr4-provider-smoke.v1\",\n"
           << "  \"capture_eligible\": false,\n"
           << "  \"input_kind\": \"synthetic_gradient_checkerboard\",\n"
           << "  \"physical_control_transform\": \"capture-only stable tanh/sigmoid equivalents from raw p0..p3; not fed into reconstruction\",\n"
           << "  \"provider\": \"pinned_amd_fsr4_i8_native_1080\",\n"
            << "  \"upstream_commit\": \"" << FSR4N10_FSR4_SOURCE_COMMIT << "\",\n"
            << "  \"build_commit\": \"" << FSR4N10_BUILD_COMMIT << "\",\n"
            << "  \"adapter\": \"" << json_escape(target.adapter_name) << "\",\n"
            << "  \"driver_version\": \"" << json_escape(target.driver_version) << "\",\n"
            << "  \"pci_id\": \"1002:731F\",\n"
            << "  \"render_size\": [1920, 1080],\n"
            << "  \"output_size\": [1920, 1080],\n"
            << "  \"format\": \"R16G16B16A16_FLOAT\",\n"
           << "  \"reset_dispatches\": 3,\n"
           << "  \"instrumented_output_sha256\": \"" << instrumented_hash_one << "\",\n"
           << "  \"reference_output_sha256\": \"" << reference_hash << "\",\n"
           << "  \"repeat_output_sha256\": \"" << instrumented_hash_two << "\",\n"
           << "  \"input_color_sha256\": \""
           << sha256_hex(extract_rgba16_rgb(bytes_from_half_rgba(color), pixels)) << "\",\n"
           << "  \"current_reconstruction_source_sha256\": \""
           << sha256_hex(extract_rgba32_region(instrumented_output_one[1], 0, kWidth * 5, kWidth, kHeight, 3))
           << "\",\n"
           << "  \"reprojected_history_sha256\": \""
           << sha256_hex(extract_rgba16_rgb(instrumented_output_one[3], pixels)) << "\",\n"
           << "  \"raw_model_parameters_sha256\": \"" << parameter_hash_one << "\",\n"
           << "  \"physical_controls_sha256\": \"" << control_hash_one << "\",\n"
           << "  \"recurrent_state_sha256\": \"" << recurrent_hash_one << "\",\n"
           << "  \"model_input_semantic_channels_sha256\": \""
           << sha256_hex(extract_semantic_channels(instrumented_output_one[1], kWidth * 5, kWidth, kHeight)) << "\",\n"
           << "  \"instrumented_matches_reference\": " << (instrumentation_matches ? "true" : "false") << ",\n"
           << "  \"identical_after_reset\": " << (deterministic_output ? "true" : "false") << ",\n"
           << "  \"identical_taps_after_reset\": " << (deterministic_taps ? "true" : "false") << ",\n"
           << "  \"finite_output_and_taps\": " << (finite_output ? "true" : "false") << ",\n"
           << "  \"capture_manifest\": \""
           << json_escape((capture_root / "manifest.json").string()) << "\"\n"
           << "}\n";
    report.close();
    if (!report) {
        throw std::runtime_error("failed while writing provider smoke report: " + report_path.string());
    }

    std::cout << "Pinned FSR4 I8 provider ran instrumented and reference reset dispatches on " << target.adapter_name
              << "; output equivalence: " << (instrumentation_matches ? "yes" : "no")
              << "; repeatable controls/recurrent taps: " << (deterministic_taps ? "yes" : "no") << ".\n"
              << "Synthetic capture arrays: " << capture_root.string() << " (not real-scene evidence).\n"
              << "Report: " << report_path.string() << ".\n";
    return 0;
}

int run_fsr4_provider_sequence(const std::filesystem::path& sequence_path,
                               const std::filesystem::path& report_path,
                               const std::filesystem::path& capture_root) {
    std::size_t wmma_environment_size = 0;
    getenv_s(&wmma_environment_size, nullptr, 0, "MLSR-WMMA");
    if (wmma_environment_size != 0) {
        throw std::runtime_error("unset MLSR-WMMA before this native/1080 I8-only provider sequence");
    }
    std::size_t watermark_environment_size = 0;
    getenv_s(&watermark_environment_size, nullptr, 0, "MLSR-WATERMARK");
    if (watermark_environment_size != 0) {
        throw std::runtime_error("unset MLSR-WATERMARK so provider sequence output stays deterministic");
    }

    auto sequence = F4Sequence::open(sequence_path);
    const auto& sequence_metadata = sequence.metadata();
    if (sequence_metadata.preset != "native" || sequence_metadata.render_width != kWidth ||
        sequence_metadata.render_height != kHeight || sequence_metadata.output_width != kWidth ||
        sequence_metadata.output_height != kHeight || sequence_metadata.reversed_depth) {
        throw std::runtime_error("the current provider sequence target is native 1920x1080 with forward [0,1] depth");
    }

    auto target = create_target_device();
    ComPtr<ID3D12CommandQueue> queue;
    D3D12_COMMAND_QUEUE_DESC queue_desc{};
    queue_desc.Type = D3D12_COMMAND_LIST_TYPE_COMPUTE;
    check_hr(target.device->CreateCommandQueue(&queue_desc, IID_PPV_ARGS(&queue)),
             "CreateCommandQueue(sequence) failed");
    ComPtr<ID3D12CommandAllocator> allocator;
    check_hr(target.device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_COMPUTE, IID_PPV_ARGS(&allocator)),
             "CreateCommandAllocator(sequence) failed");
    ComPtr<ID3D12GraphicsCommandList> command_list;
    check_hr(target.device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_COMPUTE, allocator.Get(), nullptr,
                                              IID_PPV_ARGS(&command_list)),
             "CreateCommandList(sequence) failed");
    QueueWaiter waiter(target.device.Get());
    GpuDispatchTimer gpu_timer(target.device.Get(), queue.Get());

    auto color_texture = create_texture(target.device.Get(), kWidth, kHeight, DXGI_FORMAT_R16G16B16A16_FLOAT,
                                        D3D12_RESOURCE_STATE_COPY_DEST);
    auto depth_texture = create_texture(target.device.Get(), kWidth, kHeight, DXGI_FORMAT_R32_FLOAT,
                                        D3D12_RESOURCE_STATE_COPY_DEST);
    auto motion_texture = create_texture(target.device.Get(), kWidth, kHeight, DXGI_FORMAT_R16G16_FLOAT,
                                         D3D12_RESOURCE_STATE_COPY_DEST);
    auto exposure_texture = create_texture(target.device.Get(), 1, 1, DXGI_FORMAT_R32_FLOAT,
                                           D3D12_RESOURCE_STATE_COPY_DEST);
    auto reactive_texture = create_texture(target.device.Get(), kWidth, kHeight, DXGI_FORMAT_R8_UNORM,
                                           D3D12_RESOURCE_STATE_COPY_DEST);
    auto transparency_texture = create_texture(target.device.Get(), kWidth, kHeight, DXGI_FORMAT_R8_UNORM,
                                               D3D12_RESOURCE_STATE_COPY_DEST);
    auto instrumented_output_texture = create_texture(
        target.device.Get(), kWidth, kHeight, DXGI_FORMAT_R16G16B16A16_FLOAT,
        D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS);
    auto reference_output_texture = create_texture(
        target.device.Get(), kWidth, kHeight, DXGI_FORMAT_R16G16B16A16_FLOAT,
        D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS);

    ffxCreateBackendDX12Desc backend_desc{};
    backend_desc.header.type = FFX_API_CREATE_CONTEXT_DESC_TYPE_BACKEND_DX12;
    backend_desc.header.pNext = nullptr;
    backend_desc.device = target.device.Get();
    ffxCreateContextDescUpscale context_desc{};
    context_desc.header.type = FFX_API_CREATE_CONTEXT_DESC_TYPE_UPSCALE;
    context_desc.header.pNext = &backend_desc.header;
    context_desc.maxRenderSize = {kWidth, kHeight};
    context_desc.maxUpscaleSize = {kWidth, kHeight};
    context_desc.flags = FFX_UPSCALE_ENABLE_DEBUG_VISUALIZATION;
    ProviderContext instrumented_context;
    check_ffx(ffxProvider_FSR4::Instance.CreateContext(
                  instrumented_context.address(), &context_desc.header, instrumented_context.allocator()),
              "FSR4 instrumented sequence CreateContext");
    context_desc.flags = 0;
    ProviderContext reference_context;
    check_ffx(ffxProvider_FSR4::Instance.CreateContext(
                  reference_context.address(), &context_desc.header, reference_context.allocator()),
              "FSR4 reference sequence CreateContext");

    const auto color_resource = ffxApiGetResourceDX12(color_texture.Get(), FFX_API_RESOURCE_STATE_COMPUTE_READ);
    const auto depth_resource = ffxApiGetResourceDX12(depth_texture.Get(), FFX_API_RESOURCE_STATE_COMPUTE_READ);
    const auto motion_resource = ffxApiGetResourceDX12(motion_texture.Get(), FFX_API_RESOURCE_STATE_COMPUTE_READ);
    const auto exposure_resource = ffxApiGetResourceDX12(exposure_texture.Get(), FFX_API_RESOURCE_STATE_COMPUTE_READ);
    ffxDispatchDescUpscale dispatch{};
    dispatch.header.type = FFX_API_DISPATCH_DESC_TYPE_UPSCALE;
    dispatch.color = color_resource;
    dispatch.depth = depth_resource;
    dispatch.motionVectors = motion_resource;
    dispatch.motionVectorScale = {1.0f, 1.0f};
    dispatch.renderSize = {kWidth, kHeight};
    dispatch.upscaleSize = {kWidth, kHeight};
    dispatch.enableSharpening = false;
    dispatch.sharpness = 0.0f;
    dispatch.cameraNear = 0.1f;
    dispatch.cameraFar = 1000.0f;
    dispatch.cameraFovAngleVertical = 1.0f;
    dispatch.viewSpaceToMetersFactor = 1.0f;
    dispatch.flags = 0;

    const auto shader_manifest_data = read_binary_file(FSR4N10_PROVIDER_SHADER_MANIFEST);
    const auto shader_manifest_hash = sha256_hex(shader_manifest_data);
    const std::size_t pixel_count = static_cast<std::size_t>(kWidth) * kHeight;
    std::array<ID3D12Resource*, 4> input_resources{
        color_texture.Get(), depth_texture.Get(), motion_texture.Get(), exposure_texture.Get()};
    bool inputs_uploaded = false;
    bool reactive_in_read_state = false;
    bool transparency_in_read_state = false;

    const auto upload_frame = [&](const SequenceFrame& frame) {
        if (inputs_uploaded) {
            check_hr(allocator->Reset(), "ID3D12CommandAllocator::Reset(before sequence upload) failed");
            check_hr(command_list->Reset(allocator.Get(), nullptr),
                     "ID3D12GraphicsCommandList::Reset(before sequence upload) failed");
            std::vector<D3D12_RESOURCE_BARRIER> to_copy;
            to_copy.reserve(6);
            const auto add_transition = [&](ID3D12Resource* resource, D3D12_RESOURCE_STATES before,
                                           D3D12_RESOURCE_STATES after) {
                D3D12_RESOURCE_BARRIER barrier{};
                barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
                barrier.Transition.pResource = resource;
                barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
                barrier.Transition.StateBefore = before;
                barrier.Transition.StateAfter = after;
                to_copy.push_back(barrier);
            };
            for (auto* resource : input_resources) {
                add_transition(resource, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,
                               D3D12_RESOURCE_STATE_COPY_DEST);
            }
            if (frame.metadata.reactive_mask_valid && reactive_in_read_state) {
                add_transition(reactive_texture.Get(), D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,
                               D3D12_RESOURCE_STATE_COPY_DEST);
            }
            if (frame.metadata.transparency_composition_mask_valid && transparency_in_read_state) {
                add_transition(transparency_texture.Get(), D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,
                               D3D12_RESOURCE_STATE_COPY_DEST);
            }
            command_list->ResourceBarrier(static_cast<UINT>(to_copy.size()), to_copy.data());
        }
        std::vector<ComPtr<ID3D12Resource>> uploads;
        uploads.push_back(upload_texture(
            target.device.Get(), command_list.Get(), color_texture.Get(), kWidth, kHeight,
            4 * sizeof(std::uint16_t), reinterpret_cast<const std::byte*>(frame.color_rgba_half.data()),
            frame.color_rgba_half.size() * sizeof(std::uint16_t)));
        uploads.push_back(upload_texture(
            target.device.Get(), command_list.Get(), depth_texture.Get(), kWidth, kHeight, sizeof(float),
            reinterpret_cast<const std::byte*>(frame.depth.data()), frame.depth.size() * sizeof(float)));
        uploads.push_back(upload_texture(
            target.device.Get(), command_list.Get(), motion_texture.Get(), kWidth, kHeight,
            2 * sizeof(std::uint16_t), reinterpret_cast<const std::byte*>(frame.motion_vectors_half.data()),
            frame.motion_vectors_half.size() * sizeof(std::uint16_t)));
        const float exposure = frame.metadata.exposure;
        uploads.push_back(upload_texture(
            target.device.Get(), command_list.Get(), exposure_texture.Get(), 1, 1, sizeof(float),
            reinterpret_cast<const std::byte*>(&exposure), sizeof(exposure)));
        if (frame.metadata.reactive_mask_valid) {
            uploads.push_back(upload_texture(
                target.device.Get(), command_list.Get(), reactive_texture.Get(), kWidth, kHeight, 1,
                reinterpret_cast<const std::byte*>(frame.reactive_mask.data()), frame.reactive_mask.size()));
        }
        if (frame.metadata.transparency_composition_mask_valid) {
            uploads.push_back(upload_texture(
                target.device.Get(), command_list.Get(), transparency_texture.Get(), kWidth, kHeight, 1,
                reinterpret_cast<const std::byte*>(frame.transparency_composition_mask.data()),
                frame.transparency_composition_mask.size()));
        }
        std::vector<D3D12_RESOURCE_BARRIER> to_read;
        to_read.reserve(6);
        const auto add_read_transition = [&](ID3D12Resource* resource) {
            D3D12_RESOURCE_BARRIER barrier{};
            barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
            barrier.Transition.pResource = resource;
            barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
            barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_COPY_DEST;
            barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
            to_read.push_back(barrier);
        };
        for (auto* resource : input_resources) add_read_transition(resource);
        if (frame.metadata.reactive_mask_valid) {
            add_read_transition(reactive_texture.Get());
            reactive_in_read_state = true;
        }
        if (frame.metadata.transparency_composition_mask_valid) {
            add_read_transition(transparency_texture.Get());
            transparency_in_read_state = true;
        }
        command_list->ResourceBarrier(static_cast<UINT>(to_read.size()), to_read.data());
        check_hr(command_list->Close(), "ID3D12GraphicsCommandList::Close(sequence upload) failed");
        ID3D12CommandList* lists[]{command_list.Get()};
        queue->ExecuteCommandLists(1, lists);
        waiter.wait(queue.Get());
        inputs_uploaded = true;
    };

    const auto run_dispatch = [&](ProviderContext& context, const SequenceFrameMetadata& frame_metadata,
                                  ID3D12Resource* destination_texture, bool instrumented, bool capture_taps,
                                  bool measure_gpu_time, double* measured_gpu_time_us) {
        check_hr(allocator->Reset(), "ID3D12CommandAllocator::Reset(before sequence dispatch) failed");
        check_hr(command_list->Reset(allocator.Get(), nullptr), "ID3D12GraphicsCommandList::Reset(before sequence dispatch) failed");
        dispatch.commandList = ffxGetCommandListDX12(command_list.Get());
        dispatch.output = ffxApiGetResourceDX12(destination_texture, FFX_API_RESOURCE_STATE_UNORDERED_ACCESS);
        dispatch.exposure = exposure_resource;
        dispatch.reactive = frame_metadata.reactive_mask_valid
            ? ffxApiGetResourceDX12(reactive_texture.Get(), FFX_API_RESOURCE_STATE_COMPUTE_READ)
            : FfxApiResource{};
        dispatch.transparencyAndComposition = frame_metadata.transparency_composition_mask_valid
            ? ffxApiGetResourceDX12(transparency_texture.Get(), FFX_API_RESOURCE_STATE_COMPUTE_READ)
            : FfxApiResource{};
        dispatch.jitterOffset = {frame_metadata.jitter_x, frame_metadata.jitter_y};
        dispatch.frameTimeDelta = frame_metadata.frame_time_delta_ms;
        dispatch.preExposure = frame_metadata.pre_exposure;
        dispatch.reset = frame_metadata.reset;
        if (measure_gpu_time) {
            gpu_timer.begin(command_list.Get());
        }
        check_ffx(ffxProvider_FSR4::Instance.Dispatch(context.address(), &dispatch.header),
                  instrumented ? "FSR4 instrumented sequence Dispatch" : "FSR4 reference sequence Dispatch");
        if (measure_gpu_time) {
            gpu_timer.end_and_resolve(command_list.Get());
        }
        if (!instrumented || !capture_taps) {
            const auto result = read_textures(
                target.device.Get(), queue.Get(), allocator.Get(), command_list.Get(), waiter,
                {{destination_texture, D3D12_RESOURCE_STATE_UNORDERED_ACCESS, kOutputBytesPerPixel}}, true);
            if (measure_gpu_time && measured_gpu_time_us != nullptr) {
                *measured_gpu_time_us = gpu_timer.elapsed_microseconds();
            }
            return result;
        }
        const auto debug_resource = get_provider_resource(
            context.address(), kFsr4ResourceDebugInformation, true);
        const auto recurrent_resource = get_provider_resource(
            context.address(), kFsr4ResourceRecurrent, true);
        const auto history_resource = get_provider_resource(
            context.address(), kFsr4ResourceHistoryReprojected, true);
        auto* debug_texture = static_cast<ID3D12Resource*>(debug_resource.resource);
        auto* recurrent_texture = static_cast<ID3D12Resource*>(recurrent_resource.resource);
        auto* history_texture = static_cast<ID3D12Resource*>(history_resource.resource);
        const auto debug_desc = debug_texture->GetDesc();
        const auto recurrent_desc = recurrent_texture->GetDesc();
        const auto history_desc = history_texture->GetDesc();
        if (debug_desc.Width != kWidth * 5 || debug_desc.Height != kHeight ||
            debug_desc.Format != DXGI_FORMAT_R32G32B32A32_FLOAT ||
            recurrent_desc.Width != kWidth || recurrent_desc.Height != kHeight ||
            recurrent_desc.Format != DXGI_FORMAT_R8G8B8A8_UNORM ||
            history_desc.Width != kWidth || history_desc.Height != kHeight ||
            history_desc.Format != DXGI_FORMAT_R16G16B16A16_FLOAT) {
            throw std::runtime_error("FSR4 provider sequence tap resource dimensions or formats changed");
        }
        return read_textures(
            target.device.Get(), queue.Get(), allocator.Get(), command_list.Get(), waiter,
            {{destination_texture, D3D12_RESOURCE_STATE_UNORDERED_ACCESS, kOutputBytesPerPixel},
             {debug_texture, dx12_state_from_ffx(debug_resource.state), 4 * sizeof(float)},
             {recurrent_texture, dx12_state_from_ffx(recurrent_resource.state), 4},
             {history_texture, dx12_state_from_ffx(history_resource.state), kOutputBytesPerPixel}}, true);
    };

    const auto write_sequence_capture = [&](const SequenceFrame& frame,
                                             const std::vector<std::vector<std::byte>>& capture) {
        if (capture.size() != 4) {
            throw std::runtime_error("sequence audit capture is missing provider taps");
        }
        const auto frame_root = capture_root / ("frame_" + std::to_string(frame.metadata.frame_index));
        const auto arrays_dir = frame_root / "arrays";
        const auto rgba_input = bytes_from_values(frame.color_rgba_half);
        const auto input_color = extract_rgba16_rgb(rgba_input, pixel_count);
        const auto input_depth = bytes_from_values(frame.depth);
        const auto input_motion = bytes_from_values(frame.motion_vectors_half);
        const auto current_source = extract_rgba32_region(capture[1], 0, kWidth * 5, kWidth, kHeight, 3);
        const auto semantic_channels = extract_semantic_channels(capture[1], kWidth * 5, kWidth, kHeight);
        const auto raw_parameters = extract_rgba32_region(capture[1], 3, kWidth * 5, kWidth, kHeight, 4);
        const auto physical_controls = extract_rgba32_region(capture[1], 4, kWidth * 5, kWidth, kHeight, 4);
        const auto reprojected_history = extract_rgba16_rgb(capture[3], pixel_count);
        const auto final_rgb = extract_rgba16_rgb(capture[0], pixel_count);
        write_binary_file(arrays_dir / "input_color.raw", input_color);
        write_binary_file(arrays_dir / "depth.raw", input_depth);
        write_binary_file(arrays_dir / "motion_vectors.raw", input_motion);
        write_binary_file(arrays_dir / "current_reconstruction_source.raw", current_source);
        write_binary_file(arrays_dir / "reprojected_history.raw", reprojected_history);
        write_binary_file(arrays_dir / "model_input_semantic_channels.raw", semantic_channels);
        write_binary_file(arrays_dir / "raw_model_parameters.raw", raw_parameters);
        write_binary_file(arrays_dir / "physical_controls.raw", physical_controls);
        write_binary_file(arrays_dir / "recurrent_state.raw", capture[2]);
        write_binary_file(arrays_dir / "final_rgb.raw", final_rgb);
        if (frame.metadata.reactive_mask_valid) {
            write_binary_file(arrays_dir / "reactive_mask.raw", bytes_from_values(frame.reactive_mask));
        }
        if (frame.metadata.transparency_composition_mask_valid) {
            write_binary_file(arrays_dir / "transparency_composition_mask.raw",
                              bytes_from_values(frame.transparency_composition_mask));
        }

        const bool reactive_valid = frame.metadata.reactive_mask_valid;
        const bool tcr_valid = frame.metadata.transparency_composition_mask_valid;
        std::ofstream manifest(frame_root / "manifest.json", std::ios::binary | std::ios::trunc);
        if (!manifest) {
            throw std::runtime_error("cannot write stateful teacher capture manifest");
        }
        const auto write_descriptor = [&](const char* name, const char* dtype, std::uint32_t width,
                                          std::uint32_t height, std::uint32_t channels, bool last) {
            manifest << "    \"" << name << "\": {\"file\": \"arrays/" << name << ".raw\", \"dtype\": \""
                     << dtype << "\", \"shape\": [" << height << ", " << width << ", " << channels << "]}"
                     << (last ? "\n" : ",\n");
        };
        const std::size_t descriptor_count = 10 + static_cast<std::size_t>(reactive_valid) + static_cast<std::size_t>(tcr_valid);
        std::size_t written = 0;
        const auto desc = [&](const char* name, const char* dtype, std::uint32_t width,
                              std::uint32_t height, std::uint32_t channels) {
            ++written;
            write_descriptor(name, dtype, width, height, channels, written == descriptor_count);
        };
        manifest << std::setprecision(9)
                 << "{\n"
                 << "  \"schema\": \"f4n10.teacher.capture.v1\",\n"
                 << "  \"metadata\": {\n"
                 << "    \"sequence_id\": \"" << json_escape(sequence_metadata.sequence_id) << "\",\n"
                 << "    \"source_kind\": \"" << json_escape(sequence_metadata.source_kind) << "\",\n"
                 << "    \"frame_index\": " << frame.metadata.frame_index << ",\n"
                 << "    \"input_frame_sha256\": \"" << sequence_frame_input_sha256(frame) << "\",\n"
                 << "    \"preset\": \"" << json_escape(sequence_metadata.preset) << "\",\n"
                 << "    \"render_width\": " << kWidth << ",\n"
                 << "    \"render_height\": " << kHeight << ",\n"
                 << "    \"output_width\": " << kWidth << ",\n"
                 << "    \"output_height\": " << kHeight << ",\n"
                 << "    \"jitter_current\": [" << frame.metadata.jitter_x << ", " << frame.metadata.jitter_y << "],\n"
                 << "    \"jitter_previous\": [" << frame.metadata.previous_jitter_x << ", "
                 << frame.metadata.previous_jitter_y << "],\n"
                 << "    \"frame_time_delta_ms\": " << frame.metadata.frame_time_delta_ms << ",\n"
                 << "    \"exposure\": " << frame.metadata.exposure << ",\n"
                 << "    \"pre_exposure\": " << frame.metadata.pre_exposure << ",\n"
                 << "    \"reset\": " << (frame.metadata.reset ? "true" : "false") << ",\n"
                 << "    \"camera_cut\": " << (frame.metadata.camera_cut ? "true" : "false") << ",\n"
                 << "    \"motion_convention\": \"current pixel to previous render pixel, displacement in render pixels\",\n"
                 << "    \"source_commit\": \"" << FSR4N10_FSR4_SOURCE_COMMIT << "\",\n"
                 << "    \"source_hash\": \"" << sequence_metadata.source_hash << "\",\n"
                 << "    \"sequence_hash\": \"" << sequence_metadata.sequence_hash << "\",\n"
                 << "    \"shader_hashes\": {\"provider_shader_manifest\": \"" << shader_manifest_hash << "\"},\n"
                 << "    \"build_commit\": \"" << FSR4N10_BUILD_COMMIT << "\",\n"
                 << "    \"build_mode\": \"" << FSR4N10_BUILD_CONFIGURATION << "\",\n"
                 << "    \"capture_origin\": \"" << json_escape(sequence_metadata.source_kind)
                 << "_gpu_provider_capture\",\n"
                 << "    \"physical_control_transform\": \"capture-only stable tanh/sigmoid equivalent; does not feed reconstruction\",\n"
                 << "    \"gpu_name\": \"" << json_escape(target.adapter_name) << "\",\n"
                 << "    \"driver_version\": \"" << json_escape(target.driver_version) << "\"\n"
                 << "  },\n"
                 << "  \"validity\": {\n"
                 << "    \"input_color\": true,\n"
                 << "    \"depth\": true,\n"
                 << "    \"motion_vectors\": true,\n"
                 << "    \"reactive_mask\": " << (reactive_valid ? "true" : "false") << ",\n"
                 << "    \"transparency_composition_mask\": " << (tcr_valid ? "true" : "false") << "\n"
                 << "  },\n"
                 << "  \"arrays\": {\n";
        desc("input_color", "<f2", kWidth, kHeight, 3);
        desc("depth", "<f4", kWidth, kHeight, 1);
        desc("motion_vectors", "<f2", kWidth, kHeight, 2);
        desc("current_reconstruction_source", "<f4", kWidth, kHeight, 3);
        desc("reprojected_history", "<f2", kWidth, kHeight, 3);
        desc("model_input_semantic_channels", "<f4", kWidth, kHeight, 7);
        desc("raw_model_parameters", "<f4", kWidth, kHeight, 4);
        desc("physical_controls", "<f4", kWidth, kHeight, 4);
        desc("recurrent_state", "|u1", kWidth, kHeight, 4);
        desc("final_rgb", "<f2", kWidth, kHeight, 3);
        if (reactive_valid) {
            desc("reactive_mask", "|u1", kWidth, kHeight, 1);
        }
        if (tcr_valid) {
            desc("transparency_composition_mask", "|u1", kWidth, kHeight, 1);
        }
        manifest << "  }\n}\n";
        if (!manifest) {
            throw std::runtime_error("failed writing stateful teacher capture manifest");
        }
        return frame_root / "manifest.json";
    };

    std::set<std::uint32_t> audit_frames;
    if (!capture_root.empty()) {
        audit_frames.insert(0);
        audit_frames.insert(sequence_metadata.frame_count - 1);
        for (std::uint32_t index = 0; index < sequence_metadata.frame_count; ++index) {
            const auto& frame_metadata = sequence.frame_metadata(index);
            if (frame_metadata.reset || frame_metadata.camera_cut) {
                audit_frames.insert(index);
            }
        }
    }
    std::vector<std::string> frame_reports;
    frame_reports.reserve(sequence_metadata.frame_count);
    std::vector<double> reference_gpu_times;
    std::vector<double> steady_state_gpu_times;
    reference_gpu_times.reserve(sequence_metadata.frame_count);
    steady_state_gpu_times.reserve(sequence_metadata.frame_count);
    bool all_match = true;
    for (std::uint32_t frame_index = 0; frame_index < sequence_metadata.frame_count; ++frame_index) {
        auto frame = sequence.read_frame(frame_index);
        upload_frame(frame);
        const std::string input_hash = sequence_frame_input_sha256(frame);
        const bool audit = audit_frames.contains(frame_index);
        double reference_gpu_time_us = 0.0;
        auto instrumented = run_dispatch(instrumented_context, frame.metadata, instrumented_output_texture.Get(), true,
                                         audit, false, nullptr);
        const std::string instrumented_hash = sha256_hex(instrumented[0]);
        std::string capture_manifest_path;
        std::string parameter_hash;
        std::string recurrent_hash;
        if (audit) {
            parameter_hash = sha256_hex(extract_rgba32_region(instrumented[1], 3, kWidth * 5, kWidth, kHeight, 4));
            recurrent_hash = sha256_hex(instrumented[2]);
            capture_manifest_path = write_sequence_capture(frame, instrumented).string();
        }

        auto reference = run_dispatch(reference_context, frame.metadata, reference_output_texture.Get(), false,
                                      false, true, &reference_gpu_time_us);
        reference_gpu_times.push_back(reference_gpu_time_us);
        if (frame_index != 0 && !frame.metadata.reset && !frame.metadata.camera_cut) {
            steady_state_gpu_times.push_back(reference_gpu_time_us);
        }
        const std::string reference_hash = sha256_hex(reference[0]);
        const bool matches = instrumented[0] == reference[0];
        all_match = all_match && matches;
        if (!matches || !all_half_values_are_finite(instrumented[0]) ||
            !all_half_values_are_finite(reference[0])) {
            std::ostringstream error;
            error << "stateful FSR4 provider validation failed on frame " << frame_index
                  << ": instrumented/reference match=" << matches
                  << ", instrumented SHA-256=" << instrumented_hash
                  << ", reference SHA-256=" << reference_hash;
            throw std::runtime_error(error.str());
        }

        std::ostringstream frame_json;
        frame_json << "    {\"frame_index\": " << frame_index
                   << ", \"reset\": " << (frame.metadata.reset ? "true" : "false")
                   << ", \"camera_cut\": " << (frame.metadata.camera_cut ? "true" : "false")
                   << ", \"jitter_current\": [" << frame.metadata.jitter_x << ", " << frame.metadata.jitter_y << "]"
                   << ", \"input_frame_sha256\": \"" << input_hash << '\"'
                   << ", \"reference_gpu_dispatch_us\": " << std::setprecision(9) << reference_gpu_time_us
                   << ", \"instrumented_output_sha256\": \"" << instrumented_hash << "\""
                   << ", \"reference_output_sha256\": \"" << reference_hash << "\""
                   << ", \"output_identical\": " << (matches ? "true" : "false");
        if (audit) {
            frame_json << ", \"raw_parameter_sha256\": \"" << parameter_hash << "\""
                       << ", \"recurrent_state_sha256\": \"" << recurrent_hash << "\""
                       << ", \"capture_manifest\": \"" << json_escape(capture_manifest_path) << "\"";
        }
        frame_json << '}';
        frame_reports.push_back(frame_json.str());
    }

    if (!report_path.parent_path().empty()) {
        std::filesystem::create_directories(report_path.parent_path());
    }
    std::ofstream report(report_path, std::ios::binary | std::ios::trunc);
    if (!report) {
        throw std::runtime_error("cannot write FSR4 provider sequence report: " + report_path.string());
    }
    const auto mean_gpu_time = [](const std::vector<double>& values) {
        if (values.empty()) {
            return 0.0;
        }
        return std::accumulate(values.begin(), values.end(), 0.0) / static_cast<double>(values.size());
    };
    const auto percentile_gpu_time = [](std::vector<double> values, double fraction) {
        if (values.empty()) {
            return 0.0;
        }
        std::sort(values.begin(), values.end());
        const auto rank = static_cast<std::size_t>(std::ceil(fraction * static_cast<double>(values.size())));
        return values[std::max<std::size_t>(1, rank) - 1];
    };
    report << "{\n"
           << "  \"schema\": \"f4n10.fsr4-provider-sequence.v1\",\n"
           << "  \"sequence_id\": \"" << json_escape(sequence_metadata.sequence_id) << "\",\n"
           << "  \"source_kind\": \"" << json_escape(sequence_metadata.source_kind) << "\",\n"
           << "  \"sequence_hash\": \"" << sequence_metadata.sequence_hash << "\",\n"
           << "  \"preset\": \"" << json_escape(sequence_metadata.preset) << "\",\n"
           << "  \"provider\": \"pinned_amd_fsr4_i8_native_1080\",\n"
           << "  \"upstream_commit\": \"" << FSR4N10_FSR4_SOURCE_COMMIT << "\",\n"
           << "  \"build_commit\": \"" << FSR4N10_BUILD_COMMIT << "\",\n"
           << "  \"adapter\": \"" << json_escape(target.adapter_name) << "\",\n"
           << "  \"driver_version\": \"" << json_escape(target.driver_version) << "\",\n"
           << "  \"render_size\": [" << kWidth << ", " << kHeight << "],\n"
           << "  \"output_size\": [" << kWidth << ", " << kHeight << "],\n"
           << "  \"frame_count\": " << sequence_metadata.frame_count << ",\n"
           << "  \"instrumentation_matches_reference\": " << (all_match ? "true" : "false") << ",\n"
           << "  \"gpu_timing_recorded\": true,\n"
           << "  \"gpu_timing\": {\"source\": \"D3D12 timestamp queries around non-instrumented FSR4 provider Dispatch\", "
           << "\"scope\": \"provider GPU work only; excludes input upload, output readback, CPU and packaging\", "
           << "\"timestamp_frequency_hz\": " << gpu_timer.frequency()
           << ", \"all_frames_mean_us\": " << mean_gpu_time(reference_gpu_times)
           << ", \"steady_state_excludes_first_reset_and_cuts\": true"
           << ", \"steady_state_frame_count\": " << steady_state_gpu_times.size()
           << ", \"steady_state_mean_us\": ";
    if (steady_state_gpu_times.empty()) {
        report << "null";
    } else {
        report << mean_gpu_time(steady_state_gpu_times);
    }
    report << ", \"steady_state_p50_us\": ";
    if (steady_state_gpu_times.empty()) {
        report << "null";
    } else {
        report << percentile_gpu_time(steady_state_gpu_times, 0.50);
    }
    report << ", \"steady_state_p95_us\": ";
    if (steady_state_gpu_times.empty()) {
        report << "null";
    } else {
        report << percentile_gpu_time(steady_state_gpu_times, 0.95);
    }
    report << "},\n"
           << "  \"capture_frames\": [";
    bool first_capture = true;
    for (const auto index : audit_frames) {
        if (!first_capture) {
            report << ", ";
        }
        report << index;
        first_capture = false;
    }
    report << "],\n"
           << "  \"frames\": [\n";
    for (std::size_t index = 0; index < frame_reports.size(); ++index) {
        report << frame_reports[index] << (index + 1 == frame_reports.size() ? "\n" : ",\n");
    }
    report << "  ]\n}\n";
    report.close();
    if (!report) {
        throw std::runtime_error("failed while writing FSR4 provider sequence report: " + report_path.string());
    }

    std::cout << "Pinned FSR4 I8 provider completed " << sequence_metadata.frame_count
              << " stateful frame dispatches on " << target.adapter_name
              << "; instrumented/ordinary output equality: " << (all_match ? "yes" : "no") << ".\n"
              << "Input source kind: " << sequence_metadata.source_kind
              << "; no quality or performance claim is made by this validation run.\n"
              << "Report: " << report_path.string() << ".\n";
    return 0;
}

} // namespace fsr4n10
