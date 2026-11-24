#!/usr/bin/env python3
"""Offline content-fidelity checks. No network, credentials, or source-text output."""
import argparse
import hashlib
import json
from pathlib import Path
import re


class InvalidInput(Exception):
    pass


def read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError, UnicodeError):
        raise InvalidInput('INVALID_JSON') from None


def inside(root, relative):
    if not isinstance(relative, str) or not relative:
        raise InvalidInput('INVALID_FILE_PATH')
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise InvalidInput('PATH_OUTSIDE_OUTPUT')
    return path


def integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def check_keypoints(root, book, body, body_hash):
    if not book.get('keypoints_file'):
        return []
    sidecar = read_json(inside(root, book['keypoints_file']))
    if not isinstance(sidecar, dict) or not isinstance(sidecar.get('items'), list):
        raise InvalidInput('INVALID_KEYPOINTS_SCHEMA')
    errors = []
    if sidecar.get('body_sha256') != body_hash:
        errors.append('KEYPOINT_SOURCE_HASH_MISMATCH')
    bounds = book.get('medical_body_range')
    if not (isinstance(bounds, list) and len(bounds) == 2
            and all(integer(n) for n in bounds) and 1 <= bounds[0] <= bounds[1]):
        raise InvalidInput('INVALID_PAGE_RANGE')
    for point in sidecar['items']:
        if not isinstance(point, dict):
            raise InvalidInput('INVALID_KEYPOINT_ITEM')
        quote = point.get('source_quote')
        if not isinstance(quote, str) or not quote.strip() or quote not in body:
            errors.append('KEYPOINT_QUOTE_NOT_IN_BODY')
        pages = point.get('source_pages')
        if not (isinstance(pages, list) and pages and all(
                integer(n) and bounds[0] <= n <= bounds[1] for n in pages)):
            errors.append('KEYPOINT_PAGE_OUTSIDE_BODY')
        if not isinstance(point.get('key_point'), str) or not point['key_point'].strip():
            errors.append('KEYPOINT_TEXT_MISSING')
    return sorted(set(errors))


def verify(manifest, root, remote=None):
    if not isinstance(manifest, dict) or not isinstance(manifest.get('books'), list) or not manifest['books']:
        raise InvalidInput('INVALID_MANIFEST')
    books = manifest['books']
    titles = [book.get('title') if isinstance(book, dict) else None for book in books]
    if any(not isinstance(t, str) or not t for t in titles) or len(set(titles)) != len(titles):
        raise InvalidInput('AMBIGUOUS_DOCUMENT_TITLES')
    remote_by_title = None
    if remote is not None:
        if not isinstance(remote, dict) or not isinstance(remote.get('files'), list):
            raise InvalidInput('INVALID_REMOTE_SNAPSHOT')
        if not manifest.get('dataset_id') or remote.get('dataset_id') != manifest['dataset_id']:
            raise InvalidInput('REMOTE_DATASET_MISMATCH')
        remote_by_title = {}
        seen_ids = set()
        for item in remote['files']:
            if not isinstance(item, dict) or not isinstance(item.get('title'), str):
                raise InvalidInput('INVALID_REMOTE_ROW')
            title = item['title']
            cid = item.get('collection_id')
            if title in remote_by_title or not isinstance(cid, str) or not cid or cid in seen_ids:
                raise InvalidInput('AMBIGUOUS_REMOTE_DOCUMENT')
            seen_ids.add(cid)
            remote_by_title[title] = item

    rows = []
    seen_paths = set()
    for number, book in enumerate(books, 1):
        errors = []
        try:
            path = inside(root, book.get('file'))
            if path in seen_paths:
                raise InvalidInput('DUPLICATE_DOCUMENT_FILE')
            seen_paths.add(path)
            if path.suffix.lower() != '.md':
                raise InvalidInput('BODY_MUST_BE_MARKDOWN')
            try:
                raw = path.read_bytes()
                text = raw.decode('utf-8')
            except (OSError, UnicodeError):
                raise InvalidInput('BODY_UNREADABLE') from None
            digest = hashlib.sha256(raw).hexdigest()
            if not isinstance(book.get('sha256'), str) or not re.fullmatch(r'[0-9a-f]{64}', book['sha256']):
                raise InvalidInput('INVALID_SHA256')
            for key in ['bytes', 'uploaded_document_chars']:
                if not integer(book.get(key)) or book[key] <= 0:
                    raise InvalidInput('INVALID_DOCUMENT_COUNTS')
            if not text.strip():
                errors.append('EMPTY_BODY')
            if digest != book['sha256']:
                errors.append('BODY_HASH_MISMATCH')
            if len(raw) != book['bytes']:
                errors.append('BODY_BYTES_MISMATCH')
            if len(text) != book['uploaded_document_chars']:
                errors.append('BODY_CHAR_LENGTH_MISMATCH')
            errors.extend(check_keypoints(root, book, text, digest))
            if remote_by_title is not None:
                item = remote_by_title.get(book['title'])
                if item is None:
                    errors.append('REMOTE_DOCUMENT_MISSING')
                else:
                    # FastGPT/JavaScript counts UTF-16 code units, unlike Python len().
                    js_length = len(text.encode('utf-16-le')) // 2
                    if item.get('remote_raw_text_length') != js_length:
                        errors.append('REMOTE_CHAR_LENGTH_MISMATCH')
                    if item.get('remote_bytes') != len(raw):
                        errors.append('REMOTE_BYTES_MISMATCH')
                    if not integer(item.get('index_amount')) or item['index_amount'] <= 0:
                        errors.append('REMOTE_INDEX_NOT_READY')
                    if not integer(item.get('error_count')) or item['error_count'] != 0:
                        errors.append('REMOTE_PROCESSING_ERRORS_OR_UNKNOWN')
            rows.append({'document_index': number, 'passed': not errors,
                         'local_bytes': len(raw), 'local_chars': len(text), 'errors': sorted(set(errors))})
        except InvalidInput as exc:
            rows.append({'document_index': number, 'passed': False, 'errors': [str(exc)]})
    return {'passed': all(row['passed'] for row in rows), 'document_count': len(rows),
            'evidence_scope': 'offline_files_and_supplied_snapshot' if remote is not None else 'offline_files',
            'remote_snapshot_checked': remote is not None, 'documents': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output-root', type=Path, required=True, help='All body/sidecar files must resolve inside this directory')
    parser.add_argument('--remote-snapshot', type=Path, help='Sanitized metadata snapshot; never treated as a live API check')
    args = parser.parse_args()
    try:
        root = args.output_root.resolve()
        if not root.is_dir():
            raise InvalidInput('OUTPUT_ROOT_MISSING')
        result = verify(read_json(args.manifest), root,
                        read_json(args.remote_snapshot) if args.remote_snapshot else None)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['passed'] else 1
    except InvalidInput as exc:
        print(json.dumps({'passed': False, 'error': str(exc)}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
