"""One-off source migration from process-local jobs to the persistent queue."""
from pathlib import Path
p=Path(__file__).resolve().parents[1]/'textile'/'app.py'
s=p.read_text(encoding='utf-8')
start=s.index("@app.post('/api/jobs',status_code=202)")
end=s.index("@app.get('/api/metrics')",start)
s=s[:start]+'''@app.post('/api/jobs',status_code=202)
async def create_job(data:JobRequest,user=Depends(auth)):
    from textile.task_queue import submit
    if data.mode not in {'auto','query','analysis'}: raise HTTPException(422,'未知查询模式')
    try:
        question=validate_input(data.question)
        return {'id':await submit(question,data.mode,user)}
    except ValueError as exc:raise HTTPException(422,str(exc))

@app.get('/api/jobs/{job_id}')
def get_job(job_id:str,user=Depends(auth)):
    from textile.task_queue import get_job as read_job
    job=read_job(job_id,user.user_id)
    if not job:raise HTTPException(404,'任务不存在或权限已变更')
    return job

'''+s[end:]
start=s.index("@app.get('/api/history')")
s=s[:start]+'''@app.get('/api/history')
def history(user=Depends(auth)):
    from textile.task_queue import history as list_history
    return [{k:j.get(k) for k in ['id','question','status','mode','created_at','duration_seconds']} for j in list_history(user.user_id)]

@app.get('/api/jobs/{job_id}/report')
def download_report(job_id:str,user=Depends(auth)):
    job=get_job(job_id,user)
    if not job.get('report'):raise HTTPException(409,'报告尚未生成')
    parts=['# '+job['question'],job['report'],'---\\n模拟业务数据。']
    for result in job.get('results',[]):
        if result['success']:
            parts.extend(['## '+result['step']['title'],'```json\\n'+json.dumps(result['rows'],ensure_ascii=False,indent=2)+'\\n```'])
    return Response('\\n\\n'.join(parts),media_type='text/markdown; charset=utf-8',headers={'Content-Disposition':'attachment; filename="analysis.md"'})

@app.get('/api/usage')
def usage(user=Depends(auth)):
    from textile.registry import redis_client
    r=redis_client();day=time.strftime('%Y-%m-%d')
    return {'day':day,'tokens':int(r.get(f'textile:tokens:{user.user_id}:{day}') or 0),
            'limit':int(os.getenv('TEXTILE_DAILY_TOKEN_LIMIT','1000000'))}

@app.get('/api/admin/audit')
def audit_log(user=Depends(auth)):
    require_admin(user)
    with _conn() as conn,conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute('SELECT event_id,occurred_at,username,action,detail FROM audit_events ORDER BY event_id DESC LIMIT 100')
        return {'items':cur.fetchall()}
'''
# Remove abandoned process-local worker state and old result loading.
start=s.index('jobs={}; lock=')
end=s.index('SESSION_HOURS=',start)
s=s[:start]+s[end:]
s=s.replace('user_id,username,password_hash,display_name,role,region,active FROM sys_users',
            'user_id,username,password_hash,display_name,role,region,active,session_version FROM sys_users')
s=s.replace("username,expiry=base64.urlsafe_b64decode(payload).decode().split(':')", "username,expiry,version=base64.urlsafe_b64decode(payload).decode().split(':')")
s=s.replace("if not row or not row['active']: raise ValueError()", "if not row or not row['active'] or str(row['session_version'])!=version: raise ValueError()")
s=s.replace("{int(time.time())+SESSION_HOURS*3600}\",", "{int(time.time())+SESSION_HOURS*3600}\",") if False else s
s=s.replace("{int(time.time())+SESSION_HOURS*3600}\".encode()", "{int(time.time())+SESSION_HOURS*3600}:{row['session_version']}\".encode()")
s=s.replace('UPDATE sys_users SET password_hash=%s WHERE user_id=%s','UPDATE sys_users SET password_hash=%s,session_version=session_version+1 WHERE user_id=%s')
s=s.replace("if not sets: raise HTTPException(422,'没有需要更新的字段')", "if not sets: raise HTTPException(422,'没有需要更新的字段')\n    sets.append('session_version=session_version+1')")
p.write_text(s,encoding='utf-8')
print('Queue API migration applied')
