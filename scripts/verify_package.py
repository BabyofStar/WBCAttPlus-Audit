"""Verify the single current package; optionally perform a fresh full dry run."""

import argparse
import ast
import hashlib
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from package_extract import unpack_package, file_sha256
from dataset_workflow import verify_package

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--full', action='store_true', help='Also unpack and re-decode every image/mask pair')
    parser.add_argument('--no-pdf', action='store_true', help='Full diagnostic run without creating the PDF')
    parser.add_argument('--site', choices=('local', 'server'), default='local')
    args = parser.parse_args()
    verify_package(ROOT)
    archive = ROOT / 'output/WBCAttPlus_Deployment.zip'
    if not archive.is_file():
        archive = ROOT.parent / 'WBCAttPlus_Deployment.zip'
    manifest_bytes = (ROOT / 'package_manifest.json').read_bytes()
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    checksum_path = ROOT / 'WBCAttPlus_Deployment.sha256'
    if checksum_path.is_file():
        expected, name = checksum_path.read_text(encoding='ascii').strip().split()
        assert name == 'WBCAttPlus_Deployment.zip' and file_sha256(archive) == expected
    with zipfile.ZipFile(archive) as bundle:
        if bundle.testzip():
            raise ValueError('ZIP CRC check failed')
        assert bundle.read('package_manifest.json') == manifest_bytes
        assert bundle.read('WBCAttPlus_Setup.ipynb') == (ROOT / 'WBCAttPlus_Setup.ipynb').read_bytes()
        assert bundle.read('README.md') == (ROOT / 'README.md').read_bytes()
        names = bundle.namelist()
        assert 'scripts/group_split.py' not in names
        assert not any(name.startswith(('restart/', 'tmp/')) for name in names)
        notebook = json.loads(bundle.read('WBCAttPlus_Setup.ipynb'))
        code_cells = [cell for cell in notebook['cells'] if cell['cell_type'] == 'code']
        assert len(code_cells) == 8
        text = '\n'.join(''.join(cell['source']) for cell in code_cells)
        assert ('MANIFEST_SHA256 = ' + repr(manifest_sha)) in text
        assert 'ENABLE_STRICT_SPLIT' not in text and 'import torch' not in text
        assert 'workflow_restart' not in text and 'START_HERE' not in text
        assert 'scripts/run.py' not in text and 'wbc.zip' not in text
        for cell in code_cells:
            assert cell['execution_count'] is None and not cell['outputs']
            ast.parse(''.join(cell['source']), feature_version=(3, 9))
        for name in names:
            if name.startswith(('scripts/', 'tests/')) and name.endswith('.py'):
                source = bundle.read(name).decode('utf-8')
                tree = ast.parse(source, feature_version=(3, 9))
                assert not any(isinstance(node, ast.ImportFrom) and node.module == 'group_split'
                               for node in ast.walk(tree))
    subprocess.run([sys.executable, '-u', '-m', 'unittest', 'discover', '-s', 'tests', '-v'], cwd=ROOT, check=True)
    if args.full:
        parent = ROOT / 'tmp'
        parent.mkdir(exist_ok=True)
        # TemporaryDirectory stays under this exact workspace-owned parent.
        with tempfile.TemporaryDirectory(prefix='check_', dir=str(parent)) as directory:
            project = Path(directory) / 'project'
            unpack_package(archive, project, manifest_sha)
            command = [sys.executable, '-u', str(project / 'scripts/dataset_workflow.py'), 'run',
                       '--project', str(project), '--site', args.site]
            if args.site == 'local':
                command.append('--skip-install')
            if args.no_pdf:
                command.append('--no-pdf')
            subprocess.run(command, check=True)
            state = json.loads((project / 'output/latest_run.json').read_text(encoding='utf-8'))
            result = Path(state['output'])
            summary = json.loads((result / 'audit_summary.json').read_text(encoding='utf-8'))
            assert state['status'] == 'PASS' and state['execution_site'] == args.site
            assert summary['fully_valid_image_mask_pairs'] == 10298
            assert summary['package_scope'] == 'SUPPORTED_ONLY_V2'
            assert summary['source_grouping']['strict_split_created'] is False
            assert all(item['status'] == 'NOT_IMPLEMENTED' for item in summary['not_implemented_features'])
            assert not (result / 'source_groups.template.csv').exists()
            assert (result / '功能范围与限制.md').exists()
            pixels = {row['class_id']: row['pixels'] for row in summary['pixel_area_statistics']}
            assert pixels == {0: 656927964, 1: 86668784, 2: 70669994, 3: 3429022, 4: 515846377, 5: 1078659}
            assert summary['duplicates']['decoded_cross_official_split_groups'] == 6
            print('Fresh full audit: PASS; execution site:', args.site, flush=True)
    print('Current package, imports, Python 3.9 syntax, notebook and tests: PASS', flush=True)


if __name__ == '__main__':
    main()
