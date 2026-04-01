#!/usr/bin/env python3
"""
My AI Agent - Agent循环实现
基于 learn-claude-code 教程 s01-s12

核心理念: One loop & dispatch map is all you need

支持的API类型:
- anthropic: Anthropic API (默认)
- openai: OpenAI兼容API

工具系统 (s02):
- bash: 执行shell命令
- read_file: 读取文件内容
- write_file: 创建或覆盖文件
- edit_file: 精确替换文件内容

任务规划 (s03):
- TodoWrite: 管理任务列表，跟踪进度

子Agent (s04):
- task: 派发子任务给独立的子Agent，返回执行摘要

技能加载 (s05):
- load_skill: 按需加载技能知识，两层注入避免系统提示膨胀

上下文压缩 (s06):
- compact: 手动压缩上下文，保存对话历史
- micro_compact: 静默压缩非read_file的tool_result
- auto_compact: 自动在token阈值时压缩

任务系统 (s07):
- task_create: 创建任务
- task_get: 获取任务详情
- task_update: 更新任务状态
- task_list: 列出所有任务

后台任务 (s08):
- background: 在后台启动长时间运行的任务
- get_background_tasks: 获取后台任务状态和结果

Agent团队 (s09):
- team_create: 创建Agent团队
- team_assign: 向团队分配任务
- team_status: 获取团队状态

团队协议 (s10):
- Protocol: 标准化的Agent通信协议
- 协作规则和消息格式

自主Agent (s11):
- autonomous: 启动自主Agent，自主决策执行直到目标完成
- autonomous_status: 获取自主Agent状态
- Goal: 目标定义和停止条件

工作树任务隔离 (s12):
- worktree_create: 创建隔离的工作树
- worktree_list: 列出所有工作树
- worktree_remove: 删除工作树
- WorktreeTask: 隔离任务执行环境
"""

import os
import subprocess
import re
import json
import uuid
import glob
import yaml
import time
import threading
import queue
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable, Tuple, Union
from dataclasses import dataclass, field, asdict
from enum import Enum
from abc import ABC, abstractmethod
from dotenv import load_dotenv

# 加载环境变量
load_dotenv(override=True)

