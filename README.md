# 共创申请门户

这是本地生成的外部来源与独立接收端，仅用于提供数据、页面、协议与回执。仓库提供合成来源服务与技术方 RPA 客户端，所有单位、厂商、研究记录和门户内容均为虚构数据，不连接真实业务系统。

## 启动

安装Docker后，在项目根目录运行 docker compose up --build，服务默认监听 http://127.0.0.1:8765。若直接在主机运行，Python 3.11+执行 pip install -r requirements.txt，再运行 python -m source.app --port 8765。浏览器任务通过Playwright 1.56.0提供的Chromium测试来源页面。

输入示例位于 inputs/request.json；业务字段、页面与协议边界见 docs/source-contract.md，RPA 客户端的字段身份、条件义务、冲突收敛、提交门禁与补正规则见 docs/client-contract.md。示例是项目可读输入格式，原件与来源修订均由演练服务产生。

## RPA 客户端（client/）

客户端经 Playwright 驱动真实 Chromium 页面续填门户，不生成离线申请文件：

```bash
python -m client.cli --base http://127.0.0.1:8765 --evidence-dir runs/01 import --request inputs/request.json  # 导入并保存草稿
python -m client.cli --base http://127.0.0.1:8765 reconcile --request inputs/request.json                      # 差异核对（只读）
python -m client.cli --base http://127.0.0.1:8765 --evidence-dir runs/01 submit --request inputs/request.json   # 条件满足时正式提交
python -m client.cli --base http://127.0.0.1:8765 --evidence-dir runs/01 correct --correction correction.json   # 按原申请号定向补正
python -m client.cli --base http://127.0.0.1:8765 history                                                        # 提交经历查询
```

差异核对报告逐字段标明“已保存/待填/不适用”、材料义务与场景方确认状态；证据目录留存每次页面动作、保存答复、受理回执、截图与 HTML 快照。失效枚举阻断而不兜底为第一个选项；409 冲突重读页面保留场景方新内容后重试；503/超时先复核落盘再决定，不重建申请；确认按修订生效，范围变化后明确等待场景方重新确认。

## 来源说明

服务页面 / 简述当前来源。JSON与XML接口描述输入契约，页面展示来源交互；POST /__control 只用于本地演练人员切换来源修订、可用性和延迟场景。状态可用 --state /path/outside/source-state.json 选择性落盘，默认每次启动恢复初始样本。端点行为和合成记录见 source/app.py。该控制端点仅供演练检查，RPA 客户端不引用它，技术方不能借此代场景方确认。

## 检查

运行 python -m unittest discover -s tests -v 检查来源端、原件、门户状态、合成接收端以及 RPA 客户端。涉及页面的测试会启动真实Chromium：tests/test_source.py 校验来源端本身，tests/test_client.py 以可重复的浏览器检查说明双方编辑相遇、字段字典变化、撤范围、答复丢失、确认修订与定向补正相遇时哪些内容能够提交。
