# 运行验收记录

验收日期：2026-09-14。所有业务数据均为模拟数据。

## 环境

- Docker Engine 29.6.2，经 Docker Desktop 的 Linux 引擎运行。
- MySQL 8.0.43，项目端口3318，原MySQL57/3306未修改。
- Milvus 2.6.1，端口19530；etcd、MinIO、MySQL、Milvus、Attu容器均为healthy。
- 实测MySQL只读账号可查询业务表，CREATE TABLE被1142权限错误拒绝；`textile_app` 可读写 sys_users，DELETE 被1142拒绝（用户以停用代替删除）。
- DeepSeek聊天调用成功，DashScope返回256维向量，实际索引94条（8表说明+54字段说明+32指标口径）。

## 自动化与真实模型

- `python -m pytest tests_textile -q`：**39 passed**。覆盖：
  - 安全：危险SQL、多个语句、系统库、文件输出、锁、未知列、成本字段别名与聚合绕过、区域OR/CTE/UNION过滤、匿名访问、伪造角色头、跨事实表重复汇总与空结果。
  - 集成：登录会话、看板数据与实际SQL核对、区域过滤。
  - 账户与权限：6岗位登录与菜单、错误密码与停用拒绝、改密流程、管理员维护与越权拒绝、不能停用自己、生产岗位无销售表、仓储隐藏销售金额但库存金额可见、指标角色可见性。
- `scripts/evaluate_textile.py`：**6/6**。真实模型生成SQL并执行，与人工标准SQL的执行结果比较；简单、中等、复杂各2例；口径已切换为交付日期归属。
- 本次没有运行无Few-shot对照，不报告准确率提升，也不将6例结果外推为企业准确率。

## 浏览器端到端

- 登录页：显示「织见 · 经营智能分析平台 / 某某纺织有限公司」与模拟配置声明；admin 登录成功进入主应用。
- 经营总览（admin/经营/财务）：营业收入 937.61 万元、订单 460 笔、销售 42.28 万米、毛利 275.43 万元；月度趋势与产品贡献图表渲染正常。
- 智能问数：提交「6月营业收入是多少？按产品汇总」→ 任务执行 → 生成 SQL → 返回分产品收入汇总（合计 157.95 万元）与分析报告。
- 指标中心：32 条治理指标完整渲染（编码/定义/公式/口径/负责人/版本/可见性），可按领域筛选与搜索。
- 账户管理：6 个初始账号列表、新建/编辑/启停入口正常。
- 岗位差异（API 实测）：sales 菜单无账户管理、看板无毛利；production 为产量/良品率/达成率视角；warehouse 为库存/库龄视角；finance 含毛利。
# 2026-09-15 接手验证

- `scripts/validate_understanding.py`：8例实际百炼路由调用，8/8，详见`artifacts/routing-smoke.json`。
- `scripts/evaluate_textile.py`：保留原严格结果比对，6/6，详见`artifacts/evaluation-few-shot.json`。小样本不代表生产准确率。
- `pytest tests_textile/test_understanding.py tests_textile/test_security.py tests_textile/test_integration.py -q`：44通过。
- `scripts/validate_auto_api.py`：登录、默认auto提交、轮询、轻量查询、澄清与多步分析；完整记录`artifacts/auto-api-smoke.json`。首次多步部分失败记录保留于`artifacts/auto-api-smoke-before-plan-fix.json`。
- 浏览器验证登录后的新问数表单已取消手动模式按钮，显示独立问题与自动判断说明。
- 最终HTTP验收3/3：简单查询完成（轻量分支）、缺少上下文时澄清且0次SQL、多步分析完成（2个查询子任务）。

# 2026-09-15 第二轮验收（收尾）

环境：MySQL/Milvus/etcd/MinIO/Redis 容器全部 healthy；API 与 arq worker 由 `.\start-platform.ps1` 拉起（迁移 → 指标发布 → seed → 索引检查）。

