#include "fsr4n10/model_pack.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <fstream>
#include <limits>
#include <stdexcept>
#include <string_view>
#include <utility>

namespace fsr4n10 {
namespace {

template <typename T>
T read_object(std::span<const std::byte> bytes, std::uint64_t offset, const char* label) {
    if (offset > bytes.size() || sizeof(T) > bytes.size() - static_cast<std::size_t>(offset)) {
        throw std::runtime_error(std::string("model pack ") + label + " is out of bounds");
    }
    T value{};
    std::memcpy(&value, bytes.data() + static_cast<std::size_t>(offset), sizeof(T));
    return value;
}

std::uint64_t fnv1a_64(std::string_view value) noexcept {
    std::uint64_t hash = 0xcbf29ce484222325ULL;
    for (const unsigned char byte : value) {
        hash ^= byte;
        hash *= 0x100000001b3ULL;
    }
    return hash;
}

[[noreturn]] void invalid(const char* detail) {
    throw std::runtime_error(std::string("invalid model pack: ") + detail);
}

} // namespace

ModelPack ModelPack::Load(const std::filesystem::path& path) {
    std::ifstream stream(path, std::ios::binary | std::ios::ate);
    if (!stream) {
        throw std::runtime_error("cannot open model pack: " + path.string());
    }
    const std::streamoff stream_size = stream.tellg();
    if (stream_size < static_cast<std::streamoff>(sizeof(ModelPackHeader)) ||
        static_cast<std::uintmax_t>(stream_size) > std::numeric_limits<std::size_t>::max()) {
        invalid("file is shorter than its header or too large for this process");
    }

    ModelPack pack;
    pack.file_.resize(static_cast<std::size_t>(stream_size));
    stream.seekg(0);
    stream.read(reinterpret_cast<char*>(pack.file_.data()), stream_size);
    if (!stream) {
        throw std::runtime_error("failed reading model pack: " + path.string());
    }

    const auto bytes = std::span<const std::byte>(pack.file_);
    pack.header_ = read_object<ModelPackHeader>(bytes, 0, "header");
    if (pack.header_.magic != kModelPackMagic) {
        invalid("magic does not match F4N10PK");
    }
    if (pack.header_.version != kModelPackVersion || pack.header_.headerBytes != sizeof(ModelPackHeader)) {
        invalid("unsupported version or header size");
    }
    if (pack.header_.fileBytes != bytes.size()) {
        invalid("declared file size does not match actual size");
    }
    if (pack.header_.tensorCount == 0 || pack.header_.tensorCount > 100000) {
        invalid("tensor count is outside supported bounds");
    }
    if (pack.header_.flags != 0) {
        invalid("unsupported header flags");
    }
    if (pack.header_.tensorTableOffset < pack.header_.headerBytes ||
        pack.header_.tensorTableOffset > bytes.size()) {
        invalid("tensor table offset is invalid");
    }
    const std::uint64_t tensor_table_bytes =
        static_cast<std::uint64_t>(pack.header_.tensorCount) * sizeof(TensorRecord);
    if (tensor_table_bytes > bytes.size() - pack.header_.tensorTableOffset) {
        invalid("tensor table is truncated");
    }
    const std::uint64_t tensor_table_end = pack.header_.tensorTableOffset + tensor_table_bytes;
    if (pack.header_.stringTableOffset < tensor_table_end ||
        pack.header_.stringTableOffset > pack.header_.dataOffset ||
        pack.header_.dataOffset > bytes.size()) {
        invalid("string or data table offsets are invalid");
    }

    pack.tensors_.reserve(pack.header_.tensorCount);
    std::vector<std::pair<std::uint64_t, std::uint64_t>> data_ranges;
    data_ranges.reserve(pack.header_.tensorCount);
    const std::uint64_t string_table_bytes = pack.header_.dataOffset - pack.header_.stringTableOffset;
    for (std::uint32_t index = 0; index < pack.header_.tensorCount; ++index) {
        const std::uint64_t record_offset = pack.header_.tensorTableOffset +
                                            static_cast<std::uint64_t>(index) * sizeof(TensorRecord);
        const TensorRecord record = read_object<TensorRecord>(bytes, record_offset, "tensor record");
        if (record.rank == 0 || record.rank > record.shape.size()) {
            invalid("tensor rank must be between one and four");
        }
        if (record.dataType != TensorDataType::F16 || record.layout > TensorLayout::OperatorSpecific) {
            invalid("tensor has an unsupported type or layout");
        }
        if (record.alignment < 16 || record.alignment > 4096 ||
            (record.alignment & (record.alignment - 1)) != 0 ||
            record.byteOffset % record.alignment != 0) {
            invalid("tensor alignment is invalid");
        }
        if (!std::isfinite(record.scale) || !std::isfinite(record.bias) ||
            !std::isfinite(record.clampMin) || !std::isfinite(record.clampMax)) {
            invalid("tensor metadata contains a non-finite value");
        }
        std::uint64_t element_count = 1;
        for (std::size_t dimension = 0; dimension < record.shape.size(); ++dimension) {
            if (dimension < record.rank) {
                if (record.shape[dimension] == 0 ||
                    element_count > std::numeric_limits<std::uint64_t>::max() / record.shape[dimension]) {
                    invalid("tensor shape is invalid or overflows");
                }
                element_count *= record.shape[dimension];
            } else if (record.shape[dimension] != 0) {
                invalid("unused shape dimensions must be zero");
            }
        }
        if (element_count > std::numeric_limits<std::uint64_t>::max() / sizeof(std::uint16_t) ||
            record.byteSize != element_count * sizeof(std::uint16_t)) {
            invalid("tensor byte size does not match its FP16 shape");
        }
        if (record.byteOffset < pack.header_.dataOffset || record.byteOffset > bytes.size() ||
            record.byteSize > bytes.size() - record.byteOffset) {
            invalid("tensor data range is out of bounds");
        }
        if (record.nameOffset >= string_table_bytes) {
            invalid("tensor name offset is out of bounds");
        }
        const auto name_start = static_cast<std::size_t>(pack.header_.stringTableOffset + record.nameOffset);
        const auto name_limit = static_cast<std::size_t>(pack.header_.dataOffset);
        const char* name = reinterpret_cast<const char*>(bytes.data() + name_start);
        const auto* terminator = static_cast<const char*>(std::memchr(name, '\0', name_limit - name_start));
        if (terminator == nullptr || terminator == name) {
            invalid("tensor name is empty or unterminated");
        }
        const std::string_view name_view(name, static_cast<std::size_t>(terminator - name));
        if (fnv1a_64(name_view) != record.nameHash) {
            invalid("tensor name hash does not match");
        }
        data_ranges.emplace_back(record.byteOffset, record.byteOffset + record.byteSize);
        pack.tensors_.push_back(record);
    }

    std::sort(data_ranges.begin(), data_ranges.end());
    if (data_ranges.front().first != pack.header_.dataOffset || data_ranges.back().second != bytes.size()) {
        invalid("tensor payload does not cover the declared data section");
    }
    for (std::size_t index = 1; index < data_ranges.size(); ++index) {
        if (data_ranges[index].first < data_ranges[index - 1].second) {
            invalid("tensor payload ranges overlap");
        }
    }
    return pack;
}

const ModelPackHeader& ModelPack::header() const noexcept {
    return header_;
}

std::span<const TensorRecord> ModelPack::tensors() const noexcept {
    return tensors_;
}

std::span<const std::byte> ModelPack::tensor_bytes(std::size_t index) const {
    if (index >= tensors_.size()) {
        throw std::out_of_range("model pack tensor index is out of bounds");
    }
    const auto& tensor = tensors_[index];
    return std::span<const std::byte>(file_).subspan(
        static_cast<std::size_t>(tensor.byteOffset), static_cast<std::size_t>(tensor.byteSize));
}

std::string ModelPack::tensor_name(std::size_t index) const {
    if (index >= tensors_.size()) {
        throw std::out_of_range("model pack tensor index is out of bounds");
    }
    const auto& tensor = tensors_[index];
    const char* name = reinterpret_cast<const char*>(file_.data() + header_.stringTableOffset + tensor.nameOffset);
    const auto* terminator = static_cast<const char*>(std::memchr(
        name,
        '\0',
        static_cast<std::size_t>(header_.dataOffset - header_.stringTableOffset - tensor.nameOffset)));
    return std::string(name, static_cast<std::size_t>(terminator - name));
}

} // namespace fsr4n10
