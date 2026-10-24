"""Synthetic tests of supported statistics, integrity checks and scope limits."""

import hashlib
import random
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from audit_utils import read_csv, write_csv, digest_file
from audit_scope import PACKAGE_SCOPE, SCOPE_NOTES, not_implemented_features
from dataset_audit import ATTRIBUTES, CLASSES, HashTree, dimension_summary, examine
from audit_report import report_markdown
from dataset_extract import safe_relative


class SupportedStatisticsTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / 'tmp/tests'
        parent.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=str(parent))
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def fixture(self, bad_label=False, missing_mask=False):
        root = self.root / 'dataset'
        annotations = root / 'dataset_txt'
        images = root / 'data/PBC/pbcseg_final_v1'
        annotations.mkdir(parents=True)
        images.mkdir(parents=True)
        (root / 'download_manifest.json').write_text('{"assets":[]}', encoding='utf-8')
        rows = []
        for index, split in enumerate(('train', 'val', 'test')):
            name = 'synthetic_%d.jpg' % index
            row = dict(img_name=name, label='synthetic_cell', path=name, split=split)
            row.update({attribute: 'synthetic' for attribute in ATTRIBUTES})
            rows.append(row)
            Image.new('RGB', (3, 2), (30, 50, 70)).save(images / name)
            mask = np.array([[0, 1, 2], [3, 4, 5]], dtype=np.uint8)
            if index == 0 and bad_label:
                mask[0, 0] = 6
            if not (index == 0 and missing_mask):
                Image.fromarray(mask).save(images / (Path(name).stem + '_mask.png'))
            write_csv(annotations / ('pbc_attr_v1_ccrop_%s.csv' % split), [row], list(row))
        write_csv(annotations / 'pbc_attr_v1_ccrop_all.csv', rows, list(rows[0]))
        return root

    def test_dimension_summary(self):
        self.assertEqual(dimension_summary([2, 4, 9]), {'min': 2, 'max': 9, 'mean': 5.0})

    def test_empty_dimension_summary_is_missing_not_zero(self):
        self.assertEqual(dimension_summary([]), {'min': None, 'max': None, 'mean': None})

    def test_bktree_matches_brute_force_with_collisions(self):
        randomizer = random.Random(123)
        values = [randomizer.getrandbits(16) for _ in range(120)] + [0, 0, 1]
        tree = HashTree()
        for index, value in enumerate(values):
            expected = {(str(i), bin(value ^ other).count('1')) for i, other in enumerate(values[:index])
                        if bin(value ^ other).count('1') <= 3}
            self.assertEqual(set(tree.query(value, 3)), expected)
            tree.add(value, str(index))

    def test_unsafe_archive_paths_rejected(self):
        for name in ('../outside', '/absolute', 'C:/absolute', 'a\\b'):
            with self.assertRaises(ValueError):
                safe_relative(name)

    def test_csv_and_hash_helpers(self):
        path = self.root / 'table.csv'
        write_csv(path, [{'name': '细胞核', 'count': 3}], ['name', 'count'])
        self.assertEqual(read_csv(path), [{'name': '细胞核', 'count': '3'}])
        self.assertEqual(digest_file(path), hashlib.sha256(path.read_bytes()).hexdigest())

    def test_five_actual_foreground_classes_exclude_granules(self):
        self.assertEqual(CLASSES[1:], ('cytoplasm', 'nucleus', 'platelets', 'red_blood_cells', 'vacuoles'))
        self.assertNotIn('granules', CLASSES)

    def test_unimplemented_metadata_is_explicit_and_independent(self):
        features = not_implemented_features()
        self.assertEqual({row['feature'] for row in features},
                         {'strict_patient_or_slide_split', 'granule_pixel_area', 'physical_resolution_and_area'})
        self.assertTrue(all(row['status'] == 'NOT_IMPLEMENTED' and row['reason_cn'] and row['required_data'] for row in features))
        features[0]['status'] = 'fake-pass'
        self.assertEqual(not_implemented_features()[0]['status'], 'NOT_IMPLEMENTED')

    def test_scope_notes_include_all_three_reasons(self):
        for phrase in ('患者/切片', '颗粒像素', '显微', 'NOT_IMPLEMENTED'):
            self.assertIn(phrase, SCOPE_NOTES)

    def test_small_fixture_decodes_and_counts_pixels_without_creating_splits(self):
        output = self.root / 'result'
        report = examine(self.fixture(), output)
        self.assertEqual(report['fully_valid_image_mask_pairs'], 3)
        self.assertEqual(report['resolution']['width'], {'min': 3, 'max': 3, 'mean': 3.0})
        self.assertEqual(report['total_valid_pixels'], 18)
        self.assertEqual(report['foreground_pixels'], 15)
        self.assertTrue(all(row['pixels'] == 3 for row in report['pixel_area_statistics']))
        self.assertTrue(all(row['share_foreground_pct'] == 20 for row in report['pixel_area_statistics'][1:]))
        self.assertEqual(report['issue_count'], 1)  # only the intentionally small release count
        self.assertEqual(report['package_scope'], PACKAGE_SCOPE)
        self.assertFalse(report['source_grouping']['strict_split_created'])
        self.assertFalse((output / 'source_groups.template.csv').exists())
        self.assertTrue((output / '功能范围与限制.md').exists())
        self.assertEqual(report['official_split_leakage_status'], 'FAIL_EXACT_DUPLICATE_CROSS_SPLIT')
        for split in ('train', 'val', 'test'):
            self.assertFalse((output / (split + '.csv')).exists())

    def test_invalid_mask_label_is_not_silently_counted(self):
        report = examine(self.fixture(bad_label=True), self.root / 'bad_result')
        self.assertEqual(report['fully_valid_image_mask_pairs'], 2)
        self.assertEqual(report['integrity_status'], 'FAIL')

    def test_missing_mask_is_reported(self):
        output = self.root / 'missing_result'
        examine(self.fixture(missing_mask=True), output)
        self.assertIn('missing_mask', {row['kind'] for row in read_csv(output / 'integrity_issues.csv')})

    def test_report_notes_have_no_executable_future_split_instructions(self):
        report = examine(self.fixture(), self.root / 'report_result')
        text = report_markdown(report)
        self.assertIn('未实现事项及原因', text)
        self.assertIn('颗粒像素面积：未实现', text)
        self.assertIn('物理分辨率与真实面积：未实现', text)
        self.assertNotIn('seed=123', text)
        self.assertNotIn('source_groups.template.csv', text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