| 验收项 | 命令 | 结果 | 证据 |
|---|---|---|---|
| **A4 问数结果解释**（确定性，不调模型） | `textile/explain.py` + `tests_textile/test_explain.py` | 结果随返回 `explanation`（口径/公式/单位/时间字段/来源表）；真实问数验证：单指标 SAL-001、跨表 FIN-006（含依赖指标）、扩展表查询正确改口"未命中指标知识库"。⚠️ 前三例采集于指纹 `f22ffa06f0b942cb`（PUR-005 规则改动**之前**）；**评审修复后已在当前指纹 `3b37129c4f29ff8a` 补测 1 例跨表指标**：无内部占位符泄漏、无「时间字段：。」残句、来源表来自执行 SQL | `artifacts/explanation-A4.json`（`f22ffa06f0b942cb`）+ `artifacts/explanation-A4-after-review.json`（`3b37129c4f29ff8a`） |
| 扩展评测（52 例，**新指纹复验**） | `scripts/evaluate_expanded.py` | **49/52（94.2%）**，服务模型为降级链第三个 `deepseek-v4.1-flash`（`qwen3.8-max` 额度亦耗尽）；3 例失败均为**输出格式违规**（AST 校验失败，非口径错误）：PRD-001 与 incoming_inspections 的产物里可见"依据：…"文字被拼进 SQL；PUR-004 产物只有"仅允许单条 SELECT 查询"（同类格式违规，属**推断**、未直接验证） → **评测成绩依赖实际服务模型，不得跨模型外推** | `artifacts/evaluation-expanded.json`；同次存档 `evaluation-expanded-52cases-deepseek-v41-flash-49of52.json` |
| 扩展评测（52 例真实模型） | `scripts/evaluate_expanded.py` | **52/52，1.0**；A10 收尾新增 12 例多表 join（表覆盖 8→20 张，含三表链路 `maintenance_orders`、平均值口径 `supplier_evaluations`），52 例全部由降级模型 `qwen3.8-max-0902` 服务。⚠️ 该次产物已被后续复验覆盖（当时未自动存档）——教训已修复：`write_report()` 现在覆盖前自动存档 `-prev-<时间戳>.json` | `artifacts/evaluation-expanded.json`（prompt `261182dabce6b531`，已被覆盖）；40 例基线 `evaluation-expanded-before-52-cases.json` |
| **扩展评测（52 例）— 当前指纹复验** | `scripts/evaluate_expanded.py` | **49/52（94.2%）** 于 `prompt_version=3b37129c4f29ff8a`，服务模型 `deepseek-v4.1-flash`（降级链第 4 个：qwen3.8-flash / max-0902 / max 三个模型免费额度当日耗尽）。3 例失败且**失败集合与 `ae4f3f4d` 那轮不同**（同模型、不同指纹/用例集）：① `maintenance_orders` **直接证据**——产物可见"依据：…"说明文字被拼进 SQL，触发 `Invalid expression / Unexpected token`；② `PUR-004` 报"仅允许单条 SELECT 查询"，产物未保留 SQL，**属同类推断、未直接验证**；③ `inventory_aging` 模型自行加了问题未要求的日期过滤（只回最近一天，问题明确要求"覆盖全部样本"），属语义偏差而非格式违规。**结论：失败集合依赖实际服务模型，跨模型/跨指纹不可外推** | `artifacts/evaluation-expanded.json`（`write_report()` 自动存档前一版 `evaluation-expanded-prev-*.json`） |
| 一次被基础设施污染的运行（留档，勿引用成绩） | 同上 | 同一次命令在 Docker Desktop 引擎停止期间运行 → 前 12 例通过后全部报 `(2003) Can't connect to MySQL server`，产物为 **12/52**。**该成绩无效**，仅用于说明"评测期间不得动容器/引擎" | 已被下一次运行存档覆盖 |
| 跨表指标抽查（当前指纹） | `scripts/spotcheck_cross_table.py` | **5/5**（FIN-005=287590.00、FIN-006=4.760421、INV-005=1.063898、SAL-008=6.6667、FIN-002=359386.00，均与 gold 逐位一致；无 CROSS JOIN、无明细行 JOIN） | 命令输出（`deepseek-v4.1-flash`） |
| （历史）扩展评测（40 例真实模型） | `scripts/evaluate_expanded.py` | **40/40，1.0**；报告级 `models_used`/`fallback_used` + 逐例 `model`/`fallback` 记录实际服务模型（该轮 40 例全部由降级模型 `qwen3.8-max-0902` 服务，首选 qwen3.8-flash 当日额度耗尽） | `artifacts/evaluation-expanded.json`（prompt `f8f6ad4fc9843e1b`）；首选模型上的 40/40 基线保留为 `evaluation-expanded-before-model-attribution.json`、`evaluation-expanded-qwen3.8-flash-final.json` |
| 混合检索对比（104 例） | `scripts/evaluate_retrieval.py` | 向量 0.990/0.971 → 混合 **1.000/0.981**（recall@4/hit@1）；产物自带边界注记"合成检索探针，非真实用户查询基准" | `artifacts/retrieval-comparison.json` |
| 并发 20 请求（HTTP + arq） | `scripts/validate_concurrency.py` | 20/20 完成、0 缓存命中；admission 最大 **0.266s**（三段修复：5.219s → 3.125s → 0.266s）；排队中位数 2.22s（修复前 4.13s） | `artifacts/concurrency-20.json`；修复前基线 `concurrency-20-quota-blocked.json` |
| 提交延迟隔离测量（无模型） | `scripts/probe_http.py` | 单请求 186ms → **49ms**；20 并发最大 2422ms → **493ms**（连接池修复） | 命令输出 |
| **52 张业务表覆盖**（确定性，无模型） | `scripts/validate_table_coverage.py` | **52/52**：建表有数据、字段与目录一致、每表表级+字段级向量齐全（集合 388 条）；表名提问 hit@4 **52/52**、中文描述提问 hit@4 **52/52**（52 种不同 top4 组合，非恒返回同一组） | `artifacts/table-coverage-52.json` |
| **权限矩阵**（逐角色逐表 312 项） | 同上 | **312/312** 与 `TABLES_BY_ROLE` 一致；细分计数已落进产物可复现：`permission_allowed=223`、`permission_denied=89`、`hidden_field_checked=5`、`hidden_field_blocked=5`、`region_filtered=19` | `artifacts/table-coverage-52.json` 的 `summary` |
| **52 表真实问数抽样** | `同上 --llm-sample 8` | **8/8**（每业务域抽 1 张，NL→SQL→执行→比对全通）；2026-09-15 15:13 重跑后产物内 `llm_sampled=8`、`llm_passed=8`（上一份无抽样记录，已自动存档为 `table-coverage-52-prev-20260915-151332-464.json`） | `artifacts/table-coverage-52.json` 的 `summary` 与 `tables[*].llm_sample` |
| **A8 语句超时**（MySQL 强制，含负向对照） | `tests_textile/test_sql_governance.py` | 1ms 阈值下耗时只读查询被杀、8000ms 下同语句成功；`apply_timeout` 后 `@@SESSION.max_execution_time` 等于设定值。⚠️ 真实入口会把 3024 翻译成 `QueryExecutionError(error_type='query_timeout')`，原始码丢失——`is_timeout()` 已同时识别翻译形态（评审 F1 修复） | `pytest tests_textile/test_sql_governance.py -q` 输出 |
| **A8 慢查询治理与暴露** | `TEXTILE_SLOW_QUERY_MS=1` + 一次正常查询 | 查询被归类 `slow`、计数增加、输出 `textile.sql sql_slow ...` 结构化日志；`/api/health.sql_governance` 返回本进程计数 + Redis `shared` 汇总（跨进程），健康检查自身探活不计入 | 命令输出；复现脚本 `artifacts/join-eval-prep/a8_demo.py`（gitignore，不入库） |
| **A8 LIMIT 收敛** | 同上测试文件 | 缺省注入 `LIMIT 200`；`LIMIT 99999` 压到 200；**内层子查询/CTE 的 LIMIT 同样压到 200**；`LIMIT+UNION` 改写后仍合法可解析（旧实现会生成非法 SQL，到执行才报 1064）；`SELECT SLEEP(9)` 被安全层拒绝 | `pytest tests_textile/test_sql_governance.py -q` 输出 |
| **展示名称验收** | 源码搜索、HTTP 抓取 | 前端源码与构建产物已统一为模拟企业名称 | 见工作记录任务 5 |
| 自动化测试 | `pytest tests_textile -q` | **98 passed**（79 + A8 的 19 例） | 本文件所述 |
| 指标发布幂等 | `scripts/publish_metrics.py` | 首次发布 1 条变更；重复执行 `unchanged`、零写入 | 命令输出 |
| 索引精确性 | `scripts/ensure_index.py` | `Milvus index ready: 388 vectors match 388 documents` | 命令输出 |
| 健康检查 | `curl /api/health` | `mysql/milvus/redis/worker` 全 true；`model=qwen3.8-flash`；含 `model_chain` 与 `model_last_used` | 见下 |
| 前端服务（HTTP 层） | `curl / /app /portal/ /portal/index.html` | 全部 200（`/portal/` 修复前 404） | 命令输出 |
| 真实端到端问数（API） | `POST /api/jobs` + 轮询 | 202 → `completed`，SQL 与数值正确（2026年8月营业收入 1508185.94） | 任务记录 |
| 跨表指标端到端复核（曾是失败例） | `POST /api/jobs` 问 FIN-006 期间费用率 | `completed`；SQL 为标量子查询、无 CROSS JOIN 明细行；返回 **4.760421** 与金标准逐位一致；提交 0.059s、排队 2.36s、执行 12.40s | 任务记录 + `artifacts/runs/<job_id>.json` |
| 模型额度降级实测 | 首选模型 403 后自动切换 | 首选 `qwen3.8-flash` 冷却 → 自动由 `qwen3.8-max-0902` 服务并正常产出 SQL；冷却写入 `textile:llm:exhausted:<model>`（300s，API/worker/评测共享），`/api/health` 的 `model_chain` 可见 | 命令输出 + `/api/health` |

