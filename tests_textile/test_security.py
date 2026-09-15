import pytest
from textile.security import TextileSecurity
from security import UserContext,SecurityError

guard=TextileSecurity()
sales=UserContext('sales_east','sales','华东')

@pytest.mark.parametrize('sql',[
 'DROP TABLE sales_orders','DELETE FROM sales_orders',
 'SELECT 1; SELECT 2','SELECT * FROM sales_orders',
 "SELECT LOAD_FILE('/etc/passwd')",'SELECT SLEEP(10)',
 'SELECT BENCHMARK(1000000,MD5(1))','SELECT user FROM mysql.user',
 "SELECT order_id INTO OUTFILE '/tmp/test' FROM sales_orders",
 'SELECT order_id FROM sales_orders FOR UPDATE',
 'SELECT secret_field FROM sales_orders',
 'WITH RECURSIVE x AS (SELECT 1 UNION ALL SELECT 1 FROM x) SELECT 1 FROM x',
])
def test_dangerous_queries_rejected(sql):
    with pytest.raises(SecurityError): guard.secure_sql(sql)

@pytest.mark.parametrize('sql',[
 'SELECT cost_amount AS harmless FROM sales_orders',
 'SELECT SUM(cost_amount) AS value FROM sales_orders',
 'SELECT amount FROM finance_expenses',
 'WITH c AS (SELECT cost_amount AS value FROM sales_orders) SELECT value FROM c',
 'SELECT p.standard_cost FROM dim_products p',
])
def test_sales_cannot_alias_or_aggregate_hidden_cost(sql):
    with pytest.raises(SecurityError): guard.secure_sql(sql,sales)

@pytest.mark.parametrize('sql',[
 'SELECT region, SUM(net_amount) FROM sales_orders GROUP BY region',
 'SELECT order_id FROM sales_orders WHERE region=\'华南\' OR 1=1',
 'WITH c AS (SELECT order_id FROM sales_orders) SELECT order_id FROM c',
 'SELECT order_id FROM sales_orders UNION ALL SELECT order_id FROM sales_orders',
 'SELECT s.order_id FROM sales_orders s LEFT JOIN dim_customers c ON s.customer_id=c.customer_id',
])
def test_row_filter_applies_at_every_source(sql):
    secured=guard.secure_sql(sql,sales)
    assert "region = '华东'" in secured
    assert secured.count("region = '华东'") == sql.lower().count('sales_orders')+sql.lower().count('dim_customers')

def test_count_star_allowed_and_limit_capped():
    assert 'LIMIT 200' in guard.secure_sql('SELECT COUNT(*) FROM sales_orders LIMIT 99999')

def test_invalid_role_fails_closed():
    with pytest.raises(SecurityError): guard.secure_sql('SELECT 1',UserContext('x','root'))

def test_sales_region_required():
    with pytest.raises(SecurityError): guard.secure_sql('SELECT 1',UserContext('x','sales'))

def test_fact_fanout_is_rejected():
    with pytest.raises(SecurityError):
        guard.secure_sql('SELECT SUM(s.net_amount),SUM(f.amount) FROM sales_orders s JOIN finance_expenses f ON s.region=f.region')

def test_separately_aggregated_facts_are_allowed():
    sql='WITH s AS (SELECT SUM(net_amount) AS revenue FROM sales_orders), f AS (SELECT SUM(amount) AS expense FROM finance_expenses) SELECT s.revenue-f.expense FROM s CROSS JOIN f'
    assert 'LIMIT 200' in guard.secure_sql(sql)