# 配置
WORKDIR = Path.cwd()
API_TYPE = os.environ.get("API_TYPE", "anthropic").lower()  # anthropic 或 openai
API_KEY = os.environ.get("API_KEY") or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY")
BASE_URL = os.environ.get("BASE_URL") or os.environ.get("ANTHROPIC_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
MODEL = os.environ.get("MODEL_ID", "claude-3-5-sonnet-20241022" if API_TYPE == "anthropic" else "gpt-4o")

if not API_KEY:
    print("错误: 请设置 API_KEY 环境变量")
    print("支持的配置方式:")
    print("  - API_KEY + BASE_URL + MODEL_ID + API_TYPE")
    print("  - ANTHROPIC_API_KEY + ANTHROPIC_BASE_URL (API_TYPE=anthropic)")
    print("  - OPENAI_API_KEY + OPENAI_BASE_URL (API_TYPE=openai)")
    exit(1)

# 初始化客户端
if API_TYPE == "openai":
    from openai import OpenAI
    client_kwargs = {"api_key": API_KEY}
    if BASE_URL:
        client_kwargs["base_url"] = BASE_URL
    client = OpenAI(**client_kwargs)
    print(f"✅ 使用 OpenAI 兼容 API")
else:
    from anthropic import Anthropic
    client_kwargs = {"api_key": API_KEY}
    if BASE_URL:
        client_kwargs["base_url"] = BASE_URL
    client = Anthropic(**client_kwargs)
    print(f"✅ 使用 Anthropic API")

# ============================================================
# TodoManager (s03: 任务规划)
# ============================================================

class TodoStatus(Enum):
    """任务状态"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


@dataclass
class TodoItem:
    """任务项"""
    id: str
    content: str
    status: str = "pending"
    
    def to_dict(self) -> dict:
        return {"id": self.id, "content": self.content, "status": self.status}


class TodoManager:
    """
    任务管理器 - s03
    
    功能:
    - 管理任务列表
    - 跟踪任务状态 (pending → in_progress → completed)
    - Nag reminder: 3轮未更新时提醒
    """
    
    def __init__(self):
        self.todos: List[TodoItem] = []
        self._rounds_since_update = 0
        self._last_update_round = 0
    
    def _generate_id(self) -> str:
        """生成唯一ID"""
        import random
        import string
        return ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    
    def update(self, todos_data: List[Dict[str, Any]]) -> str:
        """
        更新任务列表
        
        Args:
            todos_data: 任务列表，每项包含 id, content, status
        
        Returns:
            操作结果消息
        """
        # 如果是全新任务列表（空或第一项无id），生成新列表
        if not todos_data or not todos_data[0].get("id"):
            self.todos = [
                TodoItem(
                    id=item.get("id") or self._generate_id(),
                    content=item.get("content", ""),
                    status=item.get("status", "pending")
                )
                for item in todos_data
            ]
        else:
            # 更新现有任务
            for item in todos_data:
                item_id = item.get("id")
                new_status = item.get("status")
                
                # 查找并更新
                for todo in self.todos:
                    if todo.id == item_id:
                        if new_status:
                            todo.status = new_status
                        if item.get("content"):
                            todo.content = item["content"]
                        break
                else:
                    # 新任务
                    self.todos.append(TodoItem(
                        id=item_id or self._generate_id(),
                        content=item.get("content", ""),
                        status=item.get("status", "pending")
                    ))
        
        # 重置计数器
        self._rounds_since_update = 0
        self._last_update_round = 0
        
        return self.format_todos()
    
    def format_todos(self) -> str:
        """格式化任务列表为字符串"""
        if not self.todos:
            return "当前没有任务"
        
        lines = ["📋 任务列表:"]
        status_icons = {
            "pending": "⏳",
            "in_progress": "🔄",
            "completed": "✅"
        }
        
        for todo in self.todos:
            icon = status_icons.get(todo.status, "⏳")
            lines.append(f"  {icon} [{todo.id}] {todo.content} ({todo.status})")
        
        return "\n".join(lines)
    
    def increment_round(self) -> None:
        """增加轮次计数"""
        self._rounds_since_update += 1
        self._last_update_round += 1
    
    def should_nag(self) -> bool:
        """是否应该提醒更新任务"""
        # 有未完成任务且3轮未更新
        has_incomplete = any(t.status != "completed" for t in self.todos)
        return has_incomplete and self._rounds_since_update >= 3
    
    def get_nag_message(self) -> str:
        """获取提醒消息"""
        if not self.todos:
            return ""
        
        incomplete = [t for t in self.todos if t.status != "completed"]
        if not incomplete:
            return ""
        
        return f"""⚠️ 提醒: 已有 {self._rounds_since_update} 轮未更新任务状态。

当前未完成任务:
{self.format_todos()}

请使用 TodoWrite 工具更新任务进度，或标记任务为完成。"""
    
    def get_pending_todos(self) -> List[TodoItem]:
        """获取待处理任务"""
        return [t for t in self.todos if t.status == "pending"]
    
    def get_in_progress_todos(self) -> List[TodoItem]:
        """获取进行中任务"""
        return [t for t in self.todos if t.status == "in_progress"]
    
    def get_completed_todos(self) -> List[TodoItem]:
        """获取已完成任务"""
        return [t for t in self.todos if t.status == "completed"]
    
    def has_incomplete(self) -> bool:
        """是否有未完成任务"""
        return any(t.status != "completed" for t in self.todos)


# 全局TodoManager实例
TODO_MANAGER = TodoManager()


# ============================================================
# SkillManager (s05: 技能加载)
# ============================================================

@dataclass
class Skill:
    """技能定义"""
    name: str
    description: str
    path: Path
    content: Optional[str] = None  # 按需加载
    
    def get_summary(self) -> str:
        """获取技能摘要（Layer 1）"""
        return f"- {self.name}: {self.description}"
    
    def get_full_content(self) -> str:
        """获取完整内容（Layer 2）"""
        if self.content is None:
            try:
                with open(self.path, 'r', encoding='utf-8') as f:
                    self.content = f.read()
            except Exception as e:
                self.content = f"错误: 无法加载技能 {self.name}: {e}"
        return self.content


class SkillManager:
    """
    技能管理器 - s05
    
    两层技能注入:
    - Layer 1（廉价）: 系统提示中只有技能名称和描述
    - Layer 2（按需）: 通过load_skill工具返回完整内容
    """
    
    def __init__(self, skills_dir: Path = None):
        self.skills_dir = skills_dir or (WORKDIR / "skills")
        self.skills: Dict[str, Skill] = {}
        self._scan_skills()
    
    def _scan_skills(self):
        """扫描skills目录，注册所有技能"""
        if not self.skills_dir.exists():
            return
        
        # 扫描所有SKILL.md文件
        for skill_file in self.skills_dir.glob("**/SKILL.md"):
            skill_info = self._parse_skill_file(skill_file)
            if skill_info:
                name = skill_info.get("name", skill_file.parent.name)
                self.skills[name] = Skill(
                    name=name,
                    description=skill_info.get("description", ""),
                    path=skill_file
                )
    
    def _parse_skill_file(self, skill_path: Path) -> Optional[Dict[str, str]]:
        """
        解析SKILL.md文件
        
        格式:
        ---
        name: skill-name
        description: 技能描述
        ---
        
        技能具体内容...
        """
        try:
            with open(skill_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 解析YAML frontmatter
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    frontmatter = yaml.safe_load(parts[1]) or {}
                    return {
                        "name": frontmatter.get("name", ""),
                        "description": frontmatter.get("description", "")
                    }
            
            # 没有frontmatter，使用目录名
            return {
                "name": skill_path.parent.name,
                "description": "无描述"
            }
        except Exception as e:
            print(f"警告: 解析技能文件失败 {skill_path}: {e}")
            return None
    
    def get_skill_names(self) -> List[str]:
        """获取所有技能名称"""
        return list(self.skills.keys())
    
    def get_skills_summary(self) -> str:
        """获取技能摘要列表（Layer 1，用于系统提示）"""
        if not self.skills:
            return ""
        
        lines = ["\n可用技能（使用load_skill加载详细内容）:"]
        for skill in self.skills.values():
            lines.append(skill.get_summary())
        return "\n".join(lines)
    
    def load_skill(self, name: str) -> str:
        """加载技能完整内容（Layer 2）"""
        skill = self.skills.get(name)
        if not skill:
            available = ", ".join(self.skills.keys()) if self.skills else "无"
            return f"错误: 未找到技能 '{name}'。可用技能: {available}"
        
        return skill.get_full_content()
    
    def has_skills(self) -> bool:
        """是否有可用技能"""
        return len(self.skills) > 0


# 全局SkillManager实例
SKILL_MANAGER = SkillManager()


# ============================================================
# ContextCompactor (s06: 上下文压缩)
# ============================================================

class ContextCompactor:
    """
    上下文压缩器 - s06
    
    三层压缩策略:
    1. Layer 1: micro_compact - 静默压缩非read_file的tool_result
    2. Layer 2: auto_compact - token超过阈值时自动压缩
    3. Layer 3: compact工具 - 手动触发压缩
    """
    
    def __init__(self, 
                 auto_compact_threshold: int = 8000,
                 transcripts_dir: Path = None):
        self.auto_compact_threshold = auto_compact_threshold
        self.transcripts_dir = transcripts_dir or (WORKDIR / ".transcripts")
        self.transcripts_dir.mkdir(parents=True, exist_ok=True)
        
        # 统计信息
        self.compaction_count = 0
        self.tokens_saved = 0
    
    def estimate_tokens(self, messages: List[Dict]) -> int:
        """
        估算消息列表的token数量
        
        简单估算：每个字符约0.4个token（中文约1个token/字符）
        """
        total_chars = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total_chars += len(content)
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and "content" in item:
                        total_chars += len(str(item["content"]))
                    elif hasattr(item, "text"):
                        total_chars += len(item.text)
        
        # 粗略估算：英文约4字符/token，中文约1字符/token
        return int(total_chars * 0.5)
    
    def micro_compact(self, messages: List[Dict]) -> List[Dict]:
        """
        Layer 1: 微压缩 - 静默执行
        
        将非read_file的tool_result内容替换为占位符
        保留最近3个完整结果
        """
        compacted = []
        tool_result_count = 0
        
        # 倒序遍历，保留最近3个
        for msg in reversed(messages):
            if isinstance(msg.get("content"), list):
                # 检查是否是tool_result
                is_tool_result = any(
                    item.get("type") == "tool_result" or 
                    item.get("role") == "tool"
                    for item in msg["content"]
                )
                
                if is_tool_result:
                    tool_result_count += 1
                    if tool_result_count > 3:
                        # 压缩旧的结果
                        compacted_msg = self._compact_tool_result(msg)
                        compacted.insert(0, compacted_msg)
                        continue
            
            compacted.insert(0, msg)
        
        return compacted
    
    def _compact_tool_result(self, msg: Dict) -> Dict:
        """压缩单个tool_result消息"""
        compacted_content = []
        
        for item in msg.get("content", []):
            if isinstance(item, dict):
                if item.get("type") == "tool_result" or item.get("role") == "tool":
                    # 替换为占位符
                    tool_name = item.get("tool_use_id", "unknown")[:8]
                    compacted_content.append({
                        "type": "tool_result",
                        "tool_use_id": item.get("tool_use_id", ""),
                        "content": f"[Previous: used {tool_name}]"
                    })
                else:
                    compacted_content.append(item)
            else:
                compacted_content.append(item)
        
        return {
            "role": msg.get("role", "user"),
            "content": compacted_content
        }
    
    def should_auto_compact(self, messages: List[Dict]) -> bool:
        """检查是否应该自动压缩"""
        tokens = self.estimate_tokens(messages)
        return tokens > self.auto_compact_threshold
    
    def auto_compact(self, messages: List[Dict]) -> Tuple[List[Dict], str]:
        """
        Layer 2: 自动压缩
        
        1. 保存完整对话到.transcripts/
        2. 请求LLM总结对话
        3. 用总结替换所有消息
        
        Returns:
            (压缩后的消息列表, 总结文本)
        """
        # 保存完整对话
        transcript_path = self._save_transcript(messages)
        
        # 生成总结
        summary = self._generate_summary(messages)
        
        # 构建压缩后的消息
        compacted_messages = [
            {
                "role": "system",
                "content": f"[上下文已压缩] 完整对话已保存到: {transcript_path}\n\n对话总结:\n{summary}"
            },
            {
                "role": "user",
                "content": "请基于上述总结继续对话。如果需要查看完整历史，可以读取transcript文件。"
            }
        ]
        
        self.compaction_count += 1
        original_tokens = self.estimate_tokens(messages)
        new_tokens = self.estimate_tokens(compacted_messages)
        self.tokens_saved += (original_tokens - new_tokens)
        
        return compacted_messages, summary
    
    def _save_transcript(self, messages: List[Dict]) -> Path:
        """保存对话记录到文件"""
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"transcript_{timestamp}_{uuid.uuid4().hex[:8]}.json"
        filepath = self.transcripts_dir / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(messages, f, ensure_ascii=False, indent=2, default=str)
        
        return filepath
    
    def _generate_summary(self, messages: List[Dict]) -> str:
        """
        生成对话总结
        
        简化实现：提取关键信息
        """
        # 提取用户消息和关键工具调用
        summary_parts = []
        
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            
            if role == "user" and isinstance(content, str):
                # 用户查询
                if len(content) < 200:
                    summary_parts.append(f"用户: {content[:100]}")
            elif role == "assistant":
                # 助手响应
                if isinstance(content, str) and content:
                    summary_parts.append(f"助手: {content[:100]}...")
        
        # 限制总结长度
        summary = "\n".join(summary_parts[-10:])  # 保留最近10轮
        return summary if summary else "对话历史已压缩，具体内容请查看transcript文件。"
    
    def compact(self, messages: List[Dict]) -> Tuple[List[Dict], str]:
        """
        Layer 3: 手动压缩
        
        手动触发完整压缩
        """
        return self.auto_compact(messages)
    
    def get_stats(self) -> Dict[str, Any]:
        """获取压缩统计信息"""
        return {
            "compaction_count": self.compaction_count,
            "tokens_saved": self.tokens_saved,
            "transcripts_dir": str(self.transcripts_dir),
            "auto_compact_threshold": self.auto_compact_threshold
        }


# 全局ContextCompactor实例
COMPACTOR = ContextCompactor()


# ============================================================
# TaskManager (s07: 任务系统)
# ============================================================

class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"


@dataclass
class Task:
    """任务定义 - s07"""
    id: str
    subject: str
    status: str = "pending"
    description: str = ""
    blockedBy: List[str] = field(default_factory=list)  # 依赖的任务ID列表
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "subject": self.subject,
            "status": self.status,
            "description": self.description,
            "blockedBy": self.blockedBy,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        return cls(
            id=data["id"],
            subject=data["subject"],
            status=data.get("status", "pending"),
            description=data.get("description", ""),
            blockedBy=data.get("blockedBy", []),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time())
        )


class TaskManager:
    """
    任务管理器 - s07
    
    将扁平清单升级为持久化到磁盘的任务图（DAG）
    
    功能:
    - 任务CRUD操作
    - 依赖关系管理（blockedBy）
    - 自动解锁依赖完成的任务
    - 回答三个问题：
      1. 什么可以做？（pending且无依赖或依赖已完成）
      2. 什么被卡住？（blocked）
      3. 什么做完了？（completed）
    """
    
    def __init__(self, tasks_dir: Path = None):
        self.tasks_dir = tasks_dir or (WORKDIR / ".tasks")
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.tasks: Dict[str, Task] = {}
        self._load_all_tasks()
    
    def _generate_id(self) -> str:
        """生成唯一任务ID"""
        import random
        import string
        return ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    
    def _task_file_path(self, task_id: str) -> Path:
        """获取任务文件路径"""
        return self.tasks_dir / f"task_{task_id}.json"
    
    def _load_all_tasks(self):
        """加载所有任务"""
        if not self.tasks_dir.exists():
            return
        
        for task_file in self.tasks_dir.glob("task_*.json"):
            try:
                with open(task_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    task = Task.from_dict(data)
                    self.tasks[task.id] = task
            except Exception as e:
                print(f"警告: 加载任务文件失败 {task_file}: {e}")
    
    def _save_task(self, task: Task):
        """保存任务到磁盘"""
        task.updated_at = time.time()
        task_file = self._task_file_path(task.id)
        with open(task_file, 'w', encoding='utf-8') as f:
            json.dump(task.to_dict(), f, ensure_ascii=False, indent=2)
    
    def create(self, subject: str, description: str = "", blockedBy: List[str] = None) -> Task:
        """创建新任务"""
        task_id = self._generate_id()
        task = Task(
            id=task_id,
            subject=subject,
            description=description,
            blockedBy=blockedBy or [],
            status="pending"
        )
        
        # 检查依赖是否存在
        for dep_id in task.blockedBy:
            if dep_id not in self.tasks:
                raise ValueError(f"依赖任务不存在: {dep_id}")
        
        # 如果有依赖，设置为blocked
        if task.blockedBy:
            task.status = "blocked"
        
        self.tasks[task_id] = task
        self._save_task(task)
        return task
    
    def get(self, task_id: str) -> Optional[Task]:
        """获取任务"""
        return self.tasks.get(task_id)
    
    def update(self, task_id: str, **kwargs) -> Task:
        """更新任务"""
        task = self.tasks.get(task_id)
        if not task:
            raise ValueError(f"任务不存在: {task_id}")
        
        # 更新字段
        for key, value in kwargs.items():
            if hasattr(task, key):
                setattr(task, key, value)
        
        self._save_task(task)
        
        # 如果任务完成，解锁依赖它的任务
        if kwargs.get("status") == "completed":
            self._unlock_dependent_tasks(task_id)
        
        return task
    
    def _unlock_dependent_tasks(self, completed_task_id: str):
        """解锁依赖已完成任务的任务"""
        for task in self.tasks.values():
            if completed_task_id in task.blockedBy:
                # 移除已完成的依赖
                task.blockedBy = [dep for dep in task.blockedBy if dep != completed_task_id]
                
                # 如果没有其他依赖，设置为pending
                if not task.blockedBy and task.status == "blocked":
                    task.status = "pending"
                    self._save_task(task)
    
    def delete(self, task_id: str):
        """删除任务"""
        if task_id not in self.tasks:
            raise ValueError(f"任务不存在: {task_id}")
        
        # 检查是否有其他任务依赖此任务
        for task in self.tasks.values():
            if task_id in task.blockedBy:
                raise ValueError(f"无法删除: 任务 {task_id} 被其他任务依赖")
        
        del self.tasks[task_id]
        task_file = self._task_file_path(task_id)
        if task_file.exists():
            task_file.unlink()
    
    def list_all(self) -> List[Task]:
        """列出所有任务"""
        return list(self.tasks.values())
    
    def get_doable_tasks(self) -> List[Task]:
        """
        获取可以执行的任务
        - pending状态
        - 无依赖或依赖已完成
        """
        doable = []
        for task in self.tasks.values():
            if task.status == "pending":
                # 检查依赖是否都已完成
                deps_completed = all(
                    self.tasks.get(dep_id) and self.tasks[dep_id].status == "completed"
                    for dep_id in task.blockedBy
                )
                if deps_completed:
                    doable.append(task)
        return doable
    
    def get_blocked_tasks(self) -> List[Task]:
        """获取被卡住的任务"""
        return [t for t in self.tasks.values() if t.status == "blocked"]
    
    def get_completed_tasks(self) -> List[Task]:
        """获取已完成的任务"""
        return [t for t in self.tasks.values() if t.status == "completed"]
    
    def format_task_graph(self) -> str:
        """格式化任务图为字符串"""
        if not self.tasks:
            return "当前没有任务"
        
        lines = ["📋 任务图:"]
        
        # 按状态分组
        doable = self.get_doable_tasks()
        in_progress = [t for t in self.tasks.values() if t.status == "in_progress"]
        blocked = self.get_blocked_tasks()
        completed = self.get_completed_tasks()
        
        if doable:
            lines.append("\n🟢 可执行:")
            for t in doable:
                lines.append(f"  [{t.id}] {t.subject}")
        
        if in_progress:
            lines.append("\n🟡 进行中:")
            for t in in_progress:
                lines.append(f"  [{t.id}] {t.subject}")
        
        if blocked:
            lines.append("\n🔴 被卡住:")
            for t in blocked:
                deps = ", ".join(t.blockedBy)
                lines.append(f"  [{t.id}] {t.subject} (依赖: {deps})")
        
        if completed:
            lines.append(f"\n✅ 已完成 ({len(completed)}):")
            for t in completed[-5:]:  # 只显示最近5个
                lines.append(f"  [{t.id}] {t.subject}")
            if len(completed) > 5:
                lines.append(f"  ... 还有 {len(completed) - 5} 个")
        
        return "\n".join(lines)
    
    def get_stats(self) -> Dict[str, int]:
        """获取任务统计"""
        return {
            "total": len(self.tasks),
            "pending": len([t for t in self.tasks.values() if t.status == "pending"]),
            "in_progress": len([t for t in self.tasks.values() if t.status == "in_progress"]),
            "completed": len([t for t in self.tasks.values() if t.status == "completed"]),
            "blocked": len([t for t in self.tasks.values() if t.status == "blocked"])
        }


# 全局TaskManager实例
TASK_MANAGER = TaskManager()


# ============================================================
# BackgroundTaskManager (s08: 后台任务)
# ============================================================

class BackgroundTaskStatus(Enum):
    """后台任务状态"""
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class BackgroundTask:
    """后台任务定义 - s08"""
    id: str
    prompt: str
    status: str = "running"
    result: str = ""
    error: str = ""
    created_at: float = field(default_factory=time.time)
    completed_at: float = 0.0
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "prompt": self.prompt[:100] + "..." if len(self.prompt) > 100 else self.prompt,
            "status": self.status,
            "result": self.result[:500] + "..." if len(self.result) > 500 else self.result,
            "error": self.error,
            "created_at": self.created_at,
            "completed_at": self.completed_at
        }


class BackgroundTaskManager:
    """
    后台任务管理器 - s08
    
    功能:
    - 在后台线程中启动子Agent
    - 主Agent可以继续工作
    - 异步获取后台任务结果
    - 后台任务不阻塞主循环
    
    使用场景:
    - 长时间运行的代码审查
    - 批量文件处理
    - 异步数据收集
    """
    
    def __init__(self):
        self.tasks: Dict[str, BackgroundTask] = {}
        self._lock = threading.Lock()
    
    def _generate_id(self) -> str:
        """生成唯一任务ID"""
        import random
        import string
        return ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    
    def start(self, prompt: str) -> BackgroundTask:
        """
        启动后台任务
        
        Args:
            prompt: 给子Agent的任务描述
            
        Returns:
            后台任务对象
        """
        task_id = self._generate_id()
        task = BackgroundTask(
            id=task_id,
            prompt=prompt,
            status="running"
        )
        
        with self._lock:
            self.tasks[task_id] = task
        
        # 在后台线程中启动子Agent
        thread = threading.Thread(
            target=self._run_agent,
            args=(task_id, prompt),
            daemon=True
        )
        thread.start()
        
        return task
    
    def _run_agent(self, task_id: str, prompt: str):
        """
        在后台线程中运行子Agent
        """
        try:
            # 子Agent拥有干净的上下文
            sub_messages = [{"role": "user", "content": prompt}]
            
            # 调用子Agent循环（在后台线程中运行）
            # 注意：_subagent_loop会在后台线程中被调用
            # 但我们需要在模块加载完成后才能调用
            result = self._run_subagent_loop(sub_messages)
            
            with self._lock:
                if task_id in self.tasks:
                    self.tasks[task_id].status = "completed"
                    self.tasks[task_id].result = result
                    self.tasks[task_id].completed_at = time.time()
                    
        except Exception as e:
            with self._lock:
                if task_id in self.tasks:
                    self.tasks[task_id].status = "failed"
                    self.tasks[task_id].error = str(e)
                    self.tasks[task_id].completed_at = time.time()
    
    def _run_subagent_loop(self, messages: list) -> str:
        """
        在后台运行子Agent循环
        返回最终结果
        """
        max_turns = 20
        for _ in range(max_turns):
            response, api_format = call_llm(messages, TOOLS)
            
            if api_format == "openai":
                choice = response.choices[0]
                assistant_message = choice.message
                
                messages.append({
                    "role": "assistant",
                    "content": assistant_message.content or "",
                    "tool_calls": [{"id": tc.id, "type": "function", "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                    }} for tc in (assistant_message.tool_calls or [])]
                } if assistant_message.tool_calls else {"role": "assistant", "content": assistant_message.content or ""})
                
                if choice.finish_reason != "tool_calls":
                    # 返回最终结果
                    return assistant_message.content or "(无响应)"
                
                import json
                results = []
                for tool_call in assistant_message.tool_calls:
                    tool_name = tool_call.function.name
                    tool_input = json.loads(tool_call.function.arguments)
                    output = execute_tool(tool_name, tool_input)
                    results.append({
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "content": output,
                    })
                messages.extend(results)
                
            else:
                # Anthropic格式
                messages.append({"role": "assistant", "content": response.content})
                
                if response.stop_reason != "tool_use":
                    # 返回最终结果
                    return response.content[0].text if response.content else "(无响应)"
                
                results = []
                for block in response.content:
                    if block.type == "tool_use":
                        output = execute_tool(block.name, block.input)
                        results.append({
                            "role": "user",
                            "content": [{
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": output
                            }]
                        })
                messages.extend(results)
        
        return "达到最大轮数限制"
    
    def get(self, task_id: str) -> Optional[BackgroundTask]:
        """获取后台任务"""
        with self._lock:
            return self.tasks.get(task_id)
    
    def get_all(self) -> List[BackgroundTask]:
        """获取所有后台任务"""
        with self._lock:
            return list(self.tasks.values())
    
    def get_running(self) -> List[BackgroundTask]:
        """获取运行中的任务"""
        with self._lock:
            return [t for t in self.tasks.values() if t.status == "running"]
    
    def get_completed(self) -> List[BackgroundTask]:
        """获取已完成的任务"""
        with self._lock:
            return [t for t in self.tasks.values() if t.status == "completed"]
    
    def clear_completed(self):
        """清理已完成的任务"""
        with self._lock:
            to_remove = [tid for tid, t in self.tasks.items() 
                        if t.status in ("completed", "failed")]
            for tid in to_remove:
                del self.tasks[tid]
    
    def format_status(self) -> str:
        """格式化后台任务状态"""
        with self._lock:
            if not self.tasks:
                return "当前没有后台任务"
            
            lines = ["🔄 后台任务:"]
            
            running = [t for t in self.tasks.values() if t.status == "running"]
            completed = [t for t in self.tasks.values() if t.status == "completed"]
            failed = [t for t in self.tasks.values() if t.status == "failed"]
            
            if running:
                lines.append("\n🏃 运行中:")
                for t in running:
                    elapsed = time.time() - t.created_at
                    lines.append(f"  [{t.id}] {t.prompt[:50]}... ({elapsed:.0f}秒)")
            
            if completed:
                lines.append(f"\n✅ 已完成 ({len(completed)}):")
                for t in completed[-3:]:
                    lines.append(f"  [{t.id}] {t.prompt[:50]}...")
            
            if failed:
                lines.append(f"\n❌ 失败 ({len(failed)}):")
                for t in failed:
                    lines.append(f"  [{t.id}] {t.error[:50]}")
            
            return "\n".join(lines)


# 全局BackgroundTaskManager实例
BACKGROUND_MANAGER = BackgroundTaskManager()


# ============================================================
# s10: Team Protocols（团队协议）
# ============================================================

class MessageType(Enum):
    """消息类型 - s10"""
    TASK = "task"                    # 任务分配
    RESULT = "result"                # 结果报告
    QUERY = "query"                  # 查询请求
    RESPONSE = "response"            # 查询响应
    BROADCAST = "broadcast"          # 广播消息
    HANDOFF = "handoff"              # 任务移交
    STATUS = "status"                # 状态更新
    ERROR = "error"                  # 错误报告


@dataclass
class AgentMessage:
    """
    Agent消息格式 - s10
    
    标准化的Agent间通信消息
    """
    type: str                        # 消息类型
    sender: str                      # 发送者ID
    receiver: str                    # 接收者ID (或 "all" 表示广播)
    content: str                     # 消息内容
    metadata: Dict[str, Any] = field(default_factory=dict)  # 元数据
    timestamp: float = field(default_factory=time.time)
    message_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    
    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "sender": self.sender,
            "receiver": self.receiver,
            "content": self.content,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
            "message_id": self.message_id
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "AgentMessage":
        return cls(
            type=data["type"],
            sender=data["sender"],
            receiver=data["receiver"],
            content=data["content"],
            metadata=data.get("metadata", {}),
            timestamp=data.get("timestamp", time.time()),
            message_id=data.get("message_id", str(uuid.uuid4())[:8])
        )


class Protocol(ABC):
    """
    协议基类 - s10
    
    定义Agent之间的协作规则
    """
    
    @abstractmethod
    def validate(self, message: AgentMessage) -> bool:
        """验证消息是否符合协议"""
        pass
    
    @abstractmethod
    def process(self, message: AgentMessage) -> Optional[AgentMessage]:
        """处理消息，返回响应（如果有）"""
        pass


class TaskProtocol(Protocol):
    """
    任务协议 - s10
    
    处理任务分配和结果报告
    """
    
    def validate(self, message: AgentMessage) -> bool:
        """验证任务消息"""
        if message.type == MessageType.TASK.value:
            return "task_id" in message.metadata and "task_description" in message.metadata
        elif message.type == MessageType.RESULT.value:
            return "task_id" in message.metadata
        return True
    
    def process(self, message: AgentMessage) -> Optional[AgentMessage]:
        """处理任务相关消息"""
        if message.type == MessageType.TASK.value:
            # 任务分配：返回确认
            return AgentMessage(
                type=MessageType.STATUS.value,
                sender=message.receiver,
                receiver=message.sender,
                content=f"任务已接收: {message.metadata.get('task_id')}",
                metadata={"task_id": message.metadata.get("task_id")}
            )
        return None


class HandoffProtocol(Protocol):
    """
    移交协议 - s10
    
    处理任务在Agent之间的移交
    """
    
    def validate(self, message: AgentMessage) -> bool:
        """验证移交消息"""
        if message.type == MessageType.HANDOFF.value:
            return all(k in message.metadata for k in ["task_id", "reason"])
        return True
    
    def process(self, message: AgentMessage) -> Optional[AgentMessage]:
        """处理移交消息"""
        if message.type == MessageType.HANDOFF.value:
            return AgentMessage(
                type=MessageType.STATUS.value,
                sender=message.receiver,
                receiver=message.sender,
                content=f"移交已接受: {message.metadata.get('task_id')}",
                metadata={"task_id": message.metadata.get("task_id")}
            )
        return None


class MessageBus:
    """
    消息总线 - s10
    
    Agent之间的通信中枢
    """
    
    def __init__(self):
        self._agents: Dict[str, 'TeamAgent'] = {}
        self._messages: List[AgentMessage] = []
        self._protocols: List[Protocol] = [TaskProtocol(), HandoffProtocol()]
        self._lock = threading.Lock()
    
    def register(self, agent: 'TeamAgent'):
        """注册Agent"""
        with self._lock:
            self._agents[agent.id] = agent
    
    def unregister(self, agent_id: str):
        """注销Agent"""
        with self._lock:
            self._agents.pop(agent_id, None)
    
    def send(self, message: AgentMessage):
        """发送消息"""
        # 验证协议
        for protocol in self._protocols:
            if not protocol.validate(message):
                raise ValueError(f"消息不符合协议: {message}")
        
        with self._lock:
            self._messages.append(message)
            
            # 分发消息
            if message.receiver == "all":
                # 广播给所有Agent
                for agent in self._agents.values():
                    if agent.id != message.sender:
                        agent.receive(message)
            else:
                # 发送给特定Agent
                receiver = self._agents.get(message.receiver)
                if receiver:
                    receiver.receive(message)
    
    def get_history(self, limit: int = 100) -> List[AgentMessage]:
        """获取消息历史"""
        with self._lock:
            return self._messages[-limit:]


# 全局消息总线
MESSAGE_BUS = MessageBus()


# ============================================================
# s09: Agent Teams（Agent团队）
# ============================================================

@dataclass
class TeamAgent:
    """
    团队Agent - s09
    
    具有特定角色的Agent
    """
    id: str
    name: str
    role: str                          # 角色：developer, reviewer, tester, etc.
    skills: List[str] = field(default_factory=list)
    status: str = "idle"               # idle, working, waiting
    current_task: Optional[str] = None
    
    def __post_init__(self):
        # 注册到消息总线
        MESSAGE_BUS.register(self)
    
    def receive(self, message: AgentMessage):
        """接收消息"""
        # 根据消息类型处理
        if message.type == MessageType.TASK.value:
            self.status = "working"
            self.current_task = message.metadata.get("task_id")
        elif message.type == MessageType.RESULT.value:
            if message.metadata.get("task_id") == self.current_task:
                self.status = "idle"
                self.current_task = None
        elif message.type == MessageType.HANDOFF.value:
            if message.receiver == self.id:
                self.status = "working"
                self.current_task = message.metadata.get("task_id")
    
    def send_message(self, msg_type: str, receiver: str, content: str, metadata: dict = None):
        """发送消息"""
        message = AgentMessage(
            type=msg_type,
            sender=self.id,
            receiver=receiver,
            content=content,
            metadata=metadata or {}
        )
        MESSAGE_BUS.send(message)
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "skills": self.skills,
            "status": self.status,
            "current_task": self.current_task
        }


@dataclass
class TeamTask:
    """团队任务 - s09"""
    id: str
    description: str
    assigned_to: Optional[str] = None
    status: str = "pending"           # pending, in_progress, completed, blocked
    priority: int = 0
    dependencies: List[str] = field(default_factory=list)
    result: str = ""
    created_at: float = field(default_factory=time.time)
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "assigned_to": self.assigned_to,
            "status": self.status,
            "priority": self.priority,
            "dependencies": self.dependencies,
            "result": self.result[:200] if self.result else ""
        }


class AgentTeam:
    """
    Agent团队 - s09
    
    管理多个协作的Agent
    """
    
    def __init__(self, name: str):
        self.name = name
        self.agents: Dict[str, TeamAgent] = {}
        self.tasks: Dict[str, TeamTask] = {}
        self._lock = threading.Lock()
        self._created_at = time.time()
    
    def _generate_id(self) -> str:
        """生成唯一ID"""
        import random
        import string
        return ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    
    def add_agent(self, name: str, role: str, skills: List[str] = None) -> TeamAgent:
        """添加Agent到团队"""
        agent_id = self._generate_id()
        agent = TeamAgent(
            id=agent_id,
            name=name,
            role=role,
            skills=skills or []
        )
        with self._lock:
            self.agents[agent_id] = agent
        return agent
    
    def remove_agent(self, agent_id: str):
        """从团队移除Agent"""
        with self._lock:
            self.agents.pop(agent_id, None)
            MESSAGE_BUS.unregister(agent_id)
    
    def create_task(self, description: str, priority: int = 0, 
                   dependencies: List[str] = None) -> TeamTask:
        """创建任务"""
        task_id = self._generate_id()
        task = TeamTask(
            id=task_id,
            description=description,
            priority=priority,
            dependencies=dependencies or []
        )
        with self._lock:
            self.tasks[task_id] = task
        return task
    
    def assign_task(self, task_id: str, agent_id: str) -> bool:
        """分配任务给Agent"""
        with self._lock:
            task = self.tasks.get(task_id)
            agent = self.agents.get(agent_id)
            
            if not task or not agent:
                return False
            
            # 检查依赖是否满足
            for dep_id in task.dependencies:
                dep_task = self.tasks.get(dep_id)
                if not dep_task or dep_task.status != "completed":
                    task.status = "blocked"
                    return False
            
            task.assigned_to = agent_id
            task.status = "in_progress"
            agent.status = "working"
            agent.current_task = task_id
            
            # 发送任务消息
            agent.send_message(
                MessageType.TASK.value,
                agent_id,
                task.description,
                {"task_id": task_id, "task_description": task.description}
            )
            
            return True
    
    def complete_task(self, task_id: str, result: str):
        """完成任务"""
        with self._lock:
            task = self.tasks.get(task_id)
            if not task:
                return
            
            task.status = "completed"
            task.result = result
            
            # 更新Agent状态
            if task.assigned_to:
                agent = self.agents.get(task.assigned_to)
                if agent:
                    agent.status = "idle"
                    agent.current_task = None
            
            # 检查是否有被阻塞的任务可以解锁
            for t in self.tasks.values():
                if t.status == "blocked" and task_id in t.dependencies:
                    # 检查所有依赖是否已完成
                    all_deps_done = all(
                        self.tasks.get(d) and self.tasks[d].status == "completed"
                        for d in t.dependencies
                    )
                    if all_deps_done:
                        t.status = "pending"
    
    def get_status(self) -> Dict[str, Any]:
        """获取团队状态"""
        with self._lock:
            agents_status = {
                "total": len(self.agents),
                "idle": len([a for a in self.agents.values() if a.status == "idle"]),
                "working": len([a for a in self.agents.values() if a.status == "working"])
            }
            
            tasks_status = {
                "total": len(self.tasks),
                "pending": len([t for t in self.tasks.values() if t.status == "pending"]),
                "in_progress": len([t for t in self.tasks.values() if t.status == "in_progress"]),
                "completed": len([t for t in self.tasks.values() if t.status == "completed"]),
                "blocked": len([t for t in self.tasks.values() if t.status == "blocked"])
            }
            
            return {
                "name": self.name,
                "agents": agents_status,
                "tasks": tasks_status,
                "created_at": self._created_at
            }
    
    def format_status(self) -> str:
        """格式化团队状态为字符串"""
        status = self.get_status()
        
        lines = [f"👥 团队: {self.name}"]
        
        # Agent状态
        lines.append(f"\n🤖 Agents ({status['agents']['total']}):")
        for agent in self.agents.values():
            status_icon = "🔄" if agent.status == "working" else "⏸️"
            task_info = f" → {agent.current_task}" if agent.current_task else ""
            lines.append(f"  {status_icon} [{agent.id}] {agent.name} ({agent.role}){task_info}")
        
        # 任务状态
        lines.append(f"\n📋 Tasks ({status['tasks']['total']}):")
        
        pending = [t for t in self.tasks.values() if t.status == "pending"]
        in_progress = [t for t in self.tasks.values() if t.status == "in_progress"]
        completed = [t for t in self.tasks.values() if t.status == "completed"]
        blocked = [t for t in self.tasks.values() if t.status == "blocked"]
        
        if in_progress:
            lines.append("\n  🔄 进行中:")
            for t in in_progress:
                agent_name = self.agents[t.assigned_to].name if t.assigned_to else "未分配"
                lines.append(f"    [{t.id}] {t.description[:40]}... (by {agent_name})")
        
        if pending:
            lines.append(f"\n  ⏳ 待处理 ({len(pending)}):")
            for t in pending[:5]:
                lines.append(f"    [{t.id}] {t.description[:40]}...")
        
        if blocked:
            lines.append(f"\n  🔴 被阻塞 ({len(blocked)}):")
            for t in blocked:
                deps = ", ".join(t.dependencies)
                lines.append(f"    [{t.id}] {t.description[:40]}... (依赖: {deps})")
        
        if completed:
            lines.append(f"\n  ✅ 已完成 ({len(completed)})")
        
        return "\n".join(lines)


# 全局团队管理器
class TeamManager:
    """管理所有团队"""
    
    def __init__(self):
        self.teams: Dict[str, AgentTeam] = {}
        self._lock = threading.Lock()
    
    def create_team(self, name: str) -> AgentTeam:
        """创建新团队"""
        team = AgentTeam(name)
        with self._lock:
            self.teams[team.name] = team
        return team
    
    def get_team(self, name: str) -> Optional[AgentTeam]:
        """获取团队"""
        return self.teams.get(name)
    
    def list_teams(self) -> List[str]:
        """列出所有团队"""
        return list(self.teams.keys())


# 全局TeamManager实例
TEAM_MANAGER = TeamManager()


# ============================================================
# s11: Autonomous Agents（自主Agent）
# ============================================================

class GoalStatus(Enum):
    """目标状态"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Goal:
    """
    目标定义 - s11
    
    自主Agent的目标和停止条件
    """
    id: str
    description: str                    # 目标描述
    success_criteria: List[str]         # 成功标准列表
    max_iterations: int = 20            # 最大迭代次数
    current_iteration: int = 0
    status: str = "pending"
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    completed_at: float = 0.0
    result: str = ""
    error: str = ""
    
    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())[:8]
    
    def is_achieved(self, context: str = "") -> bool:
        """
        检查目标是否达成
        
        Args:
            context: 当前上下文/结果
            
        Returns:
            是否达成
        """
        # 简单实现：检查成功标准是否在上下文中
        # 实际应该用LLM判断
        for criteria in self.success_criteria:
            if criteria.lower() in context.lower():
                continue
            else:
                return False
        return True
    
    def should_stop(self) -> bool:
        """检查是否应该停止"""
        return (
            self.status == "completed" or
            self.status == "failed" or
            self.current_iteration >= self.max_iterations
        )
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "success_criteria": self.success_criteria,
            "max_iterations": self.max_iterations,
            "current_iteration": self.current_iteration,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "result": self.result[:200] if self.result else "",
            "error": self.error
        }


