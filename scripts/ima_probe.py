#!/usr/bin/env python3
"""Read-only IMA inventory/media preflight. Never downloads content or prints URLs."""
import argparse
import json
import os
import sys
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request


class ProbeError(Exception):
    pass


def load_credentials(environ=None, config_dir=None):
    """Resolve each field from env then private files; never return values in reports."""
    environ = os.environ if environ is None else environ
    config_dir = Path.home() / '.config' / 'ima' if config_dir is None else Path(config_dir)
    resolved, sources = {}, {}
    for field, names, filename in [
        ('client_id', ('IMA_OPENAPI_CLIENTID', 'IMA_CLIENT_ID'), 'client_id'),
        ('api_key', ('IMA_OPENAPI_APIKEY', 'IMA_API_KEY'), 'api_key'),
    ]:
        resolved[field], sources[field] = '', 'missing'
        for name in names:
            value = environ.get(name, '').strip()
            if value:
                resolved[field], sources[field] = value, 'env:' + name
                break
        if not resolved[field]:
            try:
                value = (config_dir / filename).read_text(encoding='utf-8').strip()
            except (OSError, UnicodeError):
                value = ''
            if value:
                resolved[field], sources[field] = value, 'config:' + filename
    return resolved, sources


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ImaReadAPI:
    ALLOWED = {'get_knowledge_base', 'get_knowledge_list', 'get_media_info'}

    def __init__(self, client_id, api_key, timeout=15):
        self.headers = {
            'ima-openapi-clientid': client_id,
            'ima-openapi-apikey': api_key,
            'Content-Type': 'application/json',
        }
        self.timeout = timeout
        self.opener = urllib.request.build_opener(NoRedirect())

    def __call__(self, method, body):
        if method not in self.ALLOWED:
            raise ProbeError('METHOD_NOT_ALLOWED')
        req = urllib.request.Request(
            'https://ima.qq.com/openapi/wiki/v1/' + method,
            data=json.dumps(body).encode('utf-8'), headers=self.headers, method='POST',
        )
        try:
            with self.opener.open(req, timeout=self.timeout) as response:
                raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise ProbeError('RESPONSE_TOO_LARGE')
                payload = json.loads(raw)
        except urllib.error.HTTPError as exc:
            raise ProbeError('HTTP_' + str(exc.code)) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ProbeError('NETWORK_ERROR') from None
        except (ValueError, UnicodeError):
            raise ProbeError('INVALID_JSON') from None
        if not isinstance(payload, dict):
            raise ProbeError('INVALID_ENVELOPE')
        if type(payload.get('code')) is not int or payload['code'] != 0:
            code = payload.get('code')
            # Error bodies can contain credentials or signed URLs; never echo them.
            raise ProbeError('BUSINESS_' + (str(code) if type(code) is int else 'ERROR'))
        data = payload.get('data')
        if not isinstance(data, dict):
            raise ProbeError('INVALID_DATA')
        return data


