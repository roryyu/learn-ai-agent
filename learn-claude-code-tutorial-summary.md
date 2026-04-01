# Learn Claude Code 教程学习心得

## 项目概述

**Learn Claude Code** 是一个关于"Harness Engineering（工具工程）"的教学项目，通过12个渐进式课程，教你如何为AI Agent构建"工具（Harness）"。

核心思想：**模型就是Agent，代码只是工具**。Agent的智能来自于模型本身，而非周围的代码框架。

---

## 核心理念：模型即Agent

### 什么是真正的Agent？

Agent是一个神经网络（Transformer、RNN等），通过数十亿次梯度更新训练，学会感知环境、推理目标并采取行动。

**历史证明：**
- 2013年 DeepMind DQN 玩Atari游戏
- 2019年 OpenAI Five 征服Dota 2
- 2019年 DeepMind AlphaStar 掌握星际争霸II
- 2024-2025年 LLM Agent 重塑软件工程

**共同点：Agent永远是模型本身，不是周围的代码。**

### 什么不是Agent？

- 拖放式工作流构建器
- 无代码"AI Agent"平台
- Prompt链编排库

这些都是"Prompt Plumbing"——用程序逻辑强行堆砌，试图通过胶水代码产生自主行为。这是死路一条。

### 思维转变：从"开发Agent"到"开发工具"

当有人说"我在开发Agent"时，只可能意味着两件事：

1. **训练模型** - 通过强化学习、微调、RLHF等方法调整权重
2. **构建工具（Harness）** - 编写代码为模型提供操作环境

**工具 = 工具 + 知识 + 观察 + 行动接口 + 权限**

```
Harness = Tools + Knowledge + Observation + Action Interfaces + Permissions

    Tools:          文件I/O、Shell、网络、数据库、浏览器
    Knowledge:      产品文档、领域参考、API规范、风格指南
    Observation:    git diff、错误日志、浏览器状态、传感器数据
    Action:         CLI命令、API调用、UI交互
    Permissions:    沙箱、审批工作流、信任边界
```

**模型决策，工具执行。模型推理，工具提供上下文。模型是司机，工具是车辆。**

---

## 12个渐进式课程

### Phase 1: 循环基础

#### s01: The Agent Loop（Agent循环）
**核心理念：** *"One loop & Bash is all you need"* —— 一个工具 + 一个循环 = 一个Agent

```python
def agent_loop(messages):
    while True:
        response = client.messages.create(
            model=MODEL, system=SYSTEM,
            messages=messages, tools=TOOLS,
        )
        messages.append({"role": "assistant", "content": response.content})
        
        if response.stop_reason != "tool_use":
            return
        
        results = []
        for block in response.content:
            if block.type == "tool_use":
                output = TOOL_HANDLERS[block.name](**block.input)
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output,
                })
        messages.append({"role": "user", "content": results})
```

**关键洞察：** 循环持续运行，直到模型不再调用工具。这是所有Agent的基础模式。

#### s02: Tool Use（工具使用）
**核心理念：** *"Adding a tool means adding one handler"* —— 添加工具只需添加一个处理器

- 使用dispatch map模式：`{tool_name: handler_function}`
- 循环本身不变，只需扩展TOOLS数组和TOOL_HANDLERS映射
- 新增工具：read_file、write_file、edit_file

#### s03: TodoWrite（任务规划）
**核心理念：** *"An agent without a plan drifts"* —— 没有计划的Agent会漂移

- 引入TodoManager管理多步骤任务
- 状态：pending → in_progress → completed
- 添加"nag reminder"机制：3轮未更新todo时自动提醒
- 模型自己跟踪进度，人类可见

#### s04: Subagents（子Agent）
**核心理念：** *"Break big tasks down; each subtask gets a clean context"* —— 大任务拆小，每个小任务干净的上下文

```
Parent agent                     Subagent
+------------------+             +------------------+
| messages=[...]   |             | messages=[]      |  <-- fresh
|                  |  dispatch   |                  |
| tool: task       | ----------> | while tool_use:  |
|   prompt="..."   |             |   call tools     |
|                  |  summary    |   append results |
|   result = "..." | <---------- | return last text |
+------------------+             +------------------+
```

- Subagent以空messages启动，运行自己的循环
- 只有最终文本返回给父Agent，子上下文直接丢弃
- 进程隔离带来上下文隔离

---

### Phase 2: 规划与知识

#### s05: Skills（技能加载）
**核心理念：** *"Load knowledge when you need it, not upfront"* —— 按需加载知识，不要预加载

两层技能注入避免系统提示膨胀：
- **Layer 1（廉价）**：系统提示中只有技能名称和描述（~100 tokens/技能）
- **Layer 2（按需）**：通过tool_result返回完整技能内容

```
skills/
  pdf/
    SKILL.md          <-- frontmatter (name, description) + body
  code-review/
    SKILL.md
```

#### s06: Context Compact（上下文压缩）
**核心理念：** *"Context will fill up; you need a way to make room"* —— 上下文会满，你需要清理空间

