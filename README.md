# App Store Connect IPA Uploader 安装与使用手册

**项目名称：** App Store Connect IPA Uploader  
**项目地址：** https://github.com/3010020510/app-store-connect-ipa-uploader  
**运行环境：** Python 3.10+  
**项目类型：** Python CLI + Flask Web UI

## 1. 项目简介

App Store Connect IPA Uploader 是一个使用 Python 编写的 iOS 应用构建上传工具。

它通过 Apple App Store Connect API 上传 IPA 文件，提供命令行和 Web 网页两种操作方式，适合希望在 Windows 电脑或 Linux 服务器上执行上传流程的开发者。

主要功能：

- 通过 App Store Connect API 读取应用列表。
- 自动读取 IPA 中的 Bundle ID、版本号和 Build 号。
- 创建构建上传任务。
- 根据 Apple API 返回的上传操作分段上传 IPA。
- 提交上传任务并查询处理状态。
- 记录请求 ID、API 响应和错误日志。

注意：本项目负责 IPA 上传流程，不负责编译 iOS 应用，也不保证上传后的构建一定通过 Apple 的审核或处理。

## 2. 环境要求

| 项目 | 要求 |
|---|---|
| Python | 3.10 或更高版本 |
| pip | 与当前 Python 环境匹配 |
| 网络 | 能访问 GitHub、Apple App Store Connect API 及 Apple 返回的上传地址 |
| Apple 账号 | 具备相应 App Store Connect API 权限 |
| API 密钥 | Key ID、Issuer ID、`.p8` 私钥 |
| 上传文件 | 有效的 `.ipa` 文件 |

建议使用独立 Python 虚拟环境，避免影响系统中其他项目。

## 3. 下载项目

### 3.1 使用 Git 克隆

执行：

```bash
git clone https://github.com/3010020510/app-store-connect-ipa-uploader.git
cd app-store-connect-ipa-uploader
```

如果 GitHub 网络连接失败，可以先下载仓库 ZIP 文件，解压后进入项目目录。

GitHub 仓库地址：

https://github.com/3010020510/app-store-connect-ipa-uploader

## 4. Windows 安装

### 4.1 安装 Python

从 Python 官方网站下载并安装 Python 3.10 或更高版本：

https://www.python.org/downloads/

安装时建议勾选 `Add Python to PATH`。

打开 CMD，验证：

```bat
python --version
python -m pip --version
```

如果系统中存在多个 Python 版本，应确保安装依赖和运行项目使用的是同一个 Python 解释器。

### 4.2 创建虚拟环境

进入项目目录：

```bat
cd /d C:\Users\Administrator\Desktop\data\app-store-connect-ipa-uploader
```

创建虚拟环境：

```bat
python -m venv .venv
```

激活环境：

```bat
.venv\Scripts\activate
```

### 4.3 安装依赖

执行：

```bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

项目当前使用的主要依赖：

- Flask
- Requests
- Cryptography

安装完成后，可验证：

```bat
python -m pip show Flask requests cryptography
```

### 4.4 启动 Web 服务

执行：

```bat
python web_app.py
```

默认监听端口为 `5000`。

在运行服务的电脑上打开浏览器：

http://127.0.0.1:5000

如果终端显示 Flask 服务已启动，即可尝试访问网页。

停止服务时，在 CMD 中按 `Ctrl+C`。

## 5. Linux 服务器安装

以下命令适用于常见 Linux 服务器。不同发行版的 Python 安装命令可能不同。

### 5.1 安装系统依赖

Ubuntu / Debian：

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git
```

CentOS 及其他发行版请根据系统版本安装 Python 3.10 或更高版本。较旧的 CentOS 可能需要额外配置 Python 软件源。

检查版本：

```bash
python3 --version
python3 -m pip --version
```

### 5.2 下载项目

```bash
git clone https://github.com/3010020510/app-store-connect-ipa-uploader.git
cd app-store-connect-ipa-uploader
```

### 5.3 创建虚拟环境并安装依赖

