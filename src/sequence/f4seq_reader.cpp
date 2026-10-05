#include "fsr4n10/sequence.h"

#include <Windows.h>
#include <bcrypt.h>

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <limits>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string_view>
#include <unordered_map>
#include <utility>

namespace fsr4n10 {
namespace {

constexpr std::array<std::byte, 8> kMagic{
    std::byte{'F'}, std::byte{'4'}, std::byte{'N'}, std::byte{'1'},
    std::byte{'0'}, std::byte{'S'}, std::byte{'Q'}, std::byte{'2'}};
constexpr std::uint32_t kVersion = 2;
constexpr std::uint64_t kFixedHeaderBytes = 200;
constexpr std::uint64_t kFrameRecordBytes = 212;
constexpr std::uint64_t kSequenceHashOffset = 168;
constexpr std::uint64_t kMaxManifestBytes = 16ULL * 1024ULL * 1024ULL;
constexpr std::uint64_t kMaxFrameCount = 100'000;
constexpr std::uint64_t kMaxDimension = 16'384;
constexpr std::uint64_t kMaxArrayBytes = 1024ULL * 1024ULL * 1024ULL;
constexpr std::uint64_t kMaxSequenceBytes = 64ULL * 1024ULL * 1024ULL * 1024ULL;
constexpr std::uint32_t kLocalFileHeaderSignature = 0x04034b50;
constexpr std::uint32_t kCentralDirectorySignature = 0x02014b50;
constexpr std::uint32_t kEndOfCentralDirectorySignature = 0x06054b50;
constexpr std::uint32_t kFrameReset = 1U << 0U;
constexpr std::uint32_t kFrameCameraCut = 1U << 1U;
constexpr std::uint32_t kFrameReactiveValid = 1U << 2U;
constexpr std::uint32_t kFrameTcrValid = 1U << 3U;
constexpr std::uint32_t kAllowedFrameFlags = kFrameReset | kFrameCameraCut | kFrameReactiveValid | kFrameTcrValid;

void require(bool condition, const char* message) {
    if (!condition) {
        throw std::runtime_error(message);
    }
}

std::uint16_t read_u16(const std::byte* data) noexcept {
    return static_cast<std::uint16_t>(std::to_integer<std::uint8_t>(data[0])) |
           static_cast<std::uint16_t>(static_cast<std::uint16_t>(std::to_integer<std::uint8_t>(data[1])) << 8U);
}

std::uint32_t read_u32(const std::byte* data) noexcept {
    return static_cast<std::uint32_t>(std::to_integer<std::uint8_t>(data[0])) |
           (static_cast<std::uint32_t>(std::to_integer<std::uint8_t>(data[1])) << 8U) |
           (static_cast<std::uint32_t>(std::to_integer<std::uint8_t>(data[2])) << 16U) |
           (static_cast<std::uint32_t>(std::to_integer<std::uint8_t>(data[3])) << 24U);
}

std::uint64_t read_u64(const std::byte* data) noexcept {
    return static_cast<std::uint64_t>(read_u32(data)) |
           (static_cast<std::uint64_t>(read_u32(data + 4)) << 32U);
}

float read_f32(const std::byte* data) noexcept {
    const auto bits = read_u32(data);
    return std::bit_cast<float>(bits);
}

std::string hex(const std::byte* bytes, std::size_t size) {
    constexpr char digits[] = "0123456789abcdef";
    std::string result(size * 2, '\0');
    for (std::size_t index = 0; index < size; ++index) {
        const auto value = std::to_integer<std::uint8_t>(bytes[index]);
        result[index * 2] = digits[value >> 4U];
        result[index * 2 + 1] = digits[value & 0x0fU];
    }
    return result;
}

void check_nt(NTSTATUS status, const char* operation) {
    if (status < 0) {
        std::ostringstream message;
        message << operation << " failed (NTSTATUS 0x" << std::hex << static_cast<std::uint32_t>(status) << ")";
        throw std::runtime_error(message.str());
    }
}

class Sha256 final {
public:
    Sha256() {
        check_nt(BCryptOpenAlgorithmProvider(&algorithm_, BCRYPT_SHA256_ALGORITHM, nullptr, 0),
                 "BCryptOpenAlgorithmProvider(SHA-256)");
        DWORD object_size = 0;
        DWORD returned = 0;
        try {
            check_nt(BCryptGetProperty(algorithm_, BCRYPT_OBJECT_LENGTH,
                                       reinterpret_cast<PUCHAR>(&object_size), sizeof(object_size), &returned, 0),
                     "BCryptGetProperty(BCRYPT_OBJECT_LENGTH)");
            object_.resize(object_size);
            check_nt(BCryptCreateHash(algorithm_, &hash_, reinterpret_cast<PUCHAR>(object_.data()), object_size,
                                      nullptr, 0, 0),
                     "BCryptCreateHash");
        } catch (...) {
            BCryptCloseAlgorithmProvider(algorithm_, 0);
            algorithm_ = nullptr;
            throw;
        }
    }

