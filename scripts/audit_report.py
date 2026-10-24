"""Reproducible Chinese report and standard ReportLab scientific chart."""

import base64
import html
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab import rl_config
from reportlab.graphics import renderPDF, renderSVG
from reportlab.graphics.charts.axes import LogYValueAxis
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

import pypdfium2 as pdfium


INK = colors.HexColor('#17324d')
TEAL = colors.HexColor('#127b85')


def component_chart(report, output):
    rows = sorted(report['pixel_area_statistics'][1:], key=lambda row: -row['pixels'])
    drawing = Drawing(500, 285)
    drawing.add(String(250, 270, 'Five foreground components: global pixel-area share',
                       textAnchor='middle', fontName='Helvetica-Bold', fontSize=12, fillColor=INK))
    drawing.add(String(250, 252, 'Log10 axis; denominator excludes background; bars start at 0.1%',
                       textAnchor='middle', fontSize=9, fillColor=INK))
    chart = VerticalBarChart()
    chart.x, chart.y, chart.width, chart.height = 48, 52, 432, 178
    chart.data = [[float(row['share_foreground_pct']) for row in rows]]
    chart.valueAxis = LogYValueAxis()
    chart.valueAxis.valueMin, chart.valueAxis.valueMax = 0.1, 100
    chart.valueAxis.valueSteps = [0.1, 1, 10, 100]
    chart.valueAxis.labelTextFormat = '%g%%'
    chart.valueAxis.labels.fontSize = 9
    chart.valueAxis.visibleGrid = True
    chart.valueAxis.gridStrokeColor = colors.HexColor('#dce4eb')
    chart.categoryAxis.categoryNames = ['RBCs' if row['component']=='red_blood_cells' else row['component'].capitalize() for row in rows]
    chart.categoryAxis.joinAxisMode = 'bottom'
    chart.categoryAxis.labels.fontSize = 9
    chart.categoryAxis.labels.dy = -7
    chart.bars[0].fillColor = TEAL
    chart.bars[0].strokeColor = None
    chart.barLabelFormat = '%.3f%%'
    chart.barLabels.fontSize = 9
    chart.barLabels.nudge = 6
    drawing.add(chart)
    drawing.add(String(250, 13, 'Total foreground pixels: %s | Sum of five components = 100%%' % format(report['foreground_pixels'], ','),
                       textAnchor='middle', fontSize=9, fillColor=INK))
    renderSVG.drawToFile(drawing, str(output / 'pixel_area_long_tail.svg'))
    document = pdfium.PdfDocument(renderPDF.drawToString(drawing))
    bitmap = document[0].render(scale=2.4)
    bitmap.to_pil().save(output / 'pixel_area_long_tail.png')
    bitmap.close()
    document.close()
    return drawing