```bash
python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 5.4 启动服务

```bash
python web_app.py
```

默认端口为 `5000`。

也可以在启动前设置端口：

```bash
PORT=5001 python web_app.py
```

注意：当前程序默认绑定 `0.0.0.0`，这意味着服务可能接受来自其他网络接口的连接。不要在未增加身份认证和访问控制的情况下直接暴露到公网。

初次部署建议仅在本机或受控的内网环境中测试。

## 6. 配置 Apple App Store Connect API

### 6.1 获取 API 密钥

登录 Apple 开发者相关管理页面：

https://appstoreconnect.apple.com/

在 App Store Connect 的用户与访问权限中找到 API 密钥管理入口。根据账号权限创建或获取 API Key。

准备以下信息：

| 参数 | 说明 |
|---|---|
| Key ID | API 密钥的标识 |
| Issuer ID | API 密钥所属的 Issuer 标识 |
| Private Key | 下载的 `.p8` 私钥文件 |
| App ID | App Store Connect 中对应应用的数字 ID |

创建密钥时需要选择符合实际操作要求的访问权限。具体权限取决于账号角色和 Apple 当前的 API 权限模型。

### 6.2 安全保存私钥

将 `.p8` 文件放在本机的安全目录中，例如：

Windows：

```text
C:\Users\Administrator\Documents\ASC-Keys\AuthKey_XXXXXXXXXX.p8
```

Linux：

```text
/home/youruser/asc-keys/AuthKey_XXXXXXXXXX.p8
```

Linux 下可以限制文件权限：

```bash
chmod 600 /home/youruser/asc-keys/AuthKey_XXXXXXXXXX.p8
```

请勿将 `.p8` 文件上传到 GitHub，也不要把私钥写入 README、日志或公开截图。

## 7. 使用 Web 网页上传 IPA

### 7.1 启动项目

确保已经安装依赖，然后执行：

```bash
python web_app.py
```

浏览器访问：

http://127.0.0.1:5000

### 7.2 填写 API 信息

根据网页表单填写：

- Key ID
- Issuer ID
- `.p8` 私钥文件
- 应用 ID
- 目标平台
- IPA 文件

如果网页提供应用列表获取功能，可以先填写 API 凭据并获取应用列表。

### 7.3 执行上传

选择有效的 IPA 文件并提交。

程序会尝试：

1. 生成 API 鉴权 JWT。
2. 检查 IPA 元数据。
3. 创建 Build Upload 资源。
4. 创建 Build Upload File 资源。
5. 获取 Apple 返回的上传操作。
6. 分段上传 IPA 文件。
7. 提交上传任务。
8. 查询上传处理状态。

具体执行结果以网页返回信息及日志为准。

## 8. 使用命令行上传 IPA

除了 Web 页面，本项目还提供命令行接口。

以下命令在项目根目录执行。

### 8.1 查询应用列表

```bash
python appstore_build_upload.py apps \
  --key-id YOUR_KEY_ID \
  --issuer-id YOUR_ISSUER_ID \
  --private-key "/path/to/AuthKey_XXXXXXXXXX.p8"
```

Windows CMD 示例：

```bat
python appstore_build_upload.py apps --key-id YOUR_KEY_ID --issuer-id YOUR_ISSUER_ID --private-key "C:\Users\Administrator\Documents\AuthKey_XXXXXXXXXX.p8"
```

### 8.2 完整上传 IPA

Linux 示例：

```bash
python appstore_build_upload.py upload \
  --key-id YOUR_KEY_ID \
  --issuer-id YOUR_ISSUER_ID \
  --private-key "/path/to/AuthKey_XXXXXXXXXX.p8" \
  --app-id YOUR_APP_ID \
  --version 1.2.3 \
  --build 45 \
  --ipa "/path/to/app.ipa" \
  --platform IOS