class AutonomousAgent:
    """
    自主Agent - s11
    
    可以自主决策和执行的Agent，直到目标完成
    
    特点:
    1. 目标驱动 - 有明确的目标和停止条件
    2. 自主决策 - 自己决定下一步做什么
    3. 自主执行 - 不需要每步等待用户输入
    4. 自我判断 - 自己判断何时完成任务
    """
    
    def __init__(self, goal: Goal):
        self.goal = goal
        self.messages: List[Dict] = []
        self.history: List[Dict] = []      # 执行历史
        self._lock = threading.Lock()
        self._stop_flag = False
    
    def _build_autonomous_prompt(self) -> str:
        """构建自主Agent的系统提示"""
        return f"""你是一个自主执行的AI Agent。

你的目标: {self.goal.description}

成功标准:
{chr(10).join(f'- {c}' for c in self.goal.success_criteria)}

你将自主决策和执行，不需要等待用户输入。
每次迭代，你应该:
1. 分析当前状态和已完成的工作
2. 决定下一步行动
3. 执行工具调用
4. 检查是否满足成功标准

当满足所有成功标准时，使用 report_completion 工具报告完成。
如果遇到无法解决的问题，使用 report_failure 工具报告失败。

当前迭代: {self.goal.current_iteration}/{self.goal.max_iterations}
"""
    
    def _generate_next_step_prompt(self) -> str:
        """生成下一步的提示"""
        if self.goal.current_iteration == 0:
            return f"开始执行目标: {self.goal.description}\n请规划并执行第一步。"
        else:
            return f"""继续执行目标。

已完成的工作:
{self._summarize_history()}

下一步应该做什么？"""
    
    def _summarize_history(self) -> str:
        """总结执行历史"""
        if not self.history:
            return "（无）"
        
        lines = []
        for i, step in enumerate(self.history[-5:], 1):  # 最近5步
            action = step.get("action", "unknown")
            result = step.get("result", "")[:100]
            lines.append(f"{i}. {action}: {result}...")
        return "\n".join(lines)
    
    def step(self) -> Tuple[bool, str]:
        """
        执行一步
        
        Returns:
            (是否完成, 结果消息)
        """
        if self._stop_flag:
            return True, "Agent被停止"
        
        if self.goal.should_stop():
            return True, f"达到停止条件: 迭代{self.goal.current_iteration}/{self.goal.max_iterations}"
        
        self.goal.current_iteration += 1
        
        if self.goal.status == "pending":
            self.goal.status = "in_progress"
            self.goal.started_at = time.time()
        
        # 构建带系统提示的消息
        autonomous_system = self._build_autonomous_prompt()
        
        # 生成下一步提示
        next_step = self._generate_next_step_prompt()
        
        # 构建消息（OpenAI格式需要在开头添加系统消息）
        if API_TYPE == "openai":
            # 如果是第一步，添加系统消息
            if not self.messages:
                self.messages.append({"role": "system", "content": autonomous_system})
            self.messages.append({"role": "user", "content": next_step})
        
        try:
            # 调用LLM（使用自主Agent的系统提示）
            if API_TYPE == "openai":
                # OpenAI格式：直接传递带系统消息的messages
                from openai import OpenAI
                openai_tools = [{"type": "function", "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"]
                }} for t in self._get_autonomous_tools()]
                
                response = client.chat.completions.create(
                    model=MODEL,
                    messages=self.messages,
                    tools=openai_tools if openai_tools else None,
                    temperature=0.7
                )
                api_format = "openai"
            else:
                # Anthropic格式
                response, api_format = call_llm(
                    self.messages, 
                    self._get_autonomous_tools()
                )
            
            # 处理响应
            if api_format == "openai":
                choice = response.choices[0]
                assistant_message = choice.message
                
                self.messages.append({
                    "role": "assistant",
                    "content": assistant_message.content or "",
                    "tool_calls": [{"id": tc.id, "type": "function", "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                    }} for tc in (assistant_message.tool_calls or [])]
                } if assistant_message.tool_calls else {"role": "assistant", "content": assistant_message.content or ""})
                
                # 检查是否有特殊工具调用
                if assistant_message.tool_calls:
                    for tc in assistant_message.tool_calls:
                        if tc.function.name == "report_completion":
                            self.goal.status = "completed"
                            self.goal.completed_at = time.time()
                            import json
                            args = json.loads(tc.function.arguments)
                            self.goal.result = args.get("result", "")
                            return True, f"目标完成: {self.goal.result}"
                        
                        elif tc.function.name == "report_failure":
                            self.goal.status = "failed"
                            self.goal.completed_at = time.time()
                            import json
                            args = json.loads(tc.function.arguments)
                            self.goal.error = args.get("reason", "未知原因")
                            return True, f"目标失败: {self.goal.error}"
                    
                    # 执行普通工具调用
                    results = []
                    import json
                    for tc in assistant_message.tool_calls:
                        tool_name = tc.function.name
                        tool_input = json.loads(tc.function.arguments)
                        output = execute_tool(tool_name, tool_input)
                        
                        self.history.append({
                            "iteration": self.goal.current_iteration,
                            "action": f"{tool_name}: {str(tool_input)[:50]}",
                            "result": output[:200]
                        })
                        
                        results.append({
                            "tool_call_id": tc.id,
                            "role": "tool",
                            "content": output,
                        })
                    
                    self.messages.extend(results)
                
                else:
                    # 没有工具调用，检查内容
                    content = assistant_message.content or ""
                    if self.goal.is_achieved(content):
                        self.goal.status = "completed"
                        self.goal.completed_at = time.time()
                        self.goal.result = content
                        return True, f"目标完成: {content[:200]}"
            
            return False, f"迭代 {self.goal.current_iteration} 完成"
            
        except Exception as e:
            self.goal.status = "failed"
            self.goal.error = str(e)
            return True, f"执行出错: {e}"
    
    def _get_autonomous_tools(self) -> List[Dict]:
        """获取自主Agent可用工具"""
        # 基础工具 + 特殊报告工具
        return TOOLS + [
            {
                "name": "report_completion",
                "description": "报告目标已完成。当满足所有成功标准时使用。",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "result": {"type": "string", "description": "完成结果的描述"}
                    },
                    "required": ["result"]
                }
            },
            {
                "name": "report_failure",
                "description": "报告目标无法完成。当遇到无法解决的问题时使用。",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "reason": {"type": "string", "description": "失败原因"}
                    },
                    "required": ["reason"]
                }
            }
        ]
    
    def run(self) -> str:
        """
        运行自主Agent直到完成
        
        Returns:
            最终结果
        """
        print(f"🚀 启动自主Agent: {self.goal.description}")
        print(f"   成功标准: {', '.join(self.goal.success_criteria)}")
        print(f"   最大迭代: {self.goal.max_iterations}")
        print()
        
        while not self.goal.should_stop() and not self._stop_flag:
            done, message = self.step()
            print(f"  [{self.goal.current_iteration}] {message}")
            
            if done:
                break
        
        if self.goal.status == "completed":
            return f"✅ 目标完成: {self.goal.result}"
        elif self.goal.status == "failed":
            return f"❌ 目标失败: {self.goal.error}"
        else:
            return f"⏹️ 达到最大迭代次数 ({self.goal.max_iterations})"
    
    def stop(self):
        """停止自主Agent"""
        self._stop_flag = True
    
    def get_status(self) -> Dict[str, Any]:
        """获取状态"""
        return {
            "goal": self.goal.to_dict(),
            "history_count": len(self.history),
            "message_count": len(self.messages),
            "elapsed_time": (self.goal.completed_at or time.time()) - self.goal.started_at if self.goal.started_at > 0 else 0
        }


