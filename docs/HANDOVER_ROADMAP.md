# 织见 · 纺织制造经营智能分析平台 —— 交接与路线图

> **2026-09-15 GPT接手更新**：已核验环境并实现A1基础自动理解/改写/路由、A3基础轻量/复杂Schema分支，业务页面默认自动判断。8例路由小样本8/8；原6例SQL对照本轮6/6，不能视为A5扩集完成。修正旧Few-shot按下单日期统计收入的问题。当前Milvus实测388条（52表+304字段+32指标）；下文70条为交接时旧记录。现有任务已是202异步API加进程内线程池，并非尚无异步接口；arq仍未实施。详细链路、证据与剩余范围见 [CHAIN_CURRENT.md](CHAIN_CURRENT.md)。以下历史完成记录与规划保留，不应将规划或过期数据作为当前事实。

> **2026-09-15 第二轮收尾更新（最新）**：A2 混合检索、A5 扩集评测、A6 指标落库+发布器、A7 arq 异步与结果缓存均已实施并实测：**评测 40/40（1.0）**、混合检索 104 例 recall@4 0.990→1.000、**并发 20 请求 admission 5.219s→0.781s 且无排队**、`pytest 58 passed`。模型改为 **qwen3.8-flash 首选 + 自动降级链**（免费额度按模型独立计量，耗尽即自动切换）。另修复 7 个机制缺陷（指标改动不生效、索引近似计数、PS5.1 脚本、并发阻塞、证据模型归属、`/portal/` 404 等），清单见 [CHAIN_CURRENT.md](CHAIN_CURRENT.md#本轮发现并修复的机制缺陷)。**仍未验证**：52 张表的全表端到端、浏览器端到端复验、评测回归自动化。

> **本文档用途**：由豆包（Doubao）整理，交接给 GPT 继续推进。记录「接替 GPT 后已完成的所有工作」与「规划中未干的活」，并锁定全部已拍板的技术决策。后续执行以本文档为唯一权威路线图；与旧文档（README/PROGRESS）冲突时以本文档为准。

---

## 0. 项目速览

| 项 | 值 |
|---|---|
| 项目路径 | `F:\1_Code_Git\textile_insight_agent` |
| 公司名（展示用） | 东莞德永佳纺织制衣有限公司（模拟配置声明：不代表该公司真实内部制度） |
| 定位 | 面向纺织制造企业的经营智能分析平台（Text2SQL + 多步分析 Agent） |
| 后端 | Python 3.12 + FastAPI（uvicorn，端口 8018）+ LangGraph 编排 |
| 数据库 | MySQL 8（端口 **3318**，业务库 `textile_insight`）、Milvus（向量，端口 19530）、MinIO（Milvus 依赖，9000/9001） |
| 新增中间件 | Redis（容器 `textile-insight-redis-1`，127.0.0.1:6379，7.4.11，appendonly）——已部署 |
| 前端（现状） | **Vue3 + TypeScript + Vite + Element Plus 已构建并上线**（`frontend/` → `static/portal/`，由 `/`、`/app`、`/portal/` 提供；浏览器端到端待复验）；旧原生 JS 版本（`static/app.js` 等）保留在仓库但不再作为入口 |
| 模型 | 生成：**百炼 qwen3.8-flash 首选 + 自动降级链**（`TEXTILE_LLM_MODELS`，额度耗尽自动切换；OpenAI 兼容）；向量：**text-embedding-v3**（百炼） |
| 环境 | Windows + Docker Desktop（MySQL/Milvus/MinIO/Redis 容器）+ `.venv`（uv） |
| 数据规模 | 52 张业务表（8 主表 + 44 扩展表）；Milvus **388 条向量**（52 表说明 + 304 字段说明 + 32 指标口径），每条 256 维 |

**启动方式**（GPT 接手必须会）：
```powershell
cd F:\1_Code_Git\textile_insight_agent
docker compose up -d                 # MySQL/Milvus/MinIO/Redis
.\start.ps1                          # 启动 uvicorn 8018（内部已设置 utf-8）
# 或手动：.\.venv\Scripts\python.exe -m uvicorn textile.app:app --host 127.0.0.1 --port 8018
```
验证：浏览器打开 `http://127.0.0.1:8018`，用 `admin / demo123` 登录；`/api/health` 应返回 `model: qwen3.8-flash`，并含 `model_chain`（额度冷却状态）与 `model_last_used`（最近真正服务的模型）。

---

## 1. 已拍板的技术决策（不要推翻，除非有充分新理由并记录）

| 决策项 | 结论 | 状态 |
|---|---|---|
| LLM 模型 | **弃用 DeepSeek API**，改用百炼 **qwen3.8-flash 首选 + 自动降级链**（非思考模式；免费额度按模型独立计量，403/429 自动冷却并切换下一个） | ✅ 已实施 |
| 前端 | **Vue3 + TypeScript + Vite + Element Plus**（替代原生 JS 层，FastAPI 不动） | ⚠️ 已构建上线，浏览器端到端待复验 |
| 混合检索 | **bm25s + 向量两路召回 + RRF 融合**（半结构化字段检索） | ✅ 已实施（104 例对比：recall@4 0.990→1.000） |
| 任务队列 | **arq（基于 Redis）** —— 多用户并发必须项 | ✅ 已实施（20 并发 admission 5.219s→0.781s，无排队） |
| 意图识别 / 查询改写 / 自动路由 | **自动用小模型路由识别**（结构化输出；现共用 qwen3.8-flash 验证，评测证明 qwen-turbo 效果一致则可切，同平台同 key 一行切换） | ✅ 基础版已实施（8/8 小样本） |
| 编排框架 | 用已有 **LangGraph**，**不引入 LangChain** 本体 | ✅ 已定 |
| 评测 | 沿用 **Execution Accuracy**（gold SQL 执行结果比对，忽略列名/行序、数值容差），**扩到 30-50 例** | ✅ 40 例，40/40（1.0）；逐例记录实际服务模型 |
| 指标知识库 | MySQL 主数据（metric_registry）+ Milvus 向量口径 + Redis 缓存 | ✅ 32 条已落库+缓存，`publish_metrics.py` 指纹同步 |
| 50+ 表扩展验证 | **上**（当前 8 表 → 扩展至 50+ 表验证） | ⚠️ 52 张表已建表/已向量化/可查询；仅 8 张扩展表进入评测，全表端到端未验证 |
| ~~40% Token 下降~~ | **取消，不做** | ❌ 明确取消 |
| ~~70% → 91% 对照实验~~ | **取消，不做** | ❌ 明确取消 |
| 系统稳定性优化 | 本轮不做，后续单独立项 | ✅ 已定 |

---

## 2. 已完成的工作（接替 GPT 后，勿重复）

### 2.1 企业化改造（已交付，勿重做）

1. **指标知识库 32 条治理指标**（`textile/metric_catalog.py` 重写），5 域分布：
   销售 9 / 财务 7 / 生产 6 / 采购 5 / 库存 5；含编码、定义、公式、时间口径、单位、维度、负责人、版本、状态、角色可见范围；收入/毛利/订单数口径统一到**交付日期**。
2. **正式账户与 6 岗位权限**：
   - `sys_users` 表 + PBKDF2（200k 迭代）密码 + 8h 签名会话 + 登录/登出/改密/管理员账户管理（API 保护：不能停用自己）。
   - `textile/permissions.py`：`ROLES` / `TABLES_BY_ROLE` / `HIDDEN_FIELDS` / `REGION_BOUND_ROLES`。
   - 6 账号：`admin` / `executive` / `finance` / `sales_east`（region=华东）/ `production` / `warehouse`，初始密码全部 `demo123`。当前 `sys_users` 应只剩这 6 个正式账号（user_id 1-6）。
3. **数据库账号拆分**：`textile_reader`（业务表只读）、`textile_app`（业务读 + sys_users SELECT/INSERT/UPDATE，无 DELETE）、`root`（运维）。
4. **页面重设计**：登录页（`static/index.html`）+ 深色侧边导航 + 浅色内容区企业后台（`static/app.html` / `app.css` / `app.js`），按岗位 3 种看板视图；业务网页**已移除数据浏览入口**（改独立文档 + Attu）。
5. **文档更新**：README.md（公司名/岗位/新账号/移除 /data）、docs/DATABASE_GUIDE.md（Navicat 3318 连接、Attu、端口表）、PROGRESS.md、VALIDATION.md。
6. **测试**：39 项全部通过（`tests_textile/`）。过程中修复：CATALOG NameError、textile_reader 无权 sys_users、textile_app 缺 INSERT 权限、admin 不能停用自己（API 保护）、测试尾部清理残留用户行。

### 2.2 模型切换与额度降级（已完成，勿重做）

- `textile/settings.py`：`MODEL` 默认 **`qwen3.8-flash`**，`MODELS` 由 `TEXTILE_LLM_MODELS`（逗号分隔）解析，首选在前；`LLM_URL` 默认 `https://dashscope.aliyuncs.com/compatible-mode/v1`，`LLM_KEY = TEXTILE_LLM_API_KEY or DASHSCOPE_API_KEY`。
- `textile/models.py`：`TextileLLM` 按候选链调用；覆写 `generate_text` 加 `extra_body={'enable_thinking': False}`（qwen 系默认开思考，SQL 生成需显式关闭），非 qwen 厂商自动去掉该参数。
- **额度降级**：百炼免费额度按模型独立计量。命中 403 FreeTierOnly / 429 时把该模型写入 Redis 冷却（`textile:llm:exhausted:<model>`，默认 300s，API/worker/评测共享），自动切换链上下一个模型；冷却中的模型排在候选末尾兜底。实际生效模型记录在 `TextileLLM.last_model`，用量按模型落 `textile:usage`。
- `.env`：`TEXTILE_LLM_MODEL=qwen3.8-flash`、`TEXTILE_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1`。
- 实测：qwen3.7-flash 免费额度用尽（403）→ 切换；qwen3.8-flash 完成两轮 40/40 评测后额度也打满 → 自动降级 `qwen3.8-max-0902` 完成第三轮（40/40）。证据归属经 Redis 用量记录逐分钟核对。
- 服务重启后 `/api/health` 返回 `model: qwen3.8-flash` + `model_chain` + `model_last_used`。

**历史失败例（已修复）**：`2026年8月经营利润` 曾因多返回中间列被判 False；后续同类问题（SAL-008 取消率、FIN-005 经营利润、FIN-006 期间费用率）根因是**跨表指标口径对模型不可读**——"权威计算表达式"是空占位符，模型只能用 CROSS JOIN 明细行，笛卡尔积放大分子/分母。已按机制修复：`definition_text()` 明确"各依赖指标独立聚合 + 标量子查询组合、严禁 JOIN 明细行"，并在 SQL Prompt 加通用跨表规则。三条跨表指标现全部通过（40/40）。**仍不得放宽评测判定**。

### 2.3 基础设施（已完成）

- Redis 容器已部署：`docker compose up -d` 含 `redis` service + `redis_data` volume（image `redis:7-alpine`，127.0.0.1:6379，PONG 正常）。

### 2.4 环境与配置事实（GPT 必须知道，勿泄露密钥值）

| 项 | 位置 | 说明 |
|---|---|---|
| `DASHSCOPE_API_KEY`（115字符） | **系统级环境变量**（Machine） | 当前唯一在用的模型 key（生成 + 向量） |
| `DEEPSEEK_API_KEY`（35字符） | **用户级环境变量**（User） | **已弃用**，项目不再读取；保留勿删 |
| 项目 `.env` | 4 个本地密码 + 2 行 LLM 配置 | MySQL/MinIO/会话签名密码 + 模型名/base_url |
| 端口 | MySQL 3318 / Milvus 19530 / MinIO 9000,9001 / Redis 6379 / API 8018 | Navicat 连 3318，勿连 3306 |

---

## 3. 当前系统状态与差距

### 3.1 当前运行链路（已实现）

```
用户输入业务问题
  → 用户手动选择「问数 / 经营分析」（尚无自动意图识别）
  → 问数：基础输入校验；分析：LangGraph 生成 2-4 步计划 → 按依赖执行子任务
  → 问题转 Embedding（text-embedding-v3）
  → Milvus 召回候选表（70 条向量：表/字段/指标说明）
  → 候选表内检索字段并补齐关键字段
  → BFS 推理表关联路径
  → 检索指标定义与计算口径
  → 组装 Schema、指标、规则、Few-shot
  → 模型链生成 SQL（首选 qwen3.8-flash，非思考模式；额度耗尽自动降级）
  → AST 检查、表/列权限、区域过滤 → EXPLAIN 检查 → MySQL 只读执行（textile_reader）
  → 结构化查询结果 → 根据数据生成回答或汇总报告
  → SQL 出错最多修正一次
```

### 3.2 与目标链路的差距（按简历链路对照）

| 目标环节 | 现状 | 缺口 |
|---|---|---|
| 输入校验 | ✅ 有 | — |
| 查询改写 | ✅ 有（理解器结构化输出） | 无（A1 已落地） |
| 意图识别 / 自动路由 | ✅ 自动判断（8/8 小样本） | 缺更大样本评测（A1 剩余） |
| 轻量 Schema 注入（简单查询） | ✅ 有（单表走轻量分支，不调用 Embedding） | — |
| Schema Linking（复杂查询） | ✅ 有（向量 + bm25s 词法 + RRF 融合 + 字段补齐 + BFS） | 104 例对比已记录（recall@4 0.990→1.000） |
| 指标知识库补充口径 | ✅ 32 条（MySQL 主数据 + Redis 缓存 + 发布器同步） | — |
| 组装 Prompt 生成 SQL | ✅ 有 | 40/40（1.0）；仍属合成回归，不代表企业准确率 |
| 安全校验 / 执行治理 | ✅ 有（AST/权限/EXPLAIN/只读/LIMIT） | 查询超时预算见 A8 |
| 结果解释 | ⚠️ 分析模式有，问数模式弱 | 补问数模式结果解释（A4） |
| Plan-and-Execute | ✅ 有（LangGraph） | — |
| 评测 | ✅ 40 例（逐例记录实际服务模型） | 回归自动化待做（A9） |
| 多用户并发 | ✅ arq 队列 + 按用户/权限/指标版本隔离的结果缓存 | 20 并发 admission 0.781s、排队 ≤0.85s（A7 已落地） |

### 3.3 简历口径提醒（面试诚实边界）

- 当前 8 表端到端验证；**50+ 表为架构支持、待扩展**（目标阶段 A 落地）。
- **40% Token 下降、70%→91% 对照实验：已明确取消**，任何文档/简历不得再声称有这两个数字。
- 意图识别/查询改写/自动路由在简历上描述为「规划并实现中」，未落地前不得写成已完成。

---

## 4. 规划中未干的活（按阶段执行）

### 阶段 A：链路补齐（下一阶段开工重点）

| 编号 | 任务 | 要点 / 验收标准 |
|---|---|---|
| A1 | **意图识别 / 查询改写 / 自动路由（小模型）** | LLM 结构化输出 JSON `{intent: query\|analysis, rewrite, needs: [...]}`；自动分流问数/分析，替代用户手动选择；查询改写补全省略主体、时间、口径；**现共用 qwen3.8-flash**（已验证可用），评测证明 qwen-turbo 同效果则切换；LLM 失败兜底默认走问数 + 输入校验。✅ 基础版已落地（8/8 小样本），扩样本待做 |
| A2 | **bm25s + 向量两路召回 + RRF 融合** | 引入 bm25s（纯 Python，无服务依赖）；对表/字段/指标说明建 BM25 索引；向量召回（Milvus）与 BM25 召回各取 top-k，RRF 融合排序；验收：召回命中率对比实验记录 |
| A3 | **轻量 / 复杂双分支 Schema** | 简单查询（单表/聚合明确）走轻量 Schema 上下文注入；复杂查询走完整 Schema Linking + BFS；以意图/复杂度判定分流 |
| A4 | **问数模式结果解释** | 单指标问答返回自然语言解释（含口径与单位），不只给数字 |
| A5 | **评测集扩至 30-50 例** | 覆盖 5 域 × 简单/中等/复杂 × 多表 join × 指标口径；Execution Accuracy 基线记录；修复已知失败例（经营利润多列）；**不要放宽评测判定** |
| A6 | **指标知识库落库** | MySQL `metric_registry`（主数据，32 条起步）+ Milvus 向量口径（替换原 8 条简单定义）+ Redis 缓存（TTL 设计）；问数链路从库里读指标而非 Python 常量 |
| A7 | **arq 任务队列 + 结果缓存** | 问数/分析改为异步：请求→202+job_id→worker 并发→前端轮询；相同问题命中 Redis 缓存直接返回；**多用户并发必须项**，验收：并发 20 请求无排队阻塞 |
| A8 | **SQL 资源治理** | 查询超时（如 10s）、LIMIT 强制、慢查询日志与告警 |
| A9 | **Prompt / Few-shot 版本管理 + 评测回归** | prompt 与 few-shot 示例版本化；每次改动自动跑评测回归 |
| A10 | **50+ 表扩展验证** | 合成数据生成扩至 50+ 表（分域：销售/财务/生产/库存/采购/质量）；Milvus 每表+每字段说明向量化（8→50+ 表，字段数百条）；BFS/权限（TABLES_BY_ROLE）适配新表；评测新增多表 join 用例；记录扩展成本与瓶颈 |

### 阶段 B：企业治理（A 完成后）

| 编号 | 任务 | 要点 |
|---|---|---|
| B1 | 可观测性 | 结构化日志（请求/延迟/成功率）、指标端点、告警 |
| B2 | 审计日志 | 记录「谁、何时、查了什么、返回了什么」，可追溯 |
| B3 | 成本监控与限流 | 按用户/部门统计 token 用量；超限告警/限流 |
| B4 | 备份恢复 | MySQL/Milvus/Redis 定期备份与恢复演练 |

### 阶段 C：平台化

| 编号 | 任务 | 要点 |
|---|---|---|
| C1 | 多环境 | dev / test / prod 配置分离（当前仅一套本地） |
| C2 | 前端 Vue3 重写 | Vue3 + TS + Vite + Element Plus；替换 `static/` 原生 JS；页面：登录、经营总览、智能问数、经营分析、指标中心、个人报告、账户管理（管理员）；可并行先搭骨架 |

### 明确取消（不要再做）

- ❌ 40% Token 下降实验
- ❌ 70% → 91% 对照实验
- ❌ 系统稳定性专项优化（后续单独立项）

---

## 5. 执行顺序与依赖

```
阶段 A 开工顺序（建议）：
A1（意图路由）→ A5 评测基线（与 A1 并行扩集）→ A2（混合检索）→ A3（双分支）
→ A6（指标落库）→ A4（结果解释）→ A7（arq+缓存）→ A8（资源治理）→ A9（回归）
→ A10（50+ 表扩展，依赖 A2/A6 稳定后）
阶段 B、C 在 A 整体验收后启动；C2 前端可在 A 中期并行搭骨架。
```

**阶段 A 整体验收标准与实际结果**：自动路由正确率 ≥ 90%（8/8 小样本，样本仍小）；混合检索优于纯向量基线（104 例：recall@4 0.990→**1.000**）；评测 Execution Accuracy ≥ 0.85（实际 **1.0，40/40**，属合成回归）；并发 20 请求无排队（实际 admission 最大 **0.781s**、排队 ≤**0.85s**，20/20 完成）；50+ 表索引与查询全链路可用（**部分**：52 张表已建表/索引，仅 8 张扩展表进入评测）。

---

## 6. 交接给 GPT 的第一步建议

1. **先跑通现状**：`docker compose up -d` + `.\start-platform.ps1`（含迁移/指标发布/seed/索引检查）+ 登录 admin/demo123 + 看 `/api/health`（确认 `model: qwen3.8-flash` 与 `model_chain`、`model_last_used`）。
2. **重读关键文件**：`textile/models.py`、`textile/settings.py`、`textile/retrieval.py`、`textile/task_queue.py`、`textile/registry.py`、`scripts/publish_metrics.py`、`textile/metric_catalog.py`、`scripts/evaluate_expanded.py`、`artifacts/evaluation-expanded.json`、[CHAIN_CURRENT.md](CHAIN_CURRENT.md)。
3. **从 A10 / A4 / A9 开工**：52 张表端到端与权限回归（A10 收尾）、问数模式结果解释（A4）、评测回归自动化（A9）；A1/A2/A3/A6/A7 已落地，扩展样本而不是重做。
4. **注意事项**：
   - 模型 key 在系统环境变量（DASHSCOPE_API_KEY），不在 .env；改模型走 `TEXTILE_LLM_MODEL` / `TEXTILE_LLM_BASE_URL`（.env 或环境变量）。
   - 评测失败例的处置：修 Prompt/Few-shot，**不要放宽评测判定**。
   - 改完模型/代码后必须重启 uvicorn 才生效（`llm()` 有 lru_cache）。
   - 数据库只读连接用 `textile_reader`，应用写账号用 `textile_app`，运维用 root；测试残留用户行需清理，`sys_users` 保持 6 个正式账号。
   - 前端大改前先读 `static/` 现状；引入构建链（Vite）后注意静态资源路径与 FastAPI StaticFiles 挂载的配合。

---

*文档维护：每次完成一个阶段任务，回到本文档更新状态（✅/⚠️/📋），并同步 README/PROGRESS/VALIDATION。*
