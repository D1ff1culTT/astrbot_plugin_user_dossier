"""调用 LLM 对最近对话做总结，产出档案更新数据。

本模块只负责提示词构建与结果解析，实际的 LLM 调用发生在 main.py 中
（便于统一做并发限制与异常处理）。当模型不支持工具调用时，
`/profile update` 指令依赖这里的后台总结作为兜底。
"""

from __future__ import annotations

import json
import re
from typing import Any

MAX_DIALOGUE_CHARS = 20000
"""总结时纳入提示词的对话文本上限，超出时保留最新的部分。"""

SUMMARY_SYSTEM_PROMPT = """你是一个"用户档案整理助手"。你的任务是根据【最近对话记录】和【现有档案 JSON】，输出更新后的完整档案 JSON。

记录原则：
1. 只记录与用户本人相关、值得长期保留的稳定信息；一次性的寒暄闲聊、"在吗"、"好的"之类内容不要记录。
2. 保留现有档案中仍然有效的条目；新信息与旧信息冲突、或确认旧信息已经失效时，把被取代的旧条目原文放进 removed 对象对应字段，再把新信息写进对应字段。
3. 特别注意用户表达不满、指责或纠正 AI 的内容（例如"不对"、"我说的是…"、"你错了"、"别这样"），从中提炼出"以后应该怎么做 / 不应该怎么做"，写入 lessons。
4. 用户明确提出的要求（例如"以后回答简短一点"、"别用列表"）写入 notes。
5. status.summary 记录用户的"阶段性总状态"：例如备考、放假、出差、换工作、生病休养等会持续一段时间的情况，可附带心情基调（如"备考中，压力较大"）。不要写入一次性的具体事务或正在做的琐事（如"正在做第 3 题"、"正在吃午饭"），这类内容不记录；已过时的阶段性状态（如"放假"但对话显示已开学）应被新状态取代。
6. 宁可少记也不要臆测：只总结对话中明确出现的信息，不要编造。
7. 输出必须是合法的 JSON 对象，不要输出任何解释文字，不要使用 Markdown 代码块。

JSON 字段说明（保持这些字段名）：
- display_name: 字符串，用户常用的昵称，不知道就留空字符串
- basic_info: 字符串数组，基础信息（性别、年龄、职业、所在地等）
- preferences: 字符串数组，喜好与性格（喜欢/讨厌的事物、爱好、性格特点）
- status: 对象 {"summary": "一句话描述最新状态", "updated_at": "保持原值或留空"}
- task_preferences: 字符串数组，对 AI 完成任务的方式的偏好与注意事项
- lessons: 字符串数组，用户不满或纠正后总结出的正确做法
- notes: 字符串数组，用户明确要求记住的事项
- removed: 对象，把需要从档案中删除的旧条目按字段归类，例如 {"basic_info": ["住在北京"]}；没有需要删除的内容时写 {}。删除时请使用与现有档案完全一致的原文。
"""


def build_summary_prompt(
    profile: dict[str, Any],
    dialogue: list[dict[str, str]],
    max_dialogue_chars: int = MAX_DIALOGUE_CHARS,
) -> str:
    """构建总结请求的用户提示词。"""
    profile_json = json.dumps(
        {
            key: profile.get(key)
            for key in (
                "display_name",
                "basic_info",
                "preferences",
                "status",
                "task_preferences",
                "lessons",
                "notes",
            )
        },
        ensure_ascii=False,
        indent=2,
    )
    dialogue_text = (
        "\n".join(
            "{role}：{content}".format(
                role="用户" if message.get("role") == "user" else "助手",
                content=str(message.get("content") or "").strip(),
            )
            for message in dialogue
        )
        or "（暂无对话记录）"
    )
    if max_dialogue_chars > 0 and len(dialogue_text) > max_dialogue_chars:
        dialogue_text = "（较早的对话已省略）\n" + dialogue_text[-max_dialogue_chars:]

    return (
        f"【现有档案 JSON】\n{profile_json}\n\n"
        f"【最近对话记录】\n{dialogue_text}\n\n"
        "【任务】输出更新后的完整档案 JSON。如果没有值得记录的新信息，原样输出现有档案 JSON。"
    )


def _largest_json_object(text: str) -> str | None:
    """扫描出最后一个花括号配平的 JSON 对象（正确跳过字符串内的括号与转义）。"""
    start = depth = 0
    in_string = escaped = False
    best: str | None = None
    for index, char in enumerate(text):
        if in_string:
            if char == "\\" and not escaped:
                escaped = True
                continue
            if char == '"' and not escaped:
                in_string = False
            escaped = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth > 0:
            depth -= 1
            if depth == 0:
                best = text[start : index + 1]
    return best


def parse_profile_json(text: str) -> dict[str, Any] | None:
    """从 LLM 回复中容错地提取 JSON 对象。"""
    if not text:
        return None
    raw = text.strip()

    fenced = re.search(r"```(?:json)?\s*(.+?)```", raw, re.DOTALL)
    if fenced:
        raw = fenced.group(1).strip()

    candidate = _largest_json_object(raw)
    if candidate is None:
        return None
    # 先按原样解析，失败再清理常见的尾随逗号后重试
    for attempt in (candidate, re.sub(r",\s*([}\]])", r"\1", candidate)):
        try:
            data = json.loads(attempt)
        except json.JSONDecodeError:
            continue
        return data if isinstance(data, dict) else None
    return None