class AutonomousAgentManager:
    """
    自主Agent管理器 - s11
    
    管理多个自主运行Agent
    """
    
    def __init__(self):
        self.agents: Dict[str, AutonomousAgent] = {}
        self._lock = threading.Lock()
    
    def create(self, description: str, success_criteria: List[str], 
               max_iterations: int = 20) -> AutonomousAgent:
        """创建自主Agent"""
        import random
        import string
        agent_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
        
        goal = Goal(
            id=agent_id,
            description=description,
            success_criteria=success_criteria,
            max_iterations=max_iterations
        )
        
        agent = AutonomousAgent(goal)
        
        with self._lock:
            self.agents[agent_id] = agent
        
        return agent
    
    def get(self, agent_id: str) -> Optional[AutonomousAgent]:
        """获取Agent"""
        return self.agents.get(agent_id)
    
    def stop(self, agent_id: str):
        """停止Agent"""
        agent = self.agents.get(agent_id)
        if agent:
            agent.stop()
    
    def get_all(self) -> List[Dict]:
        """获取所有Agent状态"""
        return [a.get_status() for a in self.agents.values()]
    
    def format_status(self) -> str:
        """格式化状态"""
        if not self.agents:
            return "当前没有自主Agent运行"
        
        lines = ["🤖 自主Agent状态:"]
        for agent in self.agents.values():
            status = agent.get_status()
            goal = status["goal"]
            status_icon = {
                "pending": "⏳",
                "in_progress": "🔄",
                "completed": "✅",
                "failed": "❌"
            }.get(goal["status"], "❓")
            
            lines.append(f"\n{status_icon} [{goal['id']}] {goal['description'][:50]}...")
            lines.append(f"   状态: {goal['status']}")
            lines.append(f"   迭代: {goal['current_iteration']}/{goal['max_iterations']}")
            if goal['status'] == "completed":
                lines.append(f"   结果: {goal['result'][:100]}...")
        
        return "\n".join(lines)


# 全局AutonomousAgentManager实例
AUTONOMOUS_MANAGER = AutonomousAgentManager()


# ============================================================
# s12: Worktree Task Isolation（工作树任务隔离）
# ============================================================

