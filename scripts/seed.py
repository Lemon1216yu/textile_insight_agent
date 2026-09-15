"""Create isolated demo database, deterministic seed and SELECT-only user. Idempotent."""
import sys, os, random, calendar, json, hashlib
from pathlib import Path
from datetime import date, timedelta
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pymysql
from textile.settings import DB, ROOT
from textile.catalog import CATALOG

def main():
    config = {**DB, 'user':'root', 'password':os.environ['TEXTILE_MYSQL_ROOT_PASSWORD']}
    conn = pymysql.connect(**config)
    rng = random.Random(20260914)
    regions = ['华东','华南','华北']

    def hash_password(password):
        salt = os.urandom(16)
        digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 200_000)
        return salt.hex() + '.' + digest.hex()

    with conn.cursor() as cur:
        cur.execute("CREATE TABLE IF NOT EXISTS seed_version (version VARCHAR(30) PRIMARY KEY)")
        cur.execute("SELECT version FROM seed_version WHERE version='textile-v1'")
        seeded = cur.fetchone() is not None
        # 企业用户账户（模拟配置）：幂等，已存在用户不覆盖（保留修改过的密码）。
        cur.execute("""CREATE TABLE IF NOT EXISTS sys_users (
            user_id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(50) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            display_name VARCHAR(50) NOT NULL,
            role VARCHAR(30) NOT NULL,
            region VARCHAR(20) NULL,
            active TINYINT(1) NOT NULL DEFAULT 1,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_login_at DATETIME NULL) COMMENT='企业用户账户（模拟配置）'""")
        for username, display, role, region in [
            ('admin','系统管理员','admin',None),
            ('executive','经营负责人','executive',None),
            ('finance','财务分析师','finance',None),
            ('sales_east','销售经理（华东）','sales','华东'),
            ('production','生产主管','production',None),
            ('warehouse','仓储主管','warehouse',None),
        ]:
            cur.execute('INSERT IGNORE INTO sys_users (username,password_hash,display_name,role,region) VALUES (%s,%s,%s,%s,%s)',
                        (username, hash_password('demo123'), display, role, region))
        for table, (desc, fields) in CATALOG.items():
            definitions = ','.join(f'`{f}` {typ} COMMENT %s' for f,(typ,_) in fields.items())
            cur.execute(f'CREATE TABLE IF NOT EXISTS `{table}` ({definitions}) COMMENT=%s',
                        [meaning for _,meaning in fields.values()]+[desc])
        if not seeded:
            # Refuse to append to an unversioned partial seed. No destructive reset.
            for table in CATALOG:
                cur.execute(f'SELECT COUNT(*) FROM `{table}`')
                if cur.fetchone()[0]:
                    raise RuntimeError('Unversioned data found; inspect before seeding: '+table)
            conn.begin()
            def insert(table, rows):
                cur.executemany(f'INSERT INTO `{table}` VALUES ({",".join(["%s"]*len(rows[0]))})', rows)
            insert('dim_customers',[(i,f'{["锦禾服饰","南风家纺","云织贸易","青岚服装","素棉生活","经纬商贸"][i-1]}',regions[(i-1)%3],['服装品牌','家纺企业','贸易商'][(i-1)%3]) for i in range(1,7)])
            names=['40支全棉府绸','精梳棉斜纹','涤纶春亚纺','再生涤纶牛津布','涤棉工装布','棉麻混纺布']
            costs=[14,19,9,12,16,22]
            insert('dim_products',[(i,names[i-1],['全棉','全棉','涤纶','涤纶','混纺','混纺'][i-1],costs[i-1]) for i in range(1,7)])
            insert('dim_suppliers',[(1,'恒丰棉纱'),(2,'东海化纤'),(3,'润泽纺材')])
            orders=[]; batches=[]; purchases=[]; stocks=[]; expenses=[]
            for month in range(3,9):
                for j in range(90):
                    p=rng.randint(1,6); c=rng.randint(1,6); region=regions[(c-1)%3]
                    day=date(2026,month,rng.randint(1,24)); qty=rng.randint(300,1600)
                    # July/August cotton cost shock is synthetic and deliberately testable.
                    shock=1.25 if month>=7 and p<=2 else 1.0
                    unit=round(costs[p-1]*rng.uniform(.96,1.06)*shock,2)
                    price=round(costs[p-1]*rng.uniform(1.35,1.60),2)
                    status=rng.choices(['已完成','生产中','已取消'],[85,10,5])[0]
                    promised=day+timedelta(days=3)
                    delivered=promised+timedelta(days=rng.choice([-1,0,0,0,1,2])) if status=='已完成' else None
                    orders.append((len(orders)+1,day,c,p,region,status,qty,round(qty*price,2),round(qty*unit,2),promised,delivered))
                for p in range(1,7):
                    for region in regions:
                        actual=rng.randint(7000,11000); defect=int(actual*(.07 if month>=7 and p<=2 else .025))
                        shock=1.25 if month>=7 and p<=2 else 1
                        batches.append((len(batches)+1,date(2026,month,15),p,'织造一车间' if p<=3 else '染整二车间',region,10000,actual,defect,round(actual*costs[p-1]*.65*shock,2),round(actual*2.1,2),round(actual*1.6,2)))
                        quantity=rng.randint(1500,4500)+(3500 if p==2 and month>=7 else 0)
                        aged=round(quantity*(.48 if p==2 and month>=7 else .08),2)
                        stocks.append((len(stocks)+1,date(2026,month,calendar.monthrange(2026,month)[1]),p,region+'成品仓',region,quantity,quantity*costs[p-1],aged))
                    for s in range(1,4):
                        day=date(2026,month,10); qty=rng.randint(500,1800)
                        purchases.append((len(purchases)+1,day,s,['棉纱','涤纶纱','混纺纱'][s-1],regions[s-1],qty,round(qty*rng.uniform(12,25),2),day+timedelta(days=5),day+timedelta(days=rng.choice([4,5,5,7]))))
                for region in regions:
                    for typ in ['销售费用','管理费用','财务费用']:
                        expenses.append((len(expenses)+1,date(2026,month,20),region,typ,rng.randint(5000,12000)))
            for table, rows in [('sales_orders',orders),('production_batches',batches),('purchase_orders',purchases),('inventory_snapshots',stocks),('finance_expenses',expenses)]: insert(table,rows)
            cur.execute("INSERT INTO seed_version VALUES ('textile-v1')")
            conn.commit()
        cur.execute('CREATE USER IF NOT EXISTS %s@\'%%\' IDENTIFIED BY %s',('textile_reader',DB['password']))
        for table in CATALOG:
            cur.execute(f'GRANT SELECT ON textile_insight.`{table}` TO \'textile_reader\'@\'%\'')
        # 登录与账户管理：应用账号仅能读写 sys_users（SELECT 业务表权限仅供接口只读查询复用）。
        cur.execute('CREATE USER IF NOT EXISTS %s@\'%%\' IDENTIFIED BY %s',('textile_app',DB['password']))
        for table in CATALOG:
            cur.execute(f'GRANT SELECT ON textile_insight.`{table}` TO \'textile_app\'@\'%\'')
        cur.execute("GRANT SELECT,INSERT,UPDATE ON textile_insight.sys_users TO 'textile_app'@'%'")
        counts={}
        for table in CATALOG:
            cur.execute(f'SELECT COUNT(*) FROM `{table}`'); counts[table]=cur.fetchone()[0]
    conn.close()
    print(json.dumps({'database':'textile_insight','counts':counts,'total':sum(counts.values()),'reader':'SELECT-only'},ensure_ascii=False))

if __name__=='__main__': main()
