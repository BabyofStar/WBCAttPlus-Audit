"""Independently written, streaming WBCAtt+ data examination (Python >= 3.9).

Computes statistics from decoded files, never from a precomputed report.
No torch/mmcv/CUDA, dataset wrapper, or sklearn split helper is required.
Scope: only released pixel masks and image dimensions. No source split,
granule-pixel estimate, or physical-unit conversion is implemented.
"""

import argparse
import csv
import hashlib
import json
import platform
import socket
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageFile

from audit_utils import digest_file, read_csv, write_csv
from audit_scope import PACKAGE_SCOPE, IMPLEMENTED_FEATURES, not_implemented_features, write_scope_notes


ImageFile.LOAD_TRUNCATED_IMAGES = False
CLASSES = ("background", "cytoplasm", "nucleus", "platelets", "red_blood_cells", "vacuoles")
CN_CLASSES = ("背景", "细胞质", "细胞核", "血小板", "红细胞", "空泡")
ATTRIBUTES = ("cell_size", "cell_shape", "nucleus_shape", "nuclear_cytoplasmic_ratio",
              "chromatin_density", "cytoplasm_vacuole", "cytoplasm_texture",
              "cytoplasm_colour", "granule_type", "granule_colour", "granularity")
ARCHIVE_SHA256 = "2a1730ce3a772e34bd1089b1aec44597e75b94ab0d26fbe697cb1189a9155090"
SOURCES = [
    {"name": "WBCAtt+ official release", "url": "https://huggingface.co/datasets/apple2373/wbcattplus"},
    {"name": "WBCAtt+ code and raw mask format", "url": "https://github.com/apple2373/wbcattplus"},
    {"name": "WBCAtt+ paper, official image split", "url": "https://arxiv.org/html/2605.19692v1"},
    {"name": "Original PBC release", "url": "https://data.mendeley.com/datasets/snkd93bnjr/1"},
]


def add_issue(issues, name, kind, details):
    issues.append({"img_name": name, "kind": kind, "details": str(details)})


def dimension_summary(values):
    if not values:
        return {"min": None, "max": None, "mean": None}
    return {"min": int(min(values)), "max": int(max(values)), "mean": float(sum(values) / len(values))}


_popcount = int.bit_count if hasattr(int, "bit_count") else lambda value: bin(value).count("1")


def difference_hash(image):
    """64-bit horizontal dHash, a review aid, never a patient/slide identifier."""
    pixels = np.asarray(image.convert("L").resize((9, 8), Image.Resampling.BILINEAR))
    value = 0
    for bit in (pixels[:, 1:] > pixels[:, :-1]).flat:
        value = (value << 1) | int(bit)
    return value


class HashTree:
    """A small original BK tree for bounded Hamming-distance candidate search."""

    def __init__(self):
        self.root = None

    def add(self, value, name):
        node = self.root
        if node is None:
            self.root = [value, [name], {}]
            return
        while True:
            distance = _popcount(value ^ node[0])
            if distance == 0:
                node[1].append(name)
                return
            child = node[2].get(distance)
            if child is None:
                node[2][distance] = [value, [name], {}]
                return
            node = child

    def query(self, value, radius):
        pending = [self.root] if self.root is not None else []
        while pending:
            node = pending.pop()
            distance = _popcount(value ^ node[0])
            if distance <= radius:
                for name in node[1]:
                    yield name, distance
            pending.extend(child for edge, child in node[2].items()
                           if distance - radius <= edge <= distance + radius)


def duplicate_groups(rows, field):
    groups = defaultdict(list)
    for row in rows:
        if row.get(field):
            groups[row[field]].append(row)
    result = []
    for value, members in groups.items():
        if len(members) > 1:
            splits = sorted({row["official_split"] for row in members})
            result.append({"hash": value, "images": [row["img_name"] for row in members],
                           "official_splits": splits, "cross_official_split": len(splits) > 1,
                           "cell_type_labels": sorted({row["label"] for row in members}),
                           "conflicting_cell_type_labels": len({row["label"] for row in members}) > 1,
                           "distinct_mask_sha256": sorted({row["mask_sha256"] for row in members}),
                           "conflicting_masks": len({row["mask_sha256"] for row in members}) > 1})
    return result


