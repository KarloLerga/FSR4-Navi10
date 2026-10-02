#include "fsr4n10/upstream_smoke.h"

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
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

constexpr std::uint32_t kInputWidth = 1920;
constexpr std::uint32_t kInputHeight = 1080;
constexpr std::uint32_t kInputStorageChannels = 8;
constexpr std::uint32_t kOutputWidth = 960;
constexpr std::uint32_t kOutputHeight = 540;
constexpr std::uint32_t kOutputChannels = 16;
constexpr std::uint32_t kNetworkOutputChannels = 8;
constexpr std::uint32_t kPrePassGroupSize = 16;
constexpr std::uint64_t kInputBytes =
    static_cast<std::uint64_t>(kInputWidth) * kInputHeight * kInputStorageChannels * sizeof(std::uint16_t);
constexpr std::uint64_t kOutputRowBytes = static_cast<std::uint64_t>(kOutputWidth) * kOutputChannels;
constexpr std::uint64_t kOutputBytes = kOutputRowBytes * kOutputHeight;
constexpr std::uint64_t kNetworkOutputBytes =
    static_cast<std::uint64_t>(kInputWidth) * kInputHeight * kNetworkOutputChannels * sizeof(std::uint16_t);
constexpr std::uint64_t kScratchBytes = 20736000;
constexpr std::uint32_t kOutputSentinel = 0x7f;
constexpr std::uint32_t kBenchmarkIterations = 25;
constexpr std::uint32_t kBenchmarkWarmupIterations = 5;

std::array<UINT, 3> native_1080_dispatch_groups(std::uint32_t pass_index) {
    const auto ceil_div = [](std::uint32_t value, std::uint32_t divisor) {
        return (value + divisor - 1) / divisor;
    };
    const std::uint32_t encoder1_width = kInputWidth / 2;
    const std::uint32_t encoder1_height = kInputHeight / 2;
    const std::uint32_t encoder2_width = kInputWidth / 4;
    const std::uint32_t encoder2_height = kInputHeight / 4;
    const std::uint32_t encoder3_width = kInputWidth / 8;
    const std::uint32_t encoder3_height = kInputHeight / 8;
    switch (pass_index) {
    case 0:
        return {ceil_div(kInputWidth, 16), ceil_div(kInputHeight, 16), 1};
    case 1:
    case 2:
    case 12:
        return {ceil_div(encoder1_width, 64), encoder1_height, 1};
    case 3:
    case 4:
    case 5:
    case 10:
    case 11:
        return {ceil_div(encoder2_width, 64), encoder2_height, 1};
    case 6:
    case 7:
    case 8:
        return {ceil_div(encoder3_width, 64), encoder3_height, 1};
    case 9:
        return {ceil_div(encoder3_width, 8), ceil_div(encoder3_height, 8), 1};
    case 13:
        return {ceil_div(kInputWidth, 16), ceil_div(kInputHeight, 16), 1};
    default:
        throw std::runtime_error("unsupported native 1080p FSR4 pass index");
    }
}

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

D3D12_RESOURCE_DESC buffer_description(std::uint64_t bytes, D3D12_RESOURCE_FLAGS flags = D3D12_RESOURCE_FLAG_NONE) {
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

ComPtr<ID3D12Device> create_target_device() {
    ComPtr<IDXGIFactory6> factory;
    check_hr(CreateDXGIFactory2(0, IID_PPV_ARGS(&factory)), "CreateDXGIFactory2 failed");
    for (UINT index = 0;; ++index) {
        ComPtr<IDXGIAdapter1> adapter;
        const HRESULT result = factory->EnumAdapters1(index, &adapter);
        if (result == DXGI_ERROR_NOT_FOUND) {
            break;
        }
        check_hr(result, "IDXGIFactory6::EnumAdapters1 failed");
        DXGI_ADAPTER_DESC1 description{};
        check_hr(adapter->GetDesc1(&description), "IDXGIAdapter1::GetDesc1 failed");
        if (description.VendorId != 0x1002 || description.DeviceId != 0x731F ||
            (description.Flags & DXGI_ADAPTER_FLAG_SOFTWARE) != 0) {
            continue;
        }
        ComPtr<ID3D12Device> device;
        check_hr(
            D3D12CreateDevice(adapter.Get(), D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&device)),
            "RX 5700 XT does not expose a D3D12 device");
        return device;
    }
    throw std::runtime_error("RX 5700 XT (PCI 1002:731F) was not found");
}

