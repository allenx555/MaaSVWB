# 开发指南

本文面向 MaaSVWB 的贡献者。MaaFramework Pipeline、识别算法和 Agent 接口以
[MaaFramework 官方文档](https://maafw.com/docs/1.1-QuickStarted)及项目当前 Schema 为准。

## 准备仓库

```powershell
git clone git@github.com:allenx555/MaaSVWB.git
cd MaaSVWB
powershell -ExecutionPolicy Bypass -File .\tools\setup_dev.ps1
powershell -ExecutionPolicy Bypass -File .\tools\setup_gui.ps1
```

`setup_dev.ps1` 会创建 `.venv/`、安装 Python 依赖并下载 OCR 模型；
`setup_gui.ps1` 会将 .NET 10 SDK 安装到 `.dotnet/`。这些目录都不会提交到仓库。

## 代码与资源边界

- `assets/catalog/`：前端目录、分组、顺序和依赖；
- `assets/resource/pipeline/`：MaaFramework Pipeline 与 OCR 识别节点；
- `assets/resource/layouts/`：1280×720 统一布局；
- `assets/resource/solutions/`：人工录入的语义解法；
- `agent/`：Custom Action、选关导航和解法执行器；
- `gui/MaaSVWB.Desktop/`：Avalonia 桌面前端；
- `tools/`：环境、验证、调试和发布脚本。

不要提交 `.venv/`、`.dotnet/`、OCR 模型、`debug/`、`install/` 或其他构建产物。

## 开发流程

1. 从 `main` 创建范围明确的分支；
2. 修改目录、解法或 Pipeline；
3. 若目录或解法发生变化，运行：

    ```powershell
    .\.venv\Scripts\python tools\generate_interface.py
    ```

4. 运行完整检查：

    ```powershell
    .\tools\test.ps1
    npm ci
    npx @nekosu/maa-tools check
    .\.dotnet\dotnet.exe build gui\MaaSVWB.Desktop\MaaSVWB.Desktop.csproj
    ```

5. 涉及模拟器行为时，在明确授权的设备上验证，并保留必要日志或识别截图；
6. 按 [PR 规范](./pull_request_guidelines.md)提交变更。

语义解法格式见[人工解法格式](../solution-format.md)。AI 辅助工具见
[AI 辅助开发说明](./ai-development.md)。

## 本地发布

```powershell
.\tools\package.ps1 -Version v0.1.0 -Os win -RuntimeIdentifier win-x64
```

脚本会清理并重新生成 `install/`，其中包含单文件 GUI、资源、目录、Runner、Agent 和
第三方许可。推送 `v*` 标签后，GitHub Actions 会生成各平台 ZIP 并创建 Release。

## 更新 MaaFramework

版本号需要同时更新：

- `tools/project_versions.json`；
- `requirements.txt`；
- `maatools.config.mts`；
- `.github/workflows/sync_schema_files.yml`。

完成后运行 `tools/test.ps1`。Schema 同步工作流会从 MaaFramework 获取固定版本的
Schema；不要手工修改 `deps/tools/*.schema.json`。
