import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools' / 'diagnostics'))
from evaluate_pass11_guard import assess_campaign, evaluate


def fake_campaign(variant, guard, stable, seeds=('zero', 'a5')):
    rows = []
    for seed in seeds:
        for prefix in ('pass_10', 'pass_11', 'pass_12', 'full'):
            for repeat in (1, 2, 3):
                frames = []
                for i in range(8):
                    expected = f'frame{i}'
                    raw = expected if stable else f'{expected}.{seed}.{repeat}'
                    frames.append({'frame_index': i, 'input_frame_sha256': f'input{i}',
                                   'reference_output_sha256': raw,
                                   'instrumented_output_sha256': raw,
                                   'output_identical': True, 'outputs_finite': True})
                sample = f'scratch{prefix}' if stable or prefix == 'pass_10' else f'scratch{prefix}.{seed}.{repeat}'
                rows.append({'seed': seed, 'pass_name': prefix, 'repeat': repeat,
                             'error': None, 'exit_code': 0,
                             'sequence_hash': 'sequence_same',
                             'input_hashes': [f'input{i}' for i in range(8)],
                             'files': {'ordinary': {'sha256': sample},
                                       'instrumented': {'sha256': sample}},
                             'frames': frames})
    return {'schema': 'f4n10.pass11-guard-campaign.v1', 'variant': variant,
            'expected_guard': guard, 'cases': rows}


class GuardEvaluatorTest(unittest.TestCase):
    def test_synthetic_fixed_baseline_and_guarded(self):
        baseline = fake_campaign('baseline_scalar', False, False)
        guarded_scalar = fake_campaign('guard_scalar', True, True)
        guarded_intrinsic = fake_campaign('guard_intrinsic', True, True)
        result = evaluate(baseline, guarded_scalar, guarded_intrinsic)
        self.assertFalse(result['baseline']['candidate_fixed'])
        self.assertTrue(result['guard_scalar']['candidate_fixed'])
        self.assertTrue(result['guard_intrinsic']['candidate_fixed'])
        self.assertTrue(result['pass11_bounds_hypothesis_supported_by_gpu'])
        self.assertFalse(result['o0_teacher_eligible'])

    def test_guarded_but_nondeterministic_rejected(self):
        doc = fake_campaign('guard_scalar', True, False)
        self.assertFalse(assess_campaign(doc)['candidate_fixed'])

    def test_guard_not_ready_with_error(self):
        doc = fake_campaign('guard_scalar', True, True)
        doc['cases'][0]['error'] = 'GPU fault'
        self.assertFalse(assess_campaign(doc)['candidate_fixed'])

    def test_guard_not_ready_with_missing_pass11(self):
        doc = fake_campaign('guard_scalar', True, True)
        doc['cases'] = [c for c in doc['cases'] if c['pass_name'] != 'pass_11']
        self.assertFalse(assess_campaign(doc)['candidate_fixed'])

    def test_wrong_guard_toggles_refused(self):
        doc = fake_campaign('baseline', False, False)
        with self.assertRaises(ValueError):
            evaluate(doc, doc, doc)


if __name__ == '__main__':
    unittest.main()
