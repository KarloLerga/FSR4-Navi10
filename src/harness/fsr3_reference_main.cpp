#include "fsr4n10/fsr3_reference.h"

#include <exception>
#include <iostream>
#include <string>

int main(int argc, char** argv) {
    if (argc < 3 || argc > 4) {
        std::cerr << "Usage: fsr4n10_fsr3_reference.exe <input.f4seq> <report.json> [capture-root]\n";
        return 2;
    }
    try {
        return fsr4n10::run_fsr3_reference_sequence(
            argv[1], argv[2], argc == 4 ? std::filesystem::path(argv[3]) : std::filesystem::path{});
    } catch (const std::exception& error) {
        std::cerr << "FSR3 reference sequence run failed: " << error.what() << '\n';
        return 1;
    }
}
