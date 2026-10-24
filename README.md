# WBCAtt+ 数据体检

当前唯一版本：`SUPPORTED_ONLY_V2`。推荐通过 **Git 管理代码 + GitHub Release 分发完整包** 部署，完整操作见 [GitHub_部署指南.md](GitHub_部署指南.md)。不要把约 197 MB 的完整包提交到普通 Git 仓库。

完整包：`output/WBCAttPlus_Deployment.zip`；运行入口：`WBCAttPlus_Setup.ipynb`。服务器先下载 Release，再顺序运行 Notebook，无需 JupyterLab 上传大文件。

## 功能范围

实现官方资产 SHA-256 校验、安全解压、全量图像/Mask 配对与解码检查、样本总量、宽高与每图像素数的 Min / Max / Mean、五类实际前景面积占比及长尾图、官方集合重复风险检查、中文 PDF/HTML/Markdown 体检单与本次执行回执。

五类前景是**细胞质、细胞核、血小板、红细胞、空泡**，不包含颗粒。

以下三项只备注、不实现：患者/切片级严格划分（缺少真实来源映射）、颗粒像素面积（缺少颗粒 Mask）、物理分辨率与真实面积（缺少显微标定）。详见 `功能范围与限制.md`。本包不训练模型，不宣称论文全部复现，不新建 train/val/test，不自动删重复图或改标注。

## 文件

| 文件或目录 | 用途 |
| --- | --- |
| `output/WBCAttPlus_Deployment.zip` | 上传至 GitHub Release 的完整离线包，不提交 Git |
| `WBCAttPlus_Setup.ipynb` | VS Code/Jupyter 分步入口，8 步 |
| `README.md`、`GitHub_部署指南.md`、`功能范围与限制.md` | 项目说明、GitHub 部署步骤、未实现事项 |
| `scripts/dataset_workflow.py` | 流程、日志和回执 |
| `scripts/dataset_audit.py`、`scripts/audit_report.py` | 独立统计与体检单 |
| `scripts/dataset_extract.py`、`scripts/package_extract.py` | 原始 tar 与完整 ZIP 的安全展开 |
| `scripts/audit_utils.py`、`scripts/audit_scope.py` | 文件辅助及功能边界 |
| `scripts/build_package.py`、`scripts/verify_package.py` | 重建唯一完整包、校验 |
| `tests` | 当前版本的 21 项合成测试 |
| `datasets/WBCAttPlus` | 官方原始归档、CSV 和固定版本参考资料 |
| `wheelhouse`、`wheel_manifest.json` | Linux Python 3.9 离线依赖与来源校验信息；wheel 不提交 Git |
| `requirements.txt`、`package_manifest.json` | 依赖版本与包内文件校验清单 |
| `WBCAttPlus_Deployment.sha256` | 完整包 SHA-256，随代码提交 Git；不嵌入 ZIP 本身 |

官方数据文件保留原名，以免破坏来源追踪；程序名称标明数据、报告或部署用途。当前只保留一个完整包，不保留旧版包、备份和临时副本。`.git` 为版本管理目录，不删除。`.gitignore` 已排除数据目录、离线 wheel、完整 ZIP、运行输出和常见凭证文件。

## 运行前提

继续使用你已验证的服务器环境：Linux x86_64、Python 3.9、`/home/jovyan/work/envs/wbcattplus`。依赖 wheel 要求 glibc ≥ 2.28，你之前的 Ubuntu 24.04 满足该条件。

本流程仅使用 CPU，不要求 GPU、nvcc 或 PyTorch，不重装 CUDA/驱动/Conda。保留现有训练环境。安装的只是 `requirements.txt` 中的体检依赖：NumPy 1.26.4、Pillow 10.4.0、ReportLab 4.2.5、pypdfium2 4.30.0、pickleshare 0.7.5、chardet 5.2.0。

## 操作流程

### 1. 本机打开入口

用桌面 VS Code 打开本机的 `WBCAttPlus_Setup.ipynb`，或在服务器网页打开从对应 Release tag 克隆的同名 Notebook。点击右上角内核选择器，选择已经连通的远程 Jupyter 服务器，再选择 **Python (wbcattplus server)**。不要选 Windows 本地 Python 或服务器 base Python 3.13。

远程内核决定代码在哪里执行；VS Code 左侧显示本地目录是正常现象，本次不需要 SSH。保持此前已连通的网络配置即可，不要关闭认证、SSL 或跨域保护。

