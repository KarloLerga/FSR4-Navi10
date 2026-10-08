import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools' / 'diagnostics'))
from verify_shader_diff import check_manifests, PASS11


class ShaderManifestDiffTest(unittest.TestCase):
    def make(self, guarded=False, changed=False):
        operator_hash = 'fnb-source'
        overlay_hash = 'fnb-overlay'
        path = ('C:/build/capture_shader_overrides/FSR4N10_FNB_CT2D_ADD_PASS11_GUARD.hlsli'
                if guarded else 'C:/repo/third_party/fsr4/dx12/ml2code_runtime/operators/int8_NHWC/Fused/FNB_CT2D_ADD.hlsli')
        return {'source_commit': 'pinned',
                'source_hashes_sha256': {'model': 'abc', 'pass11_fnb_operator': operator_hash},
                'diagnostic_modes': {'scalar_dot4': True, 'pass11_bounds_guard': guarded},
                'pass11_operator_include': {'path': path, 'sha256': overlay_hash if guarded else operator_hash},
                'capture_overlay_hashes_sha256': {'pass11_fnb_bounds_guard': overlay_hash} if guarded else {},
                'outputs': [{'file': PASS11, 'sha256': 'selector-guard' if changed else 'selector-base'},
                            {'file': 'fsr4_model_v07_i8_native_1080_10_permutations.h', 'sha256': 'other'},
                            {'file': 'fsr4_model_v07_i8_native_1080_11_1234567890abcdef1234567890abcdef.h',
                             'sha256': 'guard-payload' if changed else 'base-payload', 'size_bytes': 128}]}

    def test_compiled_pass11_must_change(self):
        self.assertTrue(check_manifests(self.make(), self.make(True, True))['pass11_compiled_artifact_changed'])
        self.assertFalse(check_manifests(self.make(), self.make(True, False))['pass11_compiled_artifact_changed'])

    def test_source_changed_rejected(self):
        changed = self.make(True, True)
        changed['source_hashes_sha256']['model'] = 'bad'
        with self.assertRaises(ValueError):
            check_manifests(self.make(), changed)

    def test_selector_reordering_does_not_masquerade_as_payload_change(self):
        baseline = self.make()
        guarded = self.make(True, False)
        name = 'fsr4_model_v07_i8_native_0_permutations.h'
        baseline['outputs'].append({'file': name, 'sha256': 'selector-order-a'})
        guarded['outputs'].append({'file': name, 'sha256': 'selector-order-b'})
        for suffix, digest in [('11111111111111111111111111111111', 'payload-a'),
                               ('22222222222222222222222222222222', 'payload-b')]:
            output = {'file': f'fsr4_model_v07_i8_native_0_{suffix}.h',
                      'sha256': digest, 'size_bytes': 64}
            baseline['outputs'].append(output.copy())
            guarded['outputs'].append(output.copy())
        result = check_manifests(baseline, guarded)
        self.assertFalse(result['pass11_compiled_artifact_changed'])
        self.assertEqual(result['changed_shader_payloads'], [])
        self.assertEqual(result['selector_header_hash_changed_with_same_payload_set'], [name])

    def test_non_pass11_payload_change_is_reported_separately(self):
        baseline = self.make()
        guarded = self.make(True, True)
        selector = 'fsr4_model_v07_i8_native_0_permutations.h'
        baseline['outputs'].append({'file': selector, 'sha256': 'selector-base'})
        guarded['outputs'].append({'file': selector, 'sha256': 'selector-guard'})
        name = 'fsr4_model_v07_i8_native_0_33333333333333333333333333333333.h'
        baseline['outputs'].append({'file': name, 'sha256': 'payload-a', 'size_bytes': 64})
        guarded['outputs'].append({'file': name, 'sha256': 'payload-b', 'size_bytes': 64})
        result = check_manifests(baseline, guarded)
        self.assertTrue(result['pass11_compiled_artifact_changed'])
        self.assertEqual(result['changed_shader_payloads'], [
            'fsr4_model_v07_i8_native_0_permutations.h', PASS11])

    def test_guarded_operator_dependency_must_be_overlay(self):
        changed = self.make(True, True)
        changed['pass11_operator_include']['path'] = 'C:/repo/third_party/fsr4/FNB_CT2D_ADD.hlsli'
        with self.assertRaises(ValueError):
            check_manifests(self.make(), changed)

    def test_toggle_or_scalar_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            check_manifests(self.make(True, True), self.make(True, True))
        changed = self.make(True, True)
        changed['diagnostic_modes']['scalar_dot4'] = False
        with self.assertRaises(ValueError):
            check_manifests(self.make(), changed)


if __name__ == '__main__':
    unittest.main()
