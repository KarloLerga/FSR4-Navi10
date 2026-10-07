#include "fsr4n10/fsr4_post_oracle.h"

#include <algorithm>
#include <array>
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
#include <utility>
#include <vector>

#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <wrl/client.h>
#include <Windows.h>
#include <d3d12.h>
#include <dxgi1_6.h>

namespace fsr4n10 {
namespace {
using Microsoft::WRL::ComPtr;

#pragma pack(push, 1)
struct CaseHeader {
    char magic[8];
    std::uint32_t version;
    std::uint32_t renderWidth;
    std::uint32_t renderHeight;
    std::uint32_t outputWidth;
    std::uint32_t outputHeight;
    std::uint32_t reserved0;
    std::uint32_t reserved1;
    float jitterX;
    float jitterY;
    float exposureValue;
    float reservedF;
};
#pragma pack(pop)

struct CaseData {
    CaseHeader header{};
    std::vector<float> source;
    std::vector<float> history;
    std::vector<float> parameters;
    std::vector<float> reference;
};

void check_hr(HRESULT result, const char* operation) {
    if (FAILED(result)) throw std::system_error(static_cast<int>(result), std::system_category(), operation);
}

CaseData load_case(const std::filesystem::path& path) {
    std::ifstream file(path, std::ios::binary);
    if (!file) throw std::runtime_error("cannot open f4postcase: " + path.string());
    CaseData data;
    file.read(reinterpret_cast<char*>(&data.header), sizeof(data.header));
    if (!file || std::memcmp(data.header.magic, "F4POST01", 8) != 0 || data.header.version != 1)
        throw std::runtime_error("invalid f4postcase header");
    const auto valid_dimension = [](std::uint32_t value) { return value > 0 && value <= 16384; };
    if (!valid_dimension(data.header.renderWidth) || !valid_dimension(data.header.renderHeight) ||
        !valid_dimension(data.header.outputWidth) || !valid_dimension(data.header.outputHeight))
        throw std::runtime_error("f4postcase dimensions are outside [1, 16384]");
    const std::uint64_t render_pixels = static_cast<std::uint64_t>(data.header.renderWidth) * data.header.renderHeight;
    const std::uint64_t output_pixels = static_cast<std::uint64_t>(data.header.outputWidth) * data.header.outputHeight;
    const std::uint64_t expected_bytes = sizeof(CaseHeader) +
        (render_pixels + 3 * output_pixels) * 4 * sizeof(float);
    if (expected_bytes > 1024ull * 1024ull * 1024ull)
        throw std::runtime_error("f4postcase exceeds the 1 GiB payload limit");
    file.seekg(0, std::ios::end);
    if (file.tellg() < 0 || static_cast<std::uint64_t>(file.tellg()) != expected_bytes)
        throw std::runtime_error("f4postcase byte size does not match its dimensions");
    file.seekg(sizeof(CaseHeader), std::ios::beg);
    if (!std::isfinite(data.header.jitterX) || !std::isfinite(data.header.jitterY) ||
        !std::isfinite(data.header.exposureValue) || data.header.exposureValue <= 0.0f)
        throw std::runtime_error("f4postcase exposure and jitter must be finite; exposure must be positive");
    data.source.resize(static_cast<std::size_t>(render_pixels * 4));
    data.history.resize(static_cast<std::size_t>(output_pixels * 4));
    data.parameters.resize(static_cast<std::size_t>(output_pixels * 4));
    data.reference.resize(static_cast<std::size_t>(output_pixels * 4));
    for (auto* values : {&data.source, &data.history, &data.parameters, &data.reference}) {
        file.read(reinterpret_cast<char*>(values->data()), static_cast<std::streamsize>(values->size() * sizeof(float)));
        if (!file) throw std::runtime_error("truncated f4postcase payload");
    }
    char extra = 0;
    if (file.read(&extra, 1)) throw std::runtime_error("f4postcase has trailing bytes");
    return data;
}

D3D12_HEAP_PROPERTIES heap_properties(D3D12_HEAP_TYPE type) {
    D3D12_HEAP_PROPERTIES properties{};
    properties.Type = type;
    properties.CreationNodeMask = 1;
    properties.VisibleNodeMask = 1;
    return properties;
}

ComPtr<ID3D12Resource> create_buffer(ID3D12Device* device, std::uint64_t bytes,
                                     D3D12_HEAP_TYPE heap_type, D3D12_RESOURCE_STATES state,
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
    auto heap = heap_properties(heap_type);
    ComPtr<ID3D12Resource> resource;
    check_hr(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &description, state, nullptr,
                                             IID_PPV_ARGS(&resource)),
             "CreateCommittedResource(post oracle) failed");
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
                 "D3D12CreateDevice(post oracle) failed");
        const int character_count = WideCharToMultiByte(CP_UTF8, 0, description.Description, -1, nullptr, 0, nullptr, nullptr);
        if (character_count > 1) {
            adapter_name.resize(static_cast<std::size_t>(character_count));
            WideCharToMultiByte(CP_UTF8, 0, description.Description, -1, adapter_name.data(), character_count, nullptr, nullptr);
            adapter_name.pop_back();
        }
        return device;
    }
    throw std::runtime_error("RX 5700 XT was not found");
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
    std::vector<std::byte> bytes(static_cast<std::size_t>(size));
    file.seekg(0);
    file.read(reinterpret_cast<char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
    if (!file) throw std::runtime_error("failed reading shader: " + path.string());
    return bytes;
}