def report_markdown(report):
    r, d = report['resolution'], report['duplicates']
    site = '服务器现场执行' if report['execution_site'] == 'server' else '本地执行，不能作为服务器已部署的凭证'
    lines = ['# 显微数据体检单', '', 'WBCAtt+ | 全量解码检查 | %s' % report['created_at_utc'], '',
             '## 结论与边界', '',
             '- 文件与标注完整性：%s；问题数 %s。' % (report['integrity_status'], report['issue_count']),
             '- 执行位置：%s。主机：%s。' % (site, report['hostname']),
             '- 患者／切片独立性：无法验证。官方 CSV 未提供来源 ID，未生成严格划分。',
             '- 官方划分重复泄漏检查：%s 组完全相同图像跨集合，不能视为无泄漏划分。' % d['decoded_cross_official_split_groups'],
             '- “颗粒”属于图像级形态属性，不是官方语义 Mask 类别。', '',
             '## 样本与分辨率', '',
             '图像 %s 张，Mask %s 张；完整有效配对 %s 对。' % tuple(format(report[k], ',') for k in ('image_count', 'mask_count', 'fully_valid_image_mask_pairs')), '',
             '| 指标 | Min | Max | Mean |', '|---|---:|---:|---:|']
    for key, title in [('width', '宽度 / px'), ('height', '高度 / px'), ('area_pixels', '每图像素面积 / px²')]:
        value = r[key]
        lines.append('| %s | %s | %s | %s |' % (title, value['min'], value['max'], value['mean']))
    lines += ['', '空间尺寸指像素矩阵尺寸；未提供显微物理标定，不能推算 μm/px 或真实面积。', '',
              '尺寸分布：' + '；'.join('%s × %s px：%s 张' % (row['width'], row['height'], row['count']) for row in r['distribution']), '',
              '白细胞图像类别（不是 Mask 类别）：' + '；'.join('%s %s' % item for item in report['cell_type_counts'].items()), '',
              '## 5 类前景像素面积长尾', '', '![前景像素面积占比](pixel_area_long_tail.png)', '',
              '逐张解码原始 Mask，按标签 0..5 累加。前景分母为 %s px；全部像素分母为 %s px。' %
              (format(report['foreground_pixels'], ','), format(report['total_valid_pixels'], ',')), '',
              '| 标签 | 组分 | 像素数 | 全像素占比 | 前景占比 | 出现图像数 |',
              '|---:|---|---:|---:|---:|---:|']
    for row in report['pixel_area_statistics']:
        fg = '-' if row['class_id'] == 0 else '%.4f%%' % row['share_foreground_pct']
        lines.append('| %s | %s | %s | %.4f%% | %s | %s |' %
                     (row['class_id'], row['component_cn'], format(row['pixels'], ','), row['share_all_pixels_pct'], fg, row['images_containing']))
    lines += ['', '像素面积占比不是细胞实例数量占比。图中采用对数纵轴，基线为 0.1%，精确比例见表。', '',
              '## 完整性检查', '',
              '检查下载源文件 SHA-256、文件数量、CSV 全覆盖与官方子集一致性、重复标注、图像完整解码、Mask 完整解码、图像与 Mask 尺寸一致、Mask 为二维整数且值域仅 0..5、11 个形态属性非空。', '',
              '逐样本尺寸、哈希、标签像素数：per_image_audit.csv；异常明细：integrity_issues.csv。', '',
              '## 官方划分与重复风险体检（不重新划分）', '',
              '官方图像级划分：' + '；'.join('%s %s' % item for item in report['official_split_counts'].items()) + '。它不等同于患者／切片独立划分。', '',
              '文件级完全重复组 %s；解码 RGB 完全重复组 %s，其中跨官方集合 %s 组。' %
              (d['file_groups'], d['decoded_rgb_groups'], d['decoded_cross_official_split_groups']), '',
              '完全重复组中，图像级细胞类型冲突 %s 组；Mask 文件哈希不一致 %s 组（需人工复核，不自动改标注）。' % (d['conflicting_cell_type_groups'], d['conflicting_mask_groups']), '',
              '64 位 dHash 距离 ≤ %s 的候选对 %s；候选仅供人工复核，不是来源分组依据，也不能证明无泄漏。%s' %
              (d['dhash_radius'], d['dhash_candidate_pairs'], '候选 CSV 截断于前 50,000 对。' if d['dhash_csv_truncated'] else '候选 CSV 未截断。'), '',
              '## 未实现事项及原因（非执行步骤）', '',
              '本包只实现现有官方标注支持的功能，不含严格分组划分入口，也不输出来源映射模板。', '',
              '1. 患者／切片级严格划分：未实现。缺少逐图真实来源映射；需补充数据提供方的脱敏患者／切片 ID 及可追溯出处。不得由文件名、类别或重复聚类猜测。',
              '2. 颗粒像素面积：未实现。官方仅有颗粒图像级属性，没有独立颗粒像素 Mask；需补充有效的逐像素颗粒标注。缺失不记为 0。',
              '3. 物理分辨率与真实面积：未实现。缺少显微 μm/px 标定；仅报告图像宽高和像素个数，不推算 μm/px 或 μm²。', '',
              '**上述功能状态均为 NOT_IMPLEMENTED；strict_split_created=false。这不妨碍支持范围内的文件体检完成。**', '',
              '## 可复现记录', '',
              '- Python：%s；平台：%s。' % (report['python'], report['platform']),
              '- 数据目录：`%s`。' % report['dataset_root'],
              '- 审计脚本 SHA-256：`%s`。' % report['audit_script_sha256'],
              '- 数据文件校验清单：download_manifest.json；审计机器记录：audit_summary.json。',
              '- 统计代码独立编写，不调用作者数据封装；不依赖 GPU、PyTorch 或 MMCV。', '',
              '## 来源', '']
    lines += ['- [%s](%s)' % (source['name'], source['url']) for source in report['sources']]
    return '\n'.join(lines) + '\n'


