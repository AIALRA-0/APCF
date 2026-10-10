# APCF-META {"schema":1,"visibility":"public"}
"""Run finite success/repair examples using the current natural-ledger lifecycle.

These examples execute actual commands in an exclusively new local project.
They do not review arbitrary user content, claim independent review, publish,
or reuse a machine's installed Skill cache.
"""
from pathlib import Path
import argparse,json,os,subprocess,sys


def invoke(project,script,*args):
    r=subprocess.run([sys.executable,'-B',str(project/'.agent-project-control/scripts'/script),*map(str,args)],cwd=project,capture_output=True,text=True,encoding='utf-8')
    if r.returncode:raise RuntimeError(script+': '+r.stdout[-1800:]+r.stderr[-1800:])
    return r.stdout


def worker(project,scenario):
    os.chdir(project)
    target='demo.py' if scenario=='success' else 'demo.md'
    expected_output='有限合成断言通过'
    if scenario=='success':
        final_body='def increment(value):\n    return value + 1\n'
        initial_body=final_body
        assertion_code='from demo import increment; assert increment(0)==1; assert increment(-2)==-1; print('+repr(expected_output)+')'
    else:
        initial_body='# 1. 合成说明\n\n当前结果已保存。\n\n```python\nprint("受保护原文。")\n```\n'
        final_body=initial_body.replace('当前结果已保存。','当前结果已保存')
        assertion_code='from pathlib import Path; s=Path("demo.md").read_text(encoding="utf-8"); assert "当前结果已保存。" not in s; assert \'print("受保护原文。")\' in s; print('+repr(expected_output)+')'
    (project/target).write_text('旧的合成占位内容',encoding='utf-8')
    invoke(project,'new_iteration.py','--title','有限合成示例','--objective','检查成功与修复的实际入口，不代表业务认证')
    turn=Path(invoke(project,'new_turn.py','--title',scenario,'--request-text','验证独立合成结果，保留受保护原文，不发布到远端').strip().splitlines()[-1])
    ROOT=Path.cwd();sys.path.insert(0,str(ROOT/'.agent-project-control/scripts'))
    import test_ledger as L, narrative_contract as N, execution_session as E,routing_activity as A,repair_io as IO,prose_review as P,terminology_review as T
    from common import write_md
    tr=turn;value=expected_output
    request=json.loads((tr/'evidence/execution-session.json').read_text())['request_id']
    prose='当本轮验证独立示例时，旧实现与正文错误可能使结果不符或损坏受保护原文，因此必须保存限定实现并运行真实断言，以当前结果满足预期且保留受保护原文作为完成判据'
    quotes={'context':'当本轮验证独立示例时','problem':'旧实现与正文错误','consequence':'使结果不符或损坏受保护原文','requirement':'必须保存限定实现并运行真实断言','criterion':'当前结果满足预期且保留受保护原文'}
    def goals(status):
        return '# 1. 当前目标\n\n'+N.GOAL_MARKER+'\n\n'+L.serialize_goal({'status':status,'id':'CL-01','object':'合成结果与保护边界'},prose,quotes)
    def tests(status,actual,evidence):
        body=f'为证明当前示例满足结果和保护边界，我在本轮隔离项目中保存当前实现后运行真实断言；预期断言输出为{value}，实际{actual}，据此本次示例检查'+('通过' if status=='PASS' else '等待真实执行')+f'，证据保存在 {evidence}'
        return '# 1. 当前验收\n\n'+N.TEST_MARKER+'\n\n'+L.serialize_v3({'status':status,'id':'TEST-01','refs':['CL-01'],'object':'合成结果断言'},body,{'purpose':'为证明当前示例满足结果和保护边界','context':'本轮隔离项目','action':'保存当前实现后运行真实断言','expected':f'预期断言输出为{value}','actual':'实际'+actual,'conclusion':'本次示例检查'+('通过' if status=='PASS' else '等待真实执行'),'evidence':evidence})
    write_md(tr/'CHECKLIST.md',goals('进行中'));write_md(tr/'TEST.md',tests('未执行','尚未读取新值','evidence/planned-check.json'))
    old=(ROOT/target).read_bytes()
    IO.private_json(tr/'evidence/investigation.json',{'path':target,'before_sha256':IO.digest(old),'observed':old.decode(),'purpose':'检查当前源值，然后建立计划；没有修改业务文件'})
    plan=A.record_plan(tr,[target],['evidence/investigation.json'],['TEST-01'])
    E.authorize(tr,request)
    E.apply_file(tr,request,target,initial_body.encode(),IO.digest(old))
    # Actual subprocess readback; evidence is not a prefilled success template.
    command=[sys.executable,'-B','-c',assertion_code]
    if scenario=='repair':
        failed_exit,failed_result=A.run_check(tr,['TEST-01'],[target],command,required_output=[value])
        assert failed_exit!=0, 'negative fixture was silently accepted'
        first_bytes=(ROOT/target).read_bytes()
        E.apply_file(tr,request,target,final_body.encode(),IO.digest(first_bytes))
        IO.private_json(tr/'evidence/repair-observation.json',{'first_exit':failed_exit,'before_sha256':IO.digest(first_bytes),'after_sha256':IO.digest((ROOT/target).read_bytes()),'limits':'finite editable-prose repair; protected code bytes must remain'})
    exit_code,check=A.run_check(tr,['TEST-01'],[target],command,required_output=[value])
    assert exit_code==0
    last=json.loads((tr/'evidence/checks.jsonl').read_text().splitlines()[-1]);ref=last['path']
    write_md(tr/'CHECKLIST.md',goals('已完成'));write_md(tr/'TEST.md',tests('PASS',f'断言输出为{value}',ref))
    from report_contract import SECTION_TITLES,meaningful_file_lines,split_sections
    parts=[f'- **IT / TR**：本项目的当前目标与当前请求\n- **Checklist**：已完成 1\n- **Test**：PASS 1',
           '本轮从独立示例项目开始，旧内容不能证明当前实现或正文保护正确\n\n本轮先登记当前请求与计划，再保存有限实现并通过真实子进程断言，结果只限于当前合成输入',
           '- **IT**：框架中承载稳定目标的本地编号，本例把多个请求归入有限示例目标\n- **TR**：本轮请求的独立记录编号，本例用它区分成功场景与修复场景\n- **PASS**：本地验收状态，表示当前输入在对应检查中通过，不表示真实宿主已全面验收',
           '\n'.join(meaningful_file_lines(tr/'CHECKLIST.md')),'\n'.join(meaningful_file_lines(tr/'TEST.md')),
           f'当前示例实际断言输出为{value}，与本轮请求一致，测试子进程正常退出\n\n本例没有自动接管真实桌面聊天或所有外部写入，因而不证明模型以后永不遗漏',
           f'- **示例断言输出为{value}，真实宿主仍需单独核验**：当前保存和读取结果一致，连续轮次由不同请求身份隔离；外部工具与聊天通道不在此合成场景内',
           '- **当前无需用户介入合成输入**：所有输入都是测试专用内容',
           '- **真实宿主限制保持可见**：本轮不能作为自动加载或发送通道的认证',
           '- **将同一版本送入真实项目观察后续轮次**：检查实际入口与最终交付，不从单轮函数通过推断普遍可靠性']
    report='\n\n'.join(f'## {i}. {title}\n\n{parts[i]}' for i,title in enumerate(SECTION_TITLES))
    # Author review of these known, observed fixture facts. Not an independent human label.
    r=P.draft(report,tr);r['reviewer']['identity']='有限合成案例的编写者自查，不是独立人类签收'
    for note in r['goals']:
        note['observation']='目标说明旧实现或正文错误的后果，范围在业务写入前固定，修复不得改变受保护原文'
        note['roles']={k:P.locate(prose,q) for k,q in quotes.items()}
    raw=(tr/ref).read_bytes();trow=L.parse_tests((tr/'TEST.md').read_text())[0]
    for note in r['tests']:
        note['observation']=f'已经读取本轮真实子进程输出，其中含{value}，退出码与预期一致'
        note['actual_selection']=P.locate(trow['_prose'],trow['actual'])
        note['evidence']=[{'path':ref,'sha256':IO.digest(raw),'excerpt':value}]
    for u in r['explanation_coverage']:u.update(importance='core',takeaway_indexes=[0],reason='这段分别说明实际结果或真实宿主限制，需要在关键要点保留')
    r['takeaways']=[{'sha256':IO.digest(parts[6].encode()),'source_units':['E001','E002'],'observation':'摘要保留了真实断言值与宿主没有被接管的限制'}]
    r['section_observations']={str(i):'本节只描述已执行的有限合成任务、当前请求身份及真实宿主未测边界，未声称独立人类审核' for i in range(10)}
    IO.private_json(tr/'evidence/prose-review.json',r)
    # Known finite glossary: no general dictionary and no new coined expansions.
    t=T.initial_review(report);from datetime import datetime,timezone
    stamp=datetime.now(timezone.utc).isoformat();t.update(reviewer='有限合成案例的作者',reviewed_at=stamp,audience_context='首次接触框架编号的中文读者',semantic_review_completed=True,review_method='author_self_review')
    t['attestations']={x:True for x in T.ATTESTATIONS}
    defs={'IT':('框架中承载稳定目标的本地编号','本例把多个请求归入有限示例目标','internal_identifier'),
          'TR':('本轮请求的独立记录编号','本例用它区分成功场景与修复场景','internal_identifier'),
          'PASS':('本地验收状态','表示当前输入在对应检查中通过，不表示真实宿主已全面验收','literal')}
    source=ROOT/'.agent-project-control/rules/01-context-state.md';source2=ROOT/'.agent-project-control/rules/03-verification-regression.md'
    body=source.read_bytes()+b'\n'+source2.read_bytes();(tr/'evidence/glossary-source.md').write_bytes(body)
    for item in t['items']:
        term=item['term'];assert term in defs,('unexpected term in controlled scenario',term)
        definition,relevance,kind=defs[term]
        line=next(x for x in parts[2].splitlines() if x.startswith('- **'+term+'**'))
        for meaning in item['meanings']:
            meaning.update(decision='EXPLAINED',reason='实际报告使用当前编号，需要说明用途而不是猜测英文展开',audience_context='中文首次使用者',domain_context='本地配置隔离验收',current_use=relevance,context_relevance=relevance,
                           name_status='NOT_APPLICABLE',name_limit='这里按框架实际编号或状态值说明，不声称另有已确认的正式全称',verified_full_name='',definition=definition,
                           source_or_basis='evidence/glossary-source.md 的实际当前规范',reviewer='有限合成案例的作者',reviewed_at=stamp,
                           term_kind=kind,visible_explanation=P.locate(report,line),source_evidence={'path':'evidence/glossary-source.md','sha256':IO.digest(body),'excerpt':term})
    assert not T.validate(report,t,turn_dir=tr),T.validate(report,t,turn_dir=tr)
    IO.private_json(tr/'evidence/terms-review.json',t)
    write_md(tr/'TURN.md',f'# 1. 本轮配置验证\n\n- **Status**：IN_PROGRESS\n\n## 1.1. USER REPORT\n\n{report}')
    assert not A.workflow_errors(tr),A.workflow_errors(tr)
    # Execute current receipt routing; leave its exact source output in private evidence.
    args=[sys.executable,'-B',str(ROOT/'.agent-project-control/scripts/route_context.py'),'--turn-dir',str(tr),'--phase','scope','--phase','tools','--phase','verification','--phase','finalization','--capability','human-readable']
    proc=subprocess.run(args,cwd=ROOT,capture_output=True,text=True)
    (tr/'evidence/route-output.txt').write_text(proc.stdout+'\n'+proc.stderr)
    assert proc.returncode==0,(proc.returncode,proc.stderr,proc.stdout[-2000:])
    targets=A.managed_targets(tr)
    # Include final report explicitly because it is a product even when structural classifier treats it as metadata.
    turnrel=(tr/'TURN.md').relative_to(ROOT).as_posix()
    A.record_semantic_review(tr,{rel:f'实际读取当前对象 {rel} 并核对其内容与本轮有限示例结果与保护边界相符；这里只用于本地隔离场景' for rel in targets},[ref])
    for rel in list(dict.fromkeys([*targets,turnrel,*[(tr/name).relative_to(ROOT).as_posix() for name in ('CHECKLIST.md','TEST.md')]])):
        cap=['human-readable']
        A.record_content_review(tr,rel,cap,[ref],[{'line':1,'criterion':'当前有限示例请求与候选字节关联','observed':f'真实读取结果为{value}，报告中的具体结果和限制另有逐段核验','result':'PASS'}],method='deterministic-fixture-review')
    # Host output is only prepared; caller later checks capture identity, not remote delivery.
    E.emit(tr,request,tr/'evidence/final-output.txt')
    invoke(ROOT,'finalize_turn.py',tr)
    assert E.emit(tr,request,tr/'evidence/final-output.txt',observed=True)['status']=='OBSERVED_TEXT_MATCH'
    print(json.dumps({'request_id':request,'turn':str(tr),'targets':targets,'observed':value,'checks':1,'mode':'synthetic subprocess request, not actual host chat'},ensure_ascii=False))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--project',required=True);p.add_argument('--scenario',choices=['success','repair'],required=True);p.add_argument('--installed-worker',action='store_true',help=argparse.SUPPRESS);a=p.parse_args()
    project=Path(a.project).absolute()
    if project.is_symlink() or any(x.is_symlink() for x in project.parents):raise SystemExit('FAIL: symlink target refused')
    project=project.resolve()
    if a.installed_worker:worker(project,a.scenario);return
    if project.exists() and any(project.iterdir()):raise SystemExit('FAIL: example requires a new or empty project')
    source=Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable,'-B',str(source/'.agent-project-control/scripts/bootstrap.py'),str(project)],check=True)
    subprocess.run([sys.executable,'-B',str(Path(__file__).resolve()),'--project',str(project),'--scenario',a.scenario,'--installed-worker'],cwd=project,check=True)
if __name__=='__main__':main()
