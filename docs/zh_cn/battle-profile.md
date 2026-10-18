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
- 自动战斗出牌当前支持 `target.type` 为 `none`、`enemy_leader`、`ally_leader`。
- 配置格式还保留 `enemy_follower`、`ally_follower` 及其 `selector`（例如
  `lowest_defense`、`leftmost`）；运行时尚未实现随从目标选择，使用这些目标的策略
  会在首次游戏操作前报错。此限制也适用于卡牌默认目标和组合步骤的目标。
- `when` 可以限制最低能量、最低空余场地格，以及要求敌方守护存在或不存在。

实际能否出牌以盘面观察器识别到的可用状态为准。识别到的动态费用优先于卡牌注册表
中的基础费用。

### 整手费用规划

`play_mode` 默认为 `priority`，保留按单卡优先级选择的行为。内置快梦使用
`maximize_energy`：比较当前手牌的合法出牌顺序，先选择能够消耗最多能量的路线，
再比较后出随从的铺场收益，最后用 `play_priority` 和手牌位置决定第一张。例如 5 费
手持 4、3、2 费随从时，优先出 3 费再出 2 费；艾瑟拉与一费随从都能打出时，
先铺随从再出艾瑟拉。挥毫的怪物仍保持最低基础优先级，但为提升艾瑟拉攻击力可先出。

规划会检查动态费用、场地空位、禁用规则、每回合使用上限和每一步的 `when` 条件。
随从和护符本体各占用一个场地格；卡牌注册表 `cards[].effects.summon_count`（0～4，默认 0）
表示额外召唤数量的上限。场地不足时召唤按剩余空位截断，不会因此禁止打出本体。
内置埃拉尔为 1，莉蜜儿为 2；莉蜜儿目前仍按最大占位保守估算，
出牌后重新读取实际数量。搜索按占位后的状态校验后续卡牌，为后续艾瑟拉预留位置。

Profile 的 `strategy` 默认为 `generic`。内置快梦显式选择 `aggro_nightmare`，
由独立策略模块在相同费用利用率下偏好先铺随从再出艾瑟拉，并限制残虐的炸裂只伤自己的
用法。这些偏好不由通用搜索器按卡牌 ID 判断；一般策略不会继承快梦的出牌顺序和主动
自伤限制。艾瑟拉铺场偏好只作用于 `maximize_energy` 模式，不改变固定组合顺序。
费用规划不预测抽牌、返费或减费。每次只执行一张，再根据实际
手牌、能量与盘面重新规划。运行时卡名 OCR 目前仍使用基础费用，尚未实现动态费用 OCR。
显式 `combos` 仍按原有优先级参与选择并连续执行，不纳入费用搜索。
为限制异常 OCR 输入的计算量，识别超过 12 张可用候选牌时退回单卡优先级。

### 直伤斩杀

伤害与召唤属于卡牌机制，统一放在 `battle/card_catalog.json` 的 `cards[].effects` 中，
不放在 Profile 的 `cards.<id>` 中。`leader_damage`、`self_damage` 均为 0～20，默认 0；
`damage_lowest_health` 默认为 false。内置蛇神之怒为对敌 3、自伤 2，特攻队长为
对敌 2、自伤 2；残虐的炸裂为对最低血量主战者造成 3 点。艾瑟拉配置自伤 2，
但不把其攻击力算作可立即执行的直伤。

双方血量分别从生命值盾牌区域读取；己方收拢/展开手牌使用不同 ROI，连续两次完整
读数一致才接受，动作后不复用旧血量。只在当前有可用的伤害候选牌时读取血量，
不会因为整副牌里带有伤害牌就每次读取。血量未知时不启用直伤斩杀；快梦的残虐的炸裂在
血量未知、只会打自己、或同血量会自伤致死时禁止使用。其他已配置的自伤在血量
已知时也必须保证使用后自身存活。

选择新计划前先搜索当前手牌可执行的直伤路线，检查费用、场位、次数、条件、剩余
动作预算，以及每一步伤害后的双方血量。优先选择耗费较少、张数较少的获胜路线，
已知手牌的直伤总上限不足以获胜时直接跳过斩杀搜索。
执行第一张后重新观察，不锁定剩余步骤。不把冻结、已攻击、不能打脸的随从或
条件疾驰算进斩杀；未模拟减伤、免疫、伤害触发和其他持续效果，因此这里只是按
配置伤害寻找直伤路线，胜利必须由结算画面确认。

