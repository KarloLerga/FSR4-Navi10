from __future__ import annotations

import sys
import unittest
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools" / "model"
sys.path.insert(0, str(TOOLS_DIR))

from extract_pass_contracts import parse_pass_contracts  # noqa: E402


def make_pass_source() -> str:
    sections: list[str] = []
    for index in range(14):
        macro = f"MLSR_PASS_{index}"
        entry = f"fsr4_model_v07_i8_pass{index}"
        tensor = ""
        if index == 1:
            tensor = """
    const QuantizedTensor4i8_NHWC< ConstantBufferStorage<1> > model_weight = {
        uint4(1, 1, 1, 2), // logicalSize
        uint4(0, 0, 0, 0), // threadGroupSliceStart
        uint4(1, 1, 1, 2), // threadGroupSliceSize
        uint4(1, 1, 1, 2), // storageSize
        uint4(2, 2, 1, 1), // storageByteStrides
        uint4(0, 0, 0, 0), // paddingBegin
        uint4(0, 0, 0, 0), // paddingEnd
        0, // threadGroupStorageByteOffset
        0.125,
        storage_weight };
"""
        sections.append(
            f"#ifdef {macro}\n"
            '#include "operators/Example.hlsli"\n'
            "[numthreads(8, 8, 1)]\n"
            f"void {entry}() {{\n{tensor}    ExampleOperator<32, 1>(0.5, model_weight, computeShaderParams);\n"
            f"}}\n#endif // #ifdef {macro}\n"
        )
    for index in range(13):
        macro = f"MLSR_PASS_{index}_POST"
        entry = f"fsr4_model_v07_i8_pass{index}_post"
        sections.append(
            f"#ifdef {macro}\n"
            '#include "operators/padding.hlsli"\n'
            "[numthreads(32, 1, 1)]\n"
            f"void {entry}() {{\n    ResetPadding(computeShaderParams);\n"
            f"}}\n#endif // #ifdef {macro}\n"
        )
    return "\n".join(sections)


class PassContractParserTests(unittest.TestCase):
    def test_extracts_source_entrypoints_calls_tensors_and_threadgroups(self) -> None:
        contracts = parse_pass_contracts(make_pass_source())
        self.assertEqual(len(contracts), 27)
        self.assertEqual(sum(contract["role"] == "neural_pass" for contract in contracts), 12)
        first_neural = contracts[1]
        self.assertEqual(first_neural["entryPoint"], "fsr4_model_v07_i8_pass1")
        self.assertEqual(first_neural["numThreads"], [8, 8, 1])
        self.assertEqual(first_neural["operatorIncludes"], ["operators/Example.hlsli"])
        self.assertEqual(first_neural["operatorCalls"][0]["operator"], "ExampleOperator<32,1>")
        self.assertEqual(
            first_neural["operatorCalls"][0]["argumentExpressions"],
            ["0.5", "model_weight", "computeShaderParams"],
        )
        self.assertEqual(first_neural["tensorDescriptors"][0]["name"], "model_weight")
        self.assertEqual(first_neural["tensorDescriptors"][0]["type"], "QuantizedTensor4i8_NHWC")
        self.assertEqual(
            first_neural["tensorDescriptors"][0]["fieldLabels"],
            [
                "logicalSize",
                "threadGroupSliceStart",
                "threadGroupSliceSize",
                "storageSize",
                "storageByteStrides",
                "paddingBegin",
                "paddingEnd",
                "threadGroupStorageByteOffset",
            ],
        )

    def test_fails_closed_when_entrypoint_threadgroup_is_missing(self) -> None:
        source = make_pass_source().replace("[numthreads(8, 8, 1)]\n", "", 1)
        with self.assertRaisesRegex(RuntimeError, "numthreads declaration is missing"):
            parse_pass_contracts(source)


if __name__ == "__main__":
    unittest.main()