def collect_inventory(api, kb_id, max_pages=100):
    """Return a complete recursive snapshot or fail closed; never infer deletion."""
    identity = api('get_knowledge_base', {'ids': [kb_id]})
    infos = identity.get('infos')
    if not isinstance(infos, dict) or not isinstance(infos.get(kb_id), dict):
        raise ProbeError('KB_ID_NOT_VERIFIED')
    verified = infos[kb_id]
    if verified.get('id') != kb_id:
        raise ProbeError('KB_ID_MISMATCH')
    queue = [None]
    folders_seen = set()
    items = []
    media_seen = set()
    pages = 0
    while queue:
        folder = queue.pop(0)
        cursor = ''
        cursors_seen = set()
        while True:
            pages += 1
            if pages > max_pages:
                raise ProbeError('INVENTORY_INCOMPLETE_PAGE_LIMIT')
            body = {'knowledge_base_id': kb_id, 'cursor': cursor, 'limit': 20}
            if folder is not None:
                body['folder_id'] = folder
            data = api('get_knowledge_list', body)
            rows = data.get('knowledge_list')
            if not isinstance(rows, list) or type(data.get('is_end')) is not bool:
                raise ProbeError('INVENTORY_INCOMPLETE_SCHEMA')
            for row in rows:
                if not isinstance(row, dict):
                    raise ProbeError('INVENTORY_INCOMPLETE_ITEM')
                is_folder = row.get('media_type') == 99 or bool(row.get('folder_id'))
                if is_folder:
                    folder_id = row.get('media_id') or row.get('folder_id')
                    if not isinstance(folder_id, str) or not folder_id or folder_id in folders_seen or folder_id == kb_id:
                        raise ProbeError('INVENTORY_INCOMPLETE_FOLDER_CYCLE')
                    folders_seen.add(folder_id)
                    queue.append(folder_id)
                else:
                    media_id = row.get('media_id')
                    if not isinstance(media_id, str) or not media_id:
                        raise ProbeError('INVENTORY_INCOMPLETE_MEDIA_ID')
                    if media_id not in media_seen:
                        media_seen.add(media_id)
                        items.append({
                            'media_id': media_id,
                            'title': str(row.get('title', '')),
                            'parent_folder_id': row.get('parent_folder_id', folder),
                        })
            if data['is_end']:
                break
            next_cursor = data.get('next_cursor')
            if not isinstance(next_cursor, str) or not next_cursor or next_cursor == cursor or next_cursor in cursors_seen:
                raise ProbeError('INVENTORY_INCOMPLETE_CURSOR')
            cursors_seen.add(next_cursor)
            cursor = next_cursor
    return {
        'knowledge_base_id': kb_id, 'title': str(verified.get('name', '')),
        'complete': True, 'pages': pages, 'folders': len(folders_seen), 'items': items,
    }


def summarize_media(data):
    """Preserve capability evidence, discard signed URL and all header values."""
    if data.get('media_type') == 11:
        note = data.get('notebook_ext_info') or {}
        return {'state': 'NOTE_API_REQUIRED', 'has_note_id': bool(note.get('notebook_id'))}
    info = data.get('url_info') or {}
    if not isinstance(info, dict):
        raise ProbeError('INVALID_MEDIA_INFO')
    url = info.get('url')
    if not isinstance(url, str) or not url:
        return {'state': 'CONTENT_UNAVAILABLE', 'media_type': data.get('media_type')}
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        return {'state': 'UNSAFE_DOWNLOAD_URL', 'media_type': data.get('media_type')}
    return {
        'state': 'URL_AVAILABLE_NOT_DOWNLOADED', 'media_type': data.get('media_type'),
        'url_host': parsed.hostname, 'requires_headers': bool(info.get('headers')),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kb-id', help='Official knowledge_base_id, not shareId')
    parser.add_argument('--check-credentials', action='store_true', help='Offline configuration check; never prints values')
    parser.add_argument('--probe-media', type=int, default=0, choices=range(0, 21), metavar='0..20')
    parser.add_argument('--max-pages', type=int, default=100)
    args = parser.parse_args()
    if args.max_pages < 1:
        parser.error('max-pages must be positive')
    if not args.check_credentials and (not args.kb_id or not args.kb_id.strip()):
        parser.error('kb-id is required unless checking credentials')
    credentials, sources = load_credentials()
    client_id, api_key = credentials['client_id'], credentials['api_key']
    if args.check_credentials:
        configured = bool(client_id and api_key)
        print(json.dumps({'status': 'CREDENTIALS_CONFIGURED' if configured else 'AUTH_REQUIRED',
                          'sources': sources, 'network_called': False}))
        return 0 if configured else 2
    if not client_id or not api_key:
        print(json.dumps({'status': 'AUTH_REQUIRED', 'network_called': False}))
        return 2
    try:
        api = ImaReadAPI(client_id, api_key)
        result = collect_inventory(api, args.kb_id, args.max_pages)
        probes = []
        for item in result['items'][:args.probe_media]:
            data = api('get_media_info', {'media_id': item['media_id']})
            probes.append({'media_id': item['media_id'], **summarize_media(data)})
        result.update(status='INVENTORY_VERIFIED', media_probes=probes,
                      content_downloaded=False, content_uploaded=False)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except ProbeError as exc:
        print(json.dumps({'status': str(exc), 'complete': False,
                          'content_downloaded': False, 'content_uploaded': False}))
        return 3


if __name__ == '__main__':
    sys.exit(main())