def check_downloads(root, issues):
    checked = []
    manifest_path = root / "download_manifest.json"
    if not manifest_path.is_file():
        add_issue(issues, "", "source_manifest_missing", manifest_path)
        return checked
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for asset in manifest["assets"]:
        relative = Path(asset["path"])
        if relative.is_absolute() or ".." in relative.parts:
            add_issue(issues, "", "unsafe_manifest_path", str(relative))
            continue
        path = root / relative
        valid = path.is_file() and path.stat().st_size == asset["size_bytes"]
        actual = digest_file(path) if path.is_file() else None
        valid = valid and actual == asset["sha256"]
        if relative.name == "pbcseg_final_v1.tar":
            valid = valid and actual == ARCHIVE_SHA256
        checked.append({"path": relative.as_posix(), "status": "PASS" if valid else "FAIL", "sha256": actual})
        if not valid:
            add_issue(issues, "", "download_checksum", relative.as_posix())
    return checked


def examine(root, output, site="local", near_radius=3):
    issues = []
    output.mkdir(parents=True, exist_ok=True)
    checked = check_downloads(root, issues)
    print("Verified official download assets:", len(checked), flush=True)
    annotation_path = root / "dataset_txt" / "pbc_attr_v1_ccrop_all.csv"
    annotations = read_csv(annotation_path)
    if not annotations:
        raise ValueError("Empty annotation file")
    by_name = {row["img_name"]: row for row in annotations}
    if len(by_name) != len(annotations):
        add_issue(issues, "", "duplicate_annotation_filename", len(annotations) - len(by_name))
    if len(annotations) != 10298:
        add_issue(issues, "", "official_release_count", "Expected 10298, got %d" % len(annotations))
    image_dir = root / "data" / "PBC" / "pbcseg_final_v1"
    if not image_dir.is_dir():
        raise ValueError("Image directory missing; run scripts/dataset_workflow.py extract first: %s" % image_dir)
    image_files = {path.name: path for path in image_dir.iterdir()
                   if path.is_file() and path.suffix.lower() in (".jpg", ".jpeg")}
    mask_files = {path.name: path for path in image_dir.iterdir()
                  if path.is_file() and path.name.endswith("_mask.png")}
    expected_masks = {Path(name).stem + "_mask.png" for name in by_name}
    for name in sorted(set(by_name) - set(image_files)):
        add_issue(issues, name, "missing_image", "Annotation has no JPEG")
    for name in sorted(set(image_files) - set(by_name)):
        add_issue(issues, name, "unannotated_image", "JPEG has no annotation")
    for name in sorted(expected_masks - set(mask_files)):
        add_issue(issues, name, "missing_mask", "Image has no segmentation mask")
    for name in sorted(set(mask_files) - expected_masks):
        add_issue(issues, name, "orphan_mask", "Mask has no annotated image")
    official_counts = Counter(row.get("split", "") for row in annotations)
    for split in ("train", "val", "test"):
        rows = read_csv(root / "dataset_txt" / ("pbc_attr_v1_ccrop_%s.csv" % split))
        subset = {row["img_name"]: row for row in annotations if row.get("split") == split}
        if len({row["img_name"] for row in rows}) != len(rows) or {row["img_name"]: row for row in rows} != subset:
            add_issue(issues, "", "official_split_mismatch", split)
    if set(official_counts) != {"train", "val", "test"}:
        add_issue(issues, "", "unexpected_official_splits", dict(official_counts))

    pixels = np.zeros(6, dtype=np.int64)
    containing = np.zeros(6, dtype=np.int64)
    resolution_counts = Counter()
    image_modes, mask_modes = Counter(), Counter()
    records = []
    for index, name in enumerate(sorted(by_name), 1):
        row = by_name[name]
        record = {"img_name": name, "label": row.get("label", ""), "official_split": row.get("split", ""),
                  "status": "FAIL", "error": "", "width": "", "height": "", "area_pixels": "",
                  "mask_width": "", "mask_height": "", "image_mode": "", "mask_mode": "",
                  "file_sha256": "", "decoded_rgb_sha256": "", "mask_sha256": "", "dhash64": ""}
        record.update({"pixels_%d" % label: "" for label in range(6)})
        try:
            if row.get("path") != name or Path(name).name != name:
                raise ValueError("Unexpected image path")
            if any(not row.get(attribute) for attribute in ATTRIBUTES):
                raise ValueError("Missing one or more of the 11 morphological attributes")
            image_path = image_files[name]
            mask_path = mask_files[Path(name).stem + "_mask.png"]
            with Image.open(image_path) as probe:
                probe.verify()
            with Image.open(image_path) as image:
                image.load()
                size = image.size
                original_mode = image.mode
                rgb = np.asarray(image.convert("RGB"))
                visual_hash = difference_hash(image)
            with Image.open(mask_path) as probe:
                probe.verify()
            with Image.open(mask_path) as mask:
                mask.load()
                mask_size = mask.size
                mask_mode = mask.mode
                array = np.asarray(mask)
            if mask_size != size:
                raise ValueError("Image/mask dimensions differ: %s vs %s" % (size, mask_size))
            if array.ndim != 2 or not np.issubdtype(array.dtype, np.integer):
                raise ValueError("Mask must be a 2D array of integer class indices")
            if int(array.min()) < 0 or int(array.max()) > 5:
                raise ValueError("Mask contains labels outside 0..5")
            counts = np.bincount(array.ravel().astype(np.int64), minlength=6)
            if int(counts.sum()) != size[0] * size[1]:
                raise ValueError("Mask histogram area mismatch")
            pixels += counts
            containing += counts > 0
            resolution_counts[size] += 1
            image_modes[original_mode] += 1
            mask_modes[mask_mode] += 1
            content_digest = hashlib.sha256()
            content_digest.update(("RGB:%dx%d\0" % size).encode("ascii"))
            content_digest.update(rgb.tobytes())
            record.update(status="PASS", width=size[0], height=size[1], area_pixels=size[0] * size[1],
                          mask_width=mask_size[0], mask_height=mask_size[1], image_mode=original_mode,
                          mask_mode=mask_mode, file_sha256=digest_file(image_path),
                          decoded_rgb_sha256=content_digest.hexdigest(), mask_sha256=digest_file(mask_path),
                          dhash64="%016x" % visual_hash)
            record.update({"pixels_%d" % label: int(counts[label]) for label in range(6)})
        except Exception as error:
            record["error"] = "%s: %s" % (type(error).__name__, error)
            add_issue(issues, name, "image_mask_or_attribute_validation", record["error"])
        records.append(record)
        if index % 2000 == 0:
            print("Decoded and fingerprinted %d/%d pairs" % (index, len(by_name)), flush=True)

    write_csv(output / "per_image_audit.csv", records, list(records[0]))
    write_csv(output / "integrity_issues.csv", issues, ("img_name", "kind", "details"))
    resolutions = [{"width": size[0], "height": size[1], "area_pixels": size[0] * size[1], "count": count}
                   for size, count in sorted(resolution_counts.items())]
    write_csv(output / "resolution_distribution.csv", resolutions, ("width", "height", "area_pixels", "count"))
    valid = [row for row in records if row["status"] == "PASS"]
    total_pixels, foreground_pixels = int(pixels.sum()), int(pixels[1:].sum())
    component_rows = []
    for label, name in enumerate(CLASSES):
        component_rows.append({"class_id": label, "component": name, "component_cn": CN_CLASSES[label],
                               "pixels": int(pixels[label]), "share_all_pixels_pct": 100 * int(pixels[label]) / total_pixels if total_pixels else 0,
                               "share_foreground_pct": 100 * int(pixels[label]) / foreground_pixels if label and foreground_pixels else "",
                               "images_containing": int(containing[label]),
                               "image_prevalence_pct": 100 * int(containing[label]) / len(valid) if valid else 0})
    write_csv(output / "pixel_area_statistics.csv", component_rows, list(component_rows[0]))
    file_duplicates = duplicate_groups(records, "file_sha256")
    pixel_duplicates = duplicate_groups(records, "decoded_rgb_sha256")
    (output / "exact_duplicate_groups.json").write_text(json.dumps(
        {"encoded_file": file_duplicates, "decoded_rgb": pixel_duplicates}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Exact duplicate groups:", len(pixel_duplicates), "Searching perceptual candidates...", flush=True)
    tree, candidates, near_count = HashTree(), [], 0
    valid_by_name = {row["img_name"]: row for row in valid}
    for row in valid:
        value = int(row["dhash64"], 16)
        for other_name, distance in tree.query(value, near_radius):
            near_count += 1
            if len(candidates) < 50000:
                other = valid_by_name[other_name]
                candidates.append({"image_a": other_name, "image_b": row["img_name"], "hamming_distance": distance,
                                   "split_a": other["official_split"], "split_b": row["official_split"],
                                   "cross_official_split": other["official_split"] != row["official_split"],
                                   "identical_rgb": other["decoded_rgb_sha256"] == row["decoded_rgb_sha256"]})
        tree.add(value, row["img_name"])
    write_csv(output / "near_duplicate_candidates.csv", candidates,
              ("image_a", "image_b", "hamming_distance", "split_a", "split_b", "cross_official_split", "identical_rgb"))
    # 来源 ID 不存在：只记录缺失，不输出模板、伪 ID 或任何新的划分文件。
    write_scope_notes(output / "功能范围与限制.md")
    grouping = {
        "status": "UNVERIFIABLE_MISSING_SOURCE_IDS", "strict_split_created": False,
        "implementation_status": "NOT_IMPLEMENTED_IN_THIS_PACKAGE",
        "available_annotation_columns": list(annotations[0]),
        "patient_id_available": "patient_id" in annotations[0], "slide_id_available": "slide_id" in annotations[0],
        "reason": "Released CSV has no patient_id/slide_id. Filename prefixes and numeric suffixes are not validated source groups.",
        "required_source_fields": ["img_name", "patient_id and/or globally unique slide_id", "source_reference"],
        "note": "Only existing official image-level splits are counted. No new split or source identity is generated.",
        "official_split_scope": "Image-level benchmark split; patient/slide independence is unverified",
        "anti_leakage_caveat": "No exact or perceptual duplicates does not prove patient/slide independence.",
    }
    report = {
        "dataset": "WBCAtt+", "audit_schema": "2.0", "package_scope": PACKAGE_SCOPE,
        "implemented_features": list(IMPLEMENTED_FEATURES),
        "not_implemented_features": not_implemented_features(),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "execution_site": site, "hostname": socket.gethostname(), "platform": platform.platform(),
        "python": sys.version.split()[0], "dataset_root": str(root), "audit_script_sha256": digest_file(__file__),
        "integrity_status": "PASS" if not issues else "FAIL", "issue_count": len(issues),
        "official_split_leakage_status": "FAIL_EXACT_DUPLICATE_CROSS_SPLIT" if any(g["cross_official_split"] for g in pixel_duplicates) else "NO_EXACT_CROSS_SPLIT_DUPLICATES_FOUND_SOURCE_INDEPENDENCE_UNVERIFIED",
        "source_asset_checks": checked, "expected_release_images": 10298,
        "annotation_count": len(annotations), "image_count": len(image_files), "mask_count": len(mask_files),
        "fully_valid_image_mask_pairs": len(valid), "image_modes": dict(image_modes), "mask_modes": dict(mask_modes),
        "resolution": {"definition": "Image matrix width/height in pixels, not physical microns per pixel",
                       "physical_calibration": "NOT_PROVIDED; JPEG DPI is not microscopy calibration",
                       "width": dimension_summary([row["width"] for row in valid]),
                       "height": dimension_summary([row["height"] for row in valid]),
                       "area_pixels": dimension_summary([row["area_pixels"] for row in valid]), "distribution": resolutions},
        "cell_type_counts": dict(sorted(Counter(row["label"] for row in annotations).items())),
        "official_split_counts": dict(official_counts), "total_valid_pixels": total_pixels,
        "foreground_pixels": foreground_pixels, "pixel_area_statistics": component_rows,
        "pixel_statistic_definition": "Sum mask pixels across fully valid pairs. Foreground denominator excludes class 0; all-pixel denominator includes class 0. Pixel area is not instance count or physical area.",
        "granule_note": "Granules are image-level attributes only; released semantic masks have no granule class.",
        "duplicates": {"file_groups": len(file_duplicates), "decoded_rgb_groups": len(pixel_duplicates),
                       "decoded_cross_official_split_groups": sum(group["cross_official_split"] for group in pixel_duplicates),
                       "conflicting_cell_type_groups": sum(group["conflicting_cell_type_labels"] for group in pixel_duplicates),
                       "conflicting_mask_groups": sum(group["conflicting_masks"] for group in pixel_duplicates),
                       "dhash_radius": near_radius, "dhash_candidate_pairs": near_count,
                       "dhash_csv_truncated": near_count > 50000,
                       "dhash_interpretation": "Screening candidates only; require review. Never used as source identities."},
        "source_grouping": grouping, "sources": SOURCES,
        "server_deployment_verification": "RUN_ON_SERVER" if site == "server" else "NOT_VERIFIED_FROM_LOCAL_AUDIT",
    }
    (output / "audit_summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    project = Path(__file__).resolve().parents[1]
    parser.add_argument("--root", type=Path, default=project / "datasets" / "WBCAttPlus")
    parser.add_argument("--output", type=Path, default=project / "output" / "pdf" / "wbcattplus_audit")
    parser.add_argument("--site", choices=("local", "server"), default="local")
    parser.add_argument("--near-radius", type=int, choices=range(0, 5), default=3)
    parser.add_argument("--no-pdf", action="store_true")
    args = parser.parse_args()
    report = examine(args.root.absolute(), args.output.absolute(), args.site, args.near_radius)
    from audit_report import make_reports
    make_reports(report, args.output.absolute(), with_pdf=not args.no_pdf)
    print(json.dumps({key: report[key] for key in ("integrity_status", "image_count", "mask_count",
          "fully_valid_image_mask_pairs", "resolution", "duplicates", "source_grouping")}, ensure_ascii=False, indent=2), flush=True)
    if report["integrity_status"] != "PASS":
        sys.exit(2)


if __name__ == "__main__":
    main()
