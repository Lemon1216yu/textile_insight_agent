# 织见 · 纺织制造经营智能分析平台

基于 `F:\1_Code_Git\chatbi_mvp` 教学代码改造的可运行项目。业务数据进入 MySQL，Schema 与指标向量进入 Milvus，百炼 qwen3.8-flash 完成问题理解、SQL与分析报告生成，LangGraph 编排多步执行。

> 展示用公司名「东莞德永佳纺织制衣有限公司」；公司名称、岗位与权限均为本项目模拟配置，不代表该公司真实内部制度。

## 现在打开

- 登录页：<http://127.0.0.1:8018>
- 主应用（登录后）：<http://127.0.0.1:8018/app>
- API 文档：<http://127.0.0.1:8018/docs>
- 健康检查：<http://127.0.0.1:8018/api/health>
- 数据库查看（独立管理工具，不在业务网页内）：
  - MySQL → Navicat/Workbench 连接 `127.0.0.1:3318`，详见 [docs/DATABASE_GUIDE.md](docs/DATABASE_GUIDE.md)
  - Milvus 向量库 → Attu 管理台 <http://127.0.0.1:3018>
- Docker Desktop → Containers → **textile-insight**，可看到 mysql / milvus / etcd / minio / attu 五个服务。

采用正式登录：六个企业岗位账号（见下表），初始密码统一为 `demo123`，登录后服务端通过签名 HttpOnly Cookie 确定身份与角色，不信任调用者传入的角色参数。权限同时约束**菜单、数据表、表内敏感字段、数据区域**。

| 用户名 | 岗位 | 数据区域 | 主要权限 |
|---|---|---|---|
| admin | 系统管理员 | 全部 | 全部菜单与账户管理 |
| executive | 经营负责人 | 全部 | 总览/问数/分析/指标/报告 |
| finance | 财务分析师 | 全部 | 同左，含成本与毛利 |
| sales_east | 销售经理 | 华东 | 仅华东订单与库存，隐藏成本/毛利字段，无账户管理 |
| production | 生产主管 | 全部 | 生产批次/产量/良品率/达成率，隐藏销售成本字段 |
| warehouse | 仓储主管 | 全部 | 库存数量/金额/库龄，隐藏销售金额与成本字段 |

## 启动与关闭

先打开 Docker Desktop，等引擎启动。PowerShell 执行：

```powershell
cd F:\1_Code_Git\textile_insight_agent
.\start.ps1
```

脚本会启动五个容器、幂等初始化模拟数据、检查并按需建立 Milvus 索引，然后运行前端与 API。保持此终端开启，Ctrl+C 停止 API。

若 PowerShell 执行策略阻止脚本，可使用仅对本次进程有效的方式：

```powershell
powershell -ExecutionPolicy Bypass -File F:\1_Code_Git\textile_insight_agent\start.ps1
```

数据库可通过 Docker Desktop 停止，也可以执行：

```powershell
docker compose stop
```

`stop` 不删除数据。无需使用 `down -v`。当前已在本机启动了后台 API；`start.ps1` 会识别已运行的本项目服务。需要全部停止时运行 `.\stop.ps1`，会保留数据卷。

## 新机器初始化

需要 Python 3.12、uv、Docker Desktop Linux 容器以及有效模型密钥。生成与向量统一使用 `DASHSCOPE_API_KEY`（百炼，可通过 `TEXTILE_LLM_API_KEY` 覆盖生成侧），密钥只从环境变量或本地 `.env` 读取，不入源码。`DEEPSEEK_API_KEY` 已弃用，项目不再读取。生成模型按 `TEXTILE_LLM_MODELS` 配置候选链，免费额度耗尽时自动切换到下一个模型。

```powershell
uv sync --locked
uv run python scripts/configure.py
docker compose up -d --wait --wait-timeout 180
uv run python scripts/seed.py
uv run python scripts/ensure_index.py
uv run python scripts/check_environment.py
uv run uvicorn textile.app:app --host 127.0.0.1 --port 8018
```

`scripts/configure.py` 首次随机生成 MySQL、MinIO、会话签名所需的本地密码，并保存在忽略提交的 `.env`。已有 `.env` 会保留。修改这些密码不会自动修改已初始化数据卷里的密码，不要随意删除 `.env`。

默认模型 `deepseek-chat`；Embedding `text-embedding-v3`，256 维。可在 `.env` 中设置 `TEXTILE_LLM_MODEL`、`TEXTILE_LLM_BASE_URL`、`TEXTILE_EMBED_MODEL`、`TEXTILE_EMBED_BASE_URL`。更换 Embedding 模型或维度需要重新设计索引并重建，不能混用向量。

## 演示路径

