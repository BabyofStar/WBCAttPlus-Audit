# WBCAtt+：通过公开 GitHub 仓库部署

目标：代码用 Git 推送；唯一完整包作为 Release 附件；服务器通过网络下载，不再通过 JupyterLab 上传大文件。本文中的 `你的用户名` 必须替换为你自己的 GitHub 用户名。建议仓库名为 `WBCAttPlus-Audit`。

## 先明确两种文件放哪里

| 内容 | 放置方式 |
| --- | --- |
| 代码、Notebook、说明、依赖版本、校验清单 | Git 仓库，通过 `git push` 上传 |
| `output/WBCAttPlus_Deployment.zip`，约 197 MB | GitHub Release 附件，不提交到 Git |
| 原始数据、解压图像、离线 wheel、日志 | 已在完整包中；不单独提交 Git |

GitHub 普通仓库会阻止大于 100 MiB 的文件；网页直接添加普通仓库文件的上限为 25 MiB。Release 单个附件须小于 2 GiB，当前完整包符合该大小限制。[普通文件限制](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github)、[Release 限制](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)。本方案无需 Git LFS，也不分片。

公开发布前须确认原始数据和依赖的再分发许可；你已选择在确认数据许可允许后使用公开仓库。保留完整包内的来源与上游许可，不要提交密码、Token、VPN 配置、运行日志或患者身份信息。本整理包不授予额外许可。

## 0. 先在服务器测试 GitHub 可达性

打开**浏览器 JupyterLab 的 Terminal**，不是 Windows 本地终端：

```bash
git --version
curl --version
curl -I --connect-timeout 10 --max-time 20 https://github.com
```

收到 HTTP 响应说明主页可连接，不能证明 Release 大附件也可下载。若连接超时，先停止：GitHub 不能绕过服务器本身的外网限制。本机 v2rayN 不会自动作用于远程服务器，需要平台提供外网访问/允许的代理或网络白名单，不要关闭 TLS 校验，也不要把远程代理设成本机的 127.0.0.1。

## 1. 在 GitHub 网页创建公开仓库

1. 登录 GitHub，点击右上角 `+` → `New repository`。
2. Repository name 填 `WBCAttPlus-Audit`，选择 `Public`。
3. 为避免和本地初次推送冲突，**不要勾选自动创建 README，也不要添加 .gitignore 或 License 模板**；当前项目已有说明和忽略规则，数据及依赖沿用各自上游许可。
4. 点击 `Create repository`，保留显示的 HTTPS 地址，例如 `https://github.com/你的用户名/WBCAttPlus-Audit.git`。

这里只是你自己创建仓库的操作说明；本助手没有替你创建、提交或上传任何仓库内容。

## 2. 在本机推送代码，不推送完整 ZIP

在 Windows VS Code 中打开当前本地项目文件夹，再打开本地 Terminal，使用 PowerShell。先检查 Git：

```powershell
git --version
git status
git remote -v
```

先确认终端位于你本机当前项目根目录。本项目已有 Git 仓库、当前分支为 main，不需要再次初始化。如果提示找不到 Git，先安装/启用本机 Git，再重开 VS Code；不要把 Windows Git 配置命令放进远程 Notebook。

当前 `.gitignore` 已忽略 `datasets/`、`wheelhouse/`、`output/`、临时文件和常见凭证文件。用以下**明确列表**添加当前代码：

```powershell
git add .gitignore README.md GitHub_部署指南.md 功能范围与限制.md WBCAttPlus_Setup.ipynb requirements.txt package_manifest.json wheel_manifest.json WBCAttPlus_Deployment.sha256 scripts tests
git diff --cached --stat
```

检查待提交列表中没有 `.zip`、原始 `.tar`、图像、wheel、日志或凭证，再提交：

```powershell
git commit -m "Add WBCAttPlus dataset audit deployment"
```

如果 Git 要求姓名和邮箱，按提示为本仓库配置你的身份后重试，不要提交密码或 Token。

若 `git remote -v` 没有 origin，再执行：

```powershell
git remote add origin https://github.com/你的用户名/WBCAttPlus-Audit.git
git push -u origin main
```

如果 origin 已存在，先核对地址，不要盲目覆盖；确认就是这个仓库时，只执行 push。按 Git 的提示完成账号登录，不要把访问 Token 写到 URL、Notebook 或聊天中。若推送失败，保留原始报错，不使用 force push、reset --hard 或关闭 SSL 校验。

## 3. 在 GitHub Release 上传唯一完整包

1. 打开刚才的仓库，点击 `Releases` → `Draft a new release`。
2. Tag 填 `v1.0.0`，创建新 tag，Target 选择刚推送的 main。
3. Title 可填 `WBCAttPlus audit deployment v1.0.0`。
4. 在附件区域选择本机文件：

   项目目录下的 `output\WBCAttPlus_Deployment.zip`