ComPtr<ID3D12Resource> create_buffer(
    ID3D12Device* device,
    std::uint64_t bytes,
    D3D12_HEAP_TYPE heap_type,
    D3D12_RESOURCE_STATES state,
    D3D12_RESOURCE_FLAGS flags = D3D12_RESOURCE_FLAG_NONE) {
    ComPtr<ID3D12Resource> resource;
    const auto heap = heap_properties(heap_type);
    const auto description = buffer_description(bytes, flags);
    check_hr(
        device->CreateCommittedResource(
            &heap,
            D3D12_HEAP_FLAG_NONE,
            &description,
            state,
            nullptr,
            IID_PPV_ARGS(&resource)),
        "ID3D12Device::CreateCommittedResource failed");
    return resource;
}

std::vector<std::byte> read_shader(const std::filesystem::path& path) {
    std::ifstream file(path, std::ios::binary | std::ios::ate);
    if (!file) {
        throw std::runtime_error("Cannot open compiled upstream pass 0 shader: " + path.string());
    }
    const auto size = file.tellg();
    if (size <= 0) {
        throw std::runtime_error("Binary input file is empty: " + path.string());
    }
    std::vector<std::byte> bytes(static_cast<std::size_t>(size));
    file.seekg(0);
    file.read(reinterpret_cast<char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
    if (!file) {
        throw std::runtime_error("Failed reading binary input file: " + path.string());
    }
    return bytes;
}

void transition(
    ID3D12GraphicsCommandList* command_list,
    ID3D12Resource* resource,
    D3D12_RESOURCE_STATES before,
    D3D12_RESOURCE_STATES after) {
    D3D12_RESOURCE_BARRIER barrier{};
    barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    barrier.Transition.pResource = resource;
    barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    barrier.Transition.StateBefore = before;
    barrier.Transition.StateAfter = after;
    command_list->ResourceBarrier(1, &barrier);
}

void create_raw_srv(ID3D12Device* device, ID3D12Resource* resource, std::uint64_t bytes, D3D12_CPU_DESCRIPTOR_HANDLE handle) {
    D3D12_SHADER_RESOURCE_VIEW_DESC description{};
    description.Format = DXGI_FORMAT_R32_TYPELESS;
    description.ViewDimension = D3D12_SRV_DIMENSION_BUFFER;
    description.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
    description.Buffer.NumElements = static_cast<UINT>(bytes / sizeof(std::uint32_t));
    description.Buffer.Flags = D3D12_BUFFER_SRV_FLAG_RAW;
    device->CreateShaderResourceView(resource, &description, handle);
}

void create_raw_uav(ID3D12Device* device, ID3D12Resource* resource, std::uint64_t bytes, D3D12_CPU_DESCRIPTOR_HANDLE handle) {
    D3D12_UNORDERED_ACCESS_VIEW_DESC description{};
    description.Format = DXGI_FORMAT_R32_TYPELESS;
    description.ViewDimension = D3D12_UAV_DIMENSION_BUFFER;
    description.Buffer.NumElements = static_cast<UINT>(bytes / sizeof(std::uint32_t));
    description.Buffer.Flags = D3D12_BUFFER_UAV_FLAG_RAW;
    device->CreateUnorderedAccessView(resource, nullptr, &description, handle);
}

void upload_fill(ID3D12Resource* resource, std::uint64_t bytes, std::byte value) {
    void* mapped = nullptr;
    const D3D12_RANGE no_read{0, 0};
    check_hr(resource->Map(0, &no_read, &mapped), "Map upload buffer failed");
    std::memset(mapped, std::to_integer<unsigned char>(value), static_cast<std::size_t>(bytes));
    resource->Unmap(0, nullptr);
}

} // namespace