    Sha256(const Sha256&) = delete;
    Sha256& operator=(const Sha256&) = delete;

    ~Sha256() {
        if (hash_ != nullptr) {
            BCryptDestroyHash(hash_);
        }
        if (algorithm_ != nullptr) {
            BCryptCloseAlgorithmProvider(algorithm_, 0);
        }
    }

    void update(const std::byte* data, std::size_t size) {
        while (size != 0) {
            const auto chunk = static_cast<ULONG>(std::min<std::size_t>(size, std::numeric_limits<ULONG>::max()));
            check_nt(BCryptHashData(hash_, reinterpret_cast<PUCHAR>(const_cast<std::byte*>(data)), chunk, 0),
                     "BCryptHashData");
            data += chunk;
            size -= chunk;
        }
    }

    std::array<std::byte, 32> finish() {
        std::array<std::byte, 32> digest{};
        check_nt(BCryptFinishHash(hash_, reinterpret_cast<PUCHAR>(digest.data()),
                                  static_cast<ULONG>(digest.size()), 0), "BCryptFinishHash");
        return digest;
    }

private:
    BCRYPT_ALG_HANDLE algorithm_ = nullptr;
    BCRYPT_HASH_HANDLE hash_ = nullptr;
    std::vector<std::byte> object_;
};

std::array<std::byte, 32> sha256(const std::vector<std::byte>& data) {
    Sha256 hash;
    hash.update(data.data(), data.size());
    return hash.finish();
}

std::uint32_t crc32(const std::vector<std::byte>& data) noexcept {
    std::uint32_t crc = 0xffffffffU;
    for (const auto byte : data) {
        crc ^= std::to_integer<std::uint8_t>(byte);
        for (std::uint32_t bit = 0; bit < 8; ++bit) {
            const auto mask = static_cast<std::uint32_t>(-static_cast<std::int32_t>(crc & 1U));
            crc = (crc >> 1U) ^ (0xedb88320U & mask);
        }
    }
    return ~crc;
}

bool safe_archive_path(std::string_view value) {
    if (value.empty() || value.front() == '/' || value.find('\\') != std::string_view::npos) {
        return false;
    }
    std::size_t begin = 0;
    while (begin < value.size()) {
        const std::size_t end = value.find('/', begin);
        const auto part = value.substr(begin, end == std::string_view::npos ? value.size() - begin : end - begin);
        if (part.empty() || part == "." || part == "..") {
            return false;
        }
        begin = end == std::string_view::npos ? value.size() : end + 1;
    }
    return true;
}

struct ZipMember {
    std::uint64_t offset = 0;
    std::uint64_t size = 0;
    std::uint32_t crc = 0;
};

struct FrameIndex {
    SequenceFrameMetadata metadata;
    std::array<std::array<std::byte, 32>, 5> hashes{};
};

std::uint64_t expected_array_size(std::uint32_t width, std::uint32_t height, std::uint32_t channels,
                                 std::uint32_t bytes_per_channel) {
    return static_cast<std::uint64_t>(width) * height * channels * bytes_per_channel;
}

} // namespace

struct F4Sequence::Impl {
    std::filesystem::path path;
    std::unordered_map<std::string, ZipMember> members;
    SequenceMetadata metadata;
    std::vector<FrameIndex> frames;
    std::array<std::byte, 32> expected_sequence_hash{};
    std::unique_ptr<Sha256> sequence_hasher;
    std::uint32_t next_frame_to_read = 0;

