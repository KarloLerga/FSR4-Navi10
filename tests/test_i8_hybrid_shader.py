from __future__ import annotations
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools/diagnostics'))
from verify_hybrid_shader import MODEL, verify

D0='abcd0123456789abcdef0123456789ab'


def make_manifest(pass_index=3, selected=False, extra_changed=False):
    files=[]
    for n in range(1, 13):
        stem=f'{MODEL}_{n}'
        files.append({'file':f'{stem}_permutations.h','sha256':'a'})
        hashvalue=('b' if selected and (n==pass_index or extra_changed and n==4) else 'a')
        files.append({'file':f'{stem}_{D0}.h','sha256':hashvalue,'size_bytes':123})
    return {'source_commit':'same', 'source_hashes_sha256':{'weights':'fixed'},
            'diagnostic_modes':{'pass11_bounds_guard':True,'scalar_dot4':False,
                                'stable_post_math':False,
                                'scalar_dot4_pass_set':[pass_index] if selected else []},
            'outputs':files}

class VerifyHybrid(unittest.TestCase):
    def test_only_selected_changed(self):
        result=verify(make_manifest(),make_manifest(selected=True),3)
        self.assertTrue(result['verified_isolated_pass_change'])
    def test_extra_pass_rejected(self):
        result=verify(make_manifest(),make_manifest(selected=True,extra_changed=True),3)
        self.assertFalse(result['verified_isolated_pass_change'])
    def test_different_sources_rejected(self):
        changed=make_manifest(selected=True)
        changed['source_commit']='different'
        with self.assertRaises(ValueError): verify(make_manifest(),changed,3)
    def test_mismatched_pass_set_rejected(self):
        with self.assertRaises(ValueError): verify(make_manifest(),make_manifest(selected=True),5)

if __name__=='__main__': unittest.main()
