"""WBCAtt+ 可实现范围；缺少前提的功能只备注，不提供执行入口。

患者/切片划分、颗粒像素面积、物理尺度均不得用猜测、零值或伪造 ID 补齐。
"""

from copy import deepcopy
from pathlib import Path


PACKAGE_SCOPE = 'SUPPORTED_ONLY_V2'
IMPLEMENTED_FEATURES = [
    'official_asset_checksums_and_safe_extraction',
    'full_image_mask_decode_and_pair_integrity',
    'image_count_and_pixel_dimension_distribution_min_max_mean',
    'five_official_foreground_components_pixel_area_and_long_tail_chart',
    'official_split_counts_and_duplicate_risk_screening',
    'chinese_pdf_html_markdown_reports_and_execution_receipt',
]
_NOT_IMPLEMENTED = [
    {'feature': 'strict_patient_or_slide_split', 'status': 'NOT_IMPLEMENTED',
     'reason': 'Official CSV has no verified patient_id/slide_id mapping.',
     'reason_cn': '官方 CSV 缺少真实患者/切片来源映射，无法生成或证明来源互斥划分。',
     'required_data': 'Complete image-to-anonymized-patient/slide mapping with traceable provenance.'},
    {'feature': 'granule_pixel_area', 'status': 'NOT_IMPLEMENTED',
     'reason': 'Granules are image-level attributes, not a released mask class.',
     'reason_cn': '颗粒仅有图像级属性，没有独立像素 Mask，不能统计颗粒像素面积。',
     'required_data': 'Validated per-pixel granule segmentation annotations.'},
    {'feature': 'physical_resolution_and_area', 'status': 'NOT_IMPLEMENTED',
     'reason': 'No microscopy calibration in micrometers per pixel is supplied.',
     'reason_cn': '缺少显微物理标定，不能从图像宽高或 JPEG DPI 推算 μm/px、μm²。',
     'required_data': 'Traceable microscopy calibration for each acquisition/image.'},
]

SCOPE_NOTES = '''# 功能范围与限制（SUPPORTED_ONLY_V2）

## 本包实际执行

- 官方资产 SHA-256 校验、安全解压；保留原始图像、Mask 和官方 CSV。
- 全量图像/Mask 完整解码、配对、尺寸、整数标签 0..5、CSV 与属性字段检查。
- 图像样本总量、宽/高/每图像素数的 Min / Max / Mean 和尺寸分布。
- 五类官方前景：细胞质、细胞核、血小板、红细胞、空泡。
- 逐像素面积计数、全部像素/前景像素占比及长尾柱状图。
- 官方 train/val/test 数量与精确重复跨集合检查、近似重复候选筛查。
- 中文 PDF/HTML/Markdown 体检单、CSV/JSON 明细与本次执行回执。

## 仅备注、不实现的功能

1. 患者/切片级严格划分：NOT_IMPLEMENTED。
   原因：官方 CSV 无真实患者/切片来源映射。本包不含分组划分器、执行开关或空白映射模板，
   不新建 train/val/test，不从文件名、类别、重复聚类或 dHash 猜测来源 ID。
   需要补充：覆盖全部图像、由数据提供方提供的脱敏患者/切片 ID 及可追溯出处。
   仅有切片 ID 也不能同时证明患者独立；删除重复图不等于切片无泄漏。

2. 颗粒像素面积：NOT_IMPLEMENTED。
   原因：颗粒只有图像级属性，没有独立颗粒像素 Mask。不输出颗粒面积，也不用 0 充当缺失值。
   需要补充：经过验证的逐像素颗粒分割标注。

3. 物理分辨率与物理面积：NOT_IMPLEMENTED。
   原因：未提供显微 μm/px 标定。仅报告 px 和像素个数；不换算 μm/px 或 μm²。
   需要补充：与采集图像对应的显微标定记录；JPEG DPI 不能替代该记录。

## 结果解释

文件完整性 PASS 不代表官方划分无泄漏，也不代表上述未实现功能已完成。
官方 CSV 的 split 只作为既有图像级划分被统计，不会被重新划分或改写。
近似重复候选仅供人工复核；未发现重复也不能证明患者/切片独立。
本包不自动删除重复图、不改标注、不训练模型，也不宣称论文全部复现。
缺少标注/元数据是数据本身的限制，不是安装失败；当前支持范围内的体检仍可完成。
'''


def not_implemented_features():
    return deepcopy(_NOT_IMPLEMENTED)


def write_scope_notes(path):
    Path(path).write_text(SCOPE_NOTES, encoding='utf-8')