def make_pdf(report, output, chart):
    font = 'STSong-Light'
    windows_font = Path('C:/Windows/Fonts/msyh.ttc')
    if windows_font.is_file():
        try:
            pdfmetrics.registerFont(TTFont('WBCChinese', str(windows_font), subfontIndex=0))
            font = 'WBCChinese'
        except Exception:
            pdfmetrics.registerFont(UnicodeCIDFont(font))
    else:
        pdfmetrics.registerFont(UnicodeCIDFont(font))
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle('CN', fontName=font, fontSize=9.6, leading=16, textColor=INK, wordWrap='CJK', spaceAfter=9))
    styles.add(ParagraphStyle('CNtitle', parent=styles['CN'], fontSize=25, leading=34, spaceAfter=18))
    styles.add(ParagraphStyle('CNhead', parent=styles['CN'], fontSize=14, leading=23, spaceBefore=12, spaceAfter=10, textColor=TEAL))
    styles.add(ParagraphStyle('CNsmall', parent=styles['CN'], fontSize=8, leading=12))
    def p(text, style='CN'):
        return Paragraph(escape(str(text)), styles[style])
    def table(rows, widths):
        result = Table([[p(value, 'CNsmall') for value in row] for row in rows], colWidths=widths, hAlign='LEFT', repeatRows=1)
        result.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), colors.HexColor('#e6f1f3')),
                                   ('VALIGN', (0,0), (-1,-1), 'TOP'), ('TOPPADDING',(0,0),(-1,-1),7),
                                   ('BOTTOMPADDING',(0,0),(-1,-1),7), ('LINEBELOW',(0,0),(-1,-1),.4,colors.HexColor('#d9e2e9'))]))
        return result
    story = [p('显微数据体检单', 'CNtitle'), p('WBCAtt+ / 文件完整性、像素统计与重复风险体检', 'CNhead'),
             p('生成时间（UTC）：' + report['created_at_utc'], 'CNsmall')]
    site = '服务器现场执行' if report['execution_site'] == 'server' else '本地执行；不是服务器部署验收凭证'
    story += [table([['验收项', '结果'], ['文件与标注完整性', report['integrity_status'] + '；异常 %s 项' % report['issue_count']],
                   ['执行位置', site], ['患者／切片独立性', '无法验证：官方 CSV 无 patient_id / slide_id'],
                   ['官方划分重复泄漏', '未通过：%s 组完全相同图像跨集合' % report['duplicates']['decoded_cross_official_split_groups']],
                   ['严格划分功能', '未实现；仅备注缺少真实来源映射']], [140,355]),
              p('01  样本与空间尺寸', 'CNhead'),
              p('图像 %s 张；Mask %s 张；完整有效配对 %s 对。' % tuple(format(report[k], ',') for k in ('image_count','mask_count','fully_valid_image_mask_pairs')))]
    rows = [['像素矩阵指标', 'Min', 'Max', 'Mean']]
    for key, label in [('width','宽度 / px'),('height','高度 / px'),('area_pixels','每图像素面积 / px²')]:
        values = report['resolution'][key]
        rows.append([label, values['min'], values['max'], values['mean']])
    story += [table(rows, [185,100,100,110]),
              p('尺寸分布：' + '；'.join('%s × %s px，%s 张' % (r['width'],r['height'],r['count']) for r in report['resolution']['distribution'])),
              p('没有显微物理标定，不能由像素尺寸或 JPEG DPI 推算 μm/px。'),
              p('白细胞图像类别：' + '；'.join('%s %s' % x for x in report['cell_type_counts'].items())),
              p('完整性口径', 'CNhead'),
              p('对下载清单逐项计算 SHA-256；逐张验证和完整解码图像与 Mask，检查配对、尺寸、二维整数标签值域 0..5、CSV 全覆盖及官方子集一致性、重复标注与 11 个属性非空。统计直接来自本次文件解码，不读取旧体检结果。'),
              PageBreak(), p('02  五类前景像素面积长尾', 'CNtitle'), chart,
              p('背景不属于五类前景。前景分母 %s px；全部像素分母 %s px。图的对数轴从 0.1%% 开始，不能按柱高线性比较比例。' %
                (format(report['foreground_pixels'], ','),format(report['total_valid_pixels'], ',')))]
    rows = [['ID / 组分', '像素数', '全像素 %', '前景 %', '出现图像']]
    for row in report['pixel_area_statistics']:
        rows.append(['%s / %s' % (row['class_id'],row['component_cn']), format(row['pixels'],','),
                     '%.4f' % row['share_all_pixels_pct'], '-' if not row['class_id'] else '%.4f' % row['share_foreground_pct'], row['images_containing']])
    story += [table(rows,[115,125,85,85,85]),p('关键解释', 'CNhead'),
              p('“颗粒”只在图像级形态属性中出现，官方语义 Mask 没有颗粒类。实际五类为细胞质、细胞核、血小板、红细胞、空泡。'),
              p('这里统计的是像素面积，不是细胞实例数量。空泡和血小板为稀有前景；是否采用类别权重或采样策略应仅依据训练集统计，不能用测试标签调参。'),
              PageBreak(), p('03  来源独立性与复现记录', 'CNtitle')]
    d = report['duplicates']
    story += [p('官方图像级划分：'+'；'.join('%s %s' % x for x in report['official_split_counts'].items())+'。患者／切片独立性未得到证实。'),
              p('文件级重复 %s 组；解码 RGB 重复 %s 组，其中跨官方集合 %s 组。dHash 距离 ≤ %s 的候选 %s 对，仅供复核，不能作为患者／切片标识。' %
                (d['file_groups'],d['decoded_rgb_groups'],d['decoded_cross_official_split_groups'],d['dhash_radius'],d['dhash_candidate_pairs'])),
              p('重复组中，图像级细胞类型冲突 %s 组；Mask 文件哈希不一致 %s 组。需人工复核，未自动删除或改标注。文件完整性通过不表示标注语义与来源独立性通过。' % (d['conflicting_cell_type_groups'],d['conflicting_mask_groups'])),
              p('未实现事项及原因（仅备注）','CNhead'),
              p('1. 患者／切片级严格划分：未实现。官方缺少逐图真实来源 ID；需要数据提供方的完整、可追溯映射。本包无分组划分器或执行开关，不输出来源模板、不生成新的 train/val/test。'),
              p('2. 颗粒像素面积：未实现。颗粒只有图像级属性，无独立颗粒 Mask；需要补充逐像素标注。缺失不能记为 0，图中只展示五类实际前景。'),
              p('3. 物理分辨率与真实面积：未实现。缺少显微 μm/px 标定，只报告像素单位，不从 JPEG DPI 换算。以上状态为 NOT_IMPLEMENTED，不影响已支持项目的完整性验收。'),
              p('可复现证据','CNhead'),
              p('逐图尺寸／标签像素数／哈希：per_image_audit.csv；像素比例：pixel_area_statistics.csv；异常：integrity_issues.csv；重复：exact_duplicate_groups.json、near_duplicate_candidates.csv；未实现备注：功能范围与限制.md、audit_summary.json。','CNsmall'),
              p('主机：%s；Python：%s；执行位置：%s。' % (report['hostname'],report['python'],report['execution_site']),'CNsmall'),
              p('数据目录：'+report['dataset_root'],'CNsmall'),
              p('审计脚本 SHA-256：'+report['audit_script_sha256'],'CNsmall'),
              p('来源','CNhead')]
    for source in report['sources']:
        story.append(Paragraph('<link href="%s">%s</link>' % (escape(source['url'], {'"':'&quot;'}),escape(source['name'])),styles['CNsmall']))
    def footer(canvas, doc):
        canvas.setStrokeColor(colors.HexColor('#d9e2e9'))
        canvas.line(50,43,545,43)
        canvas.setFont(font,8)
        canvas.setFillColor(INK)
        canvas.drawString(50,29,'WBCAtt+ | 数据完整性不等于患者／切片独立性')
        canvas.drawRightString(545,29,str(doc.page))
    document = SimpleDocTemplate(str(output/'显微数据体检单.pdf'),pagesize=A4,rightMargin=50,leftMargin=50,topMargin=43,bottomMargin=58,
                                 title='WBCAtt+ 显微数据体检单',author='Independent dataset audit')
    document.build(story,onFirstPage=footer,onLaterPages=footer)


def make_reports(report, output, with_pdf=True):
    output = Path(output)
    chart = component_chart(report,output)
    markdown = report_markdown(report)
    (output/'显微数据体检单.md').write_text(markdown,encoding='utf-8')
    # A self-contained, offline-readable companion without markdown dependencies.
    encoded = base64.b64encode((output/'pixel_area_long_tail.png').read_bytes()).decode('ascii')
    body = html.escape(markdown.replace('![前景像素面积占比](pixel_area_long_tail.png)', ''))
    document = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>显微数据体检单</title><style>body{max-width:1040px;margin:40px auto;padding:0 24px;color:#17324d;background:#f6f9fc;font:16px/1.8 system-ui}pre{white-space:pre-wrap;overflow-wrap:anywhere}img{width:100%;background:white}</style><h1>WBCAtt+ 显微数据体检单</h1><img alt="5类前景像素面积占比" src="data:image/png;base64,'+encoded+'"><pre>'+body+'</pre></html>'
    (output/'显微数据体检单.html').write_text(document,encoding='utf-8')
    if with_pdf:
        make_pdf(report,output,chart)