### 2. 通过 GitHub Release 下载完整 ZIP

按 `GitHub_部署指南.md` 在本机推送代码并发布 `v1.0.0` Release，附件选择 `output/WBCAttPlus_Deployment.zip`。服务器用 Git 克隆对应 tag 的代码，用 curl 下载该附件并核对仓库中的 SHA-256。

普通 Git 克隆只包含代码和校验信息，不包含数据与 wheel。GitHub 自动生成的 `Source code (zip)` 也不是完整部署包。下载完成后服务器文件路径应是：

```text
/home/jovyan/work/WBCAttPlus_Deployment.zip
```

下载成功后不需要再访问 Hugging Face、GitHub 或 PyPI；数据和体检依赖均已包含。前提是服务器能访问 GitHub 和 Release 重定向后的下载域名，GitHub 可达不代表大附件下载一定可达。本机 v2rayN 不会自动代理远程服务器；网络不通应停止并联系平台，不修改 SSL 校验或重装 CUDA。

### 3. 顺序运行 Notebook

逐格按 `Shift+Enter`，等待前一格结束后再继续；第一次不要直接点“全部运行”。默认数据项目目录为 `/home/jovyan/work/WBCAttPlus_workspace`，与克隆代码的 `WBCAttPlus_code` 分开。如该目录有不同内容，脚本会保留文件并停止；将 `PROJECT` 改为新目录（如 `WBCAttPlus_workspace_run2`）再重跑即可。

| 步骤 | 工作 | 成功标志 |
| --- | --- | --- |
| 1 | 确认 Linux、Python 3.9 和远程环境 | 显示正确系统及环境路径 |
| 2 | 对下载的完整包做 CRC/SHA-256 检查并展开 | `Package verified and unpacked` |
| 3 | 复核已展开文件的摘要 | `Payload SHA-256 checks: PASS` |
| 4 | 解出原始图像与 Mask | 20,596 个文件，`Extraction complete` |
| 5 | 从包内 wheel 离线安装体检依赖 | 无错误退出；已安装提示也正常 |
| 6 | 运行当前版本合成测试 | 21 项测试，最后 `OK` |
| 7 | 在服务器逐图重新统计并生成报告 | `FILE INTEGRITY: PASS`，生成本次回执 |
| 8 | 查看本次摘要、长尾图和结果位置 | 本次状态 `PASS`，打印 PDF 路径 |

红色报错立即停止，不要跳过。每一步保存日志，并在异常中附最后 40 行。不要只发送最外层 `RuntimeError`，应同时提供原始错误和日志末尾。

每次体检使用新时间戳结果目录，不覆盖旧运行。`output/latest_run.json` 指向本次状态；只有本次完成后才写验收回执。看到中间 CSV 或 PDF 已存在不等于整步通过。

### 4. 查看、下载结果

Notebook 第 8 步会打印实际目录，一般为：

```text
/home/jovyan/work/WBCAttPlus_workspace/output/pdf/runs/本次运行编号/
```

在浏览器 JupyterLab 中进入该目录。双击 PDF 预览，右键“Download / 下载”取回本机。若 PDF 中文预览异常，可下载用本机阅读器查看，或打开同目录 HTML。不要在 VS Code 本地文件列表中寻找远程结果。

主要结果有：

- `显微数据体检单.pdf` / `.html` / `.md`：中文体检单。
- `pixel_area_long_tail.png` / `.svg`：五类前景长尾图，对数纵轴。
- `audit_summary.json`：统计、功能边界和数据来源。
- `per_image_audit.csv`：逐对图像与 Mask 的尺寸、哈希和像素量。
- `pixel_area_statistics.csv`、`resolution_distribution.csv`：面积比例、尺寸分布。
- `integrity_issues.csv`：完整性异常；仅表头表示未发现此类异常。
- `exact_duplicate_groups.json`、`near_duplicate_candidates.csv`：精确重复证据和近似候选。
- `功能范围与限制.md`：三项未实现功能及所缺数据。
- `server_deployment_receipt.json`：本次服务器验收、版本和摘要。

## 如何解释结果

本地全量核验参考：图像 10,298 张、Mask 10,298 张，全部 360×360 px。宽高 Min/Max/Mean 均为 360，每图像素数均为 129,600。服务器会重新计算，不能用本地参考值冒充服务器已部署。