    std::vector<std::byte> read_member(std::string_view name, std::uint64_t limit) const {
        const auto found = members.find(std::string(name));
        require(found != members.end(), "f4seq is missing a required ZIP member");
        const ZipMember& member = found->second;
        require(member.size <= limit && member.size <= std::numeric_limits<std::size_t>::max(),
                "f4seq ZIP member exceeds supported size");
        std::ifstream input(path, std::ios::binary);
        require(static_cast<bool>(input), "cannot open f4seq input");
        input.seekg(static_cast<std::streamoff>(member.offset), std::ios::beg);
        std::vector<std::byte> bytes(static_cast<std::size_t>(member.size));
        if (!bytes.empty()) {
            input.read(reinterpret_cast<char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
        }
        require(static_cast<bool>(input) || bytes.empty(), "failed reading f4seq member");
        require(crc32(bytes) == member.crc, "f4seq ZIP CRC mismatch");
        return bytes;
    }

    void scan_zip() {
        std::error_code filesystem_error;
        const auto file_size = std::filesystem::file_size(path, filesystem_error);
        require(!filesystem_error, "cannot determine f4seq file size");
        require(file_size >= 22, "f4seq file is too short to be a ZIP archive");
        std::ifstream input(path, std::ios::binary);
        require(static_cast<bool>(input), "cannot open f4seq ZIP archive");
        std::uint64_t position = 0;
        while (position + 4 <= file_size) {
            std::array<std::byte, 30> header{};
            input.seekg(static_cast<std::streamoff>(position), std::ios::beg);
            input.read(reinterpret_cast<char*>(header.data()), 4);
            require(static_cast<bool>(input), "failed reading f4seq ZIP signature");
            const std::uint32_t signature = read_u32(header.data());
            if (signature == kCentralDirectorySignature || signature == kEndOfCentralDirectorySignature) {
                break;
            }
            require(signature == kLocalFileHeaderSignature && position + header.size() <= file_size,
                    "unsupported or malformed f4seq ZIP layout");
            input.seekg(static_cast<std::streamoff>(position), std::ios::beg);
            input.read(reinterpret_cast<char*>(header.data()), static_cast<std::streamsize>(header.size()));
            require(static_cast<bool>(input), "failed reading f4seq ZIP local header");
            const auto flags = read_u16(header.data() + 6);
            const auto compression = read_u16(header.data() + 8);
            const auto expected_crc = read_u32(header.data() + 14);
            const auto compressed_size = read_u32(header.data() + 18);
            const auto uncompressed_size = read_u32(header.data() + 22);
            const auto filename_size = read_u16(header.data() + 26);
            const auto extra_size = read_u16(header.data() + 28);
            require(flags == 0 && compression == 0, "f4seq entries must be unencrypted ZIP_STORED without descriptors");
            require(compressed_size == uncompressed_size && compressed_size != 0xffffffffU,
                    "unsupported f4seq ZIP64 member or compressed data");
            const std::uint64_t data_offset = position + header.size() + filename_size + extra_size;
            require(filename_size != 0 && data_offset <= file_size && compressed_size <= file_size - data_offset,
                    "f4seq ZIP member range is invalid");
            std::string name(filename_size, '\0');
            input.seekg(static_cast<std::streamoff>(position + header.size()), std::ios::beg);
            input.read(name.data(), filename_size);
            require(static_cast<bool>(input), "failed reading f4seq ZIP member name");
            require(safe_archive_path(name), "unsafe f4seq ZIP member path");
            if (extra_size != 0) {
                const std::uint64_t extra_end = data_offset;
                std::uint64_t current = position + header.size() + filename_size;
                std::vector<std::byte> extra(extra_size);
                input.seekg(static_cast<std::streamoff>(current), std::ios::beg);
                input.read(reinterpret_cast<char*>(extra.data()), extra_size);
                require(static_cast<bool>(input), "failed reading f4seq ZIP extra field");
                require(extra_end > current, "invalid f4seq ZIP extra field");
            }
            const auto [unused, inserted] = members.emplace(name, ZipMember{data_offset, compressed_size, expected_crc});
            (void)unused;
            require(inserted, "duplicate f4seq ZIP member");
            position = data_offset + compressed_size;
        }
        require(members.contains("sequence.json") && members.contains("sequence.bin"),
                "f4seq requires sequence.json and sequence.bin");
        const auto json_info = members.at("sequence.json");
        require(json_info.size <= kMaxManifestBytes, "sequence.json exceeds the 16 MiB limit");
        (void)read_member("sequence.json", kMaxManifestBytes);
    }

    void parse_index() {
        const auto bytes = read_member("sequence.bin", kFixedHeaderBytes + kFrameRecordBytes * kMaxFrameCount);
        require(bytes.size() >= kFixedHeaderBytes, "sequence.bin is shorter than its fixed header");
        const std::byte* data = bytes.data();
        require(std::equal(kMagic.begin(), kMagic.end(), data), "sequence.bin magic mismatch");
        require(read_u32(data + 8) == kVersion, "unsupported sequence.bin version");
        const auto header_size = read_u32(data + 12);
        const auto frame_count = read_u32(data + 16);
        require(frame_count > 0 && frame_count <= kMaxFrameCount, "sequence frame count is out of range");
        require(header_size == kFixedHeaderBytes + kFrameRecordBytes * frame_count && bytes.size() == header_size,
                "sequence.bin header/table size mismatch");
        metadata.render_width = read_u32(data + 20);
        metadata.render_height = read_u32(data + 24);
        metadata.output_width = read_u32(data + 28);
        metadata.output_height = read_u32(data + 32);
        const auto preset_id = read_u32(data + 36);
        metadata.scale_numerator = read_u32(data + 40);
        metadata.scale_denominator = read_u32(data + 44);
        metadata.seed = read_u64(data + 48);
        const auto source_kind_id = read_u32(data + 56);
        const auto motion_id = read_u32(data + 60);
        const auto depth_id = read_u32(data + 64);
        const auto reserved = read_u32(data + 68);
        require(source_kind_id >= 1 && source_kind_id <= 4 && reserved == 0,
                "sequence.bin has unsupported source kind or nonzero reserved data");
        require(motion_id == 1 && depth_id == 1, "sequence.bin uses an unsupported motion/depth convention");
        metadata.motion_convention_id = motion_id;
        require(metadata.render_width > 0 && metadata.render_height > 0 && metadata.output_width > 0 &&
                    metadata.output_height > 0 && metadata.render_width <= kMaxDimension &&
                    metadata.render_height <= kMaxDimension && metadata.output_width <= kMaxDimension &&
                    metadata.output_height <= kMaxDimension,
                "sequence dimensions are out of range");
        require(metadata.scale_numerator > 0 && metadata.scale_denominator > 0,
                "sequence scale factor is invalid");

        constexpr std::array<std::string_view, 5> presets{
            "native", "quality", "balanced", "performance", "ultra_performance"};
        constexpr std::array<std::string_view, 5> source_kinds{
            "", "renderer_capture", "procedural_synthetic", "imported_buffers", "test_fixture"};
        constexpr std::array<std::array<std::uint32_t, 2>, 5> scales{{{{1, 1}}, {{3, 2}}, {{17, 10}}, {{2, 1}}, {{3, 1}}}};
        require(preset_id < presets.size(), "sequence preset id is invalid");
        metadata.preset = presets[preset_id];
        metadata.source_kind = source_kinds[source_kind_id];
        require(scales[preset_id][0] == metadata.scale_numerator && scales[preset_id][1] == metadata.scale_denominator,
                "sequence preset scale factor mismatch");
        metadata.reversed_depth = false;
        metadata.frame_count = frame_count;
        metadata.sequence_id.assign(reinterpret_cast<const char*>(data + 72), 64);
        const auto nul = metadata.sequence_id.find('\0');
        if (nul != std::string::npos) {
            metadata.sequence_id.resize(nul);
        }
        require(!metadata.sequence_id.empty() &&
                    std::all_of(metadata.sequence_id.begin(), metadata.sequence_id.end(), [](unsigned char c) {
                        return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') ||
                               c == '.' || c == '_' || c == '-';
                    }),
                "sequence ID is invalid");
        metadata.source_hash = hex(data + 136, 32);
        std::copy(data + kSequenceHashOffset, data + kSequenceHashOffset + 32, expected_sequence_hash.begin());
        metadata.sequence_hash = hex(expected_sequence_hash.data(), expected_sequence_hash.size());

        auto canonical_index = bytes;
        std::fill(canonical_index.begin() + static_cast<std::ptrdiff_t>(kSequenceHashOffset),
                  canonical_index.begin() + static_cast<std::ptrdiff_t>(kSequenceHashOffset + 32), std::byte{0});
        sequence_hasher = std::make_unique<Sha256>();
        sequence_hasher->update(canonical_index.data(), canonical_index.size());

        frames.resize(frame_count);
        for (std::uint32_t index = 0; index < frame_count; ++index) {
            const std::byte* record = data + kFixedHeaderBytes + static_cast<std::uint64_t>(index) * kFrameRecordBytes;
            auto& frame = frames[index];
            require(read_u32(record) == index, "sequence frame indices are not contiguous");
            const auto frame_flags = read_u32(record + 4);
            require((frame_flags & ~kAllowedFrameFlags) == 0, "sequence frame has unsupported flags");
            frame.metadata.frame_index = index;
            frame.metadata.reset = (frame_flags & kFrameReset) != 0;
            frame.metadata.camera_cut = (frame_flags & kFrameCameraCut) != 0;
            frame.metadata.reactive_mask_valid = (frame_flags & kFrameReactiveValid) != 0;
            frame.metadata.transparency_composition_mask_valid = (frame_flags & kFrameTcrValid) != 0;
            require(!frame.metadata.camera_cut || frame.metadata.reset, "camera cut requires reset=true");
            frame.metadata.frame_time_delta_ms = read_f32(record + 8);
            frame.metadata.jitter_x = read_f32(record + 12);
            frame.metadata.jitter_y = read_f32(record + 16);
            frame.metadata.previous_jitter_x = read_f32(record + 20);
            frame.metadata.previous_jitter_y = read_f32(record + 24);
            frame.metadata.exposure = read_f32(record + 28);
            frame.metadata.pre_exposure = read_f32(record + 32);
            require(std::isfinite(frame.metadata.frame_time_delta_ms) && frame.metadata.frame_time_delta_ms > 0.0f &&
                        std::isfinite(frame.metadata.jitter_x) && std::isfinite(frame.metadata.jitter_y) &&
                        std::isfinite(frame.metadata.previous_jitter_x) && std::isfinite(frame.metadata.previous_jitter_y) &&
                        std::isfinite(frame.metadata.exposure) && frame.metadata.exposure > 0.0f &&
                        std::isfinite(frame.metadata.pre_exposure) && frame.metadata.pre_exposure > 0.0f,
                    "sequence frame timing/jitter/exposure is invalid");
            for (std::size_t reserved_index = 0; reserved_index < 4; ++reserved_index) {
                require(read_u32(record + 36 + reserved_index * 4) == 0, "sequence frame reserved data is nonzero");
            }
            for (std::size_t array = 0; array < frame.hashes.size(); ++array) {
                std::copy(record + 52 + array * 32, record + 52 + (array + 1) * 32, frame.hashes[array].begin());
                const bool should_exist = array < 3 ||
                    (array == 3 && frame.metadata.reactive_mask_valid) ||
                    (array == 4 && frame.metadata.transparency_composition_mask_valid);
                const bool has_hash = std::any_of(frame.hashes[array].begin(), frame.hashes[array].end(),
                                                  [](std::byte value) { return value != std::byte{0}; });
                require(should_exist == has_hash, "sequence plane hash and validity flags disagree");
            }
        }
    }

    void validate_member_set() const {
        require(members.size() >= 2, "f4seq ZIP has too few members");
        std::uint64_t expected_count = 2;
        std::uint64_t expected_payload = 0;
        for (const auto& frame : frames) {
            const std::array<bool, 5> present{
                true, true, true, frame.metadata.reactive_mask_valid,
                frame.metadata.transparency_composition_mask_valid};
            for (std::size_t array = 0; array < present.size(); ++array) {
                if (!present[array]) {
                    continue;
                }
                ++expected_count;
                const std::array<std::string_view, 5> names{
                    "color", "depth", "motion_vectors", "reactive_mask", "transparency_composition_mask"};
                const std::string member_name = "frames/" + (frame.metadata.frame_index < 10'000'000
                    ? std::string(6 - std::min<std::size_t>(6, std::to_string(frame.metadata.frame_index).size()), '0')
                    : std::string{}) + std::to_string(frame.metadata.frame_index) + "/" +
                    std::string(names[array]) + ".raw";
                const auto found = members.find(member_name);
                require(found != members.end(), "f4seq is missing a frame array member");
                const std::array<std::uint32_t, 5> channels{4, 1, 2, 1, 1};
                const std::array<std::uint32_t, 5> bytes_per_channel{2, 4, 2, 1, 1};
                const auto expected_size = expected_array_size(metadata.render_width, metadata.render_height,
                                                               channels[array], bytes_per_channel[array]);
                require(expected_size <= kMaxArrayBytes && found->second.size == expected_size,
                        "f4seq frame array has an invalid size");
                expected_payload += expected_size;
                require(expected_payload <= kMaxSequenceBytes, "f4seq payload exceeds the 64 GiB limit");
            }
        }
        require(members.size() == expected_count, "f4seq has unexpected ZIP members");
        require(expected_payload <= kMaxSequenceBytes, "f4seq payload exceeds the 64 GiB limit");
    }
};

F4Sequence::F4Sequence(std::unique_ptr<Impl> implementation) noexcept : implementation_(std::move(implementation)) {}
F4Sequence::F4Sequence(F4Sequence&&) noexcept = default;
F4Sequence& F4Sequence::operator=(F4Sequence&&) noexcept = default;
F4Sequence::~F4Sequence() = default;

F4Sequence F4Sequence::open(const std::filesystem::path& path) {
    static_assert(std::endian::native == std::endian::little, "f4seq v2 currently requires a little-endian host");
    auto implementation = std::make_unique<Impl>();
    implementation->path = path;
    implementation->scan_zip();
    implementation->parse_index();
    implementation->validate_member_set();
    return F4Sequence(std::move(implementation));
}

const SequenceMetadata& F4Sequence::metadata() const noexcept {
    return implementation_->metadata;
}

const SequenceFrameMetadata& F4Sequence::frame_metadata(std::uint32_t frame_index) const {
    require(frame_index < implementation_->frames.size(), "f4seq frame metadata index is out of range");
    return implementation_->frames[frame_index].metadata;
}

SequenceFrame F4Sequence::read_frame(std::uint32_t frame_index) {
    auto& impl = *implementation_;
    require(frame_index == impl.next_frame_to_read, "f4seq frames must be read exactly once in increasing order");
    require(frame_index < impl.frames.size(), "f4seq frame index is out of range");
    const auto& index = impl.frames[frame_index];
    SequenceFrame frame;
    frame.metadata = index.metadata;
    const auto pixels = static_cast<std::size_t>(impl.metadata.render_width) * impl.metadata.render_height;
    constexpr std::array<std::string_view, 5> names{
        "color", "depth", "motion_vectors", "reactive_mask", "transparency_composition_mask"};
    constexpr std::array<std::uint32_t, 5> channels{4, 1, 2, 1, 1};
    constexpr std::array<std::uint32_t, 5> bytes_per_channel{2, 4, 2, 1, 1};
    std::array<std::vector<std::byte>, 5> payloads;
    for (std::size_t array = 0; array < names.size(); ++array) {
        const bool present = array < 3 || (array == 3 && frame.metadata.reactive_mask_valid) ||
                             (array == 4 && frame.metadata.transparency_composition_mask_valid);
        if (!present) {
            continue;
        }
        const std::string member_name = "frames/" + (frame_index < 10'000'000
            ? std::string(6 - std::min<std::size_t>(6, std::to_string(frame_index).size()), '0')
            : std::string{}) + std::to_string(frame_index) + "/" + std::string(names[array]) + ".raw";
        const auto expected_size = expected_array_size(impl.metadata.render_width, impl.metadata.render_height,
                                                       channels[array], bytes_per_channel[array]);
        payloads[array] = impl.read_member(member_name, kMaxArrayBytes);
        require(payloads[array].size() == expected_size, "f4seq array payload size mismatch");
        require(sha256(payloads[array]) == index.hashes[array], "f4seq frame array SHA-256 mismatch");
        impl.sequence_hasher->update(payloads[array].data(), payloads[array].size());
    }
    const auto require_finite_half = [](const std::vector<std::byte>& data, const char* label) {
        for (std::size_t offset = 0; offset < data.size(); offset += sizeof(std::uint16_t)) {
            std::uint16_t value = 0;
            std::memcpy(&value, data.data() + offset, sizeof(value));
            if ((value & 0x7c00U) == 0x7c00U) {
                throw std::runtime_error(std::string("f4seq ") + label + " contains NaN or Inf");
            }
        }
    };
    require_finite_half(payloads[0], "color");
    require_finite_half(payloads[2], "motion vectors");
    for (std::size_t offset = 0; offset < payloads[1].size(); offset += sizeof(float)) {
        float value = 0.0f;
        std::memcpy(&value, payloads[1].data() + offset, sizeof(value));
        require(std::isfinite(value) && value >= 0.0f && value <= 1.0f,
                "f4seq forward depth must be finite and within [0,1]");
    }
    frame.color_rgba_half.resize(pixels * 4);
    frame.depth.resize(pixels);
    frame.motion_vectors_half.resize(pixels * 2);
    std::memcpy(frame.color_rgba_half.data(), payloads[0].data(), payloads[0].size());
    std::memcpy(frame.depth.data(), payloads[1].data(), payloads[1].size());
    std::memcpy(frame.motion_vectors_half.data(), payloads[2].data(), payloads[2].size());
    if (frame.metadata.reactive_mask_valid) {
        frame.reactive_mask.resize(pixels);
        std::memcpy(frame.reactive_mask.data(), payloads[3].data(), payloads[3].size());
    }
    if (frame.metadata.transparency_composition_mask_valid) {
        frame.transparency_composition_mask.resize(pixels);
        std::memcpy(frame.transparency_composition_mask.data(), payloads[4].data(), payloads[4].size());
    }
    ++impl.next_frame_to_read;
    if (impl.next_frame_to_read == impl.metadata.frame_count) {
        const auto actual_sequence_hash = impl.sequence_hasher->finish();
        require(actual_sequence_hash == impl.expected_sequence_hash, "f4seq canonical sequence hash mismatch");
    }
    return frame;
}

std::string sequence_frame_input_sha256(const SequenceFrame& frame) {
    Sha256 hash;
    hash.update(reinterpret_cast<const std::byte*>(frame.color_rgba_half.data()),
                frame.color_rgba_half.size() * sizeof(std::uint16_t));
    hash.update(reinterpret_cast<const std::byte*>(frame.depth.data()), frame.depth.size() * sizeof(float));
    hash.update(reinterpret_cast<const std::byte*>(frame.motion_vectors_half.data()),
                frame.motion_vectors_half.size() * sizeof(std::uint16_t));
    if (frame.metadata.reactive_mask_valid) {
        hash.update(reinterpret_cast<const std::byte*>(frame.reactive_mask.data()), frame.reactive_mask.size());
    }
    if (frame.metadata.transparency_composition_mask_valid) {
        hash.update(reinterpret_cast<const std::byte*>(frame.transparency_composition_mask.data()),
                    frame.transparency_composition_mask.size());
    }
    const auto digest = hash.finish();
    return hex(digest.data(), digest.size());
}

} // namespace fsr4n10
