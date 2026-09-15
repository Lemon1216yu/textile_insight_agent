# 实施任务结果

- [x] 新建 textile_insight_agent 并复制教学MVP，保存 teaching_mvp 来源快照。
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

展示用公司名「东莞德永佳纺织制衣有限公司」，公司名称、岗位与权限均为模拟配置，不代表该公司真实内部制度。
尚未实现的生产能力与简历指标边界已在README.md说明。
# 2026-09-15 更新

- A1基础版与A3基础版已接入；原39项接手基线通过，新增理解测试加原安全/数据库集成共44项通过。
- 路由8例小样本8/8，SQL6例本轮6/6；30–50例评测未完成。
- 页面默认自动判断，支持缺少信息时停止查库；轻量分支不调用Embedding。
- 修正交付日期Few-shot口径；复杂指标补齐定义及依赖；详见 [CHAIN_CURRENT.md](CHAIN_CURRENT.md)。

# 2026-09-15 收尾更新（第二轮）

- 扩展评测 **40/40，execution_accuracy 1.0**（`artifacts/evaluation-expanded.json`，prompt `f8f6ad4fc9843e1b`），含此前失败的跨表指标 FIN-006 期间费用率；报告含 `models_used`/`fallback_used`、逐例含实际服务模型，本次 40 例全部由降级模型 `qwen3.8-max-0902` 服务（首选模型基线存档 `evaluation-expanded-before-model-attribution.json`）；混合检索 104 例对比：向量 recall@4 0.990/hit@1 0.971 → 混合 **1.000/0.981**。
- 并发 20 请求：admission 最大 5.219s → 3.125s → **0.266s**（三段修复：Redis 客户端单例、arq 连接池复用、prompt 版本内容哈希缓存、24 线程 IO 池，再加认证/提交路径的 MySQL 连接池 `textile/app_pool.py`），20/20 完成且 0 缓存命中；隔离测量单请求 186ms → **49ms**、20 并发 2422ms → **493ms**。排队中位数 4.13s → 2.22s。
- 跨表指标（FIN-005/FIN-006/SAL-008）机制化修复后做了端到端复核：走真实 HTTP + arq 队列问 FIN-006，返回 **4.760421** 与金标准逐位一致，SQL 为标量子查询、无 CROSS JOIN 明细行（提交 0.059s / 排队 2.36s / 执行 12.40s），且由额度降级后的备选模型服务。
- 指标主数据 32 条落 MySQL + Redis 60s 缓存；新增 `scripts/publish_metrics.py`（内容指纹同步 + 缓存失效 + Milvus 指标向量重建），修掉 `INSERT IGNORE` 导致"改了指标口径却不生效"的缺陷，并接入 `start-platform.ps1`。
- 自动化测试 **58 passed**；测试残留账号改为真正删除（`scripts/purge_test_users.py` + 测试自清理），`sys_users` 保持 6 正式账号 + 用户自建的 `admin_ly`。
- 模型切换为 **qwen3.8-flash**（首选）+ 6 级自动降级链；`start/stop-platform.ps1` 修复 Windows PowerShell 5.1 兼容缺陷（`-AsHashtable`、非 ASCII 注释、换行）。
- 前端 Vue3 portal 已构建并由 `/`、`/app` 提供，`/portal/` 目录根 404 已修；本轮只做 HTTP 层验证，**未重跑浏览器端到端**。
- 未完成项与边界详见 [CHAIN_CURRENT.md](CHAIN_CURRENT.md)「已知边界」：50+ 表仅部分评测覆盖、报告无程序化校验、免费额度按模型独立计量会耗尽并自动降级。
