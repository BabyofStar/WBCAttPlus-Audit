"""Synthetic tests: never contact the network or use patient identifiers."""

import hashlib
import json
import stat
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from package_extract import unpack_package
from dataset_workflow import audit, offline_install_command, run_logged


class RestartTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / 'tmp/tests'
        parent.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=str(parent))
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def fixture(self, content=b'official-data', unsafe=None, altered=False, link=False):
        manifest = json.dumps({'files': [{'path': 'data.bin', 'size_bytes': len(content),
                                         'sha256': hashlib.sha256(content).hexdigest()}]}).encode()
        archive = self.root / 'bundle.zip'
        with zipfile.ZipFile(archive, 'w') as stream:
            stream.writestr('package_manifest.json', manifest)
            stream.writestr('README.md', 'guide')
            stream.writestr('WBCAttPlus_Setup.ipynb', '{}')
            if link:
                info = zipfile.ZipInfo('data.bin')
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                stream.writestr(info, content)
            else:
                stream.writestr('data.bin', b'tampered' if altered else content)
            if unsafe:
                stream.writestr(unsafe, b'outside')
        return archive, hashlib.sha256(manifest).hexdigest()

    def test_extract_and_identical_rerun(self):
        archive, digest = self.fixture()
        target = self.root / 'project'
        unpack_package(archive, target, digest)
        unpack_package(archive, target, digest)
        self.assertEqual((target / 'data.bin').read_bytes(), b'official-data')

    def test_conflict_preserves_existing_and_writes_nothing_else(self):
        archive, digest = self.fixture()
        target = self.root / 'project'
        target.mkdir()
        (target / 'data.bin').write_bytes(b'user-file')
        with self.assertRaises(ValueError):
            unpack_package(archive, target, digest)
        self.assertEqual((target / 'data.bin').read_bytes(), b'user-file')
        self.assertFalse((target / 'README.md').exists())

    def test_manifest_anchor_rejects_wrong_digest(self):
        archive, _ = self.fixture()
        with self.assertRaises(ValueError):
            unpack_package(archive, self.root / 'project', '0' * 64)

    def test_payload_tamper_rejected(self):
        archive, digest = self.fixture(altered=True)
        with self.assertRaises(ValueError):
            unpack_package(archive, self.root / 'project', digest)

    def test_paths_and_symlink_entries_rejected(self):
        for name in ('../escape', '/absolute', 'C:/outside', 'a\\b'):
            archive, digest = self.fixture(unsafe=name)
            with self.assertRaises(ValueError):
                unpack_package(archive, self.root / 'project', digest)
        archive, digest = self.fixture(link=True)
        with self.assertRaises(ValueError):
            unpack_package(archive, self.root / 'project', digest)

    def test_pip_is_offline_and_does_not_install_torch(self):
        command = offline_install_command(self.root)
        self.assertIn('--no-index', command)
        self.assertIn('--find-links', command)
        self.assertIn('--only-binary=:all:', command)
        self.assertNotIn('torch', command)

    def test_process_failure_includes_original_cause_and_log(self):
        with self.assertRaises(RuntimeError) as error:
            run_logged(self.root, [sys.executable, '-c', "print('ORIGINAL_CAUSE');raise SystemExit(7)"], 'synthetic')
        self.assertIn('ORIGINAL_CAUSE', str(error.exception))
        self.assertIn('exit=7', str(error.exception))
        self.assertEqual(len(list((self.root / 'output/logs').glob('*.log'))), 1)

    def test_failed_audit_invalidates_stale_pass_and_no_receipt(self):
        (self.root / 'output').mkdir()
        (self.root / 'output/latest_run.json').write_text('{"status":"PASS","run_id":"old"}', encoding='utf-8')
        with mock.patch('dataset_workflow.verify_package'), mock.patch('dataset_workflow.run_logged', side_effect=RuntimeError('synthetic failure')):
            with self.assertRaises(RuntimeError):
                audit(self.root, site='local')
        state = json.loads((self.root / 'output/latest_run.json').read_text(encoding='utf-8'))
        self.assertEqual(state['status'], 'FAILED')
        self.assertNotEqual(state['run_id'], 'old')
        self.assertFalse(list(self.root.rglob('*_deployment_receipt.json')))

    def test_failed_payload_verification_marks_audit_failed(self):
        with mock.patch('dataset_workflow.verify_package', side_effect=ValueError('checksum mismatch')):
            with self.assertRaises(ValueError):
                audit(self.root, site='local')
        state = json.loads((self.root / 'output/latest_run.json').read_text(encoding='utf-8'))
        self.assertEqual(state['status'], 'FAILED')
        self.assertFalse(list(self.root.rglob('*_deployment_receipt.json')))


if __name__ == '__main__':
    unittest.main(verbosity=2)