void upload_buffer(ID3D12Resource* upload, const std::vector<float>& values) {
    void* mapped = nullptr;
    D3D12_RANGE no_read{0, 0};
    check_hr(upload->Map(0, &no_read, &mapped), "Map(post upload) failed");
    std::memcpy(mapped, values.data(), values.size() * sizeof(float));
    upload->Unmap(0, nullptr);
}
}

int run_fsr4_post_gpu_oracle(const std::filesystem::path& case_path,
                             const std::filesystem::path& report_path) {
    const auto data = load_case(case_path);
    std::string adapter_name;
    auto device = create_target_device(adapter_name);

    ComPtr<ID3D12CommandQueue> queue;
    D3D12_COMMAND_QUEUE_DESC queue_description{};
    queue_description.Type = D3D12_COMMAND_LIST_TYPE_COMPUTE;
    check_hr(device->CreateCommandQueue(&queue_description, IID_PPV_ARGS(&queue)),
             "CreateCommandQueue(post oracle) failed");
    ComPtr<ID3D12CommandAllocator> allocator;
    check_hr(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_COMPUTE, IID_PPV_ARGS(&allocator)),
             "CreateCommandAllocator(post oracle) failed");
    ComPtr<ID3D12GraphicsCommandList> command_list;
    check_hr(device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_COMPUTE, allocator.Get(), nullptr,
                                       IID_PPV_ARGS(&command_list)),
             "CreateCommandList(post oracle) failed");

    const std::uint64_t source_bytes = data.source.size() * sizeof(float);
    const std::uint64_t history_bytes = data.history.size() * sizeof(float);
    const std::uint64_t parameter_bytes = data.parameters.size() * sizeof(float);
    const std::uint64_t output_bytes = data.reference.size() * sizeof(float);

    auto source = create_buffer(device.Get(), source_bytes, D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COPY_DEST);
    auto history = create_buffer(device.Get(), history_bytes, D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COPY_DEST);
    auto parameters = create_buffer(device.Get(), parameter_bytes, D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COPY_DEST);
    auto source_upload = create_buffer(device.Get(), source_bytes, D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ);
    auto history_upload = create_buffer(device.Get(), history_bytes, D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ);
    auto parameters_upload = create_buffer(device.Get(), parameter_bytes, D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ);
    auto output = create_buffer(device.Get(), output_bytes, D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
                                D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS);
    auto readback = create_buffer(device.Get(), output_bytes, D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST);

    upload_buffer(source_upload.Get(), data.source);
    upload_buffer(history_upload.Get(), data.history);
    upload_buffer(parameters_upload.Get(), data.parameters);
    command_list->CopyBufferRegion(source.Get(), 0, source_upload.Get(), 0, source_bytes);
    command_list->CopyBufferRegion(history.Get(), 0, history_upload.Get(), 0, history_bytes);
    command_list->CopyBufferRegion(parameters.Get(), 0, parameters_upload.Get(), 0, parameter_bytes);

    std::array<D3D12_RESOURCE_BARRIER, 3> to_srv{};
    ID3D12Resource* srv_resources[] = {source.Get(), history.Get(), parameters.Get()};
    for (std::size_t index = 0; index < to_srv.size(); ++index) {
        to_srv[index].Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        to_srv[index].Transition.pResource = srv_resources[index];
        to_srv[index].Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
        to_srv[index].Transition.StateBefore = D3D12_RESOURCE_STATE_COPY_DEST;
        to_srv[index].Transition.StateAfter = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
    }
    command_list->ResourceBarrier(static_cast<UINT>(to_srv.size()), to_srv.data());

    D3D12_DESCRIPTOR_RANGE ranges[2]{};
    ranges[0].RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_SRV;
    ranges[0].NumDescriptors = 3;
    ranges[0].BaseShaderRegister = 0;
    ranges[0].OffsetInDescriptorsFromTableStart = 0;
    ranges[1].RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_UAV;
    ranges[1].NumDescriptors = 1;
    ranges[1].BaseShaderRegister = 0;
    ranges[1].OffsetInDescriptorsFromTableStart = 3;

    D3D12_ROOT_PARAMETER root_parameters[2]{};
    root_parameters[0].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
    root_parameters[0].DescriptorTable.NumDescriptorRanges = 2;
    root_parameters[0].DescriptorTable.pDescriptorRanges = ranges;
    root_parameters[1].ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
    root_parameters[1].Constants.Num32BitValues = 8;
    root_parameters[1].Constants.ShaderRegister = 0;

    D3D12_ROOT_SIGNATURE_DESC root_description{};
    root_description.NumParameters = 2;
    root_description.pParameters = root_parameters;
    ComPtr<ID3DBlob> serialized_root;
    ComPtr<ID3DBlob> root_errors;
    check_hr(D3D12SerializeRootSignature(&root_description, D3D_ROOT_SIGNATURE_VERSION_1,
                                         &serialized_root, &root_errors),
             "D3D12SerializeRootSignature(post oracle) failed");
    ComPtr<ID3D12RootSignature> root_signature;
    check_hr(device->CreateRootSignature(0, serialized_root->GetBufferPointer(), serialized_root->GetBufferSize(),
                                         IID_PPV_ARGS(&root_signature)),
             "CreateRootSignature(post oracle) failed");

    const auto shader = read_shader(executable_dir() / L"fsr4_post_oracle.dxil");
    D3D12_COMPUTE_PIPELINE_STATE_DESC pipeline_description{};
    pipeline_description.pRootSignature = root_signature.Get();
    pipeline_description.CS = {shader.data(), shader.size()};
    ComPtr<ID3D12PipelineState> pipeline;
    check_hr(device->CreateComputePipelineState(&pipeline_description, IID_PPV_ARGS(&pipeline)),
             "CreateComputePipelineState(post oracle) failed");

    ComPtr<ID3D12DescriptorHeap> descriptor_heap;
    D3D12_DESCRIPTOR_HEAP_DESC heap_description{};
    heap_description.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
    heap_description.NumDescriptors = 4;
    heap_description.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
    check_hr(device->CreateDescriptorHeap(&heap_description, IID_PPV_ARGS(&descriptor_heap)),
             "CreateDescriptorHeap(post oracle) failed");
    const UINT increment = device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
    const auto cpu_start = descriptor_heap->GetCPUDescriptorHandleForHeapStart();

    const std::array<std::pair<ID3D12Resource*, std::uint64_t>, 3> srv_info{{
        {source.Get(), source_bytes}, {history.Get(), history_bytes}, {parameters.Get(), parameter_bytes}
    }};
    for (std::size_t index = 0; index < srv_info.size(); ++index) {
        D3D12_SHADER_RESOURCE_VIEW_DESC description{};
        description.Format = DXGI_FORMAT_R32_TYPELESS;
        description.ViewDimension = D3D12_SRV_DIMENSION_BUFFER;
        description.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
        description.Buffer.NumElements = static_cast<UINT>(srv_info[index].second / 4);
        description.Buffer.Flags = D3D12_BUFFER_SRV_FLAG_RAW;
        D3D12_CPU_DESCRIPTOR_HANDLE handle{cpu_start.ptr + index * increment};
        device->CreateShaderResourceView(srv_info[index].first, &description, handle);
    }
    D3D12_UNORDERED_ACCESS_VIEW_DESC uav{};
    uav.Format = DXGI_FORMAT_R32_TYPELESS;
    uav.ViewDimension = D3D12_UAV_DIMENSION_BUFFER;
    uav.Buffer.NumElements = static_cast<UINT>(output_bytes / 4);
    uav.Buffer.Flags = D3D12_BUFFER_UAV_FLAG_RAW;
    D3D12_CPU_DESCRIPTOR_HANDLE uav_cpu{cpu_start.ptr + 3 * increment};
    device->CreateUnorderedAccessView(output.Get(), nullptr, &uav, uav_cpu);

    ID3D12DescriptorHeap* heaps[] = {descriptor_heap.Get()};
    command_list->SetDescriptorHeaps(1, heaps);
    command_list->SetComputeRootSignature(root_signature.Get());
    command_list->SetPipelineState(pipeline.Get());
    command_list->SetComputeRootDescriptorTable(0, descriptor_heap->GetGPUDescriptorHandleForHeapStart());

    std::array<std::uint32_t, 8> constants{};
    constants[0] = data.header.renderWidth;
    constants[1] = data.header.renderHeight;
    constants[2] = data.header.outputWidth;
    constants[3] = data.header.outputHeight;
    std::memcpy(&constants[4], &data.header.jitterX, sizeof(float));
    std::memcpy(&constants[5], &data.header.jitterY, sizeof(float));
    std::memcpy(&constants[6], &data.header.exposureValue, sizeof(float));
    constants[7] = 0;
    command_list->SetComputeRoot32BitConstants(1, static_cast<UINT>(constants.size()), constants.data(), 0);
    command_list->Dispatch((data.header.outputWidth + 7) / 8, (data.header.outputHeight + 7) / 8, 1);

    D3D12_RESOURCE_BARRIER output_barrier{};
    output_barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    output_barrier.Transition.pResource = output.Get();
    output_barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    output_barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
    output_barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_COPY_SOURCE;
    command_list->ResourceBarrier(1, &output_barrier);
    command_list->CopyBufferRegion(readback.Get(), 0, output.Get(), 0, output_bytes);
    check_hr(command_list->Close(), "Close(post oracle) failed");
    ID3D12CommandList* lists[] = {command_list.Get()};
    queue->ExecuteCommandLists(1, lists);

    ComPtr<ID3D12Fence> fence;
    check_hr(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)), "CreateFence(post oracle) failed");
    check_hr(queue->Signal(fence.Get(), 1), "Signal(post oracle) failed");
    HANDLE event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    if (!event) throw std::runtime_error("CreateEvent(post oracle) failed");
    const auto close_event = std::unique_ptr<void, decltype(&CloseHandle)>(event, &CloseHandle);
    check_hr(fence->SetEventOnCompletion(1, event), "SetEventOnCompletion(post oracle) failed");
    if (WaitForSingleObject(event, 60000) != WAIT_OBJECT_0)
        throw std::runtime_error("post oracle GPU timeout");

    std::vector<float> actual(data.reference.size());
    void* mapped = nullptr;
    D3D12_RANGE read_range{0, static_cast<SIZE_T>(output_bytes)};
    check_hr(readback->Map(0, &read_range, &mapped), "Map(post oracle readback) failed");
    std::memcpy(actual.data(), mapped, static_cast<std::size_t>(output_bytes));
    D3D12_RANGE no_write{0, 0};
    readback->Unmap(0, &no_write);

    double sum_abs = 0.0;
    double sum_sq = 0.0;
    float max_abs = 0.0f;
    std::uint64_t compared = 0;
    std::uint64_t within = 0;
    std::uint64_t nonfinite = 0;
    const std::uint64_t pixels = static_cast<std::uint64_t>(data.header.outputWidth) * data.header.outputHeight;
    for (std::uint64_t pixel = 0; pixel < pixels; ++pixel) {
        for (int channel = 0; channel < 3; ++channel) {
            const float a = actual[static_cast<std::size_t>(pixel * 4 + channel)];
            const float b = data.reference[static_cast<std::size_t>(pixel * 4 + channel)];
            if (!std::isfinite(a) || !std::isfinite(b)) {
                ++nonfinite;
                continue;
            }
            const float difference = std::abs(a - b);
            max_abs = (std::max)(max_abs, difference);
            sum_abs += difference;
            sum_sq += static_cast<double>(difference) * difference;
            ++compared;
            if (difference <= 1.0e-3f) ++within;
        }
    }
    const double mean = compared ? sum_abs / compared : std::numeric_limits<double>::infinity();
    const double rms = compared ? std::sqrt(sum_sq / compared) : std::numeric_limits<double>::infinity();
    const double within_fraction = compared ? static_cast<double>(within) / compared : 0.0;
    const bool passed = nonfinite == 0 && within_fraction >= 0.99999 && max_abs <= 0.0025f;

    if (!report_path.parent_path().empty()) std::filesystem::create_directories(report_path.parent_path());
    std::ofstream report(report_path, std::ios::binary | std::ios::trunc);
    if (!report) throw std::runtime_error("cannot write post oracle report");
    report << "{\n"
           << "  \"schema\": \"f4n10.fsr4-post-gpu-oracle.v1\",\n"
           << "  \"adapter\": \"" << adapter_name << "\",\n"
           << "  \"render_size\": [" << data.header.renderWidth << ", " << data.header.renderHeight << "],\n"
           << "  \"output_size\": [" << data.header.outputWidth << ", " << data.header.outputHeight << "],\n"
           << "  \"nonfinite_components\": " << nonfinite << ",\n"
           << "  \"within_1e_3_fraction\": " << within_fraction << ",\n"
           << "  \"max_absolute_error\": " << max_abs << ",\n"
           << "  \"mean_absolute_error\": " << mean << ",\n"
           << "  \"rms_error\": " << rms << ",\n"
           << "  \"passed\": " << (passed ? "true" : "false") << "\n"
           << "}\n";

    std::cout << "FSR4 GPU POST oracle: within1e-3=" << within_fraction
              << ", max_abs=" << max_abs << ", rms=" << rms
              << ", pass=" << (passed ? "yes" : "no") << ".\n";
    return passed ? 0 : 4;
}
} // namespace fsr4n10
