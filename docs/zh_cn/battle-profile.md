# 用户对战策略 JSON

Battle Profile 是地城试炼自动对战使用的用户策略配置。它只描述卡组与决策偏好；卡牌
识别、坐标、MaaFramework Pipeline 和设备操作仍由 MaaSVWB 管理。

## 文件位置

内置策略随发布包放在 `battle/profiles/`。GUI 后续会把用户导入的配置复制到：

```text
%APPDATA%\MaaSVWB\battle_profiles\
```

配置必须是 UTF-8 编码的 JSON，大小不能超过 1 MiB。用户策略只能引用
`battle/card_catalog.json` 已注册的卡牌 ID。

## 基本格式

```json
{
  "$schema": "https://raw.githubusercontent.com/allenx555/MaaSVWB/main/assets/schemas/battle-profile.schema.json",
  "schema_version": 1,
  "id": "aggro_shadow",
  "name": "快鬼",
  "description": "地城试炼用快攻策略",
  "deck": [
    { "card_id": "example_follower", "copies": 3 },
    { "card_id": "example_burn", "copies": 3 }
  ],
  "cards": {
    "example_follower": {
      "play_priority": 60,
      "target": { "type": "none" }
    },
    "example_burn": {
      "play_priority": 100,
      "target": { "type": "enemy_leader" },
      "max_uses_per_turn": 3
    }
  },
  "combos": [],
  "attack": {
    "clear_ward": true,
    "otherwise": "enemy_leader",
    "attacker_order": "lowest_attack_first"
  },
  "evolution": {
    "enabled": true,
    "prefer_can_attack": true,
    "card_priority": ["example_follower"],
    "type_order": ["super", "normal"]
  },
  "mulligan": {
    "enabled": true,
    "keep": ["example_follower"],
    "keep_all_if_any_kept": false
  },
  "safety": {
    "max_actions_per_turn": 30,
    "max_retries_per_action": 1,
    "no_progress_limit": 3
  }
}
```

示例中的卡牌 ID 仅用于说明格式，必须替换为实际卡牌注册表中的 ID。

## 出牌规则

- `play_priority` 越大越优先；相同优先级按当前手牌从左到右选择。
- `enabled: false` 可临时禁止自动使用一张卡。
- `max_uses_per_turn` 限制同一回合使用次数。
- `target.type` 当前支持 `none`、`enemy_leader`、`ally_leader`、
  `enemy_follower` 和 `ally_follower`。
- 随从目标可以增加 `selector`，例如 `lowest_defense` 或 `leftmost`。
- `when` 可以限制最低能量、最低空余场地格，以及要求敌方守护存在或不存在。

实际能否出牌以盘面观察器识别到的可用状态为准。识别到的动态费用优先于卡牌注册表
中的基础费用。

## 开局换牌

换牌策略只使用明确的卡牌名单，不根据费用自动推断：

- `enabled: false`：不选择任何卡牌，直接确认起手；
- `enabled: true`：保留 `keep` 中的卡牌，交换其余成功识别的起手牌；
- `keep_all_if_any_kept: true`：只要起手中出现任意一张 `keep` 卡牌，就保留
  整手；若完全没有出现，则交换所有成功识别的起手牌；
- OCR 未能识别的起手牌会安全保留，不会盲目交换。

换牌识别和拖动属于通用基础战斗组件，地城试炼等玩法只负责提供 Battle Profile。

## 固定顺序组合

`combos` 用来表达必须按固定顺序使用的多张卡。引擎会先检查整个组合所需的手牌、
能量点、场地空位、每回合使用上限和条件。任意一步不满足时，整个组合都不会启动。

```json
{
  "id": "setup_then_burn",
  "priority": 200,
  "steps": [
    { "card_id": "example_follower" },
    {
      "card_id": "example_burn",
      "target": { "type": "enemy_leader" }
    }
  ]
}
```

组合和单卡共用优先级范围；优先级相同时，组合优先。

## 进化策略

- `enabled: true` 开启自动进化；每个己方回合最多成功进化一次。
- 回合开始时先按当前场上顺序尝试进化已有随从。
- 若场上没有可进化随从，则在出牌后尝试进化本回合新打出的随从。
- 新随从优先按卡牌注册表的 `storm`（疾驰）特性选择，再按
  `card_priority` 的顺序选择。
- `type_order` 控制尝试 `normal` 或 `super` 进化的顺序；只填写
  `normal` 时不会消耗超进化。

## 安全限制

配置不允许包含坐标、Pipeline 节点、Shell 命令、Python 表达式或任意可执行内容。
未知字段、未知卡牌、非法目标、重复 ID 和越界策略文件名都会在执行前报错。

当前版本已经提供 Schema、加载、交叉校验、换牌与确定性出牌计划，并已接入地城试炼
的 1280×720 盘面观察和战斗循环。

## 战斗次数

战斗次数属于一次自动化会话，不属于卡组策略，因此不会写入 Battle Profile。GUI 中
填写的次数包含首次挑战，并表示目标胜场数：`1` 表示取得一场胜利后返回地城，`3`
表示累计取得三场胜利。失败不计入战斗次数，之后仍会点击再战；任意胜利都会清零连续
失败次数。连续失败超过三次（即连续第 4 次失败）或结算状态无法确认时停止。

## 从 SVWBData 导入卡组

开发者可以使用 `tools/import_battle_deck.py` 从项目相邻的 `SVWBData` 中按中文名称或
稳定卡牌 ID 生成卡组限定资源。导入格式见
`docs/examples/battle_deck_import.json`。已确认的快梦完整卡组见
`docs/examples/aggro_nightmare_deck_import.json`。

如果多个版本共用同一中文名称，工具会列出候选 ID 并停止，配置中应改用稳定卡牌
ID，避免误选旧版本或特殊对象。

同一基础卡牌的异画可能显示不同名称。导入器会把 SVWBData 的 `style_aliases`
转换为运行时卡牌注册表中的 `aliases`，OCR 命中本名或任一别名时都会映射到同一个
基础卡牌 ID，并沿用相同的费用、类型、目标和策略规则。

每张牌必须人工填写 `default_target` 和 `allowed_targets`。解包得到的技能文本只作为
校对依据，不会自动决定目标；这可以避免“对敌方主战者造成伤害，同时对己方主战者
造成伤害”一类文本被错误归类。

```powershell
.\.venv\Scripts\python tools\import_battle_deck.py `
    docs\examples\battle_deck_import.json `
    --svwb-data D:\git\SVWBData `
    --output build\battle-import\aggro-shadow
```

如果 `SVWBData` 位于项目相邻目录，可以省略 `--svwb-data`，也可以设置环境变量
`SVWB_DATA_ROOT`。完整卡组可增加 `--require-40` 检查总张数；重新生成同一输出目录时
需要显式增加 `--force`。即使指定了 `--force`，工具也只会替换带有自身生成标记的
目录，不会递归删除普通目录。

输出内容如下：

```text
battle/card_catalog.json             卡组限定运行时注册表
battle/profiles/<id>.json             可继续编辑的 Battle Profile
battle/target_review.json             技能文本、源推断和人工目标对照报告
resource/image/cards/<id>/*.png       FeatureMatch 候选素材
import_request.json                   本次导入配置快照
```

生成图片使用 `CardResourceMaster` 的普通状态 UV 参数从无损原图裁剪，尺寸不会小于
64×64。它们仍是识别候选素材，接入正式资源前必须使用横屏 1280×720 实际画面校准
识别区域和阈值。不要把 APK、完整 AssetBundle、全量解包卡图或整个 `SVWBData` 放入
MaaSVWB 仓库和发布包。
