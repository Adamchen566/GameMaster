# AI 威胁模型

范围：v0.6 引入的 AI 玩家（`app/agents/`）和 AI 主持（`app/gm/`）。

核心立场：**模型不可信，模型也不拥有规则。** 不指望用提示词让模型“听话”；每一条防线都放在模型之外的代码里，并且有测试。

## 1. 信任边界

```text
玩家输入（昵称）──┐
                  v
GameState（全部秘密）──build_player_view──> PlayerView ──build_observation──> 模型
        │                                                                      │
        └──public_log──> PublicEntry ──> AI 主持 ──> 模型                       │
                                                                               v
引擎 apply_action <── to_action(view, decision) <── decision_from_data <── 模型的回答
```

| 边界 | 进去的东西 | 出来的东西 | 把关的代码 |
| --- | --- | --- | --- |
| 状态 → 玩家模型 | 只有该席位的 `PlayerView` + 公开日志 + 自己的笔记 | — | `agents/contract.py: build_observation` |
| 状态 → 主持模型 | 只有 `PublicEntry` | — | `game/public_log.py` |
| 玩家模型 → 引擎 | — | 一个动作提议 | `to_action`，然后引擎再校验一次 |
| 主持模型 → 玩家 | — | 语气、一句氛围话、规则提示的**键** | `gm/narrator.py` |

## 2. 威胁与对策

| 威胁 | 具体场景 | 对策 | 残余风险 |
| --- | --- | --- | --- |
| 秘密泄露 | 模型被诱导说出别人的角色 | 模型根本拿不到：观察只从 `PlayerView` 构造；主持只拿公开事件 | 模型可以**猜**，和真人一样 |
| 秘密泄露 | 事件日志含角色和每张任务牌 | `public_log` 丢掉 `GameStarted`、单人投票牌、单人任务牌 | 新增事件类型时必须决定是否公开；未列出的类型默认丢弃 |
| Prompt injection | 昵称写成“忽略之前的指令…” | 昵称只作为 JSON 字符串值出现在用户消息里，系统提示是固定文本；昵称去掉控制字符、压成单行、最多 20 字 | 模型仍可能被昵称影响**打法**；它能做的最坏的事是下一步合法的烂棋 |
| 越权动作 | 模型替别人投票、跳阶段、在非刺杀阶段开枪 | 决定里没有“谁在行动”字段，动作一律以本席位名义发出；动作类型必须在 `legal_actions` 里 | 无 |
| 越权动作 | 模型点名不存在或不允许的玩家 | 玩家 id 必须来自该动作的 `targets`；队伍人数、重复成员都检查 | 无 |
| 越权动作 | 好人模型被说服出失败牌 | `can_fail` 为假时拒绝失败牌；引擎也会拒绝 | 无 |
| 幻觉规则 | 主持编造不存在的规则 | `rule_hint` 是固定集合里的键，展示的文字来自 `gm/templates.py` | 氛围话是自由文本，可能含蓄地说错；事实句永远单独展示 |
| 幻觉事实 | 主持把失败说成成功 | 事实句由模板生成、始终展示；模型文字只是附加的氛围 | 氛围话与事实句矛盾时玩家会看到两句话；v0.7 评测统计 |
| 超时 | 模型 30 秒不回 | 玩家 8 秒、主持 3 秒，SDK 自动重试关闭；超时即回退 | 接入对局时 AI 回合要放到后台任务，否则真人的请求会等模型（v0.6 第二部分） |
| 坏输出 | 不是 JSON、缺字段、类型不对 | 结构化输出 + 严格类型检查（不做类型转换）；一次带原因的重试，再错回退 | 无 |
| 费用失控 | 重试风暴、长对局 | 每局 token 上限 `TokenBudget`；每回合最多 2 次调用；主持每个事件只生成一次 | 上限在调用前检查、调用后记账，最后一次调用可能超出一点 |
| 服务不可用 | 密钥失效、限流、断网 | 统一映射成 `ModelUnavailable` → 回退到随机合法 bot / 模板 | 回退后的 AI 水平下降，但对局不中断 |
| 模型拒答 | 安全策略拒绝 | 请求带服务端 fallback；仍拒绝则回退 | 同上 |
| 记忆污染 | 模型把别人的话当成自己的笔记 | 笔记只来自模型自己上一回合的 `note`，最多 400 字；目前游戏里没有玩家发言 | 加入发言功能时要重新评估 |

## 3. 回退路径

| 情况 | AI 玩家 | AI 主持 |
| --- | --- | --- |
| 没有配置模型 | 随机合法 bot | 模板 |
| 超时 | 立即回退，不重试 | 模板 |
| 服务不可用 / 拒答 | 立即回退，不重试 | 模板 |
| 输出格式或内容不合法 | 重试一次并说明原因；再错回退 | 模板 |
| 预算用完 | 不再调用模型，直接回退 | 模板 |

回退的 bot 就是 v0.3 的 `policy_fallback`：只读 `PlayerView`，永远给出合法动作。所以**每个回合都以一个合法动作结束**，对局不会卡在模型上。

## 4. 测试对应

| 保证 | 测试 |
| --- | --- |
| 每个角色的观察只含规则允许的信息 | `tests/agents/test_contract.py::test_observation_matrix_for_every_role` |
| 观察里除了自己的角色，不出现任何角色名 | `…::test_observation_names_no_role_but_your_own` |
| 观察不含 seed、单人任务牌 | `…::test_observation_never_contains_the_seed_or_individual_mission_cards` |
| 非法队伍、非本人动作、好人出失败牌、乱点刺杀目标都被拒绝 | `tests/agents/test_contract.py` 的 `to_action` 部分 |
| 注入的昵称只是数据里的一个名字 | `tests/agents/test_llm_player.py::test_injected_name_stays_inside_the_data_and_is_only_a_name` |
| 完全被控制的模型也只能得到合法动作 | `…::test_a_fully_compromised_model_still_cannot_make_an_illegal_move` |
| 邪恶方模型收到的内容里没有梅林是谁 | `…::test_a_compromised_model_cannot_learn_who_merlin_is` |
| 超时 / 不可用 / 拒答立即回退；坏输出重试一次 | `tests/agents/test_llm_player.py` |
| 预算用完后零调用 | `…::test_spent_budget_means_no_model_call_at_all` |
| 公开日志不含角色、seed、单张任务牌 | `tests/game/test_public_log.py` |
| 主持不能自造规则文字；同一事件只生成一次 | `tests/gm/test_narrator.py` |

## 5. 还没有覆盖的

| 项 | 说明 |
| --- | --- |
| 真实模型的行为 | 以上测试用的是脚本化的假模型，证明的是“模型无论回答什么都越不了权”。真实模型打得好不好、会不会被昵称带偏打法，要到 v0.7 评测 |
| 真实 API 调用 | Claude 适配器只对着假的 SDK 客户端测过请求内容和错误映射，没有用真实密钥发过请求 |
| 接入对局 | 这些模块还没有接进 `GameService` 和界面；接入时 AI 回合要改成后台任务 |
| 记忆持久化 | 笔记目前由调用方传入，还没有落库 |
