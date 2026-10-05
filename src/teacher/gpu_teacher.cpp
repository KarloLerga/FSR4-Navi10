#include "fsr4n10/gpu_teacher.h"

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
#include <bit>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <system_error>
#include <vector>

#ifndef FSR4N10_FSR4_SOURCE_COMMIT
#error FSR4N10_FSR4_SOURCE_COMMIT must be supplied from third_party/LOCK.json
#endif

namespace fsr4n10 {
namespace {

using Microsoft::WRL::ComPtr;

constexpr std::uint32_t kWidth = 1920;
constexpr std::uint32_t kHeight = 1080;
constexpr std::size_t kOutputBytesPerPixel = 8;

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

std::vector<std::byte> read_output(
    ID3D12Device* device,
    ID3D12CommandQueue* queue,
    ID3D12GraphicsCommandList* command_list,
    ID3D12Resource* output,
    ID3D12Resource* readback,
    QueueWaiter& waiter) {
    auto to_copy = D3D12_RESOURCE_BARRIER{};
    to_copy.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    to_copy.Transition.pResource = output;
    to_copy.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    to_copy.Transition.StateBefore = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
    to_copy.Transition.StateAfter = D3D12_RESOURCE_STATE_COPY_SOURCE;
    command_list->ResourceBarrier(1, &to_copy);

    const auto description = output->GetDesc();
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};
    UINT rows = 0;
    UINT64 row_size = 0;
    UINT64 total_size = 0;
    device->GetCopyableFootprints(&description, 0, 1, 0, &footprint, &rows, &row_size, &total_size);
    if (rows != kHeight || row_size != static_cast<UINT64>(kWidth) * kOutputBytesPerPixel) {
        throw std::runtime_error("unexpected provider output texture layout");
    }
    D3D12_TEXTURE_COPY_LOCATION source_location{};
    source_location.pResource = output;
    source_location.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    source_location.SubresourceIndex = 0;
    D3D12_TEXTURE_COPY_LOCATION destination_location{};
    destination_location.pResource = readback;
    destination_location.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
    destination_location.PlacedFootprint = footprint;
    command_list->CopyTextureRegion(&destination_location, 0, 0, 0, &source_location, nullptr);

    std::swap(to_copy.Transition.StateBefore, to_copy.Transition.StateAfter);
    command_list->ResourceBarrier(1, &to_copy);
    check_hr(command_list->Close(), "ID3D12GraphicsCommandList::Close(readback) failed");
    ID3D12CommandList* command_lists[]{command_list};
    queue->ExecuteCommandLists(1, command_lists);
    waiter.wait(queue);

    std::vector<std::byte> packed(static_cast<std::size_t>(row_size) * rows);
    const std::size_t readback_row_pitch = footprint.Footprint.RowPitch;
    const std::size_t aligned_size = static_cast<std::size_t>(total_size);
    void* mapped = nullptr;
    D3D12_RANGE read_range{0, aligned_size};
    check_hr(readback->Map(0, &read_range, &mapped), "Map(output readback) failed");
    for (std::uint32_t row = 0; row < rows; ++row) {
        std::memcpy(packed.data() + static_cast<std::size_t>(row) * row_size,
                    static_cast<const std::byte*>(mapped) + static_cast<std::size_t>(row) * readback_row_pitch,
                    static_cast<std::size_t>(row_size));
    }
    D3D12_RANGE no_writes{0, 0};
    readback->Unmap(0, &no_writes);
    return packed;
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

    auto readback_footprint = output_texture->GetDesc();
    UINT readback_rows = 0;
    UINT64 readback_row_size = 0;
    UINT64 readback_size = 0;
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT ignored_footprint{};
    target.device->GetCopyableFootprints(&readback_footprint, 0, 1, 0,
                                         &ignored_footprint, &readback_rows, &readback_row_size, &readback_size);
    auto output_readback = create_buffer(target.device.Get(), D3D12_HEAP_TYPE_READBACK,
                                         D3D12_RESOURCE_STATE_COPY_DEST, readback_size);

