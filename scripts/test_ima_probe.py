import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from ima_probe import ImaReadAPI, ProbeError, collect_inventory, load_credentials, summarize_media


def fake_api(pages):
    def call(method, body):
        if method == 'get_knowledge_base':
            return {'infos': {'kb': {'id': 'kb', 'name': 'fixture'}}}
        return pages[(body.get('folder_id'), body['cursor'])]
    return call


class PreflightTests(unittest.TestCase):
    def test_credentials_env_before_files_and_no_empty_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'client_id').write_text('file-client\n')
            (root / 'api_key').write_text('file-secret\n')
            creds, sources = load_credentials({'IMA_OPENAPI_CLIENTID': 'env-client', 'IMA_OPENAPI_APIKEY': ' '}, root)
            self.assertEqual(creds, {'client_id': 'env-client', 'api_key': 'file-secret'})
            self.assertEqual(sources, {'client_id': 'env:IMA_OPENAPI_CLIENTID', 'api_key': 'config:api_key'})

    def test_primary_env_before_legacy_and_files_optional(self):
        with tempfile.TemporaryDirectory() as tmp:
            creds, _ = load_credentials({'IMA_OPENAPI_CLIENTID': 'primary', 'IMA_CLIENT_ID': 'legacy', 'IMA_API_KEY': 'legacy-secret'}, tmp)
            self.assertEqual(creds, {'client_id': 'primary', 'api_key': 'legacy-secret'})
            missing, sources = load_credentials({}, tmp)
            self.assertFalse(any(missing.values()))
            self.assertEqual(set(sources.values()), {'missing'})

    def test_cli_check_is_offline_and_does_not_expose_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, HOME=tmp)
            for name in ['IMA_OPENAPI_CLIENTID', 'IMA_OPENAPI_APIKEY', 'IMA_CLIENT_ID', 'IMA_API_KEY']:
                env.pop(name, None)
            script = str(Path(__file__).with_name('ima_probe.py'))
            result = subprocess.run([sys.executable, script, '--check-credentials'], env=env, text=True, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(json.loads(result.stdout)['network_called'])
            env.update(IMA_OPENAPI_CLIENTID='fixture-client-value', IMA_OPENAPI_APIKEY='fixture-secret-value')
            result = subprocess.run([sys.executable, script, '--check-credentials'], env=env, text=True, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 0)
            self.assertFalse(json.loads(result.stdout)['network_called'])
            self.assertNotIn('fixture-', result.stdout + result.stderr)

    def test_recursive_pagination_and_folder_shapes(self):
        pages = {
            (None, ''): {'knowledge_list': [{'media_type': 99, 'media_id': 'folder_a'}], 'is_end': False, 'next_cursor': 'p2'},
            (None, 'p2'): {'knowledge_list': [{'folder_id': 'b', 'name': 'B'}, {'media_id': 'm1', 'title': 'one.pdf'}], 'is_end': True},
            ('folder_a', ''): {'knowledge_list': [{'media_id': 'm2', 'title': 'two.pdf'}], 'is_end': True},
            ('b', ''): {'knowledge_list': [{'media_id': 'm3', 'title': 'three.pdf'}], 'is_end': True},
        }
        result = collect_inventory(fake_api(pages), 'kb')
        self.assertTrue(result['complete'])
        self.assertEqual(result['folders'], 2)
        self.assertEqual({x['media_id'] for x in result['items']}, {'m1', 'm2', 'm3'})

    def test_missing_or_repeated_cursor_never_completes(self):
        for next_cursor in ['', None]:
            with self.subTest(cursor=next_cursor), self.assertRaises(ProbeError):
                collect_inventory(fake_api({(None, ''): {'knowledge_list': [], 'is_end': False, 'next_cursor': next_cursor}}), 'kb')
        pages = {
            (None, ''): {'knowledge_list': [], 'is_end': False, 'next_cursor': 'same'},
            (None, 'same'): {'knowledge_list': [], 'is_end': False, 'next_cursor': 'same'},
        }
        with self.assertRaises(ProbeError):
            collect_inventory(fake_api(pages), 'kb')

    def test_schema_error_and_folder_cycle_fail_closed(self):
        with self.assertRaises(ProbeError):
            collect_inventory(fake_api({(None, ''): {'knowledge_list': [], 'is_end': 'true'}}), 'kb')
        pages = {
            (None, ''): {'knowledge_list': [{'media_id': 'folder_a', 'media_type': 99}], 'is_end': True},
            ('folder_a', ''): {'knowledge_list': [{'media_id': 'folder_a', 'media_type': 99}], 'is_end': True},
        }
        with self.assertRaises(ProbeError):
            collect_inventory(fake_api(pages), 'kb')

    def test_url_and_header_secrets_are_not_reported(self):
        result = summarize_media({'media_type': 1, 'url_info': {
            'url': 'https://files.example.test/doc.pdf?token=PRIVATE_SIGNATURE',
            'headers': {'Authorization': 'Bearer PRIVATE_HEADER'},
        }})
        self.assertEqual(result['state'], 'URL_AVAILABLE_NOT_DOWNLOADED')
        self.assertTrue(result['requires_headers'])
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertNotIn('/doc.pdf', json.dumps(result))

    def test_missing_url_note_and_unsafe_scheme_are_distinct(self):
        self.assertEqual(summarize_media({'media_type': 1})['state'], 'CONTENT_UNAVAILABLE')
        self.assertEqual(summarize_media({'media_type': 11, 'notebook_ext_info': {'notebook_id': 'n'}})['state'], 'NOTE_API_REQUIRED')
        self.assertEqual(summarize_media({'url_info': {'url': 'http://localhost/a'}})['state'], 'UNSAFE_DOWNLOAD_URL')

    def test_page_budget_and_wrong_identity(self):
        with self.assertRaises(ProbeError):
            collect_inventory(fake_api({(None, ''): {'knowledge_list': [], 'is_end': False, 'next_cursor': 'more'}}), 'kb', max_pages=1)
        with self.assertRaises(ProbeError):
            collect_inventory(lambda method, body: {'infos': {}}, 'missing')

    def test_api_rejects_mutations_before_network(self):
        with self.assertRaises(ProbeError):
            ImaReadAPI('fake', 'fake')('add_knowledge', {})


if __name__ == '__main__':
    unittest.main()
