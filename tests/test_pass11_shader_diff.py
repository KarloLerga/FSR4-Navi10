import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools' / 'diagnostics'))
from verify_shader_diff import check_manifests, PASS11


class ShaderManifestDiffTest(unittest.TestCase):
    def make(self, guarded=False, changed=False):
        return {'source_commit': 'pinned', 'source_hashes_sha256': {'model': 'abc'},
                'diagnostic_modes': {'scalar_dot4': True, 'pass11_bounds_guard': guarded},
                'outputs': [{'file': PASS11, 'sha256': 'b' if changed else 'a'},
                            {'file': 'fsr4_model_v07_i8_native_1080_10_permutations.h', 'sha256': 'other'}]}

    def test_compiled_pass11_must_change(self):
        self.assertTrue(check_manifests(self.make(), self.make(True, True))['pass11_compiled_artifact_changed'])
        self.assertFalse(check_manifests(self.make(), self.make(True, False))['pass11_compiled_artifact_changed'])

    def test_source_changed_rejected(self):
        changed = self.make(True, True)
        changed['source_hashes_sha256']['model'] = 'bad'
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