class WorktreeStatus(Enum):
    """工作树状态"""
    CREATING = "creating"
    ACTIVE = "active"
    COMPLETED = "completed"
    REMOVED = "removed"


@dataclass
class Worktree:
    """
    工作树 - s12
    
    隔离的工作目录，用于并行任务执行
    """
    id: str
    name: str
    path: Path                           # 工作树路径
    branch: str = ""                     # Git分支名
    base_commit: str = ""                # 基础提交
    status: str = "active"
    created_at: float = field(default_factory=time.time)
    task_id: str = ""                    # 关联的任务ID
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "path": str(self.path),
            "branch": self.branch,
            "base_commit": self.base_commit,
            "status": self.status,
            "created_at": self.created_at,
            "task_id": self.task_id
        }


class WorktreeManager:
    """
    工作树管理器 - s12
    
    功能:
    - 创建隔离的工作目录
    - 管理工作树生命周期
    - 支持Git分支隔离
    - 文件冲突检测
    
    使用场景:
    - 并行开发多个功能
    - 安全测试代码变更
    - 独立的任务执行环境
    """
    
    def __init__(self, base_dir: Path = None):
        self.base_dir = base_dir or (WORKDIR / ".worktrees")
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.worktrees: Dict[str, Worktree] = {}
        self._lock = threading.Lock()
        self._load_worktrees()
    
    def _generate_id(self) -> str:
        """生成唯一ID"""
        import random
        import string
        return ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    
    def _load_worktrees(self):
        """加载现有工作树"""
        if not self.base_dir.exists():
            return
        
        for wt_dir in self.base_dir.iterdir():
            if wt_dir.is_dir() and wt_dir.name.startswith("wt_"):
                meta_file = wt_dir / ".worktree_meta.json"
                if meta_file.exists():
                    try:
                        with open(meta_file, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            wt = Worktree(
                                id=data["id"],
                                name=data["name"],
                                path=Path(data["path"]),
                                branch=data.get("branch", ""),
                                base_commit=data.get("base_commit", ""),
                                status=data.get("status", "active"),
                                created_at=data.get("created_at", time.time()),
                                task_id=data.get("task_id", "")
                            )
                            self.worktrees[wt.id] = wt
                    except Exception as e:
                        print(f"警告: 加载工作树元数据失败 {wt_dir}: {e}")
    
    def _save_worktree(self, wt: Worktree):
        """保存工作树元数据"""
        meta_file = wt.path / ".worktree_meta.json"
        with open(meta_file, 'w', encoding='utf-8') as f:
            json.dump(wt.to_dict(), f, ensure_ascii=False, indent=2)
    
    def create(self, name: str, branch: str = None, task_id: str = "") -> Worktree:
        """
        创建工作树
        
        Args:
            name: 工作树名称
            branch: Git分支名（可选）
            task_id: 关联的任务ID
            
        Returns:
            创建的工作树
        """
        wt_id = self._generate_id()
        wt_path = self.base_dir / f"wt_{wt_id}"
        
        # 创建目录
        wt_path.mkdir(parents=True, exist_ok=True)
        
        # 获取当前Git状态
        base_commit = ""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=WORKDIR,
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                base_commit = result.stdout.strip()[:8]
        except Exception:
            pass
        
        # 如果指定了分支，创建并切换
        if branch:
            try:
                subprocess.run(
                    ["git", "checkout", "-b", branch],
                    cwd=wt_path,
                    capture_output=True,
                    timeout=10
                )
            except Exception:
                pass
        
        wt = Worktree(
            id=wt_id,
            name=name,
            path=wt_path,
            branch=branch or f"worktree-{wt_id}",
            base_commit=base_commit,
            status="active",
            task_id=task_id
        )
        
        with self._lock:
            self.worktrees[wt_id] = wt
        
        self._save_worktree(wt)
        
        return wt
    
    def get(self, wt_id: str) -> Optional[Worktree]:
        """获取工作树"""
        return self.worktrees.get(wt_id)
    
    def list_all(self) -> List[Worktree]:
        """列出所有工作树"""
        return list(self.worktrees.values())
    
    def get_active(self) -> List[Worktree]:
        """获取活跃的工作树"""
        return [wt for wt in self.worktrees.values() if wt.status == "active"]
    
    def remove(self, wt_id: str, force: bool = False) -> bool:
        """
        删除工作树
        
        Args:
            wt_id: 工作树ID
            force: 是否强制删除（即使有未提交的更改）
            
        Returns:
            是否删除成功
        """
        wt = self.worktrees.get(wt_id)
        if not wt:
            return False
        
        # 检查是否有未提交的更改
        if not force:
            try:
                result = subprocess.run(
                    ["git", "status", "--porcelain"],
                    cwd=wt.path,
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if result.stdout.strip():
                    raise ValueError("工作树有未提交的更改，请先提交或使用 force=True")
            except ValueError:
                raise
            except Exception:
                pass
        
        # 删除目录
        import shutil
        try:
            shutil.rmtree(wt.path)
        except Exception as e:
            print(f"警告: 删除工作树目录失败: {e}")
        
        # 更新状态
        wt.status = "removed"
        with self._lock:
            self.worktrees.pop(wt_id, None)
        
        return True
    
    def get_worktree_files(self, wt_id: str) -> List[str]:
        """获取工作树中的文件列表"""
        wt = self.worktrees.get(wt_id)
        if not wt or not wt.path.exists():
            return []
        
        files = []
        for f in wt.path.rglob("*"):
            if f.is_file() and not f.name.startswith("."):
                files.append(str(f.relative_to(wt.path)))
        return files
    
    def format_status(self) -> str:
        """格式化工作树状态"""
        if not self.worktrees:
            return "当前没有工作树。使用 worktree_create 创建隔离的工作环境。"
        
        lines = ["🌳 工作树列表:"]
        
        for wt in self.worktrees.values():
            status_icon = {
                "active": "🟢",
                "completed": "✅",
                "removed": "🗑️"
            }.get(wt.status, "❓")
            
            lines.append(f"\n{status_icon} [{wt.id}] {wt.name}")
            lines.append(f"   路径: {wt.path}")
            lines.append(f"   分支: {wt.branch}")
            if wt.base_commit:
                lines.append(f"   基础提交: {wt.base_commit}")
            lines.append(f"   状态: {wt.status}")
            if wt.task_id:
                lines.append(f"   任务: {wt.task_id}")
        
        return "\n".join(lines)


class WorktreeTask:
    """
    工作树任务 - s12
    
    在隔离的工作树中执行任务
    """
    
    def __init__(self, worktree: Worktree):
        self.worktree = worktree
        self.messages: List[Dict] = []
        self.history: List[Dict] = []
    
    def _build_worktree_prompt(self, task_description: str) -> str:
        """构建工作树任务的系统提示"""
        return f"""你正在一个隔离的工作树环境中执行任务。

工作树信息:
- 名称: {self.worktree.name}
- 路径: {self.worktree.path}
- 分支: {self.worktree.branch}

工作目录已切换到: {self.worktree.path}

任务: {task_description}

在这个隔离的环境中，你可以安全地进行文件操作和代码修改，
不会影响主工作目录。完成后请报告结果。"""
    
    def execute(self, task_description: str, max_turns: int = 10) -> str:
        """
        在工作树中执行任务
        
        Args:
            task_description: 任务描述
            max_turns: 最大轮数
            
        Returns:
            执行结果
        """
        # 保存当前工作目录
        original_dir = os.getcwd()
        
        try:
            # 切换到工作树目录
            os.chdir(self.worktree.path)
            
            # 构建消息
            system_prompt = self._build_worktree_prompt(task_description)
            self.messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"开始在隔离环境中执行任务: {task_description}"}
            ]
            
            # 执行Agent循环
            for turn in range(max_turns):
                response, api_format = call_llm(self.messages, TOOLS)
                
                if api_format == "openai":
                    choice = response.choices[0]
                    assistant_message = choice.message
                    
                    self.messages.append({
                        "role": "assistant",
                        "content": assistant_message.content or "",
                        "tool_calls": [{"id": tc.id, "type": "function", "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }} for tc in (assistant_message.tool_calls or [])]
                    } if assistant_message.tool_calls else {"role": "assistant", "content": assistant_message.content or ""})
                    
                    if choice.finish_reason != "tool_calls":
                        # 任务完成
                        self.worktree.status = "completed"
                        return assistant_message.content or "任务完成"
                    
                    # 执行工具
                    import json
                    results = []
                    for tc in assistant_message.tool_calls:
                        tool_name = tc.function.name
                        tool_input = json.loads(tc.function.arguments)
                        
                        # 确保文件操作在工作树内
                        if tool_name in ("write_file", "edit_file", "read_file"):
                            if "file_path" in tool_input:
                                fp = Path(tool_input["file_path"])
                                if not fp.is_absolute():
                                    tool_input["file_path"] = str(self.worktree.path / fp)
                        
                        output = execute_tool(tool_name, tool_input)
                        results.append({
                            "tool_call_id": tc.id,
                            "role": "tool",
                            "content": output,
                        })
                    
                    self.messages.extend(results)
            
            return "达到最大轮数限制"
            
        finally:
            # 恢复原工作目录
            os.chdir(original_dir)


# 全局WorktreeManager实例
WORKTREE_MANAGER = WorktreeManager()


# 系统提示（动态生成，包含技能摘要）
def _build_system_prompt() -> str:
    """构建系统提示，包含技能摘要（Layer 1）"""
    base_prompt = f"""你是一个AI编程助手，工作目录是 {WORKDIR}。

你可以使用以下工具来完成任务:
- bash: 执行shell命令
- read_file: 读取文件内容
- write_file: 创建或覆盖写入文件
- edit_file: 精确替换文件中的内容
- TodoWrite: 管理任务列表，跟踪进度（重要：多步骤任务请先规划）
- task: 派发子任务给独立的子Agent执行（适合独立、明确的子任务）
- load_skill: 加载技能的详细知识内容
- task_create: 创建持久化任务（支持依赖关系）
- task_get: 获取任务详情
- task_update: 更新任务状态
- task_list: 列出所有任务
- background: 在后台启动长时间运行的任务（不阻塞主循环）
- get_background_tasks: 获取后台任务状态和结果
- team_create: 创建Agent团队，添加专业角色Agent
- team_add_agent: 向团队添加Agent
- team_create_task: 创建团队任务
- team_assign_task: 分配任务给团队Agent
- team_status: 获取团队状态
- autonomous: 启动自主Agent，自主决策执行直到目标完成
- autonomous_status: 获取自主Agent状态
- worktree_create: 创建隔离的工作树，用于并行任务执行
- worktree_list: 列出所有工作树
- worktree_remove: 删除工作树

工作原则:
1. 遇到多步骤任务时，先用TodoWrite规划任务列表
2. 对于可以独立执行的子任务，使用task派发给子Agent
3. 长时间运行的任务使用background在后台执行，不阻塞主循环
4. 需要特定领域知识时，先load_skill加载相关技能
5. 复杂项目使用task_create创建持久化任务，支持依赖关系
6. 复杂协作场景使用team_create创建Agent团队，分配专业角色
7. 需要自主完成的复杂目标使用autonomous启动自主Agent
8. 并行任务需要文件隔离时，使用worktree_create创建隔离环境
9. 每完成一步，更新任务状态
10. 所有任务完成后，标记为completed
11. 上下文过长时，使用compact工具压缩历史记录
12. 请直接行动，不要过多解释

当前任务状态会自动显示给你，请保持任务列表更新。"""
    
    # 添加技能摘要（Layer 1）
    skills_summary = SKILL_MANAGER.get_skills_summary()
    if skills_summary:
        base_prompt += "\n" + skills_summary
    
    return base_prompt


SYSTEM = _build_system_prompt()

# ============================================================
# 工具定义 (s02: dispatch map pattern)
# ============================================================

TOOLS = [
    # bash工具
    {
        "name": "bash",
        "description": "运行shell命令。可以用于执行系统命令、安装依赖、运行测试等。危险命令会被拦截。",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要执行的shell命令"}
            },
            "required": ["command"]
        }
    },
    # read_file工具
    {
        "name": "read_file",
        "description": "读取文件内容。支持指定行范围读取大文件。返回文件内容或错误信息。",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "要读取的文件路径（绝对路径或相对路径）"},
                "start_line": {"type": "integer", "description": "起始行号（可选，从1开始）"},
                "end_line": {"type": "integer", "description": "结束行号（可选）"}
            },
            "required": ["file_path"]
        }
    },
    # write_file工具
    {
        "name": "write_file",
        "description": "创建新文件或完全覆盖现有文件。如果文件所在目录不存在会自动创建。谨慎使用，会覆盖现有内容。",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "要写入的文件路径"},
                "content": {"type": "string", "description": "要写入的文件内容"}
            },
            "required": ["file_path", "content"]
        }
    },
    # edit_file工具
    {
        "name": "edit_file",
        "description": "精确替换文件中的内容。会查找原始文本并替换为新文本。要求原始文本必须完全匹配（包括空白字符）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "要编辑的文件路径"},
                "old_text": {"type": "string", "description": "要被替换的原始文本（必须完全匹配）"},
                "new_text": {"type": "string", "description": "替换后的新文本"}
            },
            "required": ["file_path", "old_text", "new_text"]
        }
    },
    # TodoWrite工具 (s03)
    {
        "name": "TodoWrite",
        "description": "管理任务列表，跟踪多步骤任务的进度。状态: pending(待处理) → in_progress(进行中) → completed(已完成)。重要：遇到多步骤任务时，先调用此工具规划任务。",
        "input_schema": {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "description": "任务列表",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "任务ID（更新时必填，新建时可选）"},
                            "content": {"type": "string", "description": "任务内容描述"},
                            "status": {"type": "string", "enum": ["pending", "in_progress", "completed"], "description": "任务状态"}
                        },
                        "required": ["content", "status"]
                    }
                }
            },
            "required": ["todos"]
        }
    },
    # task工具 (s04 - Subagents)
    {
        "name": "task",
        "description": "派发子任务给独立的子Agent执行。子Agent拥有干净的上下文，适合处理独立的子任务。返回执行摘要而非完整过程。",
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "给子Agent的任务描述，需要详细说明要完成什么"}
            },
            "required": ["prompt"]
        }
    },
    # load_skill工具 (s05 - Skills)
    {
        "name": "load_skill",
        "description": "加载技能的详细知识内容。系统提示中只显示技能名称和描述，调用此工具获取完整的技能内容（如代码规范、API用法等）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "要加载的技能名称"}
            },
            "required": ["name"]
        }
    },
    # compact工具 (s06 - Context Compact)
    {
        "name": "compact",
        "description": "压缩上下文历史。将对话历史保存到文件，并用总结替换当前上下文。用于处理长对话，节省token。",
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "压缩原因（可选）"}
            }
        }
    },
    # task_create工具 (s07 - Task System)
    {
        "name": "task_create",
        "description": "创建持久化任务。任务会保存到磁盘，支持依赖关系。返回任务ID。",
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "任务主题/标题"},
                "description": {"type": "string", "description": "任务详细描述（可选）"},
                "blockedBy": {"type": "array", "items": {"type": "string"}, "description": "依赖的任务ID列表（可选）"}
            },
            "required": ["subject"]
        }
    },
    # task_get工具 (s07 - Task System)
    {
        "name": "task_get",
        "description": "获取任务详情。",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "任务ID"}
            },
            "required": ["task_id"]
        }
    },
    # task_update工具 (s07 - Task System)
    {
        "name": "task_update",
        "description": "更新任务状态。完成任务时会自动解锁依赖它的任务。",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "任务ID"},
                "status": {"type": "string", "enum": ["pending", "in_progress", "completed"], "description": "新状态"},
                "description": {"type": "string", "description": "更新描述（可选）"}
            },
            "required": ["task_id", "status"]
        }
    },
    # task_list工具 (s07 - Task System)
    {
        "name": "task_list",
        "description": "列出所有任务，显示任务图状态（可执行/进行中/被卡住/已完成）。",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    # background工具 (s08 - Background Tasks)
    {
        "name": "background",
        "description": "在后台启动长时间运行的任务。任务会在后台线程中执行，不阻塞主Agent循环。返回任务ID，可用get_background_tasks查询状态和结果。",
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "给后台子Agent的任务描述"}
            },
            "required": ["prompt"]
        }
    },
    # get_background_tasks工具 (s08 - Background Tasks)
    {
        "name": "get_background_tasks",
        "description": "获取后台任务的状态和结果。可以指定任务ID获取特定任务，或不指定获取所有任务。",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "任务ID（可选，不指定则返回所有任务）"}
            }
        }
    },
    # team_create工具 (s09 - Agent Teams)
    {
        "name": "team_create",
        "description": "创建Agent团队。团队由多个专业角色的Agent组成，可以协作完成复杂任务。",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "团队名称"}
            },
            "required": ["name"]
        }
    },
    # team_add_agent工具 (s09 - Agent Teams)
    {
        "name": "team_add_agent",
        "description": "向团队添加Agent。每个Agent有特定角色和技能。",
        "input_schema": {
            "type": "object",
            "properties": {
                "team_name": {"type": "string", "description": "团队名称"},
                "agent_name": {"type": "string", "description": "Agent名称"},
                "role": {"type": "string", "description": "Agent角色（如：developer, reviewer, tester, architect）"},
                "skills": {"type": "array", "items": {"type": "string"}, "description": "Agent技能列表（可选）"}
            },
            "required": ["team_name", "agent_name", "role"]
        }
    },
    # team_create_task工具 (s09 - Agent Teams)
    {
        "name": "team_create_task",
        "description": "创建团队任务。可以设置优先级和依赖关系。",
        "input_schema": {
            "type": "object",
            "properties": {
                "team_name": {"type": "string", "description": "团队名称"},
                "description": {"type": "string", "description": "任务描述"},
                "priority": {"type": "integer", "description": "优先级（可选，默认0）"},
                "dependencies": {"type": "array", "items": {"type": "string"}, "description": "依赖的任务ID列表（可选）"}
            },
            "required": ["team_name", "description"]
        }
    },
    # team_assign_task工具 (s09 - Agent Teams)
    {
        "name": "team_assign_task",
        "description": "分配任务给团队中的Agent。会检查依赖关系是否满足。",
        "input_schema": {
            "type": "object",
            "properties": {
                "team_name": {"type": "string", "description": "团队名称"},
                "task_id": {"type": "string", "description": "任务ID"},
                "agent_id": {"type": "string", "description": "Agent ID"}
            },
            "required": ["team_name", "task_id", "agent_id"]
        }
    },
    # team_status工具 (s09 - Agent Teams)
    {
        "name": "team_status",
        "description": "获取团队状态，显示所有Agent和任务情况。",
        "input_schema": {
            "type": "object",
            "properties": {
                "team_name": {"type": "string", "description": "团队名称（可选，不指定则显示所有团队）"}
            }
        }
    },
    # autonomous工具 (s11 - Autonomous Agents)
    {
        "name": "autonomous",
        "description": "启动自主Agent。自主Agent会自主决策和执行，直到目标完成或达到最大迭代次数。适合需要多步自主决策的复杂任务。",
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "目标描述"},
                "success_criteria": {
                    "type": "array", 
                    "items": {"type": "string"}, 
                    "description": "成功标准列表（Agent会检查这些标准来判断是否完成）"
                },
                "max_iterations": {"type": "integer", "description": "最大迭代次数（可选，默认20）"}
            },
            "required": ["description", "success_criteria"]
        }
    },
    # autonomous_status工具 (s11 - Autonomous Agents)
    {
        "name": "autonomous_status",
        "description": "获取自主Agent状态。可以指定Agent ID获取特定Agent状态，或不指定获取所有。",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent ID（可选）"}
            }
        }
    },
    # worktree_create工具 (s12 - Worktree Task Isolation)
    {
        "name": "worktree_create",
        "description": "创建隔离的工作树。工作树是独立的工作目录，用于并行任务执行和文件隔离。适合需要独立环境的安全开发。",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "工作树名称"},
                "branch": {"type": "string", "description": "Git分支名（可选）"},
                "task_id": {"type": "string", "description": "关联的任务ID（可选）"}
            },
            "required": ["name"]
        }
    },
    # worktree_list工具 (s12 - Worktree Task Isolation)
    {
        "name": "worktree_list",
        "description": "列出所有工作树。",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    # worktree_remove工具 (s12 - Worktree Task Isolation)
    {
        "name": "worktree_remove",
        "description": "删除工作树。会删除工作树目录和所有文件。",
        "input_schema": {
            "type": "object",
            "properties": {
                "worktree_id": {"type": "string", "description": "工作树ID"},
                "force": {"type": "boolean", "description": "强制删除，即使有未提交的更改（可选，默认false）"}
            },
            "required": ["worktree_id"]
        }
    }
]