通用层保留费用/斩杀搜索、动作预算和观察能力；快梦专属判断位于
`agent/battle_engine/strategies.py`。早期开发配置中的 `summon_count`、`leader_damage`、
`self_damage`、`damage_lowest_health` 已迁移到卡牌注册表，`prefer_after_followers` 已移除。
Profile 中残留这些字段会报未知字段，不能用打法配置覆写卡牌机制。

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
组合开始后会连续执行剩余步骤，每步重新识别手牌并校验能量、场地和使用次数，
不会插入其他单卡。若剩余步骤条件不再满足或观测持续失败，将停止任务并报错。

## 进化策略

- `enabled: true` 开启自动进化；每个己方回合最多成功进化一次。
- `after_play` 默认为 false：回合开始时先按当前场上顺序尝试进化已有随从。
- 若场上没有可进化随从，则在出牌后尝试进化本回合新打出的随从。
- 新随从优先按卡牌注册表的 `storm`（疾驰）特性选择，再按
  `card_priority` 的顺序选择。
- `type_order` 控制尝试 `normal` 或 `super` 进化的顺序；只填写
  `normal` 时不会消耗超进化。
- 内置快梦设置 `after_play: true`，出牌后统一选择进化对象，避免提前耗掉进化机会。
  `prefer_can_attack: true` 时，依次优先已确认身份的无条件疾驰、回合开始时已在场的
  随从、其他随从；同类再按 `card_priority` 和场上序号选择。设为 false 时只按
  `card_priority` 和序号选择。这是基于身份和入场时间的偏好，尚不识别冻结或实际攻击权限。
- 新出随从身份只在实际新增数量与召唤模型一致时绑定到位置，额外召唤物保留未知身份。
  数量异常或截图失败时清除位置身份，回退按场上顺序尝试，不会将召唤物误当作原卡。
  小木乃伊需唤灵 4 才获得疾驰；墓场尚未识别，因此不再将其标记为无条件疾驰。

## 攻击策略

`attacker_order` 支持从左到右、低攻击力优先和高攻击力优先。攻击阶段从同一帧的
蓝色攻击力锚点执行 OCR，只读取尚未尝试攻击的位置；从左到右模式不读取攻击力。
任一待攻击随从的数字缺失或不明确时，回退从右向左，
不把未知值当作 0。攻击后重新观察守护和随从数量；单个攻击者死亡时重排剩余序号，
出现无法可靠重排的数量变化时停止本次攻击阶段。

`clear_ward: true` 时优先攻击守护；其余按 `otherwise` 攻击主战者或最左侧敌方随从。
设置为不清守护且目标是主战者时，有守护便停止攻击，避免对被阻挡目标重复拖动。
`resume_play` 默认为 false，内置快梦开启：出牌后每尝试一次攻击，就重新识别手牌、
能量和盘面并尝试续牌。攻击腾出空位、谢幕曲获得手牌、攻击降低敌方血量后都可以
在同一回合继续出牌和重新寻找直伤斩杀。新入场随从可继续尝试攻击，原有攻击记录
按实际死亡位置重排；数量异常或观测失败时放弃不可靠身份，不因重新进入攻击阶段
而重置所有随从。攻击记录只是尝试记录，尚未识别每个随从的实际攻击权限。

整回合共享出牌次数、动作预算与进化状态；最多进化一次，达到动作上限或没有可用
出牌和未尝试攻击时结束。观察到胜负结算后直接返回，不再点击结束回合。
血量与攻击力 OCR 使用仓库截图核对位置并做单元测试，尚需授权实机验证。

零费用且可识别卡池没有基础零费牌时，攻击之间不反复展开手牌，回合末统一刷新记牌；
存在零费候选时仍按正常流程观察。此判断沿用当前基础费用识别能力，不新增减费预测。
记牌只有经过独立观察器两次完整确认后才缓存，手牌、牌库数量或记牌状态变化会重新确认；
缓存不用于出牌选择。已确认的胜负结果在当前回合内复用，未确认结果仍需重新读取。

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
