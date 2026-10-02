#include "fsr4n10/fp16_probe.h"

#include <array>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <memory>
#include <iostream>
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

constexpr std::size_t kProbeCount = 64;
constexpr std::size_t kBufferBytes = kProbeCount * sizeof(std::uint32_t);

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

D3D12_RESOURCE_DESC buffer_description(D3D12_RESOURCE_FLAGS flags = D3D12_RESOURCE_FLAG_NONE) {
    D3D12_RESOURCE_DESC description{};
    description.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
    description.Width = kBufferBytes;
    description.Height = 1;
    description.DepthOrArraySize = 1;
    description.MipLevels = 1;
    description.SampleDesc.Count = 1;
    description.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    description.Flags = flags;
    return description;
}

ComPtr<ID3D12Device> create_target_device(std::string& adapter_name) {
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
        check_hr(
            D3D12CreateDevice(adapter.Get(), D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&device)),
            "RX 5700 XT does not expose a D3D12 device");

        const int character_count = WideCharToMultiByte(CP_UTF8, 0, description.Description, -1, nullptr, 0, nullptr, nullptr);
        if (character_count > 1) {
            adapter_name.resize(static_cast<std::size_t>(character_count));
            WideCharToMultiByte(CP_UTF8, 0, description.Description, -1, adapter_name.data(), character_count, nullptr, nullptr);
            adapter_name.pop_back();
        }
        return device;
    }

    throw std::runtime_error("RX 5700 XT (PCI 1002:731F) was not found");
}

ComPtr<ID3D12Resource> create_buffer(
    ID3D12Device* device,
    D3D12_HEAP_TYPE heap_type,
    D3D12_RESOURCE_STATES initial_state,
    D3D12_RESOURCE_FLAGS flags = D3D12_RESOURCE_FLAG_NONE) {
    ComPtr<ID3D12Resource> resource;
    const auto heap = heap_properties(heap_type);
    const auto description = buffer_description(flags);
    check_hr(
        device->CreateCommittedResource(
            &heap,
            D3D12_HEAP_FLAG_NONE,
            &description,
            initial_state,
            nullptr,
            IID_PPV_ARGS(&resource)),
        "ID3D12Device::CreateCommittedResource failed");
    return resource;
}

std::vector<std::byte> read_shader(const std::filesystem::path& path) {
    std::ifstream file(path, std::ios::binary | std::ios::ate);
    if (!file) {
        throw std::runtime_error("Cannot open compiled FP16 probe shader: " + path.string());
    }
    const auto size = file.tellg();
    if (size <= 0) {
        throw std::runtime_error("Compiled FP16 probe shader is empty: " + path.string());
    }
    std::vector<std::byte> bytes(static_cast<std::size_t>(size));
    file.seekg(0);
    file.read(reinterpret_cast<char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
    if (!file) {
        throw std::runtime_error("Failed reading compiled FP16 probe shader: " + path.string());
    }
    return bytes;
}

std::uint16_t input_half_a(std::size_t index) {
    constexpr std::array<std::uint16_t, 4> values{0x3E00, 0x3800, 0xC000, 0x4300};
    return values[index % values.size()];
}

std::uint16_t input_half_b(std::size_t index) {
    constexpr std::array<std::uint16_t, 4> values{0x4000, 0x3400, 0x4400, 0x3D00};
    return values[index % values.size()];
}

std::uint16_t expected_half_product(std::size_t index) {
    constexpr std::array<std::uint16_t, 4> values{0x4200, 0x3000, 0xC800, 0x4460};
    return values[index % values.size()];
}

} // namespace

