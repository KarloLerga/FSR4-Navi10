// Included from gpu_teacher.cpp *inside* its unnamed namespace, after
// read_binary_file() and before write_capture_manifest().
// Deliberately scoped to debug harness; never install as production code.

bool fsr4n10_read_environment(const wchar_t* name, std::wstring& value) {
    wchar_t* owned_value = nullptr;
    std::size_t buffer_size = 0;
    const auto status = _wdupenv_s(&owned_value, &buffer_size, name);
    if (status != 0 || owned_value == nullptr) {
        std::free(owned_value);
        return false;
    }
    value.assign(owned_value);
    std::free(owned_value);
    return true;
}

int fsr4n10_parse_environment_integer(const std::wstring& value, int minimum, int maximum) {
    wchar_t* end = nullptr;
    const long parsed = std::wcstol(value.c_str(), &end, 10);
    if (end == value.c_str() || *end != L'\0' || parsed < minimum || parsed > maximum)
        throw std::runtime_error("Invalid integer value for FSR4 diagnostic environment variable");
    return static_cast<int>(parsed);
}

struct Fsr4N10ScratchFill {
    ComPtr<ID3D12RootSignature> root;
    ComPtr<ID3D12PipelineState> pso;

    explicit Fsr4N10ScratchFill(ID3D12Device* device) {
        D3D12_ROOT_PARAMETER parameters[2]{};
        parameters[0].ParameterType = D3D12_ROOT_PARAMETER_TYPE_UAV;
        parameters[0].Descriptor.ShaderRegister = 0;
        parameters[0].Descriptor.RegisterSpace = 0;
        parameters[0].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
        parameters[1].ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
        parameters[1].Constants.ShaderRegister = 0;
        parameters[1].Constants.RegisterSpace = 0;
        parameters[1].Constants.Num32BitValues = 2;
        parameters[1].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;

        D3D12_ROOT_SIGNATURE_DESC description{};
        description.NumParameters = 2;
        description.pParameters = parameters;
        ComPtr<ID3DBlob> signature;
        ComPtr<ID3DBlob> errors;
        check_hr(D3D12SerializeRootSignature(&description, D3D_ROOT_SIGNATURE_VERSION_1,
                                             &signature, &errors),
                 "SerializeRootSignature(FSR4 scratch fill) failed");
        check_hr(device->CreateRootSignature(0, signature->GetBufferPointer(),
                                             signature->GetBufferSize(), IID_PPV_ARGS(&root)),
                 "CreateRootSignature(FSR4 scratch fill) failed");

        std::array<wchar_t, 32768> exe_path{};
        const DWORD length = GetModuleFileNameW(nullptr, exe_path.data(),
                                               static_cast<DWORD>(exe_path.size()));
        if (length == 0 || length >= exe_path.size())
            throw std::runtime_error("Unable to locate FSR4 scratch-fill DXIL near executable");
        const auto shader_path = std::filesystem::path(exe_path.data()).parent_path() /
                                 L"fsr4_scratch_fill.dxil";
        const auto shader_bytes = read_binary_file(shader_path);
        if (shader_bytes.empty())
            throw std::runtime_error("Empty FSR4 scratch-fill DXIL");
        D3D12_COMPUTE_PIPELINE_STATE_DESC pipeline{};
        pipeline.pRootSignature = root.Get();
        pipeline.CS = {shader_bytes.data(), shader_bytes.size()};
        check_hr(device->CreateComputePipelineState(&pipeline, IID_PPV_ARGS(&pso)),
                 "CreateComputePipelineState(FSR4 scratch fill) failed");
    }

