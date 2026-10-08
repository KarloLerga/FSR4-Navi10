import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools' / 'diagnostics'))
from run_pass11_guard_campaign import run

FAKE = '''import json, os, sys
from pathlib import Path
s=Path(sys.argv[2])
r=Path(sys.argv[3])
trace=Path(os.environ["FSR4N10_TRACE_SCRATCH_DIR"])
frame=os.environ["FSR4N10_TRACE_FRAME"]
p=os.environ.get("FSR4N10_LAST_MODEL_PASS", "full")
for context in ("ordinary", "instrumented"):
    (trace / f"frame_{frame}_pass_{p}_{context}.bin").write_bytes(bytes(32))
frames=[{"frame_index":i,"input_frame_sha256":f"input{i}",
         "reference_output_sha256":f"rgb{i}",
         "instrumented_output_sha256":f"rgb{i}",
         "output_identical":True,"outputs_finite":True} for i in range(8)]
r.write_text(json.dumps({"sequence_hash":"aligned", "diagnostic_prefix_only":p!="full",
                         "frames":frames}))
'''


class RunnerIntegrationTest(unittest.TestCase):
    def test_real_subprocess_runner_and_manifest_guard(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            harness = root / 'build/harness.py'
            harness.parent.mkdir(parents=True)
            harness.write_text(FAKE)
            manifest = root / 'build/teacher/provider_i8_native_1080/manifest.json'
            manifest.parent.mkdir(parents=True)
            manifest.write_text(json.dumps({'source_commit':'pinned',
                'diagnostic_modes':{'pass11_bounds_guard':True}}))
            sequence = root / 'frames.f4seq'
            sequence.write_bytes(b'fake sequence (runner trusts externally validated f4seq)')
            doc = run(harness, sequence, root / 'out', ['zero', 'a5'],
                      ['11','full'], 2, 0, 'guard-test', True)
            self.assertEqual(len(doc['cases']), 8)
            self.assertFalse([row for row in doc['cases'] if row['error']])
            self.assertTrue((root/'out/campaign.json').exists())
            self.assertTrue(all(len(row['frames']) == 8 for row in doc['cases']))
            with self.assertRaises(RuntimeError):
                run(harness, sequence, root / 'out2', ['zero'], ['11'], 2, 0,
                    'wrong-flag', False)


if __name__ == '__main__':
    unittest.main()
