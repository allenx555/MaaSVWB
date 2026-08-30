# 人工解法格式

每个解法是 `assets/resource/solutions/` 下的独立 JSON 文件，文件名必须与
`id` 一致。坐标以横屏 `1280 × 720` 为基准。

## 基础字段

```json
{
    "id": "puzzle_001",
    "name": "盘面解密 001",
    "category": "puzzle",
    "reference_resolution": [
        1280,
        720
    ],
    "points": {
        "hand_1": [
            390,
            650
        ],
        "play_area": [
            640,
            420
        ]
    },
    "steps": []
}
```

`category` 可取 `tutorial` 或 `puzzle`。盘面解密应优先使用下列语义动作，
不在解法文件中填写坐标。所有序号均从左到右、从 `1` 开始。
序号和数量都以每一步执行时的当前盘面为准；随从离场并重新排列后，后续步骤
应填写重新排列后的 `attacker_index` 和 `ally_count`。

盘面解密可增加自动选关信息：

```json
{
    "navigation": {
        "display_name": "同时学习【守护】【突进】【疾驰】吧！",
        "name_pattern": ".*守护.*突(进|击).*疾驰.*",
        "categories": [
            {"display_name": "盘面解密", "pattern": "盘面解(密|谜)|盤面解(密|謎)", "scope": "tab"},
            {"display_name": "指定系列", "pattern": "指定系列", "scope": "tab"},
            {"display_name": "基本能力①", "pattern": "基本能力(①|1)", "scope": "list"}
        ],
        "entry_wait_ms": 3500,
        "search_swipes": 20
    }
}
```

`display_name` 用于日志，`name_pattern` 是 OCR 正则。配置后，任务会从盘面解密
列表识别并点击该关卡、点击“决定”、跳过入场提示、执行解法，最后等待重新返回列表。
`categories` 是从外到内的类别路径。`scope: "tab"` 在顶部固定区域识别，
`scope: "list"` 在可滚动列表识别，并按“列表内容先向下、再向上”的顺序寻找：
在本游戏列表中，列表向下时手指从下往上拖，列表向上时手指从上往下拖。
两个固定标签点击确认后，会先查找并点击 `list` 类别，直到右侧出现“决定”，
再查找具体关卡。若类别初始展开状态不同导致第一次未命中，会切换一次状态后重试。
点击“决定”后会先等待 `entry_wait_ms` 再开始处理入场提示，默认 3500 毫秒。
批量执行会在定位题名后检查同一条目左上角的“完成”和奖励区域的“已领取”；
两个标记都识别到时直接跳过该题，不点击“决定”。
可操作状态要求主战者框顶部横边和左侧竖边同时命中，避免加载画面的单条金线误判。
当前画面未命中时，会先让列表内容向下移动，再让列表内容向上移动；
`search_swipes` 是每个方向的最大拖动次数，默认 20，允许范围为 1 到 50。

## 动作

### 使用手牌

解法中的第一次 `play_card` 默认先点击右下角手牌区，将收拢的手牌展开，
然后再按 `hand_count` 和 `hand_index` 定位并拖动。出牌后手牌保持展开，
同一解法内后续 `play_card` 不会重复点击展开区域。特殊情况下可设置
`"expand_hand": true` 强制重新展开、设置 `false` 明确跳过，或用
`expand_delay_ms` 调整展开等待时间。

```json
{
    "action": "play_card",
    "hand_index": 2,
    "hand_count": 5,
    "after_ms": 1000
}
```

表示当前有 5 张手牌，使用从左到右第 2 张。

指定目标的法术或能力可以直接携带目标：

```json
{
    "action": "play_card",
    "hand_index": 2,
    "hand_count": 5,
    "target": {
        "type": "enemy_follower",
        "index": 1,
        "count": 2
    }
}
```

目标类型支持 `enemy_leader`、`ally_leader`、`enemy_follower` 和
`ally_follower`。随从目标需要同时填写当前随从总数 `count` 和目标序号 `index`。

