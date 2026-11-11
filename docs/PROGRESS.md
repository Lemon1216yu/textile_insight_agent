# 实施任务结果

- [x] 搭建 textile_insight_agent 工程骨架：业务数据进入 MySQL，Schema 与指标说明向量进入 Milvus。
- [x] 修复Docker启动，启动独立MySQL、Milvus、etcd、MinIO、Attu。
- [x] 生成8张纺织业务表、933条模拟数据、只读业务账号。
- [x] Milvus表/字段/指标检索、BFS关联路径、业务指标口径。
- [x] SQL AST安全检查、行列权限、EXPLAIN、超时预算、有限纠错。
- [x] LangGraph多步分析、依赖结果传递、结构化证据、报告生成。
- [x] 指标知识库：32条治理指标（5领域，含公式/时间口径/负责人/版本/角色可见性），已接入问数链路并重建94条向量索引。
- [x] 正式账户与权限：PBKDF2登录/登出/改密、管理员账户维护、6岗位权限矩阵（菜单/表/隐藏字段/数据区域）、sys_users表、textile_reader/textile_app账号分工。
- [x] 企业后台页面重设计：登录页+深色侧边导航+浅色内容区，按岗位看板（经营/生产/仓储视角），问数/分析/指标中心/个人报告/账户管理；数据浏览入口已从业务网页移除。
- [x] 环境验收、39项测试、6例真实模型对照、浏览器端到端验证。

运行入口：http://127.0.0.1:8018（登录页）；主应用 http://127.0.0.1:8018/app 。
详细启动步骤见根目录README.md；数据库/向量库查看方式见DATABASE_GUIDE.md；本次验证证据见VALIDATION.md。

展示用公司名「某某纺织有限公司」，公司名称、岗位与权限均为模拟配置，不代表任何真实企业的内部制度。
尚未实现的生产能力与简历指标边界已在README.md说明。
# 2026-09-15 更新

- A1基础版与A3基础版已接入；原39项接手基线通过，新增理解测试加原安全/数据库集成共44项通过。
- 路由8例小样本8/8，SQL6例本轮6/6；30–50例评测未完成。
- 页面默认自动判断，支持缺少信息时停止查库；轻量分支不调用Embedding。
- 修正交付日期Few-shot口径；复杂指标补齐定义及依赖；详见 [CHAIN_CURRENT.md](CHAIN_CURRENT.md)。

# 2026-09-15 收尾更新（第二轮）

