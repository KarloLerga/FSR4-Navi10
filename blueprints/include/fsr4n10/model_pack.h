#pragma once
#include <array>
#include <cstdint>
#include <filesystem>
#include <span>
#include <string>
#include <vector>

namespace fsr4n10 {

constexpr std::array<char, 8> kModelPackMagic = {'F','4','N','1','0','P','K','\0'};
constexpr std::uint32_t kModelPackVersion = 1;

enum class TensorDataType : std::uint32_t {
    F16 = 1,
    F32 = 2,
    I8Reference = 3,
};

enum class TensorLayout : std::uint32_t {
    Canonical = 0,
    Half2Blocked = 1,
    OperatorSpecific = 2,
};

#pragma pack(push, 1)
struct ModelPackHeader {
    std::array<char, 8> magic;
    std::uint32_t version;
    std::uint32_t headerBytes;
    std::array<std::uint8_t, 32> sourceSha256;
    std::array<std::uint8_t, 32> manifestSha256;
    std::uint32_t tensorCount;
    std::uint32_t flags;
    std::uint64_t tensorTableOffset;
    std::uint64_t stringTableOffset;
    std::uint64_t dataOffset;
    std::uint64_t fileBytes;
};

struct TensorRecord {
    std::uint64_t nameHash;
    std::uint32_t nameOffset;
    TensorDataType dataType;
    TensorLayout layout;
    std::uint32_t rank;
    std::array<std::uint32_t, 4> shape;
    std::uint32_t alignment;
    std::uint32_t compatibilityFlags;
    std::uint64_t byteOffset;
    std::uint64_t byteSize;
    float scale;
    float bias;
    float clampMin;
    float clampMax;
};
#pragma pack(pop)

class ModelPack {
public:
    static ModelPack Load(const std::filesystem::path& path);
    const ModelPackHeader& header() const noexcept;
    std::span<const TensorRecord> tensors() const noexcept;
    std::span<const std::byte> tensor_bytes(std::size_t index) const;
    std::string tensor_name(std::size_t index) const;
private:
    std::vector<std::byte> file_;
    ModelPackHeader header_{};
    std::vector<TensorRecord> tensors_;
};

} // namespace fsr4n10