# ============================================================
# 工具处理函数
# ============================================================

def validate_path(file_path: str) -> Path:
    """验证路径安全性，防止路径穿越攻击"""
    path = Path(file_path)
    if not path.is_absolute():
        path = WORKDIR / path
    
    # 解析真实路径
    try:
        resolved = path.resolve()
    except Exception:
        resolved = path
    
    return resolved


def run_bash(command: str) -> str:
    """执行bash命令并返回结果"""
    # 安全检查：拦截危险命令
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/", "mkfs", "dd if="]
    if any(d in command for d in dangerous):
        return "错误: 危险命令被拦截"
    
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=WORKDIR,
            capture_output=True,
            text=True,
            timeout=120
        )
        output = (result.stdout + result.stderr).strip()
        return output[:50000] if output else "(无输出)"
    except subprocess.TimeoutExpired:
        return "错误: 命令超时(120秒)"
    except Exception as e:
        return f"错误: {e}"


def run_read_file(file_path: str, start_line: Optional[int] = None, end_line: Optional[int] = None) -> str:
    """读取文件内容"""
    try:
        path = validate_path(file_path)
        
        if not path.exists():
            return f"错误: 文件不存在: {path}"
        
        if not path.is_file():
            return f"错误: 不是文件: {path}"
        
        # 读取文件
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
        
        # 处理行范围
        total_lines = len(lines)
        start = max(1, start_line or 1) - 1  # 转为0索引
        end = end_line or total_lines
        
        if start >= total_lines:
            return f"错误: 起始行号 {start_line} 超出范围（文件共 {total_lines} 行）"
        
        selected_lines = lines[start:end]
        
        # 格式化输出，带行号
        result_lines = []
        for i, line in enumerate(selected_lines, start=start + 1):
            line_content = line.rstrip('\n\r')
            result_lines.append(f"{i:>6}→{line_content}")
        
        content = '\n'.join(result_lines)
        
        # 添加文件信息头
        header = f"文件: {path}\n行数: {start + 1}-{min(end, total_lines)} / {total_lines}\n{'=' * 50}\n"
        
        return header + content
        
    except Exception as e:
        return f"错误: 读取文件失败: {e}"


def run_write_file(file_path: str, content: str) -> str:
    """写入文件"""
    try:
        path = validate_path(file_path)
        
        # 创建父目录
        path.parent.mkdir(parents=True, exist_ok=True)
        
        # 写入文件
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return f"✅ 成功写入文件: {path} ({len(content)} 字符)"
        
    except Exception as e:
        return f"错误: 写入文件失败: {e}"


