# My AI Agent

基于 [learn-claude-code](https://github.com/shareAI-lab/learn-claude-code) 教程构建的最小可用 AI Agent。

## 核心理念

> **"One loop & Bash is all you need"** —— 一个循环 + Bash = 一个Agent

Agent的智能来自于模型本身，代码只是提供操作环境的 **Harness（工具）**。

## 项目结构

```
my-ai-agent/
├── src/              # 源代码目录
│   ├── __init__.py   # 包初始化文件
│   └── main.py       # 主程序模块
├── tests/            # 测试目录
│   └── __init__.py   # 测试包初始化文件
├── agent.py          # 核心Agent实现
├── requirements.txt  # Python依赖
├── .env.example      # 环境变量示例
└── README.md         # 本文件
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置API Key

```bash
cp .env.example .env
# 编辑 .env 文件，填入你的 Anthropic API Key
```

### 3. 运行Agent

```bash
python agent.py
```

## 功能特性

### 当前实现 (v0.1)

- ✅ **Agent循环** (s01): 核心的 `while stop_reason == "tool_use"` 循环
- ✅ **Bash工具** (s01): 执行shell命令，带安全检查
- ✅ **交互式REPL**: 命令行对话界面

### 架构图

```
+--------+      +-------+      +---------+
|  User  | ---> |  LLM  | ---> |  Bash   |
| prompt |      |       |      | execute |
+--------+      +---+---+      +----+----+
                    ^                |
                    |   tool_result  |
                    +----------------+
                    (loop until done)
```

## 使用示例

```
==================================================
🤖 My AI Agent - 最小可用版本
==================================================
工作目录: /Users/roryyu/Downloads/minimax-project/my-ai-agent
模型: claude-3-5-sonnet-20241022

提示: 输入 'exit' 或 'quit' 退出

👤 你: 列出当前目录的文件

🔧 执行: ls -la
📤 输出: total 32...

🤖 Agent: 当前目录包含以下文件：
- agent.py
- requirements.txt
- .env.example
- README.md

👤 你: exit

👋 再见!
```

## 下一步计划

按照 learn-claude-code 教程逐步添加：

- [ ] **s02**: 添加 read_file, write_file, edit_file 工具
- [ ] **s03**: 添加 TodoWrite 任务规划
- [ ] **s04**: 添加 Subagent 子任务
- [ ] **s05**: 添加 Skills 技能加载
- [ ] **s06**: 添加 Context Compact 上下文压缩
- [ ] **s07**: 添加 Task System 任务系统
- [ ] **s08**: 添加 Background Tasks 后台任务
- [ ] **s09+**: 添加 Agent Teams 团队协作

## 核心代码

Agent循环的核心逻辑（约30行）：

```python
def agent_loop(messages: list):
    while True:
        response = client.messages.create(
            model=MODEL, system=SYSTEM,
            messages=messages, tools=TOOLS,
            max_tokens=4000,
        )
        messages.append({"role": "assistant", "content": response.content})
        
        if response.stop_reason != "tool_use":
            return
        
        results = []
        for block in response.content:
            if block.type == "tool_use":
                output = run_bash(block.input["command"])
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output,
                })
        messages.append({"role": "user", "content": results})
```

## 参考资料

- [learn-claude-code](https://github.com/shareAI-lab/learn-claude-code) - 原始教程
- [Anthropic API文档](https://docs.anthropic.com/)

---

**建造优秀的工具，Agent会完成剩下的工作。**
