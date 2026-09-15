"""企业角色与权限矩阵（模拟配置，不冒充真实企业内部制度）。

六类企业岗位：系统管理员、经营负责人、财务分析师、销售经理、生产主管、仓储主管。
权限同时约束：可用菜单、可访问数据表、表内隐藏字段、数据区域。
区域为 None 表示全公司范围；销售经理绑定华东区域作为演示。
"""
from textile.catalog import CATALOG

ROLES = {
    'admin':     {'name': '系统管理员', 'region': None, 'menus': ['dashboard', 'query', 'analysis', 'metrics', 'reports', 'accounts']},
    'executive': {'name': '经营负责人', 'region': None, 'menus': ['dashboard', 'query', 'analysis', 'metrics', 'reports']},
    'finance':   {'name': '财务分析师', 'region': None, 'menus': ['dashboard', 'query', 'analysis', 'metrics', 'reports']},
    'sales':     {'name': '销售经理',   'region': '华东', 'menus': ['dashboard', 'query', 'analysis', 'metrics', 'reports']},
    'production':{'name': '生产主管',   'region': None, 'menus': ['dashboard', 'query', 'analysis', 'metrics', 'reports']},
    'warehouse': {'name': '仓储主管',   'region': None, 'menus': ['dashboard', 'query', 'analysis', 'metrics', 'reports']},
}

# 各岗位可见的业务表。
TABLES_BY_ROLE = {
    'admin': set(CATALOG),
    'executive': set(CATALOG),
    'finance': set(CATALOG),
    'sales': {'dim_customers', 'dim_products', 'sales_orders', 'inventory_snapshots'},
    'production': {'dim_products', 'production_batches'},
    'warehouse': {'dim_products', 'sales_orders', 'inventory_snapshots'},
}

# 各岗位表内隐藏字段（成本与金额敏感字段）。
from textile.extended_catalog import DOMAINS
for _table,_domain in DOMAINS.items():
    for _role,_domains in {'sales':{'sales','master'},'production':{'production','quality','master'},
                           'warehouse':{'inventory','quality','master'}}.items():
        if _domain in _domains:TABLES_BY_ROLE[_role].add(_table)

# 各岗位表内隐藏字段（成本与金额敏感字段）。
HIDDEN_FIELDS = {
    'sales': {'standard_cost', 'cost_amount', 'material_cost', 'labor_cost', 'energy_cost', 'inventory_value'},
    'warehouse': {'net_amount', 'cost_amount', 'material_cost', 'labor_cost', 'energy_cost', 'standard_cost'},
    'production': set(),
    'finance': set(),
    'executive': set(),
    'admin': set(),
}

# 需要绑定销售区域的角色（未绑定区域时拒绝访问）。
REGION_BOUND_ROLES = {'sales'}


def menus_for(role):
    return list(ROLES[role]['menus'])


def allowed_catalog(user):
    """按用户角色返回可访问的 {表: {字段: 类型}}，隐藏敏感字段。"""
    if user.role not in ROLES:
        raise ValueError('未知角色：' + str(user.role))
    if user.role in REGION_BOUND_ROLES and not user.region:
        raise ValueError('该角色必须绑定数据区域')
    hidden = HIDDEN_FIELDS.get(user.role, set())
    def visible(f):
        if f in hidden:return False
        if user.role in {'sales','warehouse'} and any(w in f for w in ['cost','standard_price']):return False
        return True
    return {t: {f: typ for f, (typ, _) in CATALOG[t][1].items() if visible(f)}
            for t in TABLES_BY_ROLE.get(user.role, set())}