    ffxCreateBackendDX12Desc backend_desc{};
    backend_desc.header.type = FFX_API_CREATE_CONTEXT_DESC_TYPE_BACKEND_DX12;
    backend_desc.header.pNext = nullptr;
    backend_desc.device = target.device.Get();
    ffxCreateContextDescUpscale context_desc{};
    context_desc.header.type = FFX_API_CREATE_CONTEXT_DESC_TYPE_UPSCALE;
    context_desc.header.pNext = &backend_desc.header;
    context_desc.flags = 0;
    context_desc.maxRenderSize = {kWidth, kHeight};
    context_desc.maxUpscaleSize = {kWidth, kHeight};
    ProviderContext context;
    check_ffx(ffxProvider_FSR4::Instance.CreateContext(context.address(), &context_desc.header, context.allocator()),
              "FSR4 provider CreateContext");

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

    check_hr(allocator->Reset(), "ID3D12CommandAllocator::Reset(before dispatch) failed");
    check_hr(command_list->Reset(allocator.Get(), nullptr), "ID3D12GraphicsCommandList::Reset(before dispatch) failed");
    dispatch.commandList = ffxGetCommandListDX12(command_list.Get());
    check_ffx(ffxProvider_FSR4::Instance.Dispatch(context.address(), &dispatch.header), "FSR4 provider Dispatch(frame 1)");
    const auto first_output = read_output(target.device.Get(), queue.Get(), command_list.Get(),
                                          output_texture.Get(), output_readback.Get(), waiter);

    check_hr(allocator->Reset(), "ID3D12CommandAllocator::Reset(before reset dispatch) failed");
    check_hr(command_list->Reset(allocator.Get(), nullptr), "ID3D12GraphicsCommandList::Reset(before reset dispatch) failed");
    dispatch.commandList = ffxGetCommandListDX12(command_list.Get());
    dispatch.reset = true;
    check_ffx(ffxProvider_FSR4::Instance.Dispatch(context.address(), &dispatch.header), "FSR4 provider Dispatch(frame 2)");
    const auto second_output = read_output(target.device.Get(), queue.Get(), command_list.Get(),
                                           output_texture.Get(), output_readback.Get(), waiter);

    const auto first_hash = sha256_hex(first_output);
    const auto second_hash = sha256_hex(second_output);
    const bool finite_output = all_half_values_are_finite(first_output) && all_half_values_are_finite(second_output);
    if (!finite_output) {
        throw std::runtime_error("FSR4 provider output contains an infinity or NaN");
    }
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
           << "  \"provider\": \"pinned_amd_fsr4_i8_native_1080\",\n"
           << "  \"upstream_commit\": \"" << FSR4N10_FSR4_SOURCE_COMMIT << "\",\n"
           << "  \"adapter\": \"" << json_escape(target.adapter_name) << "\",\n"
           << "  \"pci_id\": \"1002:731F\",\n"
           << "  \"render_size\": [1920, 1080],\n"
           << "  \"output_size\": [1920, 1080],\n"
           << "  \"format\": \"R16G16B16A16_FLOAT\",\n"
           << "  \"reset_dispatches\": 2,\n"
           << "  \"output_sha256_first\": \"" << first_hash << "\",\n"
           << "  \"output_sha256_second\": \"" << second_hash << "\",\n"
           << "  \"finite_output\": true,\n"
           << "  \"identical_after_reset\": " << (first_hash == second_hash ? "true" : "false") << "\n"
           << "}\n";
    report.close();
    if (!report) {
        throw std::runtime_error("failed while writing provider smoke report: " + report_path.string());
    }

    std::cout << "Pinned FSR4 I8 provider dispatched twice on " << target.adapter_name
              << " with reset; output SHA-256 " << second_hash
              << "; identical after reset: " << (first_hash == second_hash ? "yes" : "no") << ".\n"
              << "Report: " << report_path.string() << " (synthetic smoke; not a teacher capture).\n";
    return first_hash == second_hash ? 0 : 3;
}

} // namespace fsr4n10
