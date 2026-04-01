# My AI Agent

基于 [learn-claude-code](https://github.com/shareAI-lab/learn-claude-code) 教程构建的完整 AI Agent 系统。

## 核心理念

> **"One loop & dispatch map is all you need"** —— 一个循环 + 分发映射 = 一个Agent

Agent的智能来自于模型本身，代码只是提供操作环境的 **Harness（工具）**。

## 项目结构

```
learn-ai-agent/
├── agent.py          # 核心Agent实现（~3800行，24个工具）
├── requirements.txt  # Python依赖
├── .env.example      # 环境变量示例
├── .gitignore        # Git忽略规则
├── README.md         # 本文件
└── learn-claude-code-tutorial-summary.md  # 教程学习心得
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置API Key

```bash
cp .env.example .env
# 编辑 .env 文件，填入你的 API Key
```

支持两种API类型：
- **Anthropic API** (默认): `API_TYPE=anthropic`
- **OpenAI兼容API**: `API_TYPE=openai`

### 3. 运行Agent

```bash
python agent.py
```

## 功能特性

### 已实现功能 (s01-s12)

| 阶段 | 功能 | 工具 | 描述 |
|------|------|------|------|
| s01 | Agent循环 | bash | 核心循环 + Bash执行 |
| s02 | 工具系统 | read_file, write_file, edit_file | 文件操作工具 |
| s03 | 任务规划 | TodoWrite | 任务列表 + Nag提醒 |
| s04 | 子Agent | task | 上下文隔离的子任务 |
| s05 | 技能加载 | load_skill | 两层注入技能系统 |
| s06 | 上下文压缩 | compact | 三层压缩策略 |
| s07 | 任务系统 | task_create/update/list | DAG任务图 |
| s08 | 后台任务 | background | 异步执行 |
| s09 | Agent团队 | team_create/add_agent | 多Agent协作 |
| s10 | 团队协议 | MessageBus/Protocol | 标准化通信 |
| s11 | 自主Agent | autonomous | 目标驱动自主执行 |
| s12 | 工作树隔离 | worktree_create | 文件隔离环境 |

**总计: 24个工具**

### 架构图

```
┌─────────────────────────────────────────────────────────┐
│                      Agent Core                         │
│  ┌─────────┐    ┌─────────────┐    ┌─────────────────┐ │
│  │  LLM    │───▶│  Tool Call  │───▶│  Dispatch Map   │ │
│  │         │◀───│  Handler    │◀───│  (24 tools)     │ │
│  └─────────┘    └─────────────┘    └─────────────────┘ │
│        ▲                                    │           │
│        └────────────────────────────────────┘           │
│                    (loop until done)                    │
└─────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌──────────────┐    ┌────────────────┐    ┌────────────────┐
│ Task System  │    │  Agent Teams   │    │   Autonomous   │
│ (s07)        │    │  (s09+s10)     │    │   Agents(s11)  │
└──────────────┘    └────────────────┘    └────────────────┘
```

## 使用示例

### 基础对话

```
==================================================
🤖 My AI Agent - 完整版 (s01-s12)
==================================================
工作目录: /Users/roryyu/.../learn-ai-agent
API类型: openai
模型: gpt-4o

提示: 输入 'exit' 或 'quit' 退出

👤 你: 创建一个Python文件，输出Hello World

🔧 执行: write_file
📤 输出: ✅ 成功写入文件: hello.py

🤖 Agent: 已创建 hello.py 文件！

👤 你: exit

👋 再见!
```

### 使用自主Agent

```python
# 启动自主Agent完成复杂任务
autonomous(
    description="重构代码，提取所有工具函数到单独文件",
    success_criteria=["工具函数已提取", "主文件可正常导入"],
    max_iterations=20
)
```

### 创建工作树

```python
# 创建隔离的工作环境
worktree_create(
    name="feature-branch",
    branch="feature/new-feature"
)
```

## 核心代码

Agent循环的核心逻辑：

```python
def agent_loop(messages: list):
    while True:
        # s03: Nag提醒
        if TODO_MANAGER.should_nag():
            messages.append(nag_message)
        
        # s06: 上下文压缩
        if COMPACTOR.should_auto_compact(messages):
            run_compact(messages)
        
        response, api_format = call_llm(messages, TOOLS)
        
        if stop_reason != "tool_use":
            return  # 完成
        
        # Dispatch map 执行工具
        for tool_call in tool_calls:
            output = TOOL_HANDLERS[tool_call.name](**tool_call.input)
            messages.append(tool_result)
```

## 环境变量配置

```bash
# .env 文件示例
API_TYPE=openai                    # anthropic 或 openai
MODEL=gpt-4o                       # 模型名称
API_KEY=your-api-key-here          # API密钥
API_BASE=https://api.openai.com/v1 # 可选：自定义API端点
```

## 参考资料

- [learn-claude-code](https://github.com/shareAI-lab/learn-claude-code) - 原始教程
- [Anthropic API文档](https://docs.anthropic.com/)
- [OpenAI API文档](https://platform.openai.com/)

---

**建造优秀的工具，Agent会完成剩下的工作。**
