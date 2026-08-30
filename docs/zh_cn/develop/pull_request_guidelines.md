# PR 规范

## 基本要求

- 一个 PR 只处理一个明确主题；
- 说明改动原因、影响范围和验证结果；
- 不提交本地配置、日志、调试截图、OCR 模型和构建产物；
- 使用 AI 辅助时，提交者仍需理解并负责最终改动。

## 分支与提交

推荐分支前缀：`feat/`、`fix/`、`docs/`、`refactor/`、`test/`、`chore/`。

提交信息推荐遵循
[Conventional Commits](https://www.conventionalcommits.org/zh-hans/v1.0.0/)：

```text
feat: 新增盘面解密脚本
fix(navigation): 修复已展开类别被重复点击
docs: 更新用户说明
```

## PR 描述

至少包含：

- 关联 Issue 或需求来源；
- 2～5 条变更摘要；
- 实际执行过的验证命令及结果；
- 涉及 GUI 或识别行为时的截图、日志或复现步骤。

## 提交前检查

- [ ] `tools/test.ps1` 通过；
- [ ] `npm ci && npx @nekosu/maa-tools check` 通过；
- [ ] 修改 GUI 时，Avalonia 构建通过；
- [ ] 修改目录或解法后，`assets/interface.json` 已重新生成；
- [ ] 修改真实操作流程后，已在授权模拟器上验证；
- [ ] 没有混入 `debug/`、`install/`、模型或本机配置。

坐标和 ROI 统一以横屏 1280×720 为基准。关卡解法优先使用 `play_card`、`attack`、
`select_target` 等语义动作；原始坐标应保留在布局或必要的底层后备步骤中。
