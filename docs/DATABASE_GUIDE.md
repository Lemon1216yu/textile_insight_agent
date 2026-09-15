# 如何查看 MySQL 与 Milvus（独立管理工具）

> 数据库与向量库浏览入口**已从业务网页移除**，改用独立管理工具查看。以下连接信息中的密码均在项目根目录 `.env` 中（`TEXTILE_DB_PASSWORD` 等），不打印在文档里。

## 一、MySQL（业务数据，共 933 条）

使用 **Navicat for MySQL**（或 DataGrip / MySQL Workbench）新建连接：

| 项目 | 值 |
|---|---|
| 连接名 | 任意（如 textile-insight） |
| 主机 | `127.0.0.1` |
| 端口 | **3318**（注意：不是本机其他 MySQL 的 3306） |
| 用户名 | `textile_reader`（只读）或 `textile_app`（账户维护） |
| 密码 | `.env` 中 `TEXTILE_DB_PASSWORD=` 之后的值 |
| 数据库 | `textile_insight` |

`textile_reader` 只能 SELECT 业务表，不能修改数据；`textile_app` 额外可读写 `sys_users`（登录与账户管理），无 DDL 权限。

业务表 8 张：

| 表 | 中文用途 | 记录数 |
|---|---|---:|
| dim_customers | 客户、区域、客户类型 | 6 |
| dim_products | 面料产品 | 6 |
| dim_suppliers | 原料供应商 | 3 |
| sales_orders | 销售订单、实际销售成本、交付日期 | 540 |
| production_batches | 生产批次、产量、缺陷、成本 | 108 |
| purchase_orders | 原料采购与到货 | 108 |
| inventory_snapshots | 月末库存与90天以上库龄 | 108 |
| finance_expenses | 区域期间费用 | 54 |

另有内部表：

- `sys_users`：企业账户（6 个初始账号 admin/executive/finance/sales_east/production/warehouse，初始密码 demo123；密码为 PBKDF2 加盐哈希，不可反解）。
- `seed_version`：初始化版本控制，1 条记录，不算业务数据，不进向量索引。

常用口径（问数与看板同款）：

```sql
-- 营业收入（按交付日期，已完成订单）
SELECT SUM(net_amount) FROM sales_orders
WHERE order_status='已完成' AND delivery_date IS NOT NULL;

-- 毛利
SELECT SUM(net_amount - cost_amount) FROM sales_orders
WHERE order_status='已完成' AND delivery_date IS NOT NULL;

-- 最近快照库存金额
SELECT SUM(quantity * standard_cost) FROM inventory_snapshots
WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM inventory_snapshots);
```

## 二、Milvus（向量库，94 条说明向量）

Milvus 里存的**不是业务记录**，而是「说明文字 + 256 维语义向量」，用于问数时召回相关表、字段与指标口径。当前集合 `textile_schema_metrics_v1` 共 **94 条**：

| 类型 | 条数 | 说明 |
|---|---|---:|
| table | 8 | 每张业务表一段说明 |
| field | 54 | 每个字段一段说明 |
| metric | 32 | 每条治理指标一段定义与口径 |

查看方式：打开 **Attu**（Milvus 可视化管理台）<http://127.0.0.1:3018>，连接默认地址 `127.0.0.1:19530`，选择集合 `textile_schema_metrics_v1` 即可浏览向量与原文。

重建索引（更换 Embedding 或指标后执行）：

```powershell
uv run python scripts/build_index.py
```

## 三、Docker 里的服务

Docker Desktop → Containers → **textile-insight**：

| 容器 | 作用 | 对外端口 |
|---|---|---|
| textile-insight-mysql | 业务数据库 | 127.0.0.1:3318 |
| textile-insight-milvus | 向量数据库 | 127.0.0.1:19530 |
| textile-insight-etcd | Milvus 元数据服务 | — |
| textile-insight-minio | Milvus 对象存储 | 127.0.0.1:9001(控制台) |
| textile-insight-attu | Milvus 管理台 | 127.0.0.1:3018 |

日志、端口、健康状态都在 Docker Desktop 对应容器里查看。

## 四、在页面上看不到的旧入口

早期 MVP 曾在业务网页提供 `/data` 数据浏览页。该入口已移除：数据库与向量库统一走上面的独立管理工具，业务网页只保留经营功能。
