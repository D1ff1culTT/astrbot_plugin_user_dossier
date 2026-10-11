"""用户档案的持久化存储、合并与渲染。

档案以 JSON 文件形式保存在 AstrBot 数据目录下，每名用户一份，例如：
``data/plugin_data/astrbot_plugin_user_dossier/profiles/aiocqhttp_12345_1a2b3c4d5e.json``

并发说明：本模块的公开方法全部是「同步文件 IO、无 await 挂起点」的原子操作，
因此在当前实现下调用方即使不加锁也不会观察到中间状态。若将来把文件 IO 改为
``asyncio.to_thread`` 等挂起操作，必须同时把 ``load`` 纳入同一把锁，否则会出现
读-改-写竞态。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

LIST_LIMIT = 120
"""单个列表字段最多保留的条目数，超出时丢弃最旧的条目。"""

CONTENT_MAX_CHARS = 500
"""单条档案信息的最大字符数，超出时截断。"""

CACHE_LIMIT = 256
"""内存中最多缓存的档案数量，超出时按写入顺序淘汰。"""

LOCK_LIMIT = 512
"""互斥锁的最大数量，超出时淘汰未被持有的锁。"""

LIST_FIELDS: tuple[str, ...] = (
    "basic_info",
    "preferences",
    "task_preferences",
    "lessons",
    "notes",
)

CATEGORY_LABELS: dict[str, str] = {
    "basic": "基础信息",
    "preference": "喜好与性格",
    "status": "当前状态",
    "task_preference": "事务偏好",
    "lesson": "经验教训",
    "note": "明确要求",
}

CATEGORY_TO_FIELD: dict[str, str] = {
    "basic": "basic_info",
    "preference": "preferences",
    "task_preference": "task_preferences",
    "lesson": "lessons",
    "note": "notes",
}

FIELD_LABELS: dict[str, str] = {
    field: CATEGORY_LABELS[category] for category, field in CATEGORY_TO_FIELD.items()
}

_UNSAFE_TAG_RE = re.compile(r"</?(?:user_profile|dossier_reminder)\b[^>]*>", re.IGNORECASE)


def now_str() -> str:
    """返回可读的本地时间字符串。"""
    return time.strftime("%Y-%m-%d %H:%M:%S")


def clean_content(text: Any) -> str:
    """清洗一条档案信息：折叠空白、剥离注入用标签、限制长度。"""
    value = _UNSAFE_TAG_RE.sub("", str(text or ""))
    value = re.sub(r"\s+", " ", value).strip()
    return value[:CONTENT_MAX_CHARS]


def sanitize_filename(text: str) -> str:
    """把任意字符串转换为安全的文件名片段。"""
    cleaned = re.sub(r"[^\w.-]+", "_", str(text), flags=re.UNICODE)
    return cleaned.strip("._") or "unknown"


def _file_stem(platform: str, user_id: str) -> str:
    """生成档案文件名主干，附加摘要避免清洗后的文件名碰撞。"""
    raw = f"{platform}:{user_id}".encode()
    digest = hashlib.sha1(raw).hexdigest()[:10]  # 仅用于区分文件名，非安全用途
    return f"{sanitize_filename(platform)}_{sanitize_filename(user_id)}_{digest}"


def new_profile(platform: str, user_id: str, display_name: str = "") -> dict[str, Any]:
    """构造一份空白档案。"""
    return {
        "version": 1,
        "platform": platform,
        "user_id": user_id,
        "display_name": display_name,
        "basic_info": [],
        "preferences": [],
        "status": {"summary": "", "updated_at": ""},
        "task_preferences": [],
        "lessons": [],
        "notes": [],
        "stats": {"tool_updates": 0, "auto_updates": 0},
        "created_at": now_str(),
        "updated_at": now_str(),
    }


def _normalize_profile(data: dict[str, Any], platform: str, user_id: str) -> dict[str, Any]:
    """把磁盘上的原始数据规范化为完整档案结构，容忍字段缺失或类型错误。"""
    profile = new_profile(platform, user_id)
    profile.update({k: v for k, v in data.items() if k in profile})

    for field in LIST_FIELDS:
        items = profile.get(field)
        if isinstance(items, list):
            profile[field] = [str(item).strip() for item in items if str(item).strip()]
        else:
            profile[field] = []

    status = profile.get("status")
    if not isinstance(status, dict):
        status = {}
    profile["status"] = {
        "summary": clean_content(status.get("summary")),
        "updated_at": str(status.get("updated_at") or "").strip(),
    }

    stats = profile.get("stats")
    if not isinstance(stats, dict):
        stats = {}
    profile["stats"] = {
        key: stats.get(key) if isinstance(stats.get(key), int) else 0
        for key in ("tool_updates", "auto_updates")
    }

    profile["platform"] = platform
    profile["user_id"] = user_id
    profile["display_name"] = clean_content(profile.get("display_name"))
    return profile


def profile_has_content(profile: dict[str, Any] | None) -> bool:
    """判断档案中是否存在任何有效信息。"""
    if not profile:
        return False
    if any(profile.get(field) for field in LIST_FIELDS):
        return True
    status = profile.get("status") or {}
    return bool(str(status.get("summary") or "").strip())


def count_entries(profile: dict[str, Any] | None) -> int:
    """统计档案中的信息条目数。"""
    if not profile:
        return 0
    total = sum(len(profile.get(field) or []) for field in LIST_FIELDS)
    status = profile.get("status") or {}
    if str(status.get("summary") or "").strip():
        total += 1
    return total


def render_profile_text(profile: dict[str, Any], max_chars: int = 1200) -> str:
    """把档案渲染为面向 LLM 的紧凑文本。"""
    lines: list[str] = []
    display_name = str(profile.get("display_name") or "").strip()
    if display_name:
        lines.append(f"昵称：{display_name}")

    status = profile.get("status") or {}
    summary = str(status.get("summary") or "").strip()
    if summary:
        updated = str(status.get("updated_at") or "").strip()
        suffix = f"（更新于 {updated}）" if updated else ""
        lines.append(f"当前状态：{summary}{suffix}")

    for field in LIST_FIELDS:
        items = profile.get(field) or []
        if items:
            lines.append(f"{FIELD_LABELS[field]}：" + "；".join(str(item) for item in items))

    text = "\n".join(lines)
    if max_chars > 0 and len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n…（档案过长，已截断）"
    return text


def merge_profile_data(profile: dict[str, Any], incoming: dict[str, Any]) -> bool:
    """把一份（通常来自 LLM 的）档案数据合并进现有档案，返回是否有变化。

    列表字段做追加去重；``incoming["removed"]`` 中列出的旧条目会被删除，
    用于让 LLM 表达「旧信息已被取代」。
    """
    if not isinstance(incoming, dict):
        return False
    changed = False

    display_name = clean_content(incoming.get("display_name"))
    if display_name and display_name != profile.get("display_name"):
        profile["display_name"] = display_name
        changed = True

    for field in LIST_FIELDS:
        items = incoming.get(field)
        if not isinstance(items, list):
            continue
        current = profile.setdefault(field, [])
        for item in items:
            text = clean_content(item)
            if text and text not in current:
                current.append(text)
                changed = True
        if len(current) > LIST_LIMIT:
            del current[: len(current) - LIST_LIMIT]

    removed = incoming.get("removed")
    if isinstance(removed, dict):
        for field in LIST_FIELDS:
            drop = removed.get(field)
            if not isinstance(drop, list):
                continue
            drop_set = {str(item).strip() for item in drop if str(item).strip()}
            if not drop_set:
                continue
            current = profile.get(field) or []
            kept = [item for item in current if item not in drop_set]
            if len(kept) != len(current):
                profile[field] = kept
                changed = True

    status = incoming.get("status")
    if isinstance(status, dict):
        summary = clean_content(status.get("summary"))
        current_summary = str((profile.get("status") or {}).get("summary") or "").strip()
        if summary and summary != current_summary:
            profile["status"] = {"summary": summary, "updated_at": now_str()}
            changed = True

    if changed:
        profile["updated_at"] = now_str()
    return changed


class ProfileStore:
    """档案的读写与并发控制。"""

    def __init__(self, base_dir: Path, logger: Any = None) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._logger = logger
        self._cache: dict[str, dict[str, Any]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    # ------------------------------------------------------------------ 基础

    @staticmethod
    def cache_key(platform: str, user_id: str) -> str:
        return f"{platform}:{user_id}"

    def _path(self, platform: str, user_id: str) -> Path:
        return self.base_dir / f"{_file_stem(platform, user_id)}.json"

    def _export_path(self, platform: str, user_id: str) -> Path:
        return self.base_dir / "exports" / f"profile_{_file_stem(platform, user_id)}.json"

    def _lock_for(self, key: str) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
            if len(self._locks) > LOCK_LIMIT:
                for old_key, old_lock in list(self._locks.items()):
                    if old_key != key and not old_lock.locked():
                        self._locks.pop(old_key, None)
                        break
        return lock

    def _remember(self, key: str, profile: dict[str, Any]) -> None:
        self._cache[key] = profile
        if len(self._cache) > CACHE_LIMIT:
            oldest = next(iter(self._cache))
            if oldest != key:
                self._cache.pop(oldest, None)

    def _quarantine(self, path: Path, exc: Exception) -> None:
        """把损坏的档案文件改名隔离，避免后续写入覆盖原始数据。"""
        bad_path = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
        try:
            path.replace(bad_path)
            hint = f"已隔离为 {bad_path.name}"
        except OSError:
            hint = "隔离失败"
        if self._logger:
            self._logger.error(f"[user_dossier] 档案损坏（{path.name}），{hint}: {exc}")

    # ------------------------------------------------------------------ 读写

    async def load(self, platform: str, user_id: str, create: bool = True) -> dict[str, Any] | None:
        """读取档案；create 为 False 且档案不存在时返回 None。"""
        key = self.cache_key(platform, user_id)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        profile: dict[str, Any] | None = None
        path = self._path(platform, user_id)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("档案根节点不是 JSON 对象")
                profile = _normalize_profile(data, platform, user_id)
            except (OSError, ValueError, UnicodeDecodeError) as exc:
                self._quarantine(path, exc)

        if profile is None:
            if not create:
                return None
            profile = new_profile(platform, user_id)

        self._remember(key, profile)
        return profile

    async def _save(self, platform: str, user_id: str, profile: dict[str, Any]) -> None:
        """原子写盘（临时文件 + 替换），写盘成功后再更新内存缓存。"""
        path = self._path(platform, user_id)
        tmp_path = path.with_name(path.name + ".tmp")
        payload = json.dumps(profile, ensure_ascii=False, indent=2)
        tmp_path.write_text(payload, encoding="utf-8")
        os.replace(tmp_path, path)
        self._remember(self.cache_key(platform, user_id), profile)

    # ------------------------------------------------------------------ 更新

    async def upsert(
        self,
        platform: str,
        user_id: str,
        display_name: str,
        category: str,
        content: str,
    ) -> str:
        """按类别写入一条信息，返回给调用方（LLM）的回执文本。"""
        category = (category or "").strip().lower()
        content = clean_content(content)
        if not content:
            return "记录失败：内容为空。"
        if category not in CATEGORY_LABELS:
            valid = "、".join(f"{k}（{v}）" for k, v in CATEGORY_LABELS.items())
            return f"记录失败：category 必须是以下之一：{valid}"

        key = self.cache_key(platform, user_id)
        lock = self._lock_for(key)
        async with lock:
            profile = await self.load(platform, user_id, create=True)
            assert profile is not None

            clean_name = clean_content(display_name)
            if clean_name:
                profile["display_name"] = clean_name

            if category == "status":
                current = str((profile.get("status") or {}).get("summary") or "").strip()
                if current == content:
                    return "【当前状态】已是相同内容，未重复更新。"
                profile["status"] = {"summary": content, "updated_at": now_str()}
                receipt = f"已更新【当前状态】：{content}"
            else:
                field = CATEGORY_TO_FIELD[category]
                items: list[str] = profile.setdefault(field, [])
                if content in items:
                    return f"【{CATEGORY_LABELS[category]}】中已有该信息，未重复记录。"
                items.append(content)
                if len(items) > LIST_LIMIT:
                    del items[: len(items) - LIST_LIMIT]
                receipt = f"已记录到【{CATEGORY_LABELS[category]}】：{content}"

            stats = profile.setdefault("stats", {})
            stats["tool_updates"] = int(stats.get("tool_updates", 0)) + 1
            profile["updated_at"] = now_str()
            await self._save(platform, user_id, profile)
            return receipt

    async def merge_from_llm(
        self,
        platform: str,
        user_id: str,
        display_name: str,
        data: dict[str, Any],
    ) -> bool:
        """合并一份 LLM 总结出的档案数据，返回是否有变化。"""
        key = self.cache_key(platform, user_id)
        lock = self._lock_for(key)
        async with lock:
            profile = await self.load(platform, user_id, create=True)
            assert profile is not None

            changed = merge_profile_data(profile, data or {})
            clean_name = clean_content(display_name)
            if clean_name and clean_name != profile.get("display_name"):
                profile["display_name"] = clean_name
                changed = True
            if changed:
                stats = profile.setdefault("stats", {})
                stats["auto_updates"] = int(stats.get("auto_updates", 0)) + 1
                profile["updated_at"] = now_str()
                await self._save(platform, user_id, profile)
            return changed

    async def clear(self, platform: str, user_id: str) -> bool:
        """删除档案及其导出文件，返回是否确实删除了档案文件。"""
        key = self.cache_key(platform, user_id)
        lock = self._lock_for(key)
        async with lock:
            self._cache.pop(key, None)
            profile_path = self._path(platform, user_id)
            removed = False
            for path in (profile_path, self._export_path(platform, user_id)):
                if not path.exists():
                    continue
                try:
                    path.unlink()
                    if path == profile_path:
                        removed = True
                except OSError as exc:
                    if self._logger:
                        self._logger.warning(f"[user_dossier] 删除失败 {path.name}: {exc}")
            return removed

    async def export_file(self, platform: str, user_id: str) -> Path | None:
        """把档案导出为独立 JSON 文件，档案为空时返回 None。"""
        profile = await self.load(platform, user_id)
        if not profile or not profile_has_content(profile):
            return None
        path = self._export_path(platform, user_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