def run_edit_file(file_path: str, old_text: str, new_text: str) -> str:
    """编辑文件 - 精确替换"""
    try:
        path = validate_path(file_path)
        
        if not path.exists():
            return f"错误: 文件不存在: {path}"
        
        # 读取文件内容
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 检查old_text是否存在
        if old_text not in content:
            return f"错误: 未找到要替换的文本。\n请确保原始文本完全匹配（包括空白字符）。"
        
        # 检查是否有多个匹配
        count = content.count(old_text)
        if count > 1:
            return f"错误: 找到 {count} 处匹配，需要唯一匹配。\n请提供更多上下文以唯一标识要替换的位置。"
        
        # 执行替换
        new_content = content.replace(old_text, new_text, 1)
        
        # 写回文件
        with open(path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        return f"✅ 成功编辑文件: {path}\n替换了 {len(old_text)} 字符为 {len(new_text)} 字符"
        
    except Exception as e:
        return f"错误: 编辑文件失败: {e}"


def run_todo_write(todos: List[Dict[str, Any]]) -> str:
    """
    处理TodoWrite工具调用 - s03
    
    Args:
        todos: 任务列表，每项包含 id(可选), content, status
    
    Returns:
        更新后的任务列表状态
    """
    try:
        result = TODO_MANAGER.update(todos)
        return f"✅ 任务列表已更新:\n{result}"
    except Exception as e:
        return f"错误: 更新任务列表失败: {e}"


def run_task_create(subject: str, description: str = "", blockedBy: List[str] = None) -> str:
    """
    创建任务 - s07
    
    Args:
        subject: 任务主题
        description: 任务描述
        blockedBy: 依赖的任务ID列表
        
    Returns:
        创建结果
    """
    try:
        task = TASK_MANAGER.create(subject, description, blockedBy)
        deps_str = f" (依赖: {', '.join(blockedBy)})" if blockedBy else ""
        return f"✅ 任务创建成功: [{task.id}] {task.subject}{deps_str}"
    except Exception as e:
        return f"错误: 创建任务失败: {e}"


def run_task_get(task_id: str) -> str:
    """
    获取任务详情 - s07
    
    Args:
        task_id: 任务ID
        
    Returns:
        任务详情
    """
    try:
        task = TASK_MANAGER.get(task_id)
        if not task:
            return f"错误: 未找到任务 {task_id}"
        
        deps_str = f"\n依赖: {', '.join(task.blockedBy)}" if task.blockedBy else ""
        return f"📋 任务详情:\nID: {task.id}\n主题: {task.subject}\n状态: {task.status}\n描述: {task.description}{deps_str}"
    except Exception as e:
        return f"错误: 获取任务失败: {e}"


def run_task_update(task_id: str, status: str, description: str = None) -> str:
    """
    更新任务 - s07
    
    Args:
        task_id: 任务ID
        status: 新状态
        description: 更新描述
        
    Returns:
        更新结果
    """
    try:
        kwargs = {"status": status}
        if description:
            kwargs["description"] = description
        
        task = TASK_MANAGER.update(task_id, **kwargs)
        
        # 检查是否有任务被解锁
        unlocked = [t for t in TASK_MANAGER.tasks.values() 
                   if task_id in t.blockedBy and t.status == "pending"]
        
        result = f"✅ 任务已更新: [{task.id}] {task.subject} → {status}"
        if status == "completed" and unlocked:
            result += f"\n🎉 解锁了 {len(unlocked)} 个依赖任务"
        
        return result
    except Exception as e:
        return f"错误: 更新任务失败: {e}"


def run_task_list() -> str:
    """
    列出所有任务 - s07
    
    Returns:
        任务图状态
    """
    try:
        return TASK_MANAGER.format_task_graph()
    except Exception as e:
        return f"错误: 列出任务失败: {e}"


def run_background(prompt: str) -> str:
    """
    启动后台任务 - s08
    
    Args:
        prompt: 给后台子Agent的任务描述
        
    Returns:
        任务启动结果
    """
    try:
        task = BACKGROUND_MANAGER.start(prompt)
        return f"✅ 后台任务已启动: [{task.id}]\n任务: {prompt[:50]}{'...' if len(prompt) > 50 else ''}\n\n使用 get_background_tasks 查询状态，指定 task_id=\"{task.id}\" 获取结果。"
    except Exception as e:
        return f"错误: 启动后台任务失败: {e}"


def run_get_background_tasks(task_id: str = None) -> str:
    """
    获取后台任务状态 - s08
    
    Args:
        task_id: 任务ID（可选）
        
    Returns:
        任务状态或所有任务列表
    """
    try:
        if task_id:
            # 获取特定任务
            task = BACKGROUND_MANAGER.get(task_id)
            if not task:
                return f"错误: 未找到后台任务 {task_id}"
            
            status_emoji = {
                "running": "🏃",
                "completed": "✅",
                "failed": "❌"
            }.get(task.status, "❓")
            
            result = f"{status_emoji} 后台任务 [{task.id}]:\n"
            result += f"状态: {task.status}\n"
            result += f"任务: {task.prompt}\n"
            
            if task.status == "running":
                elapsed = time.time() - task.created_at
                result += f"运行时间: {elapsed:.0f}秒\n"
            elif task.status == "completed":
                result += f"\n结果:\n{task.result}\n"
            elif task.status == "failed":
                result += f"\n错误: {task.error}\n"
            
            return result
        else:
            # 获取所有任务
            return BACKGROUND_MANAGER.format_status()
    except Exception as e:
        return f"错误: 获取后台任务失败: {e}"


def run_team_create(name: str) -> str:
    """
    创建Agent团队 - s09
    
    Args:
        name: 团队名称
        
    Returns:
        创建结果
    """
    try:
        # 检查团队是否已存在
        if TEAM_MANAGER.get_team(name):
            return f"错误: 团队 '{name}' 已存在"
        
        team = TEAM_MANAGER.create_team(name)
        return f"✅ 团队创建成功: {name}\n\n使用 team_add_agent 添加Agent，使用 team_create_task 创建任务。"
    except Exception as e:
        return f"错误: 创建团队失败: {e}"


def run_team_add_agent(team_name: str, agent_name: str, role: str, skills: List[str] = None) -> str:
    """
    向团队添加Agent - s09
    
    Args:
        team_name: 团队名称
        agent_name: Agent名称
        role: Agent角色
        skills: Agent技能列表
        
    Returns:
        添加结果
    """
    try:
        team = TEAM_MANAGER.get_team(team_name)
        if not team:
            return f"错误: 团队 '{team_name}' 不存在"
        
        agent = team.add_agent(agent_name, role, skills)
        skills_str = f" (技能: {', '.join(skills)})" if skills else ""
        return f"✅ Agent添加成功: [{agent.id}] {agent_name} ({role}){skills_str}"
    except Exception as e:
        return f"错误: 添加Agent失败: {e}"


def run_team_create_task(team_name: str, description: str, priority: int = 0, 
                        dependencies: List[str] = None) -> str:
    """
    创建团队任务 - s09
    
    Args:
        team_name: 团队名称
        description: 任务描述
        priority: 优先级
        dependencies: 依赖任务ID列表
        
    Returns:
        创建结果
    """
    try:
        team = TEAM_MANAGER.get_team(team_name)
        if not team:
            return f"错误: 团队 '{team_name}' 不存在"
        
        task = team.create_task(description, priority, dependencies)
        deps_str = f" (依赖: {', '.join(dependencies)})" if dependencies else ""
        return f"✅ 任务创建成功: [{task.id}] {description[:50]}{'...' if len(description) > 50 else ''}{deps_str}"
    except Exception as e:
        return f"错误: 创建任务失败: {e}"


def run_team_assign_task(team_name: str, task_id: str, agent_id: str) -> str:
    """
    分配任务给Agent - s09
    
    Args:
        team_name: 团队名称
        task_id: 任务ID
        agent_id: Agent ID
        
    Returns:
        分配结果
    """
    try:
        team = TEAM_MANAGER.get_team(team_name)
        if not team:
            return f"错误: 团队 '{team_name}' 不存在"
        
        success = team.assign_task(task_id, agent_id)
        if success:
            task = team.tasks.get(task_id)
            agent = team.agents.get(agent_id)
            return f"✅ 任务分配成功: [{task_id}] → {agent.name if agent else agent_id}"
        else:
            return f"错误: 任务分配失败（任务或Agent不存在，或依赖未满足）"
    except Exception as e:
        return f"错误: 分配任务失败: {e}"


def run_team_status(team_name: str = None) -> str:
    """
    获取团队状态 - s09
    
    Args:
        team_name: 团队名称（可选）
        
    Returns:
        团队状态
    """
    try:
        if team_name:
            team = TEAM_MANAGER.get_team(team_name)
            if not team:
                return f"错误: 团队 '{team_name}' 不存在"
            return team.format_status()
        else:
            # 显示所有团队
            teams = TEAM_MANAGER.list_teams()
            if not teams:
                return "当前没有团队。使用 team_create 创建团队。"
            
            lines = ["👥 所有团队:"]
            for name in teams:
                team = TEAM_MANAGER.get_team(name)
                status = team.get_status()
                lines.append(f"\n  {name}:")
                lines.append(f"    Agents: {status['agents']['total']} (工作中: {status['agents']['working']})")
                lines.append(f"    Tasks: {status['tasks']['total']} (完成: {status['tasks']['completed']})")
            
            return "\n".join(lines)
    except Exception as e:
        return f"错误: 获取团队状态失败: {e}"


def run_autonomous(description: str, success_criteria: List[str], 
                   max_iterations: int = 20) -> str:
    """
    启动自主Agent - s11
    
    Args:
        description: 目标描述
        success_criteria: 成功标准列表
        max_iterations: 最大迭代次数
        
    Returns:
        启动结果
    """
    try:
        agent = AUTONOMOUS_MANAGER.create(
            description=description,
            success_criteria=success_criteria,
            max_iterations=max_iterations
        )
        
        return f"""✅ 自主Agent已启动: [{agent.goal.id}]
目标: {description}
成功标准: {', '.join(success_criteria)}
最大迭代: {max_iterations}

Agent将自主决策和执行直到目标完成。
使用 autonomous_status(agent_id="{agent.goal.id}") 查询状态。"""
    except Exception as e:
        return f"错误: 启动自主Agent失败: {e}"


def run_autonomous_run(agent_id: str) -> str:
    """
    运行自主Agent直到完成 - s11
    
    Args:
        agent_id: Agent ID
        
    Returns:
        执行结果
    """
    try:
        agent = AUTONOMOUS_MANAGER.get(agent_id)
        if not agent:
            return f"错误: 未找到自主Agent {agent_id}"
        
        return agent.run()
    except Exception as e:
        return f"错误: 运行自主Agent失败: {e}"


def run_autonomous_status(agent_id: str = None) -> str:
    """
    获取自主Agent状态 - s11
    
    Args:
        agent_id: Agent ID（可选）
        
    Returns:
        Agent状态
    """
    try:
        if agent_id:
            agent = AUTONOMOUS_MANAGER.get(agent_id)
            if not agent:
                return f"错误: 未找到自主Agent {agent_id}"
            
            status = agent.get_status()
            goal = status["goal"]
            
            status_icon = {
                "pending": "⏳",
                "in_progress": "🔄",
                "completed": "✅",
                "failed": "❌"
            }.get(goal["status"], "❓")
            
            result = f"{status_icon} 自主Agent [{goal['id']}]:\n"
            result += f"目标: {goal['description']}\n"
            result += f"状态: {goal['status']}\n"
            result += f"迭代: {goal['current_iteration']}/{goal['max_iterations']}\n"
            
            if goal['status'] == "completed":
                result += f"\n结果:\n{goal['result']}\n"
            elif goal['status'] == "failed":
                result += f"\n错误: {goal['error']}\n"
            else:
                result += f"\n执行时间: {status['elapsed_time']:.1f}秒\n"
            
            return result
        else:
            return AUTONOMOUS_MANAGER.format_status()
    except Exception as e:
        return f"错误: 获取自主Agent状态失败: {e}"


def run_worktree_create(name: str, branch: str = None, task_id: str = "") -> str:
    """
    创建工作树 - s12
    
    Args:
        name: 工作树名称
        branch: Git分支名
        task_id: 关联的任务ID
        
    Returns:
        创建结果
    """
    try:
        wt = WORKTREE_MANAGER.create(name, branch, task_id)
        
        result = f"""✅ 工作树创建成功: [{wt.id}]
名称: {name}
路径: {wt.path}
分支: {wt.branch}

工作树是隔离的工作目录，可以安全地进行文件操作。
完成后使用 worktree_remove(worktree_id="{wt.id}") 删除。"""
        return result
    except Exception as e:
        return f"错误: 创建工作树失败: {e}"


def run_worktree_list() -> str:
    """
    列出工作树 - s12
    
    Returns:
        工作树列表
    """
    try:
        return WORKTREE_MANAGER.format_status()
    except Exception as e:
        return f"错误: 列出工作树失败: {e}"


def run_worktree_remove(worktree_id: str, force: bool = False) -> str:
    """
    删除工作树 - s12
    
    Args:
        worktree_id: 工作树ID
        force: 是否强制删除
        
    Returns:
        删除结果
    """
    try:
        wt = WORKTREE_MANAGER.get(worktree_id)
        if not wt:
            return f"错误: 未找到工作树 {worktree_id}"
        
        wt_name = wt.name
        wt_path = wt.path
        
        success = WORKTREE_MANAGER.remove(worktree_id, force)
        
        if success:
            return f"✅ 工作树已删除: {wt_name}\n路径 {wt_path} 已清理。"
        else:
            return f"错误: 删除工作树失败"
    except ValueError as e:
        return f"错误: {e}"
    except Exception as e:
        return f"错误: 删除工作树失败: {e}"


def run_compact(messages: List[Dict], reason: str = "") -> str:
    """
    压缩上下文 - s06
    
    Args:
        messages: 当前消息列表（会被修改）
        reason: 压缩原因
        
    Returns:
        压缩结果
    """
    try:
        original_tokens = COMPACTOR.estimate_tokens(messages)
        compacted, summary = COMPACTOR.compact(messages)
        
        # 清空原列表并添加压缩后的消息
        messages.clear()
        messages.extend(compacted)
        
        new_tokens = COMPACTOR.estimate_tokens(messages)
        saved = original_tokens - new_tokens
        
        reason_str = f" ({reason})" if reason else ""
        return f"✅ 上下文已压缩{reason_str}\n原始: {original_tokens} tokens → 现在: {new_tokens} tokens (节省 {saved} tokens)\n\n总结:\n{summary}"
    except Exception as e:
        return f"错误: 压缩失败: {e}"


def run_load_skill(name: str) -> str:
    """
    加载技能内容 - s05
    
    两层注入:
    - Layer 1: 系统提示中的技能摘要（已自动注入）
    - Layer 2: 通过此函数返回完整技能内容
    
    Args:
        name: 技能名称
        
    Returns:
        技能完整内容
    """
    return SKILL_MANAGER.load_skill(name)


# ============================================================
# 子Agent系统 (s04: Subagents)
# ============================================================

# 子Agent系统提示
SUBAGENT_SYSTEM = f"""你是一个子任务执行Agent。你的工作是完成父Agent分配的具体任务。

工作目录: {WORKDIR}

你可以使用以下工具:
- bash: 执行shell命令
- read_file: 读取文件内容
- write_file: 创建或覆盖写入文件
- edit_file: 精确替换文件中的内容

工作原则:
1. 专注于完成分配给你的具体任务
2. 完成后简洁地汇报结果，不要过多解释
3. 如果遇到问题，说明原因和建议的解决方案
"""

# 子Agent可用工具（不包含task，避免无限嵌套）
SUBAGENT_TOOLS = [
    tool for tool in TOOLS if tool["name"] != "task"
]


def run_subagent(prompt: str) -> str:
    """
    运行子Agent执行任务 - s04
    
    核心特点:
    1. 以空messages启动，干净上下文
    2. 运行独立的agent_loop
    3. 只返回最终摘要，不返回中间过程
    4. 子上下文在完成后丢弃
    
    Args:
        prompt: 给子Agent的任务描述
        
    Returns:
        执行结果摘要
    """
    print(f"\n🚀 启动子Agent执行任务...")
    
    # 子Agent以空messages启动
    sub_messages = [{"role": "user", "content": prompt}]
    
    try:
        # 运行子Agent循环（使用子Agent的系统和工具）
        _subagent_loop(sub_messages)
        
        # 提取最终响应
        last_message = sub_messages[-1]
        result = ""
        
        if isinstance(last_message.get("content"), str):
            result = last_message["content"]
        elif isinstance(last_message.get("content"), list):
            # Anthropic格式
            for block in last_message["content"]:
                if hasattr(block, "text"):
                    result = block.text
                    break
        
        return f"✅ 子Agent执行完成:\n{result}" if result else "✅ 子Agent执行完成（无输出）"
        
    except Exception as e:
        return f"❌ 子Agent执行失败: {e}"


def _subagent_loop(messages: list):
    """
    子Agent的核心循环 - s04
    
    与主循环类似，但使用不同的系统提示和工具集
    """
    while True:
        response, api_format = _call_subagent_llm(messages)
        
        if api_format == "openai":
            choice = response.choices[0]
            assistant_message = choice.message
            
            messages.append({
                "role": "assistant",
                "content": assistant_message.content or "",
                "tool_calls": [{"id": tc.id, "type": "function", "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments
                }} for tc in (assistant_message.tool_calls or [])]
            } if assistant_message.tool_calls else {"role": "assistant", "content": assistant_message.content or ""})
            
            if choice.finish_reason != "tool_calls":
                return
            
            import json
            results = []
            for tool_call in assistant_message.tool_calls:
                tool_name = tool_call.function.name
                tool_input = json.loads(tool_call.function.arguments)
                
                print(f"    📍 子任务: {tool_input.get('command', tool_name)[:50]}...")
                output = execute_tool(tool_name, tool_input)
                
                results.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "content": output,
                })
            
            messages.extend(results)
            
        else:
            # Anthropic格式
            messages.append({"role": "assistant", "content": response.content})
            
            if response.stop_reason != "tool_use":
                return
            
            results = []
            for block in response.content:
                if block.type == "tool_use":
                    print(f"    📍 子任务: {block.input.get('command', block.name)[:50]}...")
                    output = execute_tool(block.name, block.input)
                    
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": output,
                    })
            
            messages.append({"role": "user", "content": results})


