#include "fsr4n10/device_caps.h"

#include <array>
#include <stdexcept>
#include <string>
#include <system_error>
#include <wrl/client.h>

#include <Windows.h>
#include <d3d12.h>
#include <dxgi1_6.h>

namespace fsr4n10 {
namespace {

using Microsoft::WRL::ComPtr;

std::string utf8_from_wide(const wchar_t* text) {
    if (text == nullptr || *text == L'\0') {
        return {};
    }

    const int required = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, text, -1, nullptr, 0, nullptr, nullptr);
    if (required <= 1) {
        throw std::system_error(static_cast<int>(GetLastError()), std::system_category(), "WideCharToMultiByte size query failed");
    }

    std::string result(static_cast<std::size_t>(required), '\0');
    const int converted = WideCharToMultiByte(
        CP_UTF8,
        WC_ERR_INVALID_CHARS,
        text,
        -1,
        result.data(),
        required,
        nullptr,
        nullptr);
    if (converted != required) {
        throw std::system_error(static_cast<int>(GetLastError()), std::system_category(), "WideCharToMultiByte conversion failed");
    }
    result.pop_back();
    return result;
}

std::uint32_t query_shader_model(ID3D12Device* device) {
    constexpr std::array candidates{
        D3D_SHADER_MODEL_6_8,
        D3D_SHADER_MODEL_6_7,
        D3D_SHADER_MODEL_6_6,
        D3D_SHADER_MODEL_6_5,
        D3D_SHADER_MODEL_6_4,
        D3D_SHADER_MODEL_6_3,
        D3D_SHADER_MODEL_6_2,
        D3D_SHADER_MODEL_6_1,
        D3D_SHADER_MODEL_6_0,
        D3D_SHADER_MODEL_5_1,
    };

    for (const D3D_SHADER_MODEL requested : candidates) {
        D3D12_FEATURE_DATA_SHADER_MODEL feature{requested};
        if (SUCCEEDED(device->CheckFeatureSupport(D3D12_FEATURE_SHADER_MODEL, &feature, sizeof(feature)))) {
            return static_cast<std::uint32_t>(feature.HighestShaderModel);
        }
    }
    return 0;
}

DeviceCaps describe_adapter(std::uint32_t index, IDXGIAdapter4* adapter) {
    DXGI_ADAPTER_DESC3 description{};
    const HRESULT descriptionResult = adapter->GetDesc3(&description);
    if (FAILED(descriptionResult)) {
        throw std::system_error(static_cast<int>(descriptionResult), std::system_category(), "IDXGIAdapter4::GetDesc3 failed");
    }

    DeviceCaps result{};
    result.name = utf8_from_wide(description.Description);
    result.adapterIndex = index;
    result.vendorId = description.VendorId;
    result.deviceId = description.DeviceId;
    result.subsystemId = description.SubSysId;
    result.revision = description.Revision;
    result.dedicatedVideoMemoryBytes = description.DedicatedVideoMemory;
    result.luidHighPart = description.AdapterLuid.HighPart;
    result.luidLowPart = description.AdapterLuid.LowPart;
    result.isRx5700Xt = result.vendorId == 0x1002 && result.deviceId == 0x731F;

    ComPtr<ID3D12Device> device;
    const HRESULT deviceResult = D3D12CreateDevice(adapter, D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&device));
    if (FAILED(deviceResult)) {
        return result;
    }

    result.supportsD3D12 = true;
    result.shaderModel = query_shader_model(device.Get());

    D3D12_FEATURE_DATA_D3D12_OPTIONS options{};
    if (SUCCEEDED(device->CheckFeatureSupport(D3D12_FEATURE_D3D12_OPTIONS, &options, sizeof(options)))) {
        result.resourceBindingTier = static_cast<std::uint32_t>(options.ResourceBindingTier);
    }

    D3D12_FEATURE_DATA_D3D12_OPTIONS1 options1{};
    if (SUCCEEDED(device->CheckFeatureSupport(D3D12_FEATURE_D3D12_OPTIONS1, &options1, sizeof(options1)))) {
        result.supportsWaveOps = options1.WaveOps != FALSE;
        result.waveLaneMin = options1.WaveLaneCountMin;
        result.waveLaneMax = options1.WaveLaneCountMax;
    }

    D3D12_FEATURE_DATA_D3D12_OPTIONS4 options4{};
    if (SUCCEEDED(device->CheckFeatureSupport(D3D12_FEATURE_D3D12_OPTIONS4, &options4, sizeof(options4)))) {
        result.supportsNative16BitShaderOps = options4.Native16BitShaderOpsSupported != FALSE;
    }

    return result;
}

} // namespace

std::vector<DeviceCaps> enumerate_adapters() {
    ComPtr<IDXGIFactory6> factory;
    const HRESULT factoryResult = CreateDXGIFactory2(0, IID_PPV_ARGS(&factory));
    if (FAILED(factoryResult)) {
        throw std::system_error(static_cast<int>(factoryResult), std::system_category(), "CreateDXGIFactory2 failed");
    }

    std::vector<DeviceCaps> adapters;
    for (std::uint32_t index = 0;; ++index) {
        ComPtr<IDXGIAdapter4> adapter;
        const HRESULT enumResult = factory->EnumAdapterByGpuPreference(
            index,
            DXGI_GPU_PREFERENCE_HIGH_PERFORMANCE,
            IID_PPV_ARGS(&adapter));
        if (enumResult == DXGI_ERROR_NOT_FOUND) {
            break;
        }
        if (FAILED(enumResult)) {
            throw std::system_error(static_cast<int>(enumResult), std::system_category(), "DXGI adapter enumeration failed");
        }

        DXGI_ADAPTER_DESC3 description{};
        const HRESULT descriptionResult = adapter->GetDesc3(&description);
        if (FAILED(descriptionResult)) {
            throw std::system_error(static_cast<int>(descriptionResult), std::system_category(), "IDXGIAdapter4::GetDesc3 failed");
        }
        if ((description.Flags & DXGI_ADAPTER_FLAG3_SOFTWARE) != 0) {
            continue;
        }

        adapters.push_back(describe_adapter(index, adapter.Get()));
    }
    return adapters;
}

std::string shader_model_name(std::uint32_t shader_model) {
    if (shader_model == 0) {
        return "unsupported";
    }
    const auto major = (shader_model >> 4U) & 0xFU;
    const auto minor = shader_model & 0xFU;
    return std::to_string(major) + "." + std::to_string(minor);
}

} // namespace fsr4n10
