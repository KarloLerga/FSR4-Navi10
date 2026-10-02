#pragma once
#include <cstdint>
#include <memory>
#include <span>
#include <string_view>

struct ID3D12GraphicsCommandList;

namespace fsr4n10 {

enum class BackendKind : std::uint32_t {
    ReferenceI8,
    Fp16Compat,
    Fp16HighPrecision,
    HybridAuto,
};

struct DispatchInputs;
struct DispatchOutputs;
struct ContextDesc;
struct PassTiming;

class IBackend {
public:
    virtual ~IBackend() = default;
    virtual BackendKind kind() const noexcept = 0;
    virtual std::string_view name() const noexcept = 0;
    virtual void create(const ContextDesc& desc) = 0;
    virtual void destroy() noexcept = 0;
    virtual void reset_history() = 0;
    virtual void dispatch(
        ID3D12GraphicsCommandList* commandList,
        const DispatchInputs& inputs,
        const DispatchOutputs& outputs) = 0;
    virtual std::span<const PassTiming> last_pass_timings() const noexcept = 0;
};

std::unique_ptr<IBackend> CreateBackend(BackendKind kind);

} // namespace fsr4n10
