"""AST validation and source-level row/column protection, independent of prompts."""
import sqlglot
from sqlglot import exp
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import traverse_scope
from security import SecurityError, UserContext
from textile.catalog import CATALOG
from textile.permissions import allowed_catalog as _allowed_catalog

def allowed_catalog(user):
    try:
        return _allowed_catalog(user)
    except ValueError as exc:
        raise SecurityError(str(exc))

class TextileSecurity:
    def secure_sql(self, sql, user=None):
        user=user or UserContext.demo_admin()
        catalog=allowed_catalog(user)
        try:
            statements=sqlglot.parse(sql,read='mysql')
            if len(statements)!=1 or not isinstance(statements[0],exp.Query): raise SecurityError('仅允许单条 SELECT 查询')
            tree=statements[0]
            for node in tree.walk():
                if isinstance(node,(exp.Insert,exp.Update,exp.Delete,exp.Create,exp.Drop,exp.Alter,exp.Command,exp.Into,exp.Lock)):
                    raise SecurityError('禁止写入、DDL、文件输出或锁操作')
                if isinstance(node,exp.With) and node.args.get('recursive'): raise SecurityError('禁止递归查询')
                if isinstance(node,exp.Anonymous) and node.name.upper() not in {'DATE_FORMAT','IFNULL','TIMESTAMPDIFF'}:
                    raise SecurityError('不允许的SQL函数：'+node.name)
                if isinstance(node,exp.Func) and node.sql_name().upper() in {'SLEEP','BENCHMARK','LOAD_FILE','GET_LOCK','RELEASE_LOCK'}:
                    raise SecurityError('禁止危险函数')
                if isinstance(node,exp.Star) and not isinstance(node.parent,exp.Count): raise SecurityError('请显式选择授权字段，不允许 SELECT *')
            ctes={x.alias_or_name for x in tree.find_all(exp.CTE)}
            for table in tree.find_all(exp.Table):
                if table.db or table.catalog: raise SecurityError('禁止跨数据库查询')
                if table.name in ctes:
                    if table.name in CATALOG: raise SecurityError('CTE 名称不能覆盖业务表')
                    continue
                if table.name not in catalog: raise SecurityError('无权访问数据表：'+table.name)
            # Qualify resolves aliases/CTEs and verifies source columns, blocking hidden-column aliases too.
            tree=qualify(tree,dialect='mysql',schema=catalog,validate_qualify_columns=True,identify=False)
            facts={'sales_orders','production_batches','purchase_orders','inventory_snapshots','finance_expenses'}
            from textile.extended_catalog import EXTRA_FACTS
            facts=facts|EXTRA_FACTS
            for scope in traverse_scope(tree):
                sources=[s.name for s in scope.sources.values() if isinstance(s,exp.Table) and s.name in facts]
                if len(sources)>1:
                    raise SecurityError('SQL字段或语法校验失败：多个事实来源必须先分别聚合，再关联汇总结果，避免金额重复')
            for table in list(tree.find_all(exp.Table)):
                if table.name not in catalog: continue
                if user.region:
                    name=table.name; alias=table.alias_or_name
                    source=exp.select(*[exp.column(c) for c in catalog[name]]).from_(name)
                    if 'region' in catalog[name]: source=source.where(exp.column('region').eq(exp.Literal.string(user.region)))
                    table.replace(source.subquery(alias))
            limit=tree.args.get('limit')
            if limit:
                value=limit.expression
                if not isinstance(value,exp.Literal) or not value.is_int: raise SecurityError('LIMIT 必须为常量')
                tree=tree.limit(min(max(int(value.this),0),200))
            else: tree=tree.limit(200)
            return tree.sql(dialect='mysql')
        except SecurityError: raise
        except Exception as exc: raise SecurityError('SQL字段或语法校验失败：'+str(exc)[:220]) from exc

    def mask_result(self,columns,rows,user=None): return columns,list(rows)