def _call_subagent_llm(messages: list, tools: list = None):
    """调用LLM（子Agent版本）"""
    if tools is None:
        tools = SUBAGENT_TOOLS
    
    if API_TYPE == "openai":
        openai_messages = [{"role": "system", "content": SUBAGENT_SYSTEM}] + messages
        openai_tools = [{"type": "function", "function": {
            "name": t["name"],
            "description": t["description"],
            "parameters": t["input_schema"]
        }} for t in tools]
        
        response = client.chat.completions.create(
            model=MODEL,
            messages=openai_messages,
            tools=openai_tools if openai_tools else None,
            max_tokens=4000,
        )
        return response, "openai"
    else:
        response = client.messages.create(
            model=MODEL,
            system=SUBAGENT_SYSTEM,
            messages=messages,
            tools=tools,
            max_tokens=4000,
        )
        return response, "anthropic"


# ============================================================
# 工具分发映射 (s02: dispatch map)
# ============================================================

TOOL_HANDLERS = {
    "bash": lambda **kwargs: run_bash(kwargs["command"]),
    "read_file": lambda **kwargs: run_read_file(
        kwargs["file_path"],
        kwargs.get("start_line"),
        kwargs.get("end_line")
    ),
    "write_file": lambda **kwargs: run_write_file(
        kwargs["file_path"],
        kwargs["content"]
    ),
    "edit_file": lambda **kwargs: run_edit_file(
        kwargs["file_path"],
        kwargs["old_text"],
        kwargs["new_text"]
    ),
    "TodoWrite": lambda **kwargs: run_todo_write(kwargs["todos"]),
    "task": lambda **kwargs: run_subagent(kwargs["prompt"]),  # s04
    "load_skill": lambda **kwargs: run_load_skill(kwargs["name"]),  # s05
    "task_create": lambda **kwargs: run_task_create(
        kwargs["subject"],
        kwargs.get("description", ""),
        kwargs.get("blockedBy")
    ),  # s07
    "task_get": lambda **kwargs: run_task_get(kwargs["task_id"]),  # s07
    "task_update": lambda **kwargs: run_task_update(
        kwargs["task_id"],
        kwargs["status"],
        kwargs.get("description")
    ),  # s07
    "task_list": lambda **kwargs: run_task_list(),  # s07
    "background": lambda **kwargs: run_background(kwargs["prompt"]),  # s08
    "get_background_tasks": lambda **kwargs: run_get_background_tasks(
        kwargs.get("task_id")
    ),  # s08
    "team_create": lambda **kwargs: run_team_create(kwargs["name"]),  # s09
    "team_add_agent": lambda **kwargs: run_team_add_agent(
        kwargs["team_name"],
        kwargs["agent_name"],
        kwargs["role"],
        kwargs.get("skills")
    ),  # s09
    "team_create_task": lambda **kwargs: run_team_create_task(
        kwargs["team_name"],
        kwargs["description"],
        kwargs.get("priority", 0),
        kwargs.get("dependencies")
    ),  # s09
    "team_assign_task": lambda **kwargs: run_team_assign_task(
        kwargs["team_name"],
        kwargs["task_id"],
        kwargs["agent_id"]
    ),  # s09
    "team_status": lambda **kwargs: run_team_status(kwargs.get("team_name")),  # s09
    "autonomous": lambda **kwargs: run_autonomous(
        kwargs["description"],
        kwargs["success_criteria"],
        kwargs.get("max_iterations", 20)
    ),  # s11
    "autonomous_status": lambda **kwargs: run_autonomous_status(
        kwargs.get("agent_id")
    ),  # s11
    "worktree_create": lambda **kwargs: run_worktree_create(
        kwargs["name"],
        kwargs.get("branch"),
        kwargs.get("task_id", "")
    ),  # s12
    "worktree_list": lambda **kwargs: run_worktree_list(),  # s12
    "worktree_remove": lambda **kwargs: run_worktree_remove(
        kwargs["worktree_id"],
        kwargs.get("force", False)
    ),  # s12
    # compact需要特殊处理，在agent_loop中直接调用
}


# ============================================================
def call_llm(messages: list, tools: list):
    """统一的LLM调用接口，支持Anthropic和OpenAI"""
    if API_TYPE == "openai":
        # OpenAI格式：系统提示放在messages里
        openai_messages = [{"role": "system", "content": SYSTEM}] + messages
        
        # 转换工具格式为OpenAI格式
        openai_tools = [{"type": "function", "function": {
            "name": t["name"],
            "description": t["description"],
            "parameters": t["input_schema"]
        }} for t in tools]
        
        response = client.chat.completions.create(
            model=MODEL,
            messages=openai_messages,
            tools=openai_tools if openai_tools else None,
            max_tokens=4000,
        )
        return response, "openai"
    else:
        # Anthropic格式
        response = client.messages.create(
            model=MODEL,
            system=SYSTEM,
            messages=messages,
            tools=tools,
            max_tokens=4000,
        )
        return response, "anthropic"


def execute_tool(tool_name: str, tool_input: dict) -> str:
    """执行工具调用 - 使用dispatch map模式"""
    # 处理自主Agent的特殊工具
    if tool_name == "report_completion":
        return f"✅ 目标完成报告已收到: {tool_input.get('result', '')}"
    elif tool_name == "report_failure":
        return f"❌ 目标失败报告已收到: {tool_input.get('reason', '')}"
    
    handler = TOOL_HANDLERS.get(tool_name)
    if handler:
        return handler(**tool_input)
    return f"错误: 未知工具: {tool_name}"


def agent_loop(messages: list):
    """
    Agent核心循环 (s03-s06: 带任务规划和上下文压缩)
    
    循环逻辑:
    1. 检查是否需要nag提醒
    2. s06: 检查是否需要自动压缩
    3. s06: 执行micro_compact
    4. 发送消息给LLM
    5. 检查stop_reason
    6. 如果调用了工具，执行工具并返回结果
    7. 增加round计数
    8. 重复直到stop_reason != "tool_use"
    """
    while True:
        # s03: 检查是否需要nag提醒
        if TODO_MANAGER.should_nag():
            nag_msg = TODO_MANAGER.get_nag_message()
            print(f"\n{ nag_msg}")
            messages.append({"role": "user", "content": nag_msg})
        
        # s06: 检查是否需要自动压缩
        if COMPACTOR.should_auto_compact(messages):
            print(f"\n⚠️ 上下文超过阈值({COMPACTOR.auto_compact_threshold} tokens)，自动压缩...")
            result = run_compact(messages, "token超过阈值")
            print(result)
        
        # s06: 执行micro_compact（静默）
        messages[:] = COMPACTOR.micro_compact(messages)
        
        response, api_format = call_llm(messages, TOOLS)
        
        if api_format == "openai":
            # OpenAI响应处理
            choice = response.choices[0]
            assistant_message = choice.message
            
            # 添加助手响应到历史
            messages.append({
                "role": "assistant",
                "content": assistant_message.content or "",
                "tool_calls": [{"id": tc.id, "type": "function", "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments
                }} for tc in (assistant_message.tool_calls or [])]
            } if assistant_message.tool_calls else {"role": "assistant", "content": assistant_message.content or ""})
            
            # 检查是否需要停止
            if choice.finish_reason != "tool_calls":
                return
            
            # 执行工具调用
            import json
            results = []
            todo_updated = False  # s03: 跟踪是否调用了TodoWrite
            for tool_call in assistant_message.tool_calls:
                tool_name = tool_call.function.name
                tool_input = json.loads(tool_call.function.arguments)
                
                print(f"\n🔧 执行: {tool_input.get('command', tool_name)}")
                
                # s06: 处理compact工具（需要访问messages）
                if tool_name == "compact":
                    output = run_compact(messages, tool_input.get("reason", ""))
                else:
                    output = execute_tool(tool_name, tool_input)
                
                print(f"📤 输出: {output[:200]}{'...' if len(output) > 200 else ''}")
                
                # s03: 如果调用了TodoWrite，标记已更新
                if tool_name == "TodoWrite":
                    todo_updated = True
                
                results.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "content": output,
                })
            
            # s03: 如果没有调用TodoWrite，增加round计数
            if not todo_updated:
                TODO_MANAGER.increment_round()
            
            # 添加工具结果到历史
            messages.extend(results)
            
        else:
            # Anthropic响应处理
            messages.append({"role": "assistant", "content": response.content})
            
            # 检查是否需要停止
            if response.stop_reason != "tool_use":
                return
            
            # 执行工具调用
            results = []
            todo_updated = False  # s03: 跟踪是否调用了TodoWrite
            for block in response.content:
                if block.type == "tool_use":
                    print(f"\n🔧 执行: {block.input.get('command', block.name)}")
                    output = execute_tool(block.name, block.input)
                    print(f"📤 输出: {output[:200]}{'...' if len(output) > 200 else ''}")
                    
                    # s03: 如果调用了TodoWrite，标记已更新
                    if block.name == "TodoWrite":
                        todo_updated = True
                    
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": output,
                    })
            
            # s03: 如果没有调用TodoWrite，增加round计数
            if not todo_updated:
                TODO_MANAGER.increment_round()
            
            # 添加工具结果到历史
            messages.append({"role": "user", "content": results})


def main():
    """主函数 - 交互式REPL"""
    print("=" * 50)
    print("🤖 My AI Agent - s05 技能加载版本")
    print("=" * 50)
    print(f"工作目录: {WORKDIR}")
    print(f"API类型: {API_TYPE}")
    print(f"模型: {MODEL}")
    if BASE_URL:
        print(f"API端点: {BASE_URL}")
    print(f"可用工具: {', '.join([t['name'] for t in TOOLS])}")
    
    # 显示技能信息
    skill_names = SKILL_MANAGER.get_skill_names()
    if skill_names:
        print(f"可用技能: {', '.join(skill_names)}")
    
    # 显示压缩配置
    print(f"\n上下文压缩: 启用")
    print(f"  - 自动压缩阈值: {COMPACTOR.auto_compact_threshold} tokens")
    print(f"  - 微压缩: 保留最近3个tool_result")
    
    # 显示任务系统状态
    task_stats = TASK_MANAGER.get_stats()
    if task_stats["total"] > 0:
        print(f"\n持久化任务: {task_stats['total']}个")
        print(f"  - 可执行: {task_stats['pending']}个")
        print(f"  - 进行中: {task_stats['in_progress']}个")
        print(f"  - 已完成: {task_stats['completed']}个")
        print(f"  - 被卡住: {task_stats['blocked']}个")
    
    print("\n提示: 输入 'exit' 或 'quit' 退出")
    print("提示: 使用load_skill加载技能详细内容")
    print("提示: 使用compact手动压缩上下文历史")
    print("提示: 使用task_create/task_update管理持久化任务")
    print("提示: 使用background启动后台任务，不阻塞主循环")
    print("提示: 使用autonomous启动自主Agent，自主决策执行\n")
    
    history = []
    
    while True:
        try:
            # 获取用户输入
            query = input("\n👤 你: ").strip()
            
            # 检查退出命令
            if query.lower() in ("exit", "quit", "q", ""):
                print("\n👋 再见!")
                break
            
            # 添加用户消息到历史
            history.append({"role": "user", "content": query})
            
            # 运行Agent循环
            agent_loop(history)
            
            # 获取并显示最终响应
            last_message = history[-1]
            if isinstance(last_message.get("content"), str) and last_message["content"]:
                print(f"\n🤖 Agent: {last_message['content']}")
            elif API_TYPE == "openai" and last_message.get("role") == "assistant":
                if last_message.get("content"):
                    print(f"\n🤖 Agent: {last_message['content']}")
            
        except KeyboardInterrupt:
            print("\n\n👋 再见!")
            break
        except Exception as e:
            print(f"\n❌ 错误: {e}")


if __name__ == "__main__":
    main()