int run_upstream_smoke(bool full_model, bool benchmark) {
    if (benchmark && !full_model) {
        throw std::runtime_error("the upstream I8 benchmark requires the full model chain");
    }
    if (kOutputBytes > kScratchBytes || kNetworkOutputBytes % sizeof(std::uint32_t) != 0 ||
        kInputBytes % sizeof(std::uint32_t) != 0 || kScratchBytes % sizeof(std::uint32_t) != 0) {
        throw std::runtime_error("upstream smoke buffer geometry is invalid");
    }

    const ComPtr<ID3D12Device> device = create_target_device();
    ComPtr<ID3D12CommandQueue> queue;
    D3D12_COMMAND_QUEUE_DESC queue_description{};
    queue_description.Type = D3D12_COMMAND_LIST_TYPE_COMPUTE;
    check_hr(device->CreateCommandQueue(&queue_description, IID_PPV_ARGS(&queue)), "Create compute queue failed");

    ComPtr<ID3D12CommandAllocator> allocator;
    check_hr(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_COMPUTE, IID_PPV_ARGS(&allocator)), "Create command allocator failed");
    ComPtr<ID3D12GraphicsCommandList> command_list;
    check_hr(
        device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_COMPUTE, allocator.Get(), nullptr, IID_PPV_ARGS(&command_list)),
        "Create compute command list failed");

    ComPtr<ID3D12DescriptorHeap> descriptor_heap;
    D3D12_DESCRIPTOR_HEAP_DESC heap_description{};
    heap_description.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
    heap_description.NumDescriptors = 4;
    heap_description.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
    check_hr(device->CreateDescriptorHeap(&heap_description, IID_PPV_ARGS(&descriptor_heap)), "Create descriptor heap failed");

    D3D12_DESCRIPTOR_RANGE ranges[2]{};
    ranges[0].RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_SRV;
    ranges[0].NumDescriptors = 2;
    ranges[0].BaseShaderRegister = 0;
    ranges[0].OffsetInDescriptorsFromTableStart = D3D12_DESCRIPTOR_RANGE_OFFSET_APPEND;
    ranges[1].RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_UAV;
    ranges[1].NumDescriptors = 2;
    ranges[1].BaseShaderRegister = 0;
    ranges[1].OffsetInDescriptorsFromTableStart = D3D12_DESCRIPTOR_RANGE_OFFSET_APPEND;
    D3D12_ROOT_PARAMETER parameters[2]{};
    for (UINT index = 0; index < 2; ++index) {
        parameters[index].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
        parameters[index].DescriptorTable.NumDescriptorRanges = 1;
        parameters[index].DescriptorTable.pDescriptorRanges = &ranges[index];
        parameters[index].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
    }
    D3D12_ROOT_SIGNATURE_DESC root_description{};
    root_description.NumParameters = 2;
    root_description.pParameters = parameters;
    ComPtr<ID3DBlob> serialized_root;
    ComPtr<ID3DBlob> root_errors;
    check_hr(
        D3D12SerializeRootSignature(&root_description, D3D_ROOT_SIGNATURE_VERSION_1, &serialized_root, &root_errors),
        "Serialize upstream pass root signature failed");
    ComPtr<ID3D12RootSignature> root_signature;
    check_hr(
        device->CreateRootSignature(0, serialized_root->GetBufferPointer(), serialized_root->GetBufferSize(), IID_PPV_ARGS(&root_signature)),
        "Create upstream pass root signature failed");

    std::array<wchar_t, 32768> executable_path{};
    const DWORD executable_path_length = GetModuleFileNameW(nullptr, executable_path.data(), static_cast<DWORD>(executable_path.size()));
    if (executable_path_length == 0 || executable_path_length >= static_cast<DWORD>(executable_path.size())) {
        throw std::system_error(static_cast<int>(GetLastError()), std::system_category(), "GetModuleFileNameW failed");
    }
    const auto reference_dir = std::filesystem::path(executable_path.data()).parent_path() /
                              L"reference" / L"i8" / L"native" / L"1080";
    const std::uint32_t pass_count = full_model ? 14 : 1;
    std::array<ComPtr<ID3D12PipelineState>, 14> pipelines{};
    for (std::uint32_t pass_index = 0; pass_index < pass_count; ++pass_index) {
        std::wstring filename = L"pass_";
        if (pass_index < 10) {
            filename += L"0";
        }
        filename += std::to_wstring(pass_index) + L".dxil";
        const auto shader = read_shader(reference_dir / filename);
        D3D12_COMPUTE_PIPELINE_STATE_DESC pipeline_description{};
        pipeline_description.pRootSignature = root_signature.Get();
        pipeline_description.CS = {shader.data(), shader.size()};
        check_hr(
            device->CreateComputePipelineState(&pipeline_description, IID_PPV_ARGS(&pipelines[pass_index])),
            "Create upstream pass PSO failed");
    }

    std::vector<std::byte> initializer_data;
    if (full_model) {
        initializer_data = read_shader(reference_dir / L"initializers.bin");
        if (initializer_data.empty() || initializer_data.size() % sizeof(std::uint32_t) != 0) {
            throw std::runtime_error("upstream initializer buffer has an invalid size");
        }
    }

    auto input_default = create_buffer(
        device.Get(), kInputBytes, D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COPY_DEST);
    auto input_upload = create_buffer(
        device.Get(), kInputBytes, D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ);
    auto output_u0 = create_buffer(
        device.Get(), kNetworkOutputBytes, D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COPY_DEST,
        D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS);
    auto output_upload = create_buffer(
        device.Get(), kNetworkOutputBytes, D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ);
    auto scratch_u1 = create_buffer(
        device.Get(), kScratchBytes, D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COPY_DEST,
        D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS);
    auto scratch_upload = create_buffer(
        device.Get(), kScratchBytes, D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ);
    const std::uint64_t readback_bytes = full_model ? kNetworkOutputBytes : kOutputBytes;
    auto output_readback = create_buffer(
        device.Get(), readback_bytes, D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST);

    const std::uint32_t dispatch_iterations = benchmark ? kBenchmarkIterations : 1;
    const std::uint32_t query_count = dispatch_iterations * pass_count * 2;
    ComPtr<ID3D12QueryHeap> timestamp_heap;
    ComPtr<ID3D12Resource> timestamp_readback;
    UINT64 timestamp_frequency = 0;
    if (benchmark) {
        D3D12_QUERY_HEAP_DESC query_description{};
        query_description.Type = D3D12_QUERY_HEAP_TYPE_TIMESTAMP;
        query_description.Count = query_count;
        check_hr(device->CreateQueryHeap(&query_description, IID_PPV_ARGS(&timestamp_heap)), "Create timestamp query heap failed");
        timestamp_readback = create_buffer(
            device.Get(),
            static_cast<std::uint64_t>(query_count) * sizeof(UINT64),
            D3D12_HEAP_TYPE_READBACK,
            D3D12_RESOURCE_STATE_COPY_DEST);
        check_hr(queue->GetTimestampFrequency(&timestamp_frequency), "Get compute queue timestamp frequency failed");
        if (timestamp_frequency == 0) {
            throw std::runtime_error("compute queue reported a zero timestamp frequency");
        }
    }

    ComPtr<ID3D12Resource> initializer_default;
    ComPtr<ID3D12Resource> initializer_upload;
    if (full_model) {
        initializer_default = create_buffer(
            device.Get(), initializer_data.size(), D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COPY_DEST);
        initializer_upload = create_buffer(
            device.Get(), initializer_data.size(), D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ);
    }

    upload_fill(input_upload.Get(), kInputBytes, std::byte{0});
    upload_fill(output_upload.Get(), kNetworkOutputBytes, static_cast<std::byte>(kOutputSentinel));
    upload_fill(scratch_upload.Get(), kScratchBytes, full_model ? std::byte{0} : static_cast<std::byte>(kOutputSentinel));
    command_list->CopyBufferRegion(input_default.Get(), 0, input_upload.Get(), 0, kInputBytes);
    command_list->CopyBufferRegion(output_u0.Get(), 0, output_upload.Get(), 0, kNetworkOutputBytes);
    command_list->CopyBufferRegion(scratch_u1.Get(), 0, scratch_upload.Get(), 0, kScratchBytes);
    if (full_model) {
        void* mapped = nullptr;
        const D3D12_RANGE no_read{0, 0};
        check_hr(initializer_upload->Map(0, &no_read, &mapped), "Map initializer upload buffer failed");
        std::memcpy(mapped, initializer_data.data(), initializer_data.size());
        initializer_upload->Unmap(0, nullptr);
        command_list->CopyBufferRegion(initializer_default.Get(), 0, initializer_upload.Get(), 0, initializer_data.size());
        transition(
            command_list.Get(),
            initializer_default.Get(),
            D3D12_RESOURCE_STATE_COPY_DEST,
            D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    }
    transition(command_list.Get(), input_default.Get(), D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    transition(command_list.Get(), output_u0.Get(), D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    transition(command_list.Get(), scratch_u1.Get(), D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);

    const UINT descriptor_increment = device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
    const auto cpu_start = descriptor_heap->GetCPUDescriptorHandleForHeapStart();
    const auto gpu_start = descriptor_heap->GetGPUDescriptorHandleForHeapStart();
    const auto handle_at = [descriptor_increment](D3D12_CPU_DESCRIPTOR_HANDLE start, UINT index) {
        return D3D12_CPU_DESCRIPTOR_HANDLE{start.ptr + static_cast<SIZE_T>(descriptor_increment) * index};
    };
    create_raw_srv(device.Get(), input_default.Get(), kInputBytes, handle_at(cpu_start, 0));
    ID3D12Resource* initializer_resource = full_model ? initializer_default.Get() : input_default.Get();
    const std::uint64_t initializer_size = full_model ? initializer_data.size() : kInputBytes;
    create_raw_srv(device.Get(), initializer_resource, initializer_size, handle_at(cpu_start, 1));
    create_raw_uav(device.Get(), output_u0.Get(), kNetworkOutputBytes, handle_at(cpu_start, 2));
    create_raw_uav(device.Get(), scratch_u1.Get(), kScratchBytes, handle_at(cpu_start, 3));

    ID3D12DescriptorHeap* descriptor_heaps[] = {descriptor_heap.Get()};
    command_list->SetDescriptorHeaps(1, descriptor_heaps);
    command_list->SetComputeRootSignature(root_signature.Get());
    command_list->SetComputeRootDescriptorTable(
        0,
        gpu_start);
    command_list->SetComputeRootDescriptorTable(
        1,
        D3D12_GPU_DESCRIPTOR_HANDLE{gpu_start.ptr + static_cast<UINT64>(descriptor_increment) * 2});
    UINT query_index = 0;
    for (std::uint32_t iteration = 0; iteration < dispatch_iterations; ++iteration) {
        for (std::uint32_t pass_index = 0; pass_index < pass_count; ++pass_index) {
            const auto groups = native_1080_dispatch_groups(pass_index);
            command_list->SetPipelineState(pipelines[pass_index].Get());
            if (benchmark) {
                command_list->EndQuery(timestamp_heap.Get(), D3D12_QUERY_TYPE_TIMESTAMP, query_index++);
            }
            command_list->Dispatch(groups[0], groups[1], groups[2]);
            if (benchmark) {
                command_list->EndQuery(timestamp_heap.Get(), D3D12_QUERY_TYPE_TIMESTAMP, query_index++);
            }
            if (pass_index + 1 < pass_count || iteration + 1 < dispatch_iterations) {
                D3D12_RESOURCE_BARRIER barrier{};
                barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_UAV;
                barrier.UAV.pResource = scratch_u1.Get();
                command_list->ResourceBarrier(1, &barrier);
            }
        }
    }

    if (benchmark) {
        command_list->ResolveQueryData(
            timestamp_heap.Get(),
            D3D12_QUERY_TYPE_TIMESTAMP,
            0,
            query_count,
            timestamp_readback.Get(),
            0);
    }

    ID3D12Resource* final_resource = full_model ? output_u0.Get() : scratch_u1.Get();
    transition(
        command_list.Get(),
        final_resource,
        D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
        D3D12_RESOURCE_STATE_COPY_SOURCE);
    command_list->CopyBufferRegion(output_readback.Get(), 0, final_resource, 0, readback_bytes);
    check_hr(command_list->Close(), "Close upstream pass command list failed");
    ID3D12CommandList* command_lists[] = {command_list.Get()};
    queue->ExecuteCommandLists(1, command_lists);

    ComPtr<ID3D12Fence> fence;
    check_hr(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)), "Create dispatch fence failed");
    check_hr(queue->Signal(fence.Get(), 1), "Signal dispatch fence failed");
    HANDLE fence_event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    if (fence_event == nullptr) {
        throw std::system_error(static_cast<int>(GetLastError()), std::system_category(), "CreateEventW failed");
    }
    const auto close_event = std::unique_ptr<void, decltype(&CloseHandle)>(fence_event, &CloseHandle);
    check_hr(fence->SetEventOnCompletion(1, fence_event), "SetEventOnCompletion failed");
    if (WaitForSingleObject(fence_event, 120000) != WAIT_OBJECT_0) {
        throw std::runtime_error("Timed out waiting for the upstream FSR4 smoke dispatch");
    }

    std::vector<std::byte> results(static_cast<std::size_t>(readback_bytes));
    void* mapped = nullptr;
    const D3D12_RANGE read_range{0, static_cast<SIZE_T>(readback_bytes)};
    check_hr(output_readback->Map(0, &read_range, &mapped), "Map upstream pass readback failed");
    std::memcpy(results.data(), mapped, results.size());
    const D3D12_RANGE no_write{0, 0};
    output_readback->Unmap(0, &no_write);

    if (!full_model) {
        std::array<bool, 256> unique_values{};
        bool changed_from_sentinel = false;
        for (std::uint32_t channel = 0; channel < kOutputChannels; ++channel) {
            unique_values[std::to_integer<std::uint8_t>(results[channel])] = true;
        }
        for (std::uint32_t y = 0; y < kOutputHeight; ++y) {
            for (std::uint32_t x = 0; x < kOutputWidth; ++x) {
                const std::uint64_t pixel_start = static_cast<std::uint64_t>(y) * kOutputRowBytes + x * kOutputChannels;
                for (std::uint32_t channel = 0; channel < kOutputChannels; ++channel) {
                    const std::byte value = results[static_cast<std::size_t>(pixel_start + channel)];
                    changed_from_sentinel = changed_from_sentinel || std::to_integer<std::uint32_t>(value) != kOutputSentinel;
                    if (value != results[channel]) {
                        throw std::runtime_error("upstream pass 0 zero-input output varies spatially");
                    }
                }
            }
        }
        if (!changed_from_sentinel) {
            throw std::runtime_error("upstream pass 0 did not overwrite the sentinel output");
        }
        const auto unique_count = static_cast<std::size_t>(std::count(unique_values.begin(), unique_values.end(), true));
        std::cout << "Upstream I8 pass 0 smoke dispatch passed on RX 5700 XT: 1920x1080 zero FP16 input, "
                  << kOutputWidth << 'x' << kOutputHeight << "x" << kOutputChannels
                  << " output; spatially constant bias response with " << unique_count << " distinct channel values.\n";
        return 0;
    }

    bool changed_from_sentinel = false;
    std::uint64_t nonzero_values = 0;
    for (std::size_t index = 0; index < results.size(); index += sizeof(std::uint16_t)) {
        const std::uint16_t value = static_cast<std::uint16_t>(std::to_integer<std::uint8_t>(results[index])) |
                                    static_cast<std::uint16_t>(std::to_integer<std::uint8_t>(results[index + 1]) << 8U);
        changed_from_sentinel = changed_from_sentinel || value != 0x7f7f;
        if (((value >> 10U) & 0x1fU) == 0x1fU) {
            throw std::runtime_error("upstream zero-model smoke output contains FP16 NaN or infinity");
        }
        nonzero_values += value != 0;
    }
    if (!changed_from_sentinel || nonzero_values == 0) {
        throw std::runtime_error("upstream zero-model smoke did not produce an FP16 feature output");
    }
    if (benchmark) {
        std::vector<UINT64> timestamps(query_count);
        void* timestamp_data = nullptr;
        const D3D12_RANGE timestamp_range{0, static_cast<SIZE_T>(query_count) * sizeof(UINT64)};
        check_hr(timestamp_readback->Map(0, &timestamp_range, &timestamp_data), "Map timestamp query readback failed");
        std::memcpy(timestamps.data(), timestamp_data, timestamps.size() * sizeof(UINT64));
        const D3D12_RANGE no_timestamp_write{0, 0};
        timestamp_readback->Unmap(0, &no_timestamp_write);

        const double microseconds_per_tick = 1.0e6 / static_cast<double>(timestamp_frequency);
        std::cout << "Preliminary upstream I8 synthetic-feature GPU timing on RX 5700 XT; "
                  << kBenchmarkWarmupIterations << " warmup iterations, "
                  << (kBenchmarkIterations - kBenchmarkWarmupIterations) << " measured iterations.\n";
        std::cout << "Pass  Avg (us)  Median (us)\n";
        double graph_average = 0.0;
        for (std::uint32_t pass_index = 0; pass_index < pass_count; ++pass_index) {
            std::vector<double> samples;
            samples.reserve(kBenchmarkIterations - kBenchmarkWarmupIterations);
            for (std::uint32_t iteration = kBenchmarkWarmupIterations; iteration < kBenchmarkIterations; ++iteration) {
                const std::size_t base = (static_cast<std::size_t>(iteration) * pass_count + pass_index) * 2;
                samples.push_back(static_cast<double>(timestamps[base + 1] - timestamps[base]) * microseconds_per_tick);
            }
            const double sample_sum = [&samples] {
                double value = 0.0;
                for (const double sample : samples) value += sample;
                return value;
            }();
            const double average = sample_sum / static_cast<double>(samples.size());
            std::sort(samples.begin(), samples.end());
            const double median = (samples[samples.size() / 2 - 1] + samples[samples.size() / 2]) * 0.5;
            graph_average += average;
            std::cout << std::setw(4) << std::setfill('0') << pass_index << std::setfill(' ') << "  "
                      << std::fixed << std::setprecision(3) << std::setw(8) << average << "  "
                      << std::setw(11) << median << '\n';
        }
        std::cout << "Sum of pass averages: " << std::fixed << std::setprecision(3) << graph_average
                  << " us of kernel time; excludes barriers, frame preprocessing, and image postprocessing.\n";
    }
    std::cout << "Upstream I8 model smoke passed on RX 5700 XT: pass 0, all 12 neural passes, and pass 13 ran "
              << "on synthetic zero features. The final 1920x1080x8 FP16 feature tensor contains "
              << nonzero_values << " nonzero finite values. This is not an image-quality result.\n";
    return 0;
}

int run_upstream_pass0_smoke() {
    return run_upstream_smoke(false, false);
}

int run_upstream_i8_zero_model_smoke() {
    return run_upstream_smoke(true, false);
}

int run_upstream_i8_zero_model_benchmark() {
    return run_upstream_smoke(true, true);
}

} // namespace fsr4n10