三层压缩策略实现无限会话：

1. **Layer 1: micro_compact**（静默，每轮执行）
   - 将非read_file的tool_result内容替换为"[Previous: used {tool_name}]"
   - 保留最近3个结果

2. **Layer 2: auto_compact**（token超过阈值时触发）
   - 保存完整对话到.transcripts/
   - 请求LLM总结对话
   - 用总结替换所有消息

3. **Layer 3: compact tool**（手动触发）
   - 模型调用compact工具立即压缩

#### s07: Task System（任务系统）
**核心理念：** *"Break big goals into small tasks, order them, persist to disk"* —— 大目标拆成小任务，排好序，记在磁盘上

将扁平清单升级为持久化到磁盘的**任务图**：

```
.tasks/
  task_1.json  {"id":1, "status":"completed"}
  task_2.json  {"id":2, "blockedBy":[1], "status":"pending"}
  task_3.json  {"id":3, "blockedBy":[1], "status":"pending"}

任务图 (DAG):
                 +----------+
            +--> | task 2   | --+
            |    | pending  |   |
+----------+     +----------+    +--> +----------+
| task 1   |                          | task 4   |
| completed| --> +----------+    +--> | blocked  |
+----------+     | task 3   | --+     +----------+
                 | pending  |
                 +----------+
```

- 任务图回答三个问题：什么可以做？什么被卡住？什么做完了？
- 完成任务时自动解锁后续任务
- 持久化存储，上下文压缩后仍然存活

---

### Phase 3: 持久化

#### s08: Background Tasks（后台任务）
**核心理念：** *"Run slow operations in the background; the agent keeps thinking"* —— 慢操作在后台运行，Agent继续思考

```
Main thread                Background thread
+-----------------+        +-----------------+
| agent loop      |        | task executes   |
| ...             |        | ...             |
| [LLM call] <---+------- | enqueue(result) |
|  ^drain queue   |        +-----------------+
+-----------------+
```

- 后台线程执行命令，通知队列传递结果
- Agent不阻塞，可以继续其他工作
- 结果在下一轮LLM调用前注入

---

### Phase 4: 团队协作

#### s09: Agent Teams（Agent团队）
**核心理念：** *"When the task is too big for one, delegate to teammates"* —— 任务太大时，委派给队友

```
.team/config.json                   .team/inbox/
+----------------------------+      +------------------+
| {"team_name": "default",   |      | alice.jsonl      |
|  "members": [              |      | bob.jsonl        |
|    {"name":"alice",        |      | lead.jsonl       |
|     "role":"coder",        |      +------------------+
|     "status":"idle"}       |
|  ]}                        |
+----------------------------+
```

- 持久化命名Agent，基于文件的JSONL收件箱
- 每个队友在独立线程中运行自己的Agent循环
- 通过append-only收件箱通信

#### s10: Team Protocols（团队协议）
**核心理念：** *"Teammates need shared communication rules"* —— 队友需要共享通信规则

实现两个协议：

1. **Shutdown Protocol（关闭协议）**
   ```
   pending -> approved | rejected
   ```
   - Lead发送shutdown_request（带request_id）
   - Teammate回复shutdown_response（相同request_id）

2. **Plan Approval Protocol（计划审批协议）**
   ```
   pending -> approved | rejected
   ```
   - Teammate提交plan_approval
   - Lead审批后回复plan_approval_response

使用相同的request_id关联模式处理两个领域。

#### s11: Autonomous Agents（自主Agent）
**核心理念：** *"Teammates scan the board and claim tasks themselves"* —— 队友自己扫描任务板并认领任务

```
Teammate lifecycle:
+-------+
| spawn |
+---+---+
    |
    v
+-------+  tool_use    +-------+
| WORK  | <----------- |  LLM  |
+---+---+              +-------+
    |
    | stop_reason != tool_use
    v
+--------+
| IDLE   | poll every 5s for up to 60s
+---+----+
    |
    +---> check inbox -> message? -> resume WORK
    |
    +---> scan .tasks/ -> unclaimed? -> claim -> resume WORK
    |
    +---> timeout (60s) -> shutdown
```

- 空闲循环：轮询收件箱和未认领任务
- 自动认领任务，无需Lead分配
- 上下文压缩后重新注入身份信息

#### s12: Worktree + Task Isolation（工作树与任务隔离）
**核心理念：** *"Each works in its own directory, no interference"* —— 各自在自己的目录工作，互不干扰

```
.tasks/task_12.json
  {
    "id": 12,
    "subject": "Implement auth refactor",
    "status": "in_progress",
    "worktree": "auth-refactor"
  }

.worktrees/index.json
  {
    "worktrees": [
      {
        "name": "auth-refactor",
        "path": ".../.worktrees/auth-refactor",
        "branch": "wt/auth-refactor",
        "task_id": 12,
        "status": "active"
      }
    ]
  }
```

- 目录级隔离实现并行任务执行
- 任务是控制平面，worktree是执行平面
- 通过task_id绑定，协调一致

