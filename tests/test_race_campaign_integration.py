import importlib.util
import pathlib
import tempfile
import unittest

repository = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('campaign_module', repository/'tools/diagnostics/run_prefix_campaign.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
spec2 = importlib.util.spec_from_file_location('analyzer_module', repository/'tools/diagnostics/analyze_scratch_campaign.py')
ana = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(ana)
spec3 = importlib.util.spec_from_file_location('variant_module', repository/'tools/diagnostics/compare_campaign_variants.py')
variant_compare = importlib.util.module_from_spec(spec3)
spec3.loader.exec_module(variant_compare)


class CampaignIntegrationTest(unittest.TestCase):
    def test_variant_comparison_requires_matching_inputs(self):
        with tempfile.TemporaryDirectory() as root:
            root = pathlib.Path(root)
            reports = []
            for name, instrumented, ordinary in (('standard', 'rgb-a', 'ref-a'),
                                                  ('barrier', 'rgb-b', 'ref-b')):
                path = root / f'{name}.json'
                path.write_text('''{"sequence_hash":"same-sequence","frames":[
                    {"input_frame_sha256":"same-input","instrumented_output_sha256":"''' + instrumented +
                    '''","reference_output_sha256":"''' + ordinary + '''"}]}''', encoding='utf-8')
                reports.append({"sequence_hash": "same-sequence", "input_hashes": ["same-input"],
                                "report_path": str(path), "files": {
                                    "instrumented": {"size": 128, "sha256": instrumented},
                                    "ordinary": {"size": 128, "sha256": ordinary},
                                }, "error": None, "seed": "zero", "pass_name": "full", "repeat": 1})
            result = variant_compare.compare_campaigns(
                {"variant": "standard", "cases": [reports[0]]},
                {"variant": "global-barrier", "cases": [reports[1]]})
            self.assertTrue(result["all_common_inputs_equal"])
            self.assertEqual(result["full_rgb_differences_on_equal_inputs"], 1)

    def test_tiny_fake_gpu_harness(self):
        with tempfile.TemporaryDirectory() as root:
            root = pathlib.Path(root)
            harness = root / 'fake_harness.py'
            harness.write_text('''#!/usr/bin/env python3
import os,sys,json,pathlib
assert sys.argv[1]=='--run-fsr4-provider-sequence'
report=pathlib.Path(sys.argv[3]); report.parent.mkdir(parents=True,exist_ok=True)
final_pass=os.getenv('FSR4N10_LAST_MODEL_PASS')
seed=os.getenv('FSR4N10_SCRATCH_INIT','off')
label=final_pass or 'full'
trace=pathlib.Path(os.environ['FSR4N10_TRACE_SCRATCH_DIR']); trace.mkdir(parents=True,exist_ok=True)
value=0 if seed=='zero' else 41
for context in ('instrumented','ordinary'):
    (trace/f'frame_0_pass_{label}_{context}.bin').write_bytes(bytes([value]*128))
rep={'sequence_hash':'abc','diagnostic_prefix_only':final_pass is not None,'frames':[
    {'input_frame_sha256':'same','frame_index':0,
     'instrumented_output_sha256':seed,'reference_output_sha256':seed}]}
report.write_text(json.dumps(rep))
''')
            harness.chmod(0o755)
            seq = root / 'sequence.f4seq'
            seq.write_bytes(b'fake')
            report = mod.run_campaign(harness,seq,root/'output',['zero','a5'],1,2,10,0,'test')
            self.assertEqual(len(report['cases']),12)
            self.assertTrue(all(c['error'] is None for c in report['cases']))
            findings = ana.analyze_campaign(report)
            self.assertIsNone(findings['first_by_seed']['zero']['first_repeat_divergent_prefix'])
            self.assertFalse(findings['cross_seed_full_rgb']['zero_vs_a5']['all_reference_rgb_equal'])


if __name__=='__main__':
    unittest.main()