```

Windows CMD 示例：

```bat
python appstore_build_upload.py upload --key-id YOUR_KEY_ID --issuer-id YOUR_ISSUER_ID --private-key "C:\Users\Administrator\Documents\AuthKey_XXXXXXXXXX.p8" --app-id YOUR_APP_ID --version 1.2.3 --build 45 --ipa "C:\Users\Administrator\Desktop\app.ipa" --platform IOS
```

请替换所有示例参数：

- `YOUR_KEY_ID`：实际 Key ID。
- `YOUR_ISSUER_ID`：实际 Issuer ID。
- `YOUR_APP_ID`：目标应用的数字 ID。
- `.p8` 路径：实际私钥文件路径。
- `.ipa` 路径：待上传的 IPA 文件路径。
- `1.2.3` 和 `45`：示例版本号和 Build 号。

程序会读取 IPA 内部的版本信息，并按当前代码的逻辑处理版本号和 Build 号。

### 8.3 平台参数

当前代码允许以下平台值：

- `IOS`
- `MAC_OS`
- `TV_OS`
- `VISION_OS`

可选值不代表每种平台都已经完成端到端验证。实际支持情况应以 Apple API 要求、IPA 类型及测试结果为准。

### 8.4 只创建上传任务

如果需要单独调试创建 Build Upload 资源，可以执行：

```bash
python appstore_build_upload.py create-upload \
  --key-id YOUR_KEY_ID \
  --issuer-id YOUR_ISSUER_ID \
  --private-key "/path/to/AuthKey_XXXXXXXXXX.p8" \
  --app-id YOUR_APP_ID \
  --version 1.2.3 \
  --build 45
```

此命令只创建上传资源，不会执行完整 IPA 文件上传流程。请勿将它误认为完整上传测试。

## 9. 环境变量配置

命令行支持以下环境变量：

| 变量名 | 说明 |
|---|---|
| `ASC_KEY_ID` | App Store Connect Key ID |
| `ASC_ISSUER_ID` | Issuer ID |
| `ASC_PRIVATE_KEY_PATH` | `.p8` 私钥文件路径 |
| `ASC_APP_ID` | App ID |

Linux 示例：

```bash
export ASC_KEY_ID="YOUR_KEY_ID"
export ASC_ISSUER_ID="YOUR_ISSUER_ID"
export ASC_PRIVATE_KEY_PATH="/path/to/AuthKey_XXXXXXXXXX.p8"
export ASC_APP_ID="YOUR_APP_ID"
```

配置后可以简化命令：

```bash
python appstore_build_upload.py apps
```

环境变量只在当前 Shell 及其子进程中生效，除非你另外配置持久化环境变量。

不要把包含真实凭据的 `.env` 或其他配置文件提交到公开仓库。

## 10. 日志与问题排查

项目会在 `logs/` 目录记录 JSON Lines 格式的日志。

日志可用于检查：

- API 请求是否成功。
- 请求 ID 和执行耗时。
- IPA 上传各阶段的状态。
- Apple API 返回的错误。
- 上传处理阶段是否失败。

日志可能包含应用元数据、API 响应和临时上传信息。向他人提交问题或公开日志前，请先检查并脱敏。

### 常见问题

**问题一：ModuleNotFoundError**

通常是依赖没有安装，或者使用了错误的 Python 环境。

```bash
python -m pip install -r requirements.txt
```

**问题二：Missing required value**

检查命令行参数或对应环境变量是否填写完整。

**问题三：Invalid private key**

检查 `.p8` 文件是否正确、路径是否可访问，以及 Key ID 和 Issuer ID 是否匹配。

**问题四：HTTP 401 或 403**

检查 API 密钥、Issuer ID、访问权限以及账号是否有权访问目标应用。

**问题五：IPA 元数据读取失败**

检查文件是否为有效 IPA，以及内部是否包含主应用的 `Payload/*.app/Info.plist`。

**问题六：上传或处理失败**

检查 API 响应、网络连接、Apple 返回的错误信息以及日志中的请求 ID。上传文件时还需要确保服务器能够访问 Apple 返回的实际上传地址。

**问题七：网页无法访问**

确认 Flask 服务仍在运行、端口配置正确，并检查防火墙和服务器访问规则。

## 11. 安全建议

1. 不要公开 `.p8` 私钥、真实 API 凭据或 IPA 文件。
2. 不要把运行日志直接提交到公开仓库。
3. 不要在未设置身份认证的情况下将 Web 服务直接暴露到公网。
4. 通过反向代理部署时，应配置 HTTPS、身份认证、访问控制和合理的上传大小限制。
5. 不要在公共电脑或共享浏览器中长期保存 API 配置。
6. 正式使用前，先用测试应用或适当的测试构建验证完整上传流程。

## 12. 项目声明

本项目是独立开发者工具，与 Apple Inc. 没有隶属、赞助或官方背书关系。

项目功能和兼容性以实际代码及测试结果为准。App Store Connect 的接口、权限要求和处理流程可能发生变化。
