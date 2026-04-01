cd /Users/roryyu/Downloads/code/qoder-app/my-ai-agent
source venv/bin/activate
python agent.py

# 03
```
创建一个简单的Python计算器项目，包含以下步骤：
1. 创建calc.py文件，实现加减乘除
2. 创建test_calc.py测试文件
3. 运行测试验证
```

# 04
请帮我完成以下任务：1. 使用task工具派发子任务创建一个Python函数文件utils.py，包含add和subtract函数。2. 使用task工具派发子任务创建测试文件test_utils.py。3. 运行测试验证。请使用task工具派发前两个子任务给子Agent执行。

# 05
请帮我完成以下任务：1. 创建一个Python函数文件utils.py，包含add和subtract函数。2. 加载`code-review`技能。3.使用`code-review`对utils.py进行code review。4.将review结果，写入result.md中

# 07
请帮我创建一个Web项目任务计划：1. 先创建设计文档任务。2. 创建前端开发任务，依赖设计文档。3. 创建后端开发任务，依赖设计文档。4. 创建测试任务，依赖前端和后端。5. 列出所有任务查看状态。6. 将设计文档标记为完成。7. 再次列出任务查看解锁情况。

# 08
请帮我做以下事情：1. 在后台启动一个任务：统计当前目录下所有.py文件的代码行数。2. 然后立即告诉我后台任务已经启动。3. 等待几秒后查询后台任务的结果。

# 09/10
请帮我创建一个开发团队来完成Web项目：1. 创建团队名为\"Web开发组\"。2. 添加一个前端开发者（角色：frontend-developer，技能：react, typescript）。3. 添加一个后端开发者（角色：backend-developer，技能：python, fastapi）。4. 添加一个测试工程师（角色：qa-engineer，技能：automation, selenium）。5. 创建任务：开发登录页面。6. 创建任务：开发登录API（依赖登录页面任务）。7. 将登录页面任务分配给前端开发者。8. 显示团队状态。

# 11
`run_autonomous`,description: 写一个js遍历dom的函数，写完后做code review，然后依据review的结果再次优化，以此往复。success_criteria: 复杂度小于等于n/2。max_iterations: 10