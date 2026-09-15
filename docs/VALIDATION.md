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

- 登录页：显示「织见 · 经营智能分析平台 / 东莞德永佳纺织制衣有限公司」与模拟配置声明；admin 登录成功进入主应用。
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
| 扩展评测（40 例真实模型） | `scripts/evaluate_expanded.py` | **40/40，1.0**；报告级 `models_used`/`fallback_used` + 逐例 `model`/`fallback` 记录实际服务模型（本次 40 例全部由降级模型 `qwen3.8-max-0902` 服务，首选 qwen3.8-flash 当日额度耗尽） | `artifacts/evaluation-expanded.json`（prompt `f8f6ad4fc9843e1b`）；首选模型上的 40/40 基线保留为 `evaluation-expanded-before-model-attribution.json`、`evaluation-expanded-qwen3.8-flash-final.json` |
| 混合检索对比（104 例） | `scripts/compare_retrieval.py` | 向量 0.990/0.971 → 混合 **1.000/0.981**（recall@4/hit@1） | `artifacts/retrieval-comparison.json` |
| 并发 20 请求（HTTP + arq） | `scripts/validate_concurrency.py` | 20/20 完成、0 缓存命中；admission 最大 **0.266s**（三段修复：5.219s → 3.125s → 0.266s）；排队中位数 2.22s（修复前 4.13s） | `artifacts/concurrency-20.json`；修复前基线 `concurrency-20-quota-blocked.json` |
| 提交延迟隔离测量（无模型） | `scripts/probe_http.py` | 单请求 186ms → **49ms**；20 并发最大 2422ms → **493ms**（连接池修复） | 命令输出 |
| 自动化测试 | `pytest tests_textile -q` | **58 passed** | 本文件所述 |
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