---

## 完整实现：s_full.py

`s_full.py`是综合所有机制的完整参考实现（s01-s11），展示了如何将各个组件组合在一起：

```
+------------------------------------------------------------------+
|                        FULL AGENT                                 |
|                                                                   |
|  System prompt (s05 skills, task-first + optional todo nag)      |
|                                                                   |
|  Before each LLM call:                                            |
|  +--------------------+  +------------------+  +--------------+  |
|  | Microcompact (s06) |  | Drain bg (s08)   |  | Check inbox  |  |
|  | Auto-compact (s06) |  | notifications    |  | (s09)        |  |
|  +--------------------+  +------------------+  +--------------+  |
|                                                                   |
|  Tool dispatch (s02 pattern):                                     |
|  +--------+----------+----------+---------+-----------+          |
|  | bash   | read     | write    | edit    | TodoWrite |          |
|  | task   | load_sk  | compress | bg_run  | bg_check  |          |
|  | t_crt  | t_get    | t_upd    | t_list  | spawn_tm  |          |
|  | list_tm| send_msg | rd_inbox | bcast   | shutdown  |          |
|  | plan   | idle     | claim    |         |           |          |
|  +--------+----------+----------+---------+-----------+          |
|                                                                   |
|  Subagent (s04):  spawn -> work -> return summary                 |
|  Teammate (s09):  spawn -> work -> idle -> auto-claim (s11)      |
|  Shutdown (s10):  request_id handshake                            |
|  Plan gate (s10): submit -> approve/reject                        |
+------------------------------------------------------------------+
```

---

## 关键设计原则

### 1. 循环不变原则
所有机制都叠加在基础循环之上，**循环本身始终不变**。

### 2. 模型驱动原则
模型决定何时调用工具、何时停止。代码只负责执行模型的请求。

### 3. 上下文管理原则
- 及时清理（micro_compact）
- 必要时总结（auto_compact）
- 子任务隔离（subagent）
- 身份重新注入（compression后）

### 4. 持久化原则
重要状态必须持久化到磁盘，不能仅存在于内存：
- 任务图 → `.tasks/`
- 团队配置 → `.team/config.json`
- 对话记录 → `.transcripts/`

### 5. 权限边界原则
- 危险命令拦截（rm -rf /, sudo等）
- 路径安全检查（防止逃离工作区）
- 协议审批（shutdown、plan approval）

---

## 学习路径建议

```
Phase 1: THE LOOP                    Phase 2: PLANNING & KNOWLEDGE
==================                   ==============================
s01  The Agent Loop          [1]     s03  TodoWrite               [5]
     while + stop_reason                  TodoManager + nag reminder
     |                                    |
     +-> s02  Tool Use            [4]     s04  Subagents            [5]
              dispatch map: name->handler     fresh messages[] per child
                                              |
                                         s05  Skills               [5]
                                              SKILL.md via tool_result
                                              |
                                         s06  Context Compact      [5]
                                              3-layer compression

Phase 3: PERSISTENCE                 Phase 4: TEAMS
==================                   =====================
s07  Tasks                   [8]     s09  Agent Teams             [9]
     file-based CRUD + deps graph         teammates + JSONL mailboxes
     |                                    |
s08  Background Tasks        [6]     s10  Team Protocols          [12]
     daemon threads + notify queue        shutdown + plan approval FSM
                                          |
                                     s11  Autonomous Agents       [14]
                                          idle cycle + auto-claim
                                     |
                                     s12  Worktree Isolation      [16]
                                          task coordination + optional isolated execution lanes

[N] = number of tools
```

---

## 实践应用

这些模式不仅适用于编码Agent，也适用于任何领域：

```
Estate management agent    = model + property sensors + maintenance tools + tenant comms
Agricultural agent         = model + soil/weather data + irrigation controls + crop knowledge
Hotel operations agent     = model + booking system + guest channels + facility APIs
Medical research agent     = model + literature search + lab instruments + protocol docs
Manufacturing agent        = model + production line sensors + quality controls + logistics
Education agent            = model + curriculum knowledge + student progress + assessment tools
```

**循环永远相同，工具变化，知识变化，权限变化，Agent（模型）通用。**

---

## 总结

Learn Claude Code 教会我们：

1. **Agent的本质是模型**，不是框架或工作流
2. **代码的角色是Harness（工具）**，为模型提供操作环境
3. **基础循环极其简单**，复杂来自于正确叠加机制
4. **上下文管理是关键**，决定Agent能工作多久
5. **持久化是协作基础**，让状态超越单次对话
6. **协议让多Agent协作成为可能**

**建造优秀的工具，Agent会完成剩下的工作。**

---

## 相关项目

- **Kode Agent CLI**: `npm i -g @shareai-lab/kode` - 开源编码Agent CLI
- **Kode Agent SDK**: 可嵌入后端的Agent能力库
- **claw0**: 从"按需会话"到"始终在线助手"的教学项目

---

*"Bash is all you need. Real agents are all the universe needs."*