5. 等待附件上传完全结束，再点击 `Publish release`。
6. 发布后在 Assets 中确认存在 **WBCAttPlus_Deployment.zip**，不要改名。

不要通过仓库首页 `Add file → Upload files` 上传完整 ZIP。GitHub 自动生成的 `Source code (zip)` / `Source code (tar.gz)` 只含仓库代码，**不是包含数据和离线依赖的完整包**。官方发布操作见 [管理 Releases](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository)。

发布时，本地 `WBCAttPlus_Deployment.sha256` 必须与该附件同一次构建生成，并已在对应 tag 的代码中提交。以后修改代码或重建包，使用新的 tag（如 v1.0.1），不要混用新代码、旧附件和旧校验值。

## 4. 服务器克隆对应 tag 的代码

回到服务器 JupyterLab Terminal。以下是 **Linux 服务器命令**，先替换 URL 中的 `你的用户名`：

```bash
cd /home/jovyan/work
git clone --depth 1 --branch v1.0.0 https://github.com/你的用户名/WBCAttPlus-Audit.git WBCAttPlus_code
```

克隆 tag 时出现 detached HEAD 提示是正常的，不是下载失败。公开仓库正常不需要服务器登录 GitHub。

如果 `WBCAttPlus_code` 已存在，不要删除或强制覆盖；先确认它属于哪个项目和 tag。想保持旧目录时，克隆到新目录，并相应修改后面 checksum 的路径。

## 5. 服务器下载完整 Release 附件

仍在服务器 `/home/jovyan/work` 目录执行，替换 URL 中的用户名：

```bash
curl --fail --location --show-error --retry 4 --retry-delay 3 --connect-timeout 20 --continue-at - --output WBCAttPlus_Deployment.zip https://github.com/你的用户名/WBCAttPlus-Audit/releases/download/v1.0.0/WBCAttPlus_Deployment.zip
```

这里将 GitHub 的公开完整附件下载到服务器，而不是从你的电脑经过 JupyterLab 上传。仍然是一个完整 ZIP，不分片。

第一次运行前，确认该路径没有你其他项目的重要同名文件。下载中断时保留残缺文件，使用相同 URL 重跑可尝试续传；curl 必须成功结束，才执行校验。若已完整下载且校验通过，不必再次下载。

若 404，先检查用户名、仓库名、tag、附件名及 Release 是否已正式发布。若主页可达但这里超时，可能是 Release 重定向后的附件域名受限；保留 curl 原始报错，让平台检查网络，不猜测成 Python/GPU 问题。

## 6. 核对 SHA-256，成功后才展开

保持当前目录为 `/home/jovyan/work`：

```bash
sha256sum -c WBCAttPlus_code/WBCAttPlus_Deployment.sha256
```

预期：

```text
WBCAttPlus_Deployment.zip: OK
```

不是 OK 就停止，不运行 Notebook 第 2 步、不手动跳过校验。先确认代码 tag 和附件版本一致、下载完整。不要因为 Git clone 成功就以为数据也已部署。

## 7. 打开 Notebook，顺序运行第 1-8 步

两种打开方式任选其一：

- 本机 VS Code 打开更新后的 `WBCAttPlus_Setup.ipynb`，内核选择已连通的服务器 → `Python (wbcattplus server)`。
- 浏览器 JupyterLab 进入 `WBCAttPlus_code`，打开同名 Notebook，选择同一个 wbcattplus 内核。

Notebook 默认路径已配置：

```text
完整附件：/home/jovyan/work/WBCAttPlus_Deployment.zip
数据项目：/home/jovyan/work/WBCAttPlus_workspace
克隆代码：/home/jovyan/work/WBCAttPlus_code
```

代码目录与实际数据项目分开，避免覆盖 Git 克隆中的文件。逐格按 Shift+Enter：环境检查 → 包校验与展开 → 载荷复核 → 原始数据解压 → 离线依赖 → 测试 → 全量体检与报告 → 查看结果。不要使用旧的 run.ipynb 或旧清单摘要。

正式体检使用 CPU，继续使用既有 Linux Python 3.9 环境；不安装 PyTorch/CUDA，不要求 nvcc。完成附件下载后，不再依赖 Hugging Face、GitHub 或 PyPI。

## 8. 查看本次报告

Notebook 第 8 步会打印目录，一般为：

```text
/home/jovyan/work/WBCAttPlus_workspace/output/pdf/runs/本次运行编号/
```

在浏览器 JupyterLab 进入该目录，预览或下载 `显微数据体检单.pdf`、长尾图、CSV/JSON 和 `server_deployment_receipt.json`。只有本次状态 PASS 和回执生成后才算支持范围内的体检完成。

患者/切片严格划分、颗粒像素面积、物理尺度换算仍为 NOT_IMPLEMENTED，理由见 `功能范围与限制.md`；GitHub 部署不会补齐这些缺失的标注和元数据。
