"""Build a single self-contained data + Linux wheel + notebook delivery ZIP."""

import ast
import argparse
import hashlib
import json
import os
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = 'WBCAttPlus_Deployment.zip'
sys.path.insert(0, str(ROOT / 'scripts'))
from audit_scope import PACKAGE_SCOPE, write_scope_notes


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def notebook(manifest_sha):
    cells = []

    def markdown(text):
        cells.append({'cell_type': 'markdown', 'metadata': {}, 'source': text.splitlines(keepends=True)})

    def code(text):
        ast.parse(text, feature_version=(3, 9))
        cells.append({'cell_type': 'code', 'metadata': {}, 'execution_count': None,
                      'outputs': [], 'source': text.splitlines(keepends=True)})

    markdown('''# WBCAtt+：现阶段可实现功能（SUPPORTED_ONLY_V2）

请先阅读同包 `GitHub_部署指南.md`。代码用 Git 克隆，完整数据包从同一版本的 GitHub Release 下载到服务器 `/home/jovyan/work/`，无需通过 JupyterLab 上传大文件。本 Notebook 可留在 Windows，用 VS Code 选择已连接的 **Python (wbcattplus server)** 远程内核执行。

逐格按 Shift+Enter，等上一格结束再运行下一格。红色报错立即停止。请先在服务器终端下载 Release 中的完整 ZIP 并核对 SHA-256；Git clone 本身不含数据与离线依赖。本流程不重装 PyTorch/CUDA，不做训练。

**功能边界：** 本包仅部署数据、校验完整性、统计像素尺寸和五类实际前景面积、检查官方集合重复风险并输出报告。患者/切片严格划分、颗粒像素面积及物理单位换算均不实现，仅备注原因。没有第 9 步执行开关。''')
    markdown('## 第 1 步：确认远程内核与既有环境（只检查）')
    code('''import sys
import platform
from pathlib import Path

print("System:", platform.system(), platform.machine())
print("Python:", sys.version.split()[0])
print("Executable:", sys.executable)
assert platform.system() == "Linux", "请选择服务器内核，不是 Windows 本地内核"
assert platform.machine().lower() in ("x86_64", "amd64")
assert sys.version_info[:2] == (3, 9), "请选择 wbcattplus，不是 base Python 3.13"
assert Path(sys.prefix).resolve() == Path("/home/jovyan/work/envs/wbcattplus").resolve(), "环境不对，请更换内核"

UPLOAD = Path("/home/jovyan/work/WBCAttPlus_Deployment.zip")
PROJECT = Path("/home/jovyan/work/WBCAttPlus_workspace")

# 本次任务全程 CPU：不导入 torch、不做 GPU 检查、不训练模型。
print("Supported-only audit uses CPU; GPU/PyTorch are not required.")
print("Downloaded release ZIP exists:", UPLOAD.is_file())
''')
    markdown('## 第 2 步：核验并展开完整 Release 包\n先按 GitHub_部署指南完成服务器下载与 SHA-256 校验。以下代码还会复核固定清单及逐文件摘要，不覆盖已有的不同文件。')
    source = (ROOT / 'scripts/package_extract.py').read_text(encoding='utf-8')
    code(source + '\nMANIFEST_SHA256 = ' + repr(manifest_sha) + '\nunpack_package(UPLOAD, PROJECT, MANIFEST_SHA256)\n')
    markdown('## 第 3 步：初始化日志助手、复核已展开项目\n后续子进程都用当前远程 Python。任何失败都会同时给出日志位置与原始错误末尾。')
    code('''import json
import importlib
sys.path.insert(0, str(PROJECT / "scripts"))
import dataset_workflow as workflow
importlib.reload(workflow)

def run_step(step):
    command = [sys.executable, "-u", str(PROJECT / "scripts/dataset_workflow.py"), step,
               "--project", str(PROJECT), "--site", "server"]
    return workflow.run_logged(PROJECT, command, "step_" + step)

run_step("verify")
''')
    markdown('## 第 4 步：展开并复核 10,298 对图像与 Mask\nNFS 小文件较多，可能需要等待。每 4,000 个文件打印进度；相同文件重跑会复用。')
    code('run_step("extract")\n')
    markdown('## 第 5 步：离线安装体检依赖\n只读取包内 wheel，不访问 PyPI，不安装 torch/CUDA。后续统计用新的子进程，不必重启本内核。')
    code('run_step("install")\n')
    markdown('## 第 6 步：运行合成测试\n看到最后的 `OK` 再继续；测试只验证统计、文件检查与功能边界，不生成真实数据的新划分。')
    code('run_step("test")\n')
    markdown('## 第 7 步：重新逐图体检并生成 PDF\n所有统计从服务器文件重新计算。每次运行写入一个新结果目录，不覆盖旧报告。完整性通过不等于官方集合无重复或来源可核验。')
    code('run_step("audit")\n')
    markdown('## 第 8 步：查看本次结果\n只读 latest_run.json 指向的本次输出。PDF/CSV 可在浏览器 JupyterLab 文件面板找到后右键下载，路径在下方打印。')
    code('''state = json.loads((PROJECT / "output/latest_run.json").read_text(encoding="utf-8"))
print(json.dumps(state, ensure_ascii=False, indent=2))
assert state["status"] == "PASS", "本次尚未通过，请检查日志，不要读取旧报告当作成功"
assert state["execution_site"] == "server"
RESULT = Path(state["output"])
summary = json.loads((RESULT / "audit_summary.json").read_text(encoding="utf-8"))
receipt = json.loads(Path(state["receipt"]).read_text(encoding="utf-8"))
print("Images / masks / valid pairs:", summary["image_count"], summary["mask_count"], summary["fully_valid_image_mask_pairs"])
print("Resolution:", summary["resolution"])
print("Official split leakage:", summary["official_split_leakage_status"])
print("Strict source grouping:", summary["source_grouping"]["status"])
print("Receipt:", state["receipt"])
print("PDF:", RESULT / "显微数据体检单.pdf")
print("Unsupported feature notes:", RESULT / "功能范围与限制.md")
for item in summary["not_implemented_features"]:
    print(item["feature"], item["status"], item["reason_cn"])
assert summary["package_scope"] == "SUPPORTED_ONLY_V2"
assert receipt["status"] == "FILE_INTEGRITY_PASS"
assert receipt["execution_site"] == "server" and receipt["pdf_created"]
from IPython.display import Image, display
display(Image(filename=str(RESULT / "pixel_area_long_tail.png")))
''')
    markdown('''## 未实现事项备注（不是运行步骤）

- **患者/切片严格划分：未实现。** 无逐图真实来源映射，不能证明无来源泄漏。仅统计官方既有集合，不输出新划分。
- **颗粒像素面积：未实现。** 颗粒只有图像级属性，无独立颗粒 Mask；不会虚构像素面积或以 0 代替缺失。
- **物理分辨率/面积：未实现。** 无显微标定，仅统计宽高 px 和像素个数，不换算 μm/px 或 μm²。

详见同包及每次输出的 `功能范围与限制.md`。这三项未实现不影响支持范围内的体检通过；文件完整性 PASS 不代表患者/切片独立或论文完整复现。''')
    return {'cells': cells, 'metadata': {'kernelspec': {'display_name': 'Python (wbcattplus server)',
            'language': 'python', 'name': 'wbcattplus-server-py39'},
            'language_info': {'name': 'python', 'version': '3.9.19'}}, 'nbformat': 4, 'nbformat_minor': 4}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replace', action='store_true', help='Replace the current output/WBCAttPlus_Deployment.zip after CRC validation')
    args = parser.parse_args()
    output = ROOT / 'output'
    output.mkdir(parents=True, exist_ok=True)
    wheelhouse = ROOT / 'wheelhouse'
    provenance = ROOT / 'wheel_manifest.json'
    verified = json.loads(provenance.read_text(encoding='utf-8'))
    if verified['status'] != 'OFFICIAL_PYPI_HASH_AND_TARGET_DEPENDENCY_CLOSURE_PASS':
        raise ValueError('Wheel verification missing')
    payload = {}
    for name in ('audit_utils.py', 'audit_scope.py', 'dataset_audit.py', 'audit_report.py', 'dataset_extract.py', 'package_extract.py', 'dataset_workflow.py', 'build_package.py', 'verify_package.py'):
        payload['scripts/' + name] = ROOT / 'scripts' / name
    payload['tests/test_dataset_audit.py'] = ROOT / 'tests/test_dataset_audit.py'
    payload['tests/test_dataset_workflow.py'] = ROOT / 'tests/test_dataset_workflow.py'
    payload['requirements.txt'] = ROOT / 'requirements.txt'
    payload['wheel_manifest.json'] = provenance
    payload['GitHub_部署指南.md'] = ROOT / 'GitHub_部署指南.md'
    payload['.gitignore'] = ROOT / '.gitignore'
    scope_path = ROOT / '功能范围与限制.md'
    write_scope_notes(scope_path)
    payload['功能范围与限制.md'] = scope_path
    for entry in verified['wheels']:
        wheel = wheelhouse / entry['filename']
        if wheel.stat().st_size != entry['size_bytes'] or digest(wheel) != entry['sha256']:
            raise ValueError('Wheel changed after verification')
        payload['wheelhouse/' + wheel.name] = wheel
    dataset = ROOT / 'datasets/WBCAttPlus'
    manifest = dataset / 'download_manifest.json'
    payload['datasets/WBCAttPlus/download_manifest.json'] = manifest
    for entry in json.loads(manifest.read_text(encoding='utf-8'))['assets']:
        path = dataset / entry['path']
        if path.stat().st_size != entry['size_bytes'] or digest(path) != entry['sha256']:
            raise ValueError('Official source asset mismatch: ' + str(path))
        payload['datasets/WBCAttPlus/' + entry['path']] = path
    manifest_bytes = json_bytes({'package': NAME, 'schema': 2, 'package_scope': PACKAGE_SCOPE,
        'target': 'Existing Linux x86_64 glibc>=2.28 CPython 3.9 wbcattplus environment',
        'scope': 'Supported-only integrity/pixel statistics/duplicate-risk audit. Source splitting, granule masks and physical-unit conversion are NOT_IMPLEMENTED.',
        'files': [{'path': name, 'size_bytes': path.stat().st_size, 'sha256': digest(path)}
                  for name, path in sorted(payload.items())]})
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    notebook_bytes = json_bytes(notebook(manifest_sha))
    guide = (ROOT / 'README.md').read_bytes()
    destination = output / NAME
    if destination.exists() and not args.replace:
        raise FileExistsError('Deployment package already exists; use --replace to update this one package')
    temporary = output / 'WBCAttPlus_Deployment.tmp'
    with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, path in sorted(payload.items()):
            method = zipfile.ZIP_STORED if name.endswith('.whl') else zipfile.ZIP_DEFLATED
            archive.write(path, name, compress_type=method)
        archive.writestr('package_manifest.json', manifest_bytes)
        archive.writestr('WBCAttPlus_Setup.ipynb', notebook_bytes)
        archive.writestr('README.md', guide)
    with zipfile.ZipFile(temporary) as archive:
        bad = archive.testzip()
        if bad:
            raise ValueError('Final ZIP CRC failure: ' + bad)
    os.replace(str(temporary), str(destination))
    zip_sha = digest(destination)
    (ROOT / 'WBCAttPlus_Setup.ipynb').write_bytes(notebook_bytes)
    (ROOT / 'package_manifest.json').write_bytes(manifest_bytes)
    # Kept outside the ZIP/payload to avoid embedding a file's own checksum.
    (ROOT / 'WBCAttPlus_Deployment.sha256').write_text(zip_sha + '  ' + NAME + '\n', encoding='ascii')
    result = {'archive': str(destination), 'package_scope': PACKAGE_SCOPE, 'size_bytes': destination.stat().st_size,
              'sha256': zip_sha, 'manifest_sha256': manifest_sha,
              'payload_files': len(payload), 'wheel_files': len(verified['wheels']),
              'notebook_code_cells': sum(cell['cell_type'] == 'code' for cell in notebook(manifest_sha)['cells']),
              'validation_note': 'ZIP CRC, payload hashes, Python 3.9 syntax, PyPI wheel hashes and dependency metadata verified. Server execution not yet performed.'}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