1. 打开 <http://127.0.0.1:8018>，用 `admin / demo123`（或任一岗位账号）登录。
2. 经营总览：按岗位展示 KPI 卡片与月度图表（收入/毛利/订单/产品贡献/库存，生产、仓储为独立视角）。
3. 智能问数：输入业务问题，查看执行过程时间线、SQL 与依据、结果表格。
4. 经营分析：先生成 2–4 步执行计划，按依赖执行并汇总报告，可下载 Markdown。
5. 指标中心：浏览 32 条治理指标（编码/定义/公式/时间口径/单位/维度/负责人/版本/状态），按岗位控制可见性。
6. 个人报告：查看自己的历史任务与报告。
7. 账户管理（仅系统管理员）：新建/编辑用户、启停账号、重置密码。

可直接复制的问题：

- 2026年3月至8月每个月的营业收入和毛利是多少？
- 2026年8月按客户统计营业收入，按收入降序排列。
- 2026年8月各车间的生产良品率是多少？
- 最近一次库存快照，各面料的90天以上库龄占比是多少？
- 分析2026年7月至8月相对5月至6月的利润变化，分别查询销售收入毛利、期间费用和面料产品毛利结构，提出需要核实的因素。

## 数据与口径

所有数据均为生成的模拟数据，不代表真实公司记录。固定随机种子 `20260914`，时间范围为 **2026-03-01 至 2026-08-31**。

| 表 | 用途 | 行数 |
|---|---|---:|
| dim_customers | 客户、区域、客户类型 | 6 |
| dim_products | 全棉、涤纶、混纺面料 | 6 |
| dim_suppliers | 原料供应商 | 3 |
| sales_orders | 销售订单、实际销售成本、交付日期 | 540 |
| production_batches | 生产批次、产量、缺陷、材料人工能源成本 | 108 |
| purchase_orders | 原料采购与到货 | 108 |
| inventory_snapshots | 月末库存与90天以上库龄 | 108 |
| finance_expenses | 区域期间费用 | 54 |
| 合计 | 不含初始化版本控制表 | 933 |

- 营业收入只统计已完成且已交付订单（`delivery_date` 非空）的 `net_amount`，金额均为不含税人民币；收入、毛利、订单数均按**交付日期**归属。
- 毛利为实际收入减订单实际销售成本；不拿产品标准成本替代实际成本。
- 经营利润采用简化管理口径：同期间销售毛利减期间费用，不称为法定净利润。
- 订单和费用是独立事实表，必须分别聚合；AST 校验拒绝直接连接多个事实来源。
- 库存是月末快照，默认最近快照日；不能把多个月库存直接相加。
- 面料数量为米，采购原料为千克；比率用汇总分子除以汇总分母。
- 样本刻意设置了7、8月部分全棉产品成本上升和库存积压，用来验证分析功能。
- “最近”“上月”按系统当前日期计算，样本期以外可能无数据。

## 指标知识库

`textile/metric_catalog.py` 维护 **32 条治理指标**，覆盖销售(9)、财务(7)、生产(6)、采购(5)、库存(5)五个领域。每条包含：指标编码、名称、定义、计算公式、时间字段与口径、单位、可分析维度、负责人、版本、状态、适用范围与限制、管理目标、角色可见范围。示例：

- `SAL-001 营业收入`：按交付月统计已完成订单净额；公式 `Σ 已完成且已交付订单 net_amount`；单位元；时间口径 `delivery_date`；负责销售部；角色可见范围 admin/executive/finance/sales。
- `FIN-004 毛利率`：毛利 ÷ 营业收入 × 100%；口径与 SAL-001 一致，避免分子分母时间错配。
- `PRO-002 良品率`：`(实际产量 − 缺陷量) ÷ 实际产量 × 100%`。
- `INV-002 期末库存金额`：最近快照日各面料 `quantity × 最近标准成本` 求和。
- `INV-005 90天以上库龄占比`：`库存90天以上米数 ÷ 库存总量 × 100%`。

问数链路会先召回指标定义与计算口径，再生成 SQL，保证口径一致。指标说明（32 条）与表说明（8 条）、字段说明（54 条）共 **94 条向量**写入 Milvus 集合 `textile_schema_metrics_v1`（每条 256 维）。重建入口：`uv run python scripts/build_index.py`。

## 结构与教学代码来源

`teaching_mvp/` 是改造前复制的教学代码快照。根目录保留原有教学模块供对照，**实际新入口为 `textile.app:app`，不是旧 `api_service.py`**。

