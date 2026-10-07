#include "fsr4n10/dot4_probe.h"

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
constexpr std::size_t kCases = 256;
constexpr std::size_t kStride = 16;
constexpr std::size_t kBytes = kCases * kStride;

void check_hr(HRESULT result, const char* operation) {
    if (FAILED(result)) throw std::system_error(static_cast<int>(result), std::system_category(), operation);
}

D3D12_HEAP_PROPERTIES heap_properties(D3D12_HEAP_TYPE type) {
    D3D12_HEAP_PROPERTIES properties{};
    properties.Type = type;
    properties.CreationNodeMask = 1;
    properties.VisibleNodeMask = 1;
    return properties;
}

ComPtr<ID3D12Resource> create_buffer(ID3D12Device* device, D3D12_HEAP_TYPE heap_type,
                                     D3D12_RESOURCE_STATES state, D3D12_RESOURCE_FLAGS flags) {
    D3D12_RESOURCE_DESC description{};
    description.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
    description.Width = kBytes;
    description.Height = 1;
    description.DepthOrArraySize = 1;
    description.MipLevels = 1;
    description.SampleDesc.Count = 1;
    description.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    description.Flags = flags;
    auto heap = heap_properties(heap_type);
    ComPtr<ID3D12Resource> resource;
    check_hr(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &description, state, nullptr,
                                             IID_PPV_ARGS(&resource)),
             "CreateCommittedResource(dot4) failed");
    return resource;
}

ComPtr<ID3D12Device> create_target_device(std::string& adapter_name) {
    ComPtr<IDXGIFactory6> factory;
    check_hr(CreateDXGIFactory2(0, IID_PPV_ARGS(&factory)), "CreateDXGIFactory2 failed");
    for (UINT index = 0;; ++index) {
        ComPtr<IDXGIAdapter1> adapter;
        HRESULT result = factory->EnumAdapters1(index, &adapter);
        if (result == DXGI_ERROR_NOT_FOUND) break;
        check_hr(result, "EnumAdapters1 failed");
        DXGI_ADAPTER_DESC1 description{};
        check_hr(adapter->GetDesc1(&description), "GetDesc1 failed");
        if (description.VendorId != 0x1002 || description.DeviceId != 0x731F ||
            (description.Flags & DXGI_ADAPTER_FLAG_SOFTWARE) != 0)
            continue;
        ComPtr<ID3D12Device> device;
        check_hr(D3D12CreateDevice(adapter.Get(), D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&device)),
                 "D3D12CreateDevice(dot4) failed");
        const int character_count = WideCharToMultiByte(CP_UTF8, 0, description.Description, -1, nullptr, 0, nullptr, nullptr);
        if (character_count > 1) {
            adapter_name.resize(static_cast<std::size_t>(character_count));
            WideCharToMultiByte(CP_UTF8, 0, description.Description, -1, adapter_name.data(), character_count, nullptr, nullptr);
            adapter_name.pop_back();
        }
        return device;
    }
    throw std::runtime_error("RX 5700 XT (1002:731F) was not found");
}

std::filesystem::path executable_dir() {
    std::array<wchar_t, 32768> path{};
    DWORD length = GetModuleFileNameW(nullptr, path.data(), static_cast<DWORD>(path.size()));
    if (length == 0 || length >= path.size())
        throw std::system_error(static_cast<int>(GetLastError()), std::system_category(), "GetModuleFileNameW failed");
    return std::filesystem::path(path.data()).parent_path();
}

std::vector<std::byte> read_shader(const std::filesystem::path& path) {
    std::ifstream file(path, std::ios::binary | std::ios::ate);
    if (!file) throw std::runtime_error("cannot open shader: " + path.string());
    const auto size = file.tellg();
    if (size <= 0) throw std::runtime_error("shader is empty: " + path.string());
    std::vector<std::byte> data(static_cast<std::size_t>(size));
    file.seekg(0);
    file.read(reinterpret_cast<char*>(data.data()), static_cast<std::streamsize>(data.size()));
    if (!file) throw std::runtime_error("failed reading shader: " + path.string());
    return data;
}
}