int run_fp16_probe() {
    std::string adapter_name;
    ComPtr<ID3D12Device> device = create_target_device(adapter_name);

    ComPtr<ID3D12CommandQueue> queue;
    D3D12_COMMAND_QUEUE_DESC queue_description{};
    queue_description.Type = D3D12_COMMAND_LIST_TYPE_COMPUTE;
    check_hr(device->CreateCommandQueue(&queue_description, IID_PPV_ARGS(&queue)), "CreateCommandQueue failed");

    ComPtr<ID3D12CommandAllocator> allocator;
    check_hr(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_COMPUTE, IID_PPV_ARGS(&allocator)), "CreateCommandAllocator failed");

    ComPtr<ID3D12GraphicsCommandList> command_list;
    check_hr(
        device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_COMPUTE, allocator.Get(), nullptr, IID_PPV_ARGS(&command_list)),
        "CreateCommandList failed");

    ComPtr<ID3D12DescriptorHeap> descriptor_heap;
    D3D12_DESCRIPTOR_HEAP_DESC descriptor_heap_description{};
    descriptor_heap_description.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
    descriptor_heap_description.NumDescriptors = 2;
    descriptor_heap_description.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
    check_hr(device->CreateDescriptorHeap(&descriptor_heap_description, IID_PPV_ARGS(&descriptor_heap)), "CreateDescriptorHeap failed");

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
    root_description.Flags = D3D12_ROOT_SIGNATURE_FLAG_NONE;
    ComPtr<ID3DBlob> serialized_root;
    ComPtr<ID3DBlob> root_errors;
    check_hr(
        D3D12SerializeRootSignature(&root_description, D3D_ROOT_SIGNATURE_VERSION_1, &serialized_root, &root_errors),
        "D3D12SerializeRootSignature failed");

    ComPtr<ID3D12RootSignature> root_signature;
    check_hr(
        device->CreateRootSignature(0, serialized_root->GetBufferPointer(), serialized_root->GetBufferSize(), IID_PPV_ARGS(&root_signature)),
        "CreateRootSignature failed");

    std::array<wchar_t, 32768> executable_path{};
    const DWORD executable_path_length = GetModuleFileNameW(nullptr, executable_path.data(), static_cast<DWORD>(executable_path.size()));
    if (executable_path_length == 0 || executable_path_length >= static_cast<DWORD>(executable_path.size())) {
        throw std::system_error(static_cast<int>(GetLastError()), std::system_category(), "GetModuleFileNameW failed");
    }
    const auto shader_path = std::filesystem::path(executable_path.data()).parent_path() / L"fp16_probe.dxil";
    const auto shader = read_shader(shader_path);
    D3D12_COMPUTE_PIPELINE_STATE_DESC pipeline_description{};
    pipeline_description.pRootSignature = root_signature.Get();
    pipeline_description.CS = {shader.data(), shader.size()};
    ComPtr<ID3D12PipelineState> pipeline;
    check_hr(device->CreateComputePipelineState(&pipeline_description, IID_PPV_ARGS(&pipeline)), "CreateComputePipelineState failed");

    auto input_default = create_buffer(device.Get(), D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COPY_DEST);
    auto input_upload = create_buffer(device.Get(), D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ);
    auto output_default = create_buffer(
        device.Get(),
        D3D12_HEAP_TYPE_DEFAULT,
        D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
        D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS);
    auto output_readback = create_buffer(device.Get(), D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST);

    std::array<std::uint32_t, kProbeCount> inputs{};
    for (std::size_t index = 0; index < inputs.size(); ++index) {
        inputs[index] = static_cast<std::uint32_t>(input_half_a(index)) |
                        (static_cast<std::uint32_t>(input_half_b(index)) << 16U);
    }
    void* upload_data = nullptr;
    D3D12_RANGE no_read{0, 0};
    check_hr(input_upload->Map(0, &no_read, &upload_data), "Map input upload buffer failed");
    std::memcpy(upload_data, inputs.data(), kBufferBytes);
    input_upload->Unmap(0, nullptr);

    command_list->CopyBufferRegion(input_default.Get(), 0, input_upload.Get(), 0, kBufferBytes);
    D3D12_RESOURCE_BARRIER input_barrier{};
    input_barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    input_barrier.Transition.pResource = input_default.Get();
    input_barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    input_barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_COPY_DEST;
    input_barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
    command_list->ResourceBarrier(1, &input_barrier);

    const UINT descriptor_increment = device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
    const auto cpu_start = descriptor_heap->GetCPUDescriptorHandleForHeapStart();
    D3D12_CPU_DESCRIPTOR_HANDLE cpu_uav{cpu_start.ptr + descriptor_increment};
    const auto gpu_start = descriptor_heap->GetGPUDescriptorHandleForHeapStart();
    D3D12_GPU_DESCRIPTOR_HANDLE gpu_uav{gpu_start.ptr + descriptor_increment};

    D3D12_SHADER_RESOURCE_VIEW_DESC srv_description{};
    srv_description.Format = DXGI_FORMAT_R32_TYPELESS;
    srv_description.ViewDimension = D3D12_SRV_DIMENSION_BUFFER;
    srv_description.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
    srv_description.Buffer.NumElements = static_cast<UINT>(kProbeCount);
    srv_description.Buffer.Flags = D3D12_BUFFER_SRV_FLAG_RAW;
    device->CreateShaderResourceView(input_default.Get(), &srv_description, cpu_start);

    D3D12_UNORDERED_ACCESS_VIEW_DESC uav_description{};
    uav_description.Format = DXGI_FORMAT_R32_TYPELESS;
    uav_description.ViewDimension = D3D12_UAV_DIMENSION_BUFFER;
    uav_description.Buffer.NumElements = static_cast<UINT>(kProbeCount);
    uav_description.Buffer.Flags = D3D12_BUFFER_UAV_FLAG_RAW;
    device->CreateUnorderedAccessView(output_default.Get(), nullptr, &uav_description, cpu_uav);

    ID3D12DescriptorHeap* descriptor_heaps[] = {descriptor_heap.Get()};
    command_list->SetDescriptorHeaps(1, descriptor_heaps);
    command_list->SetComputeRootSignature(root_signature.Get());
    command_list->SetPipelineState(pipeline.Get());
    command_list->SetComputeRootDescriptorTable(0, gpu_start);
    command_list->SetComputeRootDescriptorTable(1, gpu_uav);
    command_list->Dispatch(1, 1, 1);

    D3D12_RESOURCE_BARRIER output_barrier{};
    output_barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    output_barrier.Transition.pResource = output_default.Get();
    output_barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    output_barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
    output_barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_COPY_SOURCE;
    command_list->ResourceBarrier(1, &output_barrier);
    command_list->CopyBufferRegion(output_readback.Get(), 0, output_default.Get(), 0, kBufferBytes);
    check_hr(command_list->Close(), "Close compute command list failed");

    ID3D12CommandList* command_lists[] = {command_list.Get()};
    queue->ExecuteCommandLists(1, command_lists);
    ComPtr<ID3D12Fence> fence;
    check_hr(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)), "CreateFence failed");
    check_hr(queue->Signal(fence.Get(), 1), "Signal fence failed");
    HANDLE fence_event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    if (fence_event == nullptr) {
        throw std::system_error(static_cast<int>(GetLastError()), std::system_category(), "CreateEventW failed");
    }
    const auto close_event = std::unique_ptr<void, decltype(&CloseHandle)>(fence_event, &CloseHandle);
    check_hr(fence->SetEventOnCompletion(1, fence_event), "SetEventOnCompletion failed");
    if (WaitForSingleObject(fence_event, 30000) != WAIT_OBJECT_0) {
        throw std::runtime_error("Timed out waiting for the RX 5700 XT FP16 probe dispatch");
    }

    void* readback_data = nullptr;
    D3D12_RANGE read_range{0, kBufferBytes};
    check_hr(output_readback->Map(0, &read_range, &readback_data), "Map FP16 probe readback buffer failed");
    std::array<std::uint32_t, kProbeCount> outputs{};
    std::memcpy(outputs.data(), readback_data, kBufferBytes);
    D3D12_RANGE no_write{0, 0};
    output_readback->Unmap(0, &no_write);

    for (std::size_t index = 0; index < outputs.size(); ++index) {
        const auto actual = static_cast<std::uint16_t>(outputs[index] & 0xffffU);
        if (actual != expected_half_product(index)) {
            throw std::runtime_error(
                "FP16 probe mismatch at element " + std::to_string(index) + ": expected 0x" +
                std::to_string(expected_half_product(index)) + ", got 0x" + std::to_string(actual));
        }
    }

    std::cout << "FP16 GPU arithmetic self-check passed on " << adapter_name << ": " << kProbeCount
              << " half-precision products matched expected results.\n";
    return 0;
}

} // namespace fsr4n10