模型额度实测：qwen3.7-flash 免费额度用尽（403 FreeTierOnly）→ 切 qwen3.8-flash；本轮多轮评测把 3.8-flash 免费额度也打满 → 自动降级到 `qwen3.8-max-0902` 完成评测（`artifacts/evaluation-expanded-fallback-quota.json`）。前两次 40/40 经 Redis 用量记录逐分钟核对，确认全部由 qwen3.8-flash 服务。

额度耗尽不是一次性故障：本轮稍后 qwen3.8-flash 再次 403（`runs/4b802dd6…json` 记录了原始报错），同一问题经自动降级后一次通过；`/api/health` 新增 `model_chain`（逐模型 cooling 状态）与 `model_last_used`（最近真正服务的模型）供排查，不用翻日志猜是哪个模型在服务。

未做：浏览器端到端复验（本轮只到 HTTP/API 层）；52 张表的全表端到端查询。

**核验指纹与后续复验**：本文件上方大部分证据采集于 `prompt_version = 717d70662b59c5e6`；随后仓库被并发修改（`metric_catalog.py`、`models.py`）→ `261182dabce6b531`；A4（`explain.py`/`agent.py`/`catalog.py`）改动后当前为 **`3b37129c4f29ff8a`**。在 `261182dabce6b531` 上追加复验：`scripts/spotcheck_cross_table.py` **5/5**（FIN-005/FIN-006/INV-005/SAL-008/FIN-002 数值与标准 SQL 一致，生成 SQL 无 CROSS JOIN、无明细行 JOIN）、真实问数（finance 账号问「2026年8月期间费用率」）返回 `4.760421`、`/api/health` 全绿且 `model_chain`/`model_last_used` 正常。**引用本文件数据前请先核对 `prompt_revision()`；跨指纹的评测成绩不得当作当前代码的成绩。**