| 实际前景 | 像素量 | 前景像素占比 |
| --- | ---: | ---: |
| 红细胞 | 515,846,377 | 76.1180% |
| 细胞质 | 86,668,784 | 12.7888% |
| 细胞核 | 70,669,994 | 10.4280% |
| 血小板 | 3,429,022 | 0.5060% |
| 空泡 | 1,078,659 | 0.1592% |

这是像素面积，不是细胞实例数，也不是 μm²。颗粒不在上述 Mask 类别中，不能以 0 或伪造数值补齐。图像矩阵尺寸也不是 μm/px 物理标定。

官方图像级集合为 train 6,169、val 1,030、test 3,099。本地发现 14 个精确重复图组，其中 6 组跨官方集合，另有 1 组图片类别标签冲突。程序只报告证据，不自动删除或改标签。

`integrity_status=PASS` 与 `official_split_leakage_status=FAIL_EXACT_DUPLICATE_CROSS_SPLIT` 可以同时出现：文件完整不代表划分无泄漏。官方无患者/切片 ID；文件名、细胞类别、重复聚类、dHash 均不能替代来源映射。未发现重复也不能证明患者/切片独立。

## 常见问题

1. **找不到 ZIP：** 检查 Release 附件是否下载完成、路径是否正确，不能用 GitHub 自动的 Source code ZIP 代替。
2. **CRC/SHA-256 不符：** 停止使用残缺或混版副本，确认代码 tag 与 Release 附件对应，不跳过校验。
3. **Python 或系统不对：** 重新选择远程 wbcattplus 内核，不要向 Windows/base 环境安装 Linux wheel。
4. **Existing file differs：** 原文件不会覆盖；使用新 `PROJECT` 目录，不盲目删除服务器数据。
5. **解压中断：** 重跑会复核并复用完整文件；若存在半写入的残缺文件，选新项目目录重跑。
6. **报告中断：** 源数据不变；重跑第 7 步产生新运行目录，按 `latest_run.json` 判断本次状态。
7. **No matching distribution：** 先检查 Linux x86_64、Python 3.9、glibc ≥ 2.28 和包内依赖文件，不随意更换版本。
8. **空间不足：** 检查个人配额、可用 inode 和空间。建议至少 2 GiB；NFS 总空闲不是你的配额。
9. **pickleshare 警告：** 不影响此前计算，本包已包含该小依赖。统计在新子进程执行，不必为统计重启内核。
10. **颗粒面积/严格划分没输出：** 这是明确的功能边界，不是安装失败，见 `功能范围与限制.md`。

## 终端与重新打包（可选）

已有第 2 步展开的项目后，可在服务器 JupyterLab 终端使用以下命令替代 Notebook 第 3-7 步；不要与 Notebook 同时运行，也不要在 Windows 本地终端运行服务器命令：

```bash
/home/jovyan/work/envs/wbcattplus/bin/python -u /home/jovyan/work/WBCAttPlus_workspace/scripts/dataset_workflow.py run
```

维护代码时，在项目根目录使用当前 Python 执行：

```bash
python -m unittest discover -s tests -v
python scripts/build_package.py --replace
python scripts/verify_package.py
```

构建必须在保留本地官方资产和 wheel 的完整工作目录执行，而不是只有代码的 Git 克隆目录。构建先核对摘要，再更新唯一完整 ZIP、Notebook 固定清单摘要和 `WBCAttPlus_Deployment.sha256`，不生成分片或备份。改动后重新构建、提交，并发布新 tag 的 Release，不能混用不同版本的代码与附件。

## 来源与许可

- [官方数据](https://huggingface.co/datasets/apple2373/wbcattplus)，固定版本 `b62f8e5019a2583fed2f30761267a89a85a77273`。
- [官方代码](https://github.com/apple2373/wbcattplus)，固定版本 `9bbf41d778dcd6c0b727d9ad42ff482d31733ee1`。
- 原始 tar SHA-256：`2a1730ce3a772e34bd1089b1aec44597e75b94ab0d26fbe697cb1189a9155090`。
- 13 个官方资产及各自 URL/摘要见完整包中的 `datasets/WBCAttPlus/download_manifest.json`；依赖来源与官方 PyPI 摘要见 `wheel_manifest.json`。
- 数据及依赖使用、再分发遵守各自上游许可，本整理包不授予额外许可；未分发 Windows 字体。官方参考代码仅作来源证据，不是本包执行入口。
- 本机 Windows 的检查不等于 Linux wheel 已实际执行。正式服务器安装与验收，以你运行生成的 `server_deployment_receipt.json` 为准。