- **A4 问数结果解释已完成**：`textile/explain.py` 给问数结果附 `explanation`（口径/公式/单位/时间字段/来源表），确定性拼装、不调模型；口径只认理解步骤识别的指标编码+依赖指标（不采信检索候选，避免错误归属），来源表从执行 SQL 解析。新增 `tests_textile/test_explain.py` 12 个断言（含两条负向对照）。真实问数 3 例验证通过（`artifacts/explanation-A4.json`）。
- **评测复验与模型依赖**：A4 改动使 `prompt_version` 变为 `ae4f3f4d936684e4`，按纪律在新指纹复验 52 例 → **49/52（94.2%）**，服务模型为降级链第三个 `deepseek-v4.1-flash`。3 例失败（PRD-001/PUR-004/incoming_inspections）均为**输出格式违规**（AST 校验失败）：前两例产物可见"依据"文字被拼进 SQL，PUR-004 产物只有"仅允许单条 SELECT 查询"（同类推断）；`qwen3.8-max` 上同套用例为 52/52。结论：**成绩必须与 `models_used` 一起报**。
- **当前指纹已完成复验（补充）**：`prompt_version = 3b37129c4f29ff8a` 上重跑 52 例 → **49/52**，同为 `deepseek-v4.1-flash`，但**失败集合不同**：`maintenance_orders`（"依据：…"文字混入 SQL，直接证据）、`PUR-004`（同类推断）、`inventory_aging`（模型自行加了未要求的日期过滤）。失败集合随模型/指纹变化，**不得跨模型外推**；跨表抽查在当前指纹上 5/5 通过。
- **PUR-005 取整缺陷已修**：真实验证发现模型把"不四舍五入"理解为截断（`TRUNCATE(AVG(...),0)` → 4 而 gold 为 4.2778），连跑 3 次 1 次复现（模型不确定性）。已在 `RULES` 增加"用户说'不四舍五入'时保留原始精度、禁止 TRUNCATE/ROUND/FLOOR/CEIL/CAST 取整"；定点复测 **5/5 返回 4.2778**。
- **评测产物覆盖前自动存档**：`scripts/evaluate_expanded.py` 新增 `write_report()`，覆盖前把上一次结果存为 `evaluation-expanded-prev-<时间戳>.json`（此前一次 52/52 产物被静默覆盖丢失），并补 `tests_textile/test_eval_artifacts.py` 2 例。
- 并发 20 请求：admission 最大 5.219s → 3.125s → **0.266s**（三段修复：Redis 客户端单例、arq 连接池复用、prompt 版本内容哈希缓存、24 线程 IO 池，再加认证/提交路径的 MySQL 连接池 `textile/app_pool.py`），20/20 完成且 0 缓存命中；隔离测量单请求 186ms → **49ms**、20 并发 2422ms → **493ms**。排队中位数 4.13s → 2.22s。
- 跨表指标（FIN-005/FIN-006/SAL-008）机制化修复后做了端到端复核：走真实 HTTP + arq 队列问 FIN-006，返回 **4.760421** 与金标准逐位一致，SQL 为标量子查询、无 CROSS JOIN 明细行（提交 0.059s / 排队 2.36s / 执行 12.40s），且由额度降级后的备选模型服务。
- 指标主数据 32 条落 MySQL + Redis 60s 缓存；新增 `scripts/publish_metrics.py`（内容指纹同步 + 缓存失效 + Milvus 指标向量重建），修掉 `INSERT IGNORE` 导致"改了指标口径却不生效"的缺陷，并接入 `start-platform.ps1`。
- **A8 SQL 资源治理已完成（含评审修复）**：新增 `textile/governance.py`（计数、结构化日志、超时判定、`stats()`）；语句超时与慢查询阈值配置化（`TEXTILE_QUERY_TIMEOUT_MS`=8000、`TEXTILE_SLOW_QUERY_MS`=200，空值/非法值回落默认并设下限）；`/api/health` 增加 `sql_governance`（本进程计数 + Redis 跨进程汇总，健康检查自身探活不计入）。评审后修复：① 超时识别覆盖翻译层的 `query_timeout`（否则真实入口把超时错记成 error）② EXPLAIN 预检纳入治理统计与错误翻译 ③ 跨进程计数落 Redis ④ 内层子查询/CTE 的 LIMIT 也收敛到 200、`LIMIT+UNION` 改写后仍合法 ⑤ 测试从 9 例扩到 19 例（杀掉评审发现的 5 个存活变异体）。**实测边界**：`max_execution_time` 不打断 SLEEP、极小查询可能来不及检查 → 超时是兜底。
- **展示名称统一完成**：前端源码与构建产物一致，指标主数据与向量已核对。遗留测试失败已与变更前基线对照，具体限制见验收记录。
- **自动化测试 98 passed**（A4 的 `test_explain.py`、产物存档 `test_artifact_io.py`、A8 的 `test_sql_governance.py`）；测试残留账号改为真正删除（`scripts/purge_test_users.py` + 测试自清理），`sys_users` 保持 6 正式账号 + 用户自建的 `admin_ly`。
- 模型切换为 **qwen3.8-flash**（首选）+ 6 级自动降级链；`start/stop-platform.ps1` 修复 Windows PowerShell 5.1 兼容缺陷（`-AsHashtable`、非 ASCII 注释、换行）。
- 前端 Vue3 portal 已构建并由 `/`、`/app` 提供，`/portal/` 目录根 404 已修；本轮只做 HTTP 层验证，**未重跑浏览器端到端**。
- 未完成项与边界详见 [CHAIN_CURRENT.md](CHAIN_CURRENT.md)「已知边界」：50+ 表仅部分评测覆盖、报告无程序化校验、免费额度按模型独立计量会耗尽并自动降级。
- **52 张业务表覆盖验收**：新增 `scripts/validate_table_coverage.py`（确定性检查 + 可选真实问数抽样）。结果 52/52（数据、字段、表级/字段级向量、表名与中文描述两种提问 hit@4）、权限矩阵 312/312（放行 223 / 拒绝 89 / 隐藏字段 5 / 区域过滤 19，均已落进产物）、真实问数抽样 8/8（每域 1 张；2026-09-15 15:13 重跑留档 `llm_sampled=8`/`llm_passed=8`）。排查记录：首轮抽样 0/8 是脚本用裸 `==` 比对、把列别名不同误判为失败，改用评测标准比较器 `equal()` 后 8/8——**缺陷在验收脚本，不在链路**。
