# astrbot_plugin_user_dossier

> 用户档案 · 让机器人真正"认识"每一位用户

根据对话自动总结、持续更新每位用户的个人档案，并在对话时把档案注入给 AI。
档案涵盖：**基础信息、喜好与性格、当前状态、事务偏好、经验教训、明确要求**。

## 特性

- 🤖 **AI 自主记录**：用户累计发言达到阈值后，自动注入一段提醒，由 AI 判断近期对话是否包含值得长期记住的信息，并自主调用工具记录
- 🖥️ **Web 管理面板**：在 WebUI 插件详情页打开「用户档案管理」，可视化查看/编辑档案、调整设置、触发更新
- 📄 **档案注入**：每轮对话把用户档案作为临时内容块注入（`extra_user_content_parts`），AI 自然"认识"你，且不破坏模型端的提示词缓存
- 🎓 **经验教训**：用户表达不满、指责或纠正 AI 时，自动总结出"以后应该怎么做 / 不应该怎么做"
- 🛠️ **完整管理指令**：查看、手动更新、直接教导、导出、清除、管理员操作
- 🔒 **本地存储**：档案只保存在 AstrBot 数据目录，不会发送给任何第三方服务
- 🧩 **零第三方依赖**：不需要额外安装任何 pip 包

## 安装

要求：AstrBot `>= 4.26.0`。

- 方式一：在 AstrBot WebUI 的「插件市场」中搜索 `astrbot_plugin_user_dossier` 安装；
- 方式二：手动克隆到 `data/plugins/` 目录：

```bash
cd data/plugins
git clone https://github.com/D1ff1culTT/astrbot_plugin_user_dossier
```

安装后在插件页重载（或重启 AstrBot）即可。

## 指令

| 指令 | 权限 | 说明 |
| --- | --- | --- |
| `/profile`（别名 `/档案`） | 所有人 | 指令组；直接发送会列出全部子指令 |
| `/profile view` | 所有人 | 查看自己的档案 |
| `/profile update` | 所有人 | 立即根据最近对话总结并更新自己的档案（后台 LLM 总结，不依赖工具调用能力） |
| `/profile teach <内容>` | 所有人 | 直接告诉 AI 一条要记住的要求，例如 `/profile teach 以后回答我简短一点，别用列表` |
| `/profile clear` | 所有人 | 清除自己的全部档案（含导出文件），需要按提示发送 `/profile clear confirm` 二次确认 |
| `/profile export` | 所有人 | 把档案导出为 JSON 文件发送给自己 |
| `/profile admin view <用户ID>` | 管理员 | 查看指定用户的档案 |
| `/profile admin clear <用户ID>` | 管理员 | 清除指定用户的档案 |

## Web 管理面板

在 AstrBot WebUI 的插件页打开本插件详情，即可进入「用户档案管理」视图：

- **档案总览**：列出全部用户档案（昵称 / 平台 / 条目数 / 更新时间），支持按昵称或 ID 搜索；
- **编辑档案**：增删改基础信息、喜好、事务偏好、经验教训、明确要求等条目，修改昵称与当前状态；
- **触发更新**：对指定用户立即执行一次对话总结（需要该用户近期有缓存的对话）；
- **插件设置**：在面板中直接调整全部配置项，保存后即时生效，与 WebUI 插件配置页共用同一份配置。

## 工作原理

1. **计数**：插件监听用户消息，同一用户累计发送 `remind_after_messages`（默认 20）条后，标记"待提醒"；
2. **提醒**：该用户下一次对话触发 LLM 请求时，注入一段内部提醒，让 AI 回顾最近对话、判断是否有值得长期记住的信息；
3. **记录**：AI 判断需要记录时调用 `update_user_profile` 工具，按类别（基础信息 / 喜好 / 状态 / 事务偏好 / 经验教训 / 明确要求）把一条条信息写入该用户的档案；
4. **注入**：档案更新后，之后的每轮对话都会把该用户的档案注入给 AI。

> 提醒与档案都通过 `extra_user_content_parts` 以**临时内容块**注入：只作用于本轮请求，不写入会话历史，也不会破坏提示词缓存。

> 如果使用的模型不支持 function calling，AI 将无法调用记录工具。此时可以：
> - 用 `/profile teach <内容>` 手动添加要求；
> - 用 `/profile update` 手动触发一次后台总结（使用 `summary_provider_id` 配置的模型或当前会话模型）。

## 配置

插件配置可在 WebUI 的插件管理页中修改：

| 配置项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `enabled` | bool | `true` | 总开关 |
| `remind_after_messages` | int | `20` | 累计多少条消息后触发一次档案维护提醒 |
| `tool_enabled` | bool | `true` | 是否注册并启用 `update_user_profile` 工具 |
| `inject_enabled` | bool | `true` | 是否在对话时注入用户档案 |
| `inject_max_chars` | int | `1200` | 注入档案的最大字符数，超长截断 |
| `context_size` | int | `30` | 手动总结时回顾的最近对话条数 |
| `summary_provider_id` | string | 空 | 档案总结使用的模型，留空则用当前会话模型 |
| `allow_admin_view` | bool | `true` | 是否允许管理员查看/清除他人档案 |

## 档案结构

档案保存在 `data/plugin_data/astrbot_plugin_user_dossier/profiles/`，每名用户一份 JSON：

```json
{
  "version": 1,
  "platform": "aiocqhttp",
  "user_id": "12345678",
  "display_name": "小明",
  "basic_info": ["性别：男", "职业：程序员"],
  "preferences": ["喜欢吃川菜", "性格比较直接"],
  "status": {
    "summary": "最近在准备考试，心情不错",
    "updated_at": "2026-10-11 12:00:00"
  },
  "task_preferences": ["回答时先给结论"],
  "lessons": ["不要用列表形式回答，用户更喜欢自然段"],
  "notes": ["称呼我为小明"],
  "stats": { "tool_updates": 12, "auto_updates": 3 },
  "created_at": "2026-10-01 09:00:00",
  "updated_at": "2026-10-11 12:00:00"
}
```

## 数据与隐私

- 档案仅保存在本机的 AstrBot 数据目录中；
- 总结时会把「现有档案 + 最近对话」发送给你自己配置的 LLM 服务（与正常对话相同的数据流向）；
- 随时可用 `/profile clear confirm` 删除自己的全部档案记录；
- 管理员（`allow_admin_view` 开启时）可以查看/清除他人档案，可根据需要关闭。

## 常见问题

**Q：AI 一直没有记录我的信息？**
A：确认 `enabled` 和 `tool_enabled` 均开启，且所用模型支持 function calling；也可以直接用 `/profile teach` 或 `/profile update`。

**Q：档案会占用很多 token 吗？**
A：注入时按 `inject_max_chars` 截断（默认 1200 字符），并且只注入当前对话用户的档案。

**Q：重启 AstrBot 后消息计数会清零吗？**
A：会。计数和"最近对话缓存"仅存在于内存中（用于触发提醒和手动总结）；已写入的档案本身是持久化的。

## 贡献

欢迎提交 Issue 与 PR。

## License

[AGPL-3.0](LICENSE)