    void record(ID3D12GraphicsCommandList* list, ID3D12Resource* scratch,
                std::uint32_t pattern) const {
        if (scratch == nullptr)
            throw std::runtime_error("Missing FSR4 scratch buffer");
        const auto description = scratch->GetDesc();
        if (description.Dimension != D3D12_RESOURCE_DIMENSION_BUFFER ||
            description.Width == 0 || description.Width % 4u != 0 ||
            description.Width / 4u > static_cast<std::uint64_t>(65535u) * 256u ||
            (description.Flags & D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS) == 0)
            throw std::runtime_error("Unexpected scratch buffer size/flags for diagnostic fill");
        const std::uint32_t word_count = static_cast<std::uint32_t>(description.Width / 4u);
        const std::uint32_t constants[2]{word_count, pattern};
        list->SetComputeRootSignature(root.Get());
        list->SetPipelineState(pso.Get());
        list->SetComputeRootUnorderedAccessView(0, scratch->GetGPUVirtualAddress());
        list->SetComputeRoot32BitConstants(1, 2, constants, 0);
        list->Dispatch((word_count + 255u) / 256u, 1, 1);

        D3D12_RESOURCE_BARRIER barrier{};
        barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_UAV;
        barrier.UAV.pResource = scratch;
        list->ResourceBarrier(1, &barrier);
    }
};

std::vector<std::byte> fsr4n10_read_scratch(
    ID3D12Device* device, ID3D12CommandQueue* queue, ID3D12CommandAllocator* allocator,
    ID3D12GraphicsCommandList* command_list, QueueWaiter& waiter,
    ID3D12Resource* scratch, D3D12_RESOURCE_STATES initial_state) {
    if (scratch == nullptr)
        throw std::runtime_error("Null FSR4 scratch readback");
    const auto desc = scratch->GetDesc();
    if (desc.Dimension != D3D12_RESOURCE_DIMENSION_BUFFER || desc.Width == 0 ||
        desc.Width > static_cast<std::uint64_t>(512) * 1024 * 1024)
        throw std::runtime_error("Invalid or excessive FSR4 scratch readback buffer size");

    auto readback = create_buffer(device, D3D12_HEAP_TYPE_READBACK,
                                  D3D12_RESOURCE_STATE_COPY_DEST, desc.Width);
    check_hr(allocator->Reset(), "Reset scratch readback allocator failed");
    check_hr(command_list->Reset(allocator, nullptr), "Reset scratch readback list failed");
    if (initial_state != D3D12_RESOURCE_STATE_COPY_SOURCE) {
        D3D12_RESOURCE_BARRIER to_copy{};
        to_copy.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        to_copy.Transition.pResource = scratch;
        to_copy.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
        to_copy.Transition.StateBefore = initial_state;
        to_copy.Transition.StateAfter = D3D12_RESOURCE_STATE_COPY_SOURCE;
        command_list->ResourceBarrier(1, &to_copy);
    }
    command_list->CopyBufferRegion(readback.Get(), 0, scratch, 0, desc.Width);
    if (initial_state != D3D12_RESOURCE_STATE_COPY_SOURCE) {
        D3D12_RESOURCE_BARRIER restore{};
        restore.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        restore.Transition.pResource = scratch;
        restore.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
        restore.Transition.StateBefore = D3D12_RESOURCE_STATE_COPY_SOURCE;
        restore.Transition.StateAfter = initial_state;
        command_list->ResourceBarrier(1, &restore);
    }
    check_hr(command_list->Close(), "Close scratch readback list failed");
    ID3D12CommandList* lists[]{command_list};
    queue->ExecuteCommandLists(1, lists);
    waiter.wait(queue);

    std::vector<std::byte> output(static_cast<std::size_t>(desc.Width));
    void* mapped = nullptr;
    const D3D12_RANGE read_range{0, static_cast<SIZE_T>(desc.Width)};
    check_hr(readback->Map(0, &read_range, &mapped), "Map scratch readback failed");
    std::memcpy(output.data(), mapped, output.size());
    const D3D12_RANGE no_write{0, 0};
    readback->Unmap(0, &no_write);
    return output;
}

std::uint32_t fsr4n10_scratch_pattern_from_mode(const std::wstring& mode,
                                               std::string& canonical_mode) {
    if (mode.empty() || mode == L"off") {
        canonical_mode = "off";
        return 0;
    }
    if (mode == L"zero") {
        canonical_mode = "zero";
        return 0;
    }
    if (mode == L"a5") {
        canonical_mode = "a5";
        return 0xa5a5a5a5u;
    }
    if (mode == L"5a") {
        canonical_mode = "5a";
        return 0x5a5a5a5au;
    }
    if (mode == L"ones") {
        canonical_mode = "ones";
        return 0xffffffffu;
    }
    throw std::runtime_error("Invalid FSR4N10_SCRATCH_INIT: expected off/zero/a5/5a/ones");
}
