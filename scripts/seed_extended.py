"""Seed 44 meaningful extension tables with linked, small synthetic records."""
import sys,os,random
from pathlib import Path
from datetime import date
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pymysql
from textile.settings import DB
from textile.extended_catalog import SPECS,EXTRA_CATALOG,PRIMARY

def main():
    rng=random.Random(20260915)
    with pymysql.connect(**{**DB,'user':'root','password':os.environ['TEXTILE_MYSQL_ROOT_PASSWORD']}) as conn,conn.cursor() as cur:
        for domain,table,description,target,key,_ in SPECS:
            fields=EXTRA_CATALOG[table][1]
            cur.execute(f'CREATE TABLE IF NOT EXISTS `{table}` ('+','.join(f'`{f}` {typ} COMMENT %s' for f,(typ,_) in fields.items())+') COMMENT=%s',
                        [meaning for _,meaning in fields.values()]+[description+'（模拟）'])
            cur.execute(f'SELECT COUNT(*) FROM `{table}`')
            if not cur.fetchone()[0]:
                for i in range(1,13):
                    row=[];reference_count=3 if target=='dim_suppliers' else 6 if target in {'dim_products','dim_customers'} else 12
                    for field,(typ,meaning) in fields.items():
                        if 'PRIMARY KEY' in typ:value=i
                        elif field==key:value=(i-1)%reference_count+1
                        elif field=='region':value=['华东','华南','华北'][(i-1)%3]
                        elif typ=='DATE':value=date(2026,3+(i-1)%6,10 if field=='business_date' else 25)
                        elif typ.startswith('DECIMAL'):
                            value=round(100+i*17+rng.random()*20,2)
                            if 'score' in field:value=round(75+rng.random()*24,2)
                            if field in {'defect_meters','rejected_kg','rework_hours','steam_tons'}:value=round(1+i*.3,2)
                            if field in {'qualified_meters','counted_meters','accepted_kg','completed_meters','collected_amount','paid_amount','released_meters'}:value=round(80+i*13,2)
                        else:
                            value={'movement_type':['入库','出库'][i%2],'reason':['设备保养','换批调整','异常处理'][i%3],
                                   'severity':['轻微','一般','严重'][i%3],'payment_method':'银行转账','contract_status':'生效',
                                   'warehouse_type':'成品仓','allocation_basis':'工时','process_type':['织造','染色','后整理'][i%3]}.get(field,meaning+f'{i:02d}')
                        row.append(value)
                    cur.execute(f'INSERT INTO `{table}` VALUES ('+','.join(['%s']*len(row))+')',row)
            for user in ['textile_reader','textile_app']:
                cur.execute(f"GRANT SELECT ON textile_insight.`{table}` TO '{user}'@'%'")
    print('44 extension tables initialized; 12 rows each; original business records untouched.')
if __name__=='__main__':main()