int run_dot4_conformance(const std::filesystem::path& report_path) {
    std::string adapter_name;
    auto device = create_target_device(adapter_name);

    ComPtr<ID3D12CommandQueue> queue;
    D3D12_COMMAND_QUEUE_DESC queue_description{};
    queue_description.Type = D3D12_COMMAND_LIST_TYPE_COMPUTE;
    check_hr(device->CreateCommandQueue(&queue_description, IID_PPV_ARGS(&queue)), "CreateCommandQueue(dot4) failed");

    ComPtr<ID3D12CommandAllocator> allocator;
    check_hr(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_COMPUTE, IID_PPV_ARGS(&allocator)),
             "CreateCommandAllocator(dot4) failed");
    ComPtr<ID3D12GraphicsCommandList> command_list;
    check_hr(device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_COMPUTE, allocator.Get(), nullptr,
                                       IID_PPV_ARGS(&command_list)),
             "CreateCommandList(dot4) failed");

    D3D12_DESCRIPTOR_RANGE range{};
    range.RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_UAV;
    range.NumDescriptors = 1;
    range.BaseShaderRegister = 0;
    D3D12_ROOT_PARAMETER parameter{};
    parameter.ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
    parameter.DescriptorTable.NumDescriptorRanges = 1;
    parameter.DescriptorTable.pDescriptorRanges = &range;
    D3D12_ROOT_SIGNATURE_DESC root_description{};
    root_description.NumParameters = 1;
    root_description.pParameters = &parameter;
    ComPtr<ID3DBlob> serialized_root;
    ComPtr<ID3DBlob> root_errors;
    check_hr(D3D12SerializeRootSignature(&root_description, D3D_ROOT_SIGNATURE_VERSION_1,
                                         &serialized_root, &root_errors),
             "D3D12SerializeRootSignature(dot4) failed");
    ComPtr<ID3D12RootSignature> root_signature;
    check_hr(device->CreateRootSignature(0, serialized_root->GetBufferPointer(), serialized_root->GetBufferSize(),
                                         IID_PPV_ARGS(&root_signature)),
             "CreateRootSignature(dot4) failed");

    const auto shader = read_shader(executable_dir() / L"dot4_conformance.dxil");
    D3D12_COMPUTE_PIPELINE_STATE_DESC pipeline_description{};
    pipeline_description.pRootSignature = root_signature.Get();
    pipeline_description.CS = {shader.data(), shader.size()};
    ComPtr<ID3D12PipelineState> pipeline;
    check_hr(device->CreateComputePipelineState(&pipeline_description, IID_PPV_ARGS(&pipeline)),
             "CreateComputePipelineState(dot4) failed");

    auto output = create_buffer(device.Get(), D3D12_HEAP_TYPE_DEFAULT,
                                D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
                                D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS);
    auto readback = create_buffer(device.Get(), D3D12_HEAP_TYPE_READBACK,
                                  D3D12_RESOURCE_STATE_COPY_DEST,
                                  D3D12_RESOURCE_FLAG_NONE);

    ComPtr<ID3D12DescriptorHeap> descriptor_heap;
    D3D12_DESCRIPTOR_HEAP_DESC heap_description{};
    heap_description.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
    heap_description.NumDescriptors = 1;
    heap_description.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
    check_hr(device->CreateDescriptorHeap(&heap_description, IID_PPV_ARGS(&descriptor_heap)),
             "CreateDescriptorHeap(dot4) failed");

    D3D12_UNORDERED_ACCESS_VIEW_DESC uav{};
    uav.Format = DXGI_FORMAT_R32_TYPELESS;
    uav.ViewDimension = D3D12_UAV_DIMENSION_BUFFER;
    uav.Buffer.NumElements = static_cast<UINT>(kBytes / 4);
    uav.Buffer.Flags = D3D12_BUFFER_UAV_FLAG_RAW;
    device->CreateUnorderedAccessView(output.Get(), nullptr, &uav, descriptor_heap->GetCPUDescriptorHandleForHeapStart());

    ID3D12DescriptorHeap* descriptor_heaps[] = {descriptor_heap.Get()};
    command_list->SetDescriptorHeaps(1, descriptor_heaps);
    command_list->SetComputeRootSignature(root_signature.Get());
    command_list->SetPipelineState(pipeline.Get());
    command_list->SetComputeRootDescriptorTable(0, descriptor_heap->GetGPUDescriptorHandleForHeapStart());
    command_list->Dispatch(static_cast<UINT>((kCases + 63) / 64), 1, 1);

    D3D12_RESOURCE_BARRIER barrier{};
    barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    barrier.Transition.pResource = output.Get();
    barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
    barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_COPY_SOURCE;
    command_list->ResourceBarrier(1, &barrier);
    command_list->CopyBufferRegion(readback.Get(), 0, output.Get(), 0, kBytes);
    check_hr(command_list->Close(), "Close(dot4) failed");
    ID3D12CommandList* lists[] = {command_list.Get()};
    queue->ExecuteCommandLists(1, lists);

    ComPtr<ID3D12Fence> fence;
    check_hr(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)), "CreateFence(dot4) failed");
    check_hr(queue->Signal(fence.Get(), 1), "Signal(dot4) failed");
    HANDLE event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    if (!event) throw std::system_error(static_cast<int>(GetLastError()), std::system_category(), "CreateEventW(dot4) failed");
    const auto close_event = std::unique_ptr<void, decltype(&CloseHandle)>(event, &CloseHandle);
    check_hr(fence->SetEventOnCompletion(1, event), "SetEventOnCompletion(dot4) failed");
    if (WaitForSingleObject(event, 30000) != WAIT_OBJECT_0)
        throw std::runtime_error("dot4 conformance GPU timeout");

    void* mapped = nullptr;
    D3D12_RANGE read_range{0, kBytes};
    check_hr(readback->Map(0, &read_range, &mapped), "Map(dot4) failed");
    std::array<std::uint32_t, kBytes / 4> words{};
    std::memcpy(words.data(), mapped, kBytes);
    D3D12_RANGE no_write{0, 0};
    readback->Unmap(0, &no_write);

    std::size_t mismatches = 0;
    struct Example { std::size_t index; std::int32_t native; std::int32_t scalar; std::uint32_t a; std::uint32_t b; };
    std::vector<Example> examples;
    for (std::size_t index = 0; index < kCases; ++index) {
        const std::size_t base = index * 4;
        const auto native_value = static_cast<std::int32_t>(words[base]);
        const auto scalar_value = static_cast<std::int32_t>(words[base + 1]);
        if (native_value != scalar_value) {
            ++mismatches;
            if (examples.size() < 16)
                examples.push_back({index, native_value, scalar_value, words[base + 2], words[base + 3]});
        }
    }

    if (!report_path.parent_path().empty()) std::filesystem::create_directories(report_path.parent_path());
    std::ofstream report(report_path, std::ios::binary | std::ios::trunc);
    if (!report) throw std::runtime_error("cannot write dot4 report");
    report << "{\n"
           << "  \"schema\": \"f4n10.dot4-conformance.v1\",\n"
           << "  \"adapter\": \"" << adapter_name << "\",\n"
           << "  \"case_count\": " << kCases << ",\n"
           << "  \"mismatch_count\": " << mismatches << ",\n"
           << "  \"native_matches_scalar\": " << (mismatches == 0 ? "true" : "false") << ",\n"
           << "  \"examples\": [";
    for (std::size_t index = 0; index < examples.size(); ++index) {
        if (index) report << ',';
        const auto& example = examples[index];
        report << "\n    {\"index\": " << example.index
               << ", \"native\": " << example.native
               << ", \"scalar\": " << example.scalar
               << ", \"a\": \"0x" << std::hex << std::setw(8) << std::setfill('0') << example.a
               << "\", \"b\": \"0x" << std::setw(8) << example.b << "\"}" << std::dec;
    }
    if (!examples.empty()) report << '\n';
    report << "  ]\n}\n";

    std::cout << "dot4add_i8packed conformance on " << adapter_name << ": "
              << (kCases - mismatches) << "/" << kCases
              << " cases matched scalar signed-I8 semantics.\n";
    return mismatches == 0 ? 0 : 3;
}
} // namespace fsr4n10