### 随从攻击

```json
{
    "action": "attack",
    "attacker_index": 1,
    "ally_count": 3,
    "target": {
        "type": "enemy_leader"
    }
}
```

攻击敌方随从：

```json
{
    "action": "attack",
    "attacker_index": 2,
    "ally_count": 3,
    "target": {
        "type": "enemy_follower",
        "index": 2,
        "count": 2
    }
}
```

### 单独选择目标

```json
{
    "action": "select_target",
    "target": {
        "type": "ally_follower",
        "index": 1,
        "count": 3
    }
}
```

### 结束回合

```json
{
    "action": "end_turn"
}
```

### 跳过教程对话（内部动作）

```json
{
    "action": "skip_dialogue",
    "pipeline_node": "识别_教程主战者框可操作",
    "max_clicks": 30,
    "interval_ms": 350,
    "stable_hits": 2
}
```

`skip_dialogue` 每轮都会点击布局中的 `dialog_advance` 安全点，因此也能推进
没有继续箭头的“目标”说明遮罩。左上角出现主战者框代表盘面已经允许操作；
`stable_hits` 表示需要连续命中多少帧后退出，默认 2，最大为 5。
循环同时受 `max_clicks` 限制，超过上限仍未进入可操作状态会明确失败。
主战者框识别使用各职业共用的顶部金色外框，不依赖框内底色、职业文字或头像。

默认点击点位于“好的”按钮中心，普通对话和目标说明也允许在该位置推进。

实际触控位置统一维护在 `assets/resource/layouts/default.json`。进入真实战斗盘面后
只需校准这个布局文件一次，不需要逐关填写坐标。

## 底层动作

以下动作仅用于暂时无法用语义动作表达的特殊界面。

### 点击

```json
{
    "action": "tap",
    "point": "end_turn",
    "after_ms": 1000
}
```

`point` 也可以直接写成 `[x, y]`。

### 拖动

```json
{
    "action": "swipe",
    "from": "hand_1",
    "to": "play_area",
    "duration_ms": 350,
    "after_ms": 1200
}
```

### 等待

```json
{
    "action": "wait",
    "duration_ms": 1500
}
```

### 安卓按键

```json
{
    "action": "key",
    "keycode": 4
}
```

例如，Android 返回键的 keycode 是 `4`。

### 图像校验

```json
{
    "action": "verify",
    "pipeline_node": "校验_胜利界面",
    "retries": 5,
    "interval_ms": 1000
}
```

校验节点在 `assets/resource/pipeline/` 中定义。任何动作失败或校验超过重试次数，
当前解法都会立即停止，以免继续误操作。

### 动作后置条件

出牌、攻击等关键动作不应只依赖固定等待。可以要求指定布局区域发生变化：

```json
{
    "action": "play_card",
    "hand_index": 2,
    "hand_count": 2,
    "change_roi": "battle_board",
    "change_threshold": 2.5,
    "change_settle_ms": 350,
    "post_timeout_ms": 5000
}
```

`change_roi` 引用 `assets/resource/layouts/default.json` 的 `regions`。执行器会先保存动作前
截图，等待画面稳定后比较该区域；没有达到变化阈值就终止。

也可以等待 Pipeline 状态出现或消失：

```json
{
    "action": "end_turn",
    "wait_for": "识别_对方回合",
    "wait_until_gone": "识别_己方回合",
    "post_timeout_ms": 8000,
    "post_interval_ms": 300
}
```

## 接入桌面前端

新增 JSON 后，在对应的 `assets/catalog/*_catalog.json` 中加入同 ID 项即可。
桌面前端以同名解法文件是否存在判断该项目能否选择：

```json
{
    "id": "puzzle_001",
    "name": "同时学习【守护】【突进】【疾驰】吧！",
    "series": "指定系列",
    "group": "基本能力1"
}
```

最后运行 `python tools/generate_interface.py`。`assets/interface.json` 是生成文件，目录与
实际存在的解法文件才是任务清单的唯一数据源。