| 当前模块 | 职责与复用 |
|---|---|
| textile/catalog.py | 纺织 Schema、字段说明与 Few-shot |
| textile/metric_catalog.py | 32 条治理指标知识库（定义/公式/口径/负责人/版本/角色可见性） |
| textile/permissions.py | 6 岗位权限矩阵（菜单/表/隐藏字段/区域绑定） |
| textile/models.py | 继承教学 LLMClient 接口，分开聊天和 Embedding 服务 |
| textile/retrieval.py | Milvus 表/字段/指标召回，确定性关键字段补齐，复用教学 BFS |
| textile/security.py | SQLGlot AST 检查、表列权限、用户区域过滤、返回条数上限 |
| textile/db.py | 复用教学 DatabaseClient、连接池、异常分类和慢查询 EXPLAIN；新增前置 EXPLAIN 与8秒查询预算 |
| textile/agent.py | 复用输入校验，LangGraph 规划、依赖执行、一次 SQL 修正、失败保留、证据报告 |
| textile/app.py | API、PBKDF2 登录与会话、改密/退出、账户管理、受限任务池、结果持久化、按岗位看板 |
| static/index.html / app.html / app.css / app.js | 企业后台前端（深色侧边导航 + 浅色内容区），原生实现，ECharts 本地渲染 |
| scripts/ | 环境初始化、数据生成、账户与权限初始化、索引、验收和真实模型评测 |
| tests_textile/ | 安全、集成与账户权限测试 |

数据库账号分工（均绑定 `127.0.0.1:3318`，密码在 `.env`）：

- `textile_reader`：仅 SELECT 业务表，用于问数查询，无法修改数据。
- `textile_app`：SELECT 业务表 + 对 `sys_users` 表 SELECT/INSERT/UPDATE，用于登录与账户维护；无 DDL、无 DELETE（用户用“停用”代替删除）。
- `root`：仅初始化与运维（密码 `TEXTILE_MYSQL_ROOT_PASSWORD`）。

问数路径：输入 → Milvus 表召回 → 候选字段匹配与关键字段补齐 → BFS 关系 → 指标口径检索 → Prompt → LLM SQL → AST/权限/EXPLAIN → MySQL → 带数据的结论。

Agent 路径：LangGraph 生成2–4步计划 → 检查前置依赖 → 每步执行上述问数路径 → 记录结构化结果 → 失败依赖跳过 → 汇总报告。每个任务内部顺序执行；服务同时最多执行2个任务，最多6个运行与排队任务。不是多智能体系统。

## 验证

```powershell
uv run pytest
uv run python scripts/check_environment.py
uv run python scripts/evaluate_textile.py
```

目前实测：**39 项测试通过**（安全、集成、6 岗位账户与权限矩阵）；6 个真实模型问题与标准 SQL 结果一致；浏览器端到端问数与分析成功。详细证据见 [docs/VALIDATION.md](docs/VALIDATION.md)。

评测生成 `artifacts/evaluation-few-shot.json`。可加 `--no-few-shot` 运行不含示例的对照，但本次没有测量基线提升，因此不声称 Few-shot 提升了准确率。比对忽略列别名与行顺序，检查结果形状、字符串与数值容差。这是6例小样本，不是严格企业级基准。

## 当前工程边界

具备真实数据库、真实模型、分层模块、账户与岗位权限、区域/列权限、任务进度、超时与有限纠错、评测和报告证据；以小数据量在本机演示。

账号使用共享初始密码，可在界面修改密码，但整体仍为演示环境，不能视为真实企业身份认证。尚未接入 SSO、生产级审计平台、分布式任务队列、多实例会话管理、高可用与灾备；不应直接暴露到公网。模型可能误解业务问题，关键判断应核对 SQL 和数据。系统稳定性优化（并发、监控、备份等）按项目安排暂缓，后续再做。

不宣称完成简历中的50+表规模、40% Token下降、70%→91%准确率，也不将本次AI辅助实现写成用户此前的独立工作经历。

## 环境修复记录与资料

此次修复了 Docker Desktop 遗留 socket 导致的启动失败，通过备份重命名运行目录解决，未清空 Docker 数据。原 MySQL57/3306 未修改；新实例绑定127.0.0.1:3318，Milvus绑定127.0.0.1:19530。

参考 [Milvus官方Compose示例](https://github.com/milvus-io/milvus/blob/v2.6.2/deployments/docker/standalone/docker-compose.yml)、[LangGraph图API](https://docs.langchain.com/oss/python/langgraph/graph-api)、[DashScope向量接口](https://help.aliyun.com/zh/model-studio/text-embedding-synchronous-api/)。Compose使用命名数据卷保存数据，MinIO镜像通过Quay拉取。
# 2026-09-15 接手更新

业务问数已默认先校验输入、理解与改写问题，再自动选择查询或多步分析；明确单表采用轻量Schema，复杂问题采用Schema Linking。缺少上文的问题提示补充，不直接查库。当前运行链路、验证证据及未完成事项见 [docs/CHAIN_CURRENT.md](docs/CHAIN_CURRENT.md)。
