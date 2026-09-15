"""44 distinct synthetic business entities extending the eight original tables.

Header/transaction tables are independent facts; join each to its master data,
never add amounts across unrelated fact rows. Measures carry explicit units.
"""
# domain, table, description, foreign-key target, key, additional typed fields
SPECS=[
('master','dim_factories','工厂档案',None,None,'factory_name:s:工厂名称|capacity_meters:n:月产能米'),
('master','dim_workshops','车间档案','dim_factories','factory_id','workshop_name:s:车间名称|process_type:s:工序类别'),
('master','dim_warehouses','仓库档案','dim_factories','factory_id','warehouse_name:s:仓库名称|warehouse_type:s:原料或成品仓'),
('master','dim_departments','部门档案',None,None,'department_name:s:部门名称'),
('master','dim_shifts','生产班次档案',None,None,'shift_name:s:班次名称|hours:n:班次工时'),
('master','dim_machines','织机与染整设备档案','dim_workshops','workshop_id','machine_name:s:设备名称|rated_kw:n:额定功率千瓦'),
('master','dim_materials','纱线染料原料档案','dim_suppliers','supplier_id','material_name:s:原料名称|standard_price:n:标准采购价元每千克'),
('master','dim_colors','染色颜色档案',None,None,'color_name:s:颜色名称|color_code:s:色号'),
('master','dim_process_routes','工艺路线档案','dim_products','product_id','route_name:s:工艺名称|standard_minutes:n:每批标准分钟'),
('master','dim_defect_types','疵点类别档案',None,None,'defect_name:s:疵点名称|severity:s:严重程度'),
('sales','sales_quotes','客户报价单','dim_customers','customer_id','quote_price:n:报价元每米|valid_until:d:报价有效期'),
('sales','sales_contracts','销售合同','dim_customers','customer_id','contract_amount:n:不含税合同金额元|contract_status:s:合同状态'),
('sales','sales_shipments','发运记录，数量不等于财务确认收入','dim_products','product_id','shipped_meters:n:发运米数|freight_amount:n:运费元'),
('sales','sales_returns','销售退货单，独立示例未回写原销售收入','dim_products','product_id','return_meters:n:退货米数|return_amount:n:退货金额元'),
('sales','customer_claims','客户投诉登记','dim_customers','customer_id','claim_type:s:投诉类型|resolved_days:n:处理用时天'),
('sales','sales_targets','区域月度销售目标','dim_products','product_id','target_amount:n:目标收入元|target_meters:n:目标销量米'),
('production','work_orders','生产工单','dim_products','product_id','planned_meters:n:计划米数|completed_meters:n:完工米数'),
('production','dyeing_batches','染色批次','dim_colors','color_id','input_meters:n:投染米数|water_tons:n:用水吨'),
('production','finishing_jobs','后整理作业','dim_products','product_id','processed_meters:n:整理米数|labor_hours:n:作业工时'),
('production','machine_downtime','设备停机事件','dim_machines','machine_id','downtime_minutes:n:停机分钟|reason:s:停机原因'),
('production','maintenance_orders','设备保养维修工单','dim_machines','machine_id','maintenance_cost:n:维修费用元|maintenance_hours:n:维修工时'),
('production','energy_readings','车间能源日用量','dim_workshops','workshop_id','electricity_kwh:n:电耗千瓦时|steam_tons:n:蒸汽吨'),
('production','material_consumption','生产领料消耗','dim_materials','material_id','consumed_kg:n:实际耗料千克|planned_kg:n:计划耗料千克'),
('production','outsourcing_orders','委外加工单','dim_suppliers','supplier_id','processed_meters:n:委外加工米数|processing_amount:n:加工费用元'),
('procurement','purchase_requisitions','采购申请单','dim_materials','material_id','requested_kg:n:申请千克|approved_kg:n:批准千克'),
('procurement','supplier_quotes','供应商原料报价','dim_suppliers','supplier_id','quoted_price:n:报价元每千克|minimum_kg:n:最小采购千克'),
('procurement','goods_receipts','原料到货签收','dim_materials','material_id','received_kg:n:签收千克|accepted_kg:n:验收合格千克'),
('procurement','purchase_returns','采购退货记录','dim_suppliers','supplier_id','returned_kg:n:采购退货千克|refund_amount:n:退货退款元'),
('procurement','supplier_evaluations','供应商月度评分','dim_suppliers','supplier_id','quality_score:n:质量评分满分100|delivery_score:n:交付评分满分100'),
('procurement','purchase_contracts','原料采购合同','dim_suppliers','supplier_id','contract_kg:n:合同采购千克|contract_amount:n:不含税合同金额元'),
('inventory','stock_movements','出入库流水，方向单列','dim_warehouses','warehouse_id','movement_type:s:入库或出库|quantity_meters:n:移动米数'),
('inventory','stock_counts','仓库盘点记录','dim_warehouses','warehouse_id','book_meters:n:账面米数|counted_meters:n:实盘米数'),
('inventory','stock_reservations','订单库存预留','dim_products','product_id','reserved_meters:n:预留米数|released_meters:n:释放米数'),
('inventory','stock_transfers','仓间调拨记录','dim_warehouses','warehouse_id','transferred_meters:n:调拨米数|destination:s:目标仓名称'),
('inventory','inventory_aging','单批库存库龄明细快照','dim_products','product_id','age_days:n:库龄天|quantity_meters:n:库存米数'),
('inventory','inventory_adjustments','库存调整单','dim_warehouses','warehouse_id','adjustment_meters:n:带正负号的调整米数|reason:s:调整原因'),
('quality','incoming_inspections','来料质检记录','dim_materials','material_id','sample_kg:n:抽样千克|rejected_kg:n:不合格千克'),
('quality','process_inspections','过程巡检记录','dim_defect_types','defect_type_id','inspected_meters:n:检验米数|defect_meters:n:疵点米数'),
('quality','finished_inspections','成品验布记录','dim_products','product_id','inspected_meters:n:验布米数|qualified_meters:n:合格米数'),
('quality','quality_rework','质量返工作业','dim_defect_types','defect_type_id','rework_meters:n:返工米数|rework_hours:n:返工工时'),
('finance','accounts_receivable','应收款明细，不并入销售收入','dim_customers','customer_id','receivable_amount:n:应收原值元|collected_amount:n:已收款元|due_date:d:到期日'),
('finance','accounts_payable','应付款明细','dim_suppliers','supplier_id','payable_amount:n:应付原值元|paid_amount:n:已付款元|due_date:d:到期日'),
('finance','cash_receipts','客户回款流水','dim_customers','customer_id','receipt_amount:n:本次收款元|payment_method:s:收款方式'),
('finance','cost_allocations','部门费用分摊明细','dim_departments','department_id','allocated_amount:n:分摊费用元|allocation_basis:s:分摊依据'),
]
PRIMARY={'dim_factories':'factory_id','dim_workshops':'workshop_id','dim_warehouses':'warehouse_id',
 'dim_departments':'department_id','dim_shifts':'shift_id','dim_machines':'machine_id','dim_materials':'material_id',
 'dim_colors':'color_id','dim_process_routes':'route_id','dim_defect_types':'defect_type_id'}
EXTRA_CATALOG={};EXTRA_RELATIONS={};DOMAINS={};EXTRA_FACTS=set()
for domain,table,description,target,key,extra in SPECS:
    fields={PRIMARY.get(table,'record_id'):('INT PRIMARY KEY','唯一记录编号')}
    if key:fields[key]=('INT',key+'，关联'+target)
    fields['region']=('VARCHAR(20)','业务区域：华东、华南、华北')
    if domain!='master':fields['business_date']=('DATE','业务发生日期；快照表为快照日期');EXTRA_FACTS.add(table)
    for item in extra.split('|'):
        name,kind,meaning=item.split(':',2)
        fields[name]=({'s':'VARCHAR(80)','n':'DECIMAL(14,2)','d':'DATE'}[kind],meaning)
    EXTRA_CATALOG[table]=(description+'；扩展模拟数据，与原始8表独立口径',fields)
    DOMAINS[table]=domain
    if target:EXTRA_RELATIONS[table]=[(target,key)]
