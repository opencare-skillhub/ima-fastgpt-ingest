import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from verify_content_manifest import InvalidInput, verify


class ContentFidelityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.text = '# 文献\n\n原PDF物理页12\n\n请保留原文中的适用条件与否定词。🧭\n'
        self.file = self.root / 'body.md'
        self.file.write_text(self.text, encoding='utf-8')
        digest = hashlib.sha256(self.file.read_bytes()).hexdigest()
        self.manifest = {'dataset_id': 'example-dataset', 'books': [{'title': '示例文献',
            'file': 'body.md', 'bytes': self.file.stat().st_size, 'uploaded_document_chars': len(self.text),
            'sha256': digest, 'medical_body_range': [10, 20]}]}
        self.remote = {'dataset_id': 'example-dataset', 'files': [{'title': '示例文献',
            'collection_id': 'example-collection', 'remote_raw_text_length': len(self.text.encode('utf-16-le')) // 2,
            'remote_bytes': self.file.stat().st_size, 'index_amount': 3, 'error_count': 0}]}

    def errors(self, result):
        return result['documents'][0]['errors']

    def test_full_file_and_javascript_character_length_match(self):
        self.assertTrue(verify(self.manifest, self.root, self.remote)['passed'])
        self.remote['files'][0]['remote_raw_text_length'] = len(self.text)
        self.assertIn('REMOTE_CHAR_LENGTH_MISMATCH', self.errors(verify(self.manifest, self.root, self.remote)))

    def test_truncation_and_equal_length_rewriting_both_detected(self):
        self.file.write_text(self.text[:12], encoding='utf-8')
        result = verify(self.manifest, self.root)
        self.assertIn('BODY_BYTES_MISMATCH', self.errors(result))
        self.assertIn('BODY_HASH_MISMATCH', self.errors(result))
        self.file.write_text(self.text.replace('否定词', '肯定词'), encoding='utf-8')
        result = verify(self.manifest, self.root)
        self.assertIn('BODY_HASH_MISMATCH', self.errors(result))
        self.assertNotIn('BODY_CHAR_LENGTH_MISMATCH', self.errors(result))

    def test_missing_source_pending_indexes_and_processing_errors(self):
        empty = copy.deepcopy(self.remote)
        empty['files'] = []
        self.assertIn('REMOTE_DOCUMENT_MISSING', self.errors(verify(self.manifest, self.root, empty)))
        self.remote['files'][0].update(index_amount=0, error_count=2)
        errors = self.errors(verify(self.manifest, self.root, self.remote))
        self.assertIn('REMOTE_INDEX_NOT_READY', errors)
        self.assertIn('REMOTE_PROCESSING_ERRORS_OR_UNKNOWN', errors)

    def test_wrong_dataset_and_duplicate_identity_rejected(self):
        self.remote['dataset_id'] = 'different-dataset'
        with self.assertRaisesRegex(InvalidInput, 'REMOTE_DATASET_MISMATCH'):
            verify(self.manifest, self.root, self.remote)
        self.remote['dataset_id'] = 'example-dataset'
        self.remote['files'].append(dict(self.remote['files'][0]))
        with self.assertRaisesRegex(InvalidInput, 'AMBIGUOUS_REMOTE_DOCUMENT'):
            verify(self.manifest, self.root, self.remote)

    def test_traversal_and_outside_symlink_cannot_read_credentials(self):
        for name in ['../credentials.env', '/private/credentials.env']:
            self.manifest['books'][0]['file'] = name
            self.assertIn('PATH_OUTSIDE_OUTPUT', self.errors(verify(self.manifest, self.root)))
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / 'private.md'
            target.write_text('SECRET-CONTENT', encoding='utf-8')
            (self.root / 'link.md').symlink_to(target)
            self.manifest['books'][0]['file'] = 'link.md'
            self.assertIn('PATH_OUTSIDE_OUTPUT', self.errors(verify(self.manifest, self.root)))

    def test_keypoints_are_sidecars_bound_to_body_and_quotes(self):
        book = self.manifest['books'][0]
        book['keypoints_file'] = 'keypoints.json'
        sidecar = {'body_sha256': book['sha256'], 'items': [{'key_point': '保留条件和否定词',
            'source_quote': '请保留原文中的适用条件与否定词。', 'source_pages': [12]}]}
        path = self.root / 'keypoints.json'
        path.write_text(json.dumps(sidecar), encoding='utf-8')
        self.assertTrue(verify(self.manifest, self.root)['passed'])
        sidecar['body_sha256'] = '0' * 64
        sidecar['items'][0].update(source_quote='原文中没有的建议', source_pages=[99])
        path.write_text(json.dumps(sidecar), encoding='utf-8')
        errors = self.errors(verify(self.manifest, self.root))
        for expected in ['KEYPOINT_SOURCE_HASH_MISMATCH', 'KEYPOINT_QUOTE_NOT_IN_BODY', 'KEYPOINT_PAGE_OUTSIDE_BODY']:
            self.assertIn(expected, errors)

    def test_cli_reports_failure_without_source_or_credential_output(self):
        manifest = self.root / 'manifest.json'
        manifest.write_text(json.dumps(self.manifest), encoding='utf-8')
        self.file.write_text('PRIVATE-TEXT-DO-NOT-LOG', encoding='utf-8')
        result = subprocess.run([sys.executable, str(Path(__file__).with_name('verify_content_manifest.py')),
            '--manifest', str(manifest), '--output-root', str(self.root)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('PRIVATE-TEXT-DO-NOT-LOG', result.stdout + result.stderr)
        self.assertFalse(json.loads(result.stdout)['passed'])


if __name__ == '__main__':
    unittest.main()
