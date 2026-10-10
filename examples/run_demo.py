# APCF-META {"schema":1,"visibility":"public"}
"""Self-owned success/repair examples through the actual current writing and closeout path.

Synthetic author review is specific to these finite fixtures, not a generic PASS
factory for user documents. No real model invocation or remote publish is claimed.
"""
from pathlib import Path
import argparse,json,os,subprocess,sys,tempfile


def worker(ROOT,scenario):
    ROOT=ROOT.resolve();os.chdir(ROOT);sys.path.insert(0,str(ROOT/'.agent-project-control/scripts'))
    import writing_guard as G,execution_session as E,routing_activity as A,terminology_review as T,prose_review as P
    from common import write_md
    from repair_io import private_json,digest
    from test_ledger import serialize_goal,serialize_v3
    from narrative_contract import GOAL_MARKER,TEST_MARKER
    from report_contract import SECTION_TITLES,meaningful_file_lines,validate_report
    
    def run(name,*args):
     p=subprocess.run([sys.executable,'-B',str(ROOT/'.agent-project-control/scripts'/name),*map(str,args)],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
     if p.returncode:raise RuntimeError(name+' '+p.stdout[-4500:]+p.stderr[-4500:])
     return p.stdout
    
    run('new_iteration.py','--title','独立行为示例','--objective','验证真实行为和写作交付不混同')
    target='demo.py' if scenario=='success' else 'demo.md'
    original=ROOT/target
    if scenario=='success':
        original.write_text('def increment(value):\n    return value\n',encoding='utf-8')
        initial_body='def increment(value):\n    return value + 1\n'
        final_body=initial_body
        command_code='from demo import increment; assert increment(0)==1; assert increment(-2)==-1; print("两项行为断言通过")'
    else:
        original.write_text('# 1. 初始文稿\n\n尚未处理\n',encoding='utf-8')
        initial_body='# 1. 合成说明\n\n当前结果已保存。\n\n```python\nprint("受保护原文。")\n```\n'
        final_body=initial_body.replace('当前结果已保存。','当前结果已保存')
        command_code='from pathlib import Path; s=Path("demo.md").read_text(encoding="utf-8"); assert "当前结果已保存。" not in s; assert \'print("受保护原文。")\' in s; print("两项行为断言通过")'
    TR=Path(run('new_turn.py','--title','验证'+scenario,'--request-text','验证独立示例的真实行为和原文保护，不发布').strip().splitlines()[-1])
    assert G.enabled(TR)
    request=json.loads((TR/'evidence/execution-session.json').read_text(encoding='utf-8-sig'))['request_id'];report_target=(TR/'TURN.md').relative_to(ROOT).as_posix()
    goal='当本轮示例需要更新时，旧实现或文字错误会使行为与目标不符并可能损坏原文，因此必须限定修改并运行两项真实断言，以实际断言通过且代码中的保护原文未变作为完成判据'
    gq={'context':'当本轮示例需要更新时','problem':'旧实现或文字错误','consequence':'使行为与目标不符并可能损坏原文','requirement':'必须限定修改并运行两项真实断言','criterion':'实际断言通过且代码中的保护原文未变'}
    def checklist(status):return '# 1. 当前目标\n\n'+GOAL_MARKER+'\n\n'+serialize_goal({'id':'CL-01','status':status,'object':'隔离行为更新'},goal,gq)+'\n'
    def ledger(status,actual,ref):
     s=f'为核对当前示例行为，我在当前隔离目录保存限定实现后实际运行断言；预期两项行为断言通过，实际{actual}，因此本次示例检查'+('通过' if status=='PASS' else '尚未完成')+f'，证据保存在 `{ref}`'
     q={'purpose':'为核对当前示例行为','context':'当前隔离目录','action':'保存限定实现后实际运行断言','expected':'预期两项行为断言通过','actual':'实际'+actual,'conclusion':'本次示例检查'+('通过' if status=='PASS' else '尚未完成'),'evidence':'`'+ref+'`'}
     return '# 1. 当前验收\n\n'+TEST_MARKER+'\n\n'+serialize_v3({'id':'TEST-01','status':status,'refs':['CL-01'],'object':'真实行为断言'},s,q)+'\n'
    write_md(TR/'CHECKLIST.md',checklist('进行中'));write_md(TR/'TEST.md',ledger('未执行','尚未读回','evidence/planned.json'))
    private_json(TR/'evidence/investigation.json',{'before_sha256':digest(original.read_bytes()),'scope':target,'investigation':'实际读取旧内容并确认本例两项断言，不修改外部项目'})
    A.record_plan(TR,[target],['evidence/investigation.json'],['TEST-01']);E.authorize(TR,request)
    if scenario=='repair':G.prepare(TR,target,'draft')
    old=original.read_bytes();E.apply_file(TR,request,target,initial_body.encode(),digest(old))
    cmd=[sys.executable,'-B','-c',command_code]
    if scenario=='repair':
        failed,_=A.run_check(TR,['TEST-01'],[target],cmd,required_output=['两项行为断言通过'])
        assert failed!=0,'incorrect editable prose unexpectedly passed'
        G.prepare(TR,target,'draft')
        E.apply_file(TR,request,target,final_body.encode(),digest(original.read_bytes()))
    exit_code,_=A.run_check(TR,['TEST-01'],[target],cmd,required_output=['两项行为断言通过']);assert exit_code==0
    ref=json.loads((TR/'evidence/checks.jsonl').read_text(encoding='utf-8-sig').splitlines()[-1])['path']
    write_md(TR/'CHECKLIST.md',checklist('已完成'));write_md(TR/'TEST.md',ledger('PASS','两项行为断言通过',ref))
    G.prepare(TR,report_target,'draft')
    D1='在交付前检查当前验收与证据是否满足要求的步骤';R1='本例用它判断当前任务是否可以收口';M1='直观来说，它像出厂前的检验关卡，不负责把文件归档'
    D2='在检查通过后按同一过程保存最终报告和项目当前状态的操作';R2='本例用它防止报告与状态各自更新后不一致';M2='直观来说，它像把验收单和项目档案一起归档，而不是重新检查一遍产品'
    terms=f'- **交付门禁（Gate）**：{D1}；{R1}；{M1}\n- **正式收口（Finalize）**：{D2}；{R2}；{M2}'
    parts=[
    '- 当前目标：`IT-0001`\n- 本轮记录：`TR-0001`\n- 执行清单：已完成1\n- 验收：通过1；失败0\n- 范围：本地隔离读回，不含远端发布',
    '此前隔离示例保留旧内容，不能直接证明当前行为正确\n\n本轮先建立目标与判据，再实际执行两项行为断言，并将当前结果交给原有检查及收口流程',terms,
    '\n'.join(meaningful_file_lines(TR/'CHECKLIST.md')),'\n'.join(meaningful_file_lines(TR/'TEST.md')),
    '当前示例的两项行为断言已实际通过，与本轮请求一致，检查子进程正常退出；交付门禁（Gate）用于核对当前证据，正式收口（Finalize）用于一致地保存报告与状态\n\n本例没有调用真实模型或进行远端发布，也不能证明所有外部工具都必须遵守这个入口',
    '- **实际断言符合请求，真实宿主仍未验收**：当前两项断言通过，写入和行为检查有对应证据；模型多轮理解、外部工具和实际聊天不在本例的验证范围',
    '- **当前无需用户介入合成检查**：本轮只处理测试自有文件，不修改真实项目',
    '- **真实使用仍需现场观察**：脚本正确拒绝格式错误不等于模型永远理解正确，也不等于用户签收',
    '- **按同一候选继续实际项目验证**：保留当前机制证据，下一步核对真实用户任务与最终聊天内容，不扩大这次合成结果的证明范围']
    report='\n\n'.join(f'## {i}. {title}\n\n{parts[i]}' for i,title in enumerate(SECTION_TITLES))
    write_md(TR/'TURN.md','# 1. 当前执行轮次\n\n- **Status**：IN_PROGRESS\n\n## 1.1. USER REPORT\n\n'+report)
    # Finite literal review rows backed by current rule text; not a general auto-pass author.
    source=(ROOT/'.agent-project-control/interfaces/APCF_ONBOARDING.md').read_bytes()+(ROOT/'.agent-project-control/scripts/finalize_turn.py').read_bytes()
    (TR/'evidence/term-sources.txt').write_bytes(source)
    t=T.initial_review(report)
    from datetime import datetime,timezone
    stamp=datetime.now(timezone.utc).isoformat()
    t.update(reviewer='有限合成案例编写者',reviewed_at=stamp,audience_context='首次使用本地配置任务的中文读者',semantic_review_completed=True,review_method='author_self_review')
    t['schema']=2;t['attestations']={k:True for k in T.ATTESTATIONS}
    assert not t['items'],t['items']
    for term,zh,d,r,m in [('Gate','交付门禁',D1,R1,M1),('Finalize','正式收口',D2,R2,M2)]:
     line=next(x for x in terms.splitlines() if term in x);loc=[i for i,x in enumerate(report.splitlines(),1) if term in x and not x.startswith('- **')]
     meaning={'meaning_id':term,'line_numbers':loc,'decision':'EXPLAINED','reason':'本轮用到检查与保存两个不同动作，需要分开解释','audience_context':'中文首次使用者','domain_context':'隔离配置验收','current_use':r,'context_relevance':r,'source_or_basis':'evidence/term-sources.txt 为当前实际规范原文','reviewer':'有限合成案例编写者','reviewed_at':stamp,'name_status':'VERIFIED','verified_full_name':term,'definition':d,'term_kind':'proper_name','display_name':zh+'（'+term+'）','chinese_name':zh,'analogy':m,'analogy_basis':'仅以检验和归档的先后职责作类比，未把检查等同于保存或模拟人类签收','visible_explanation':P.locate(report,line),'source_evidence':{'path':'evidence/term-sources.txt','sha256':digest(source),'excerpt':term}}
     t['manual_terms'].append({'term':term,'line_numbers':loc,'observed_uses':len(loc),'meanings':[meaning]})
    private_json(TR/'evidence/terms-review.json',t)
    assert G.content_errors(report,t)==[],G.content_errors(report,t)
    assert T.validate(report,t,turn_dir=TR)==[],T.validate(report,t,turn_dir=TR)
    r=P.draft(report,TR);r['reviewer']['identity']='有限合成输入的编写者，非独立人类认证'
    for row in r['goals']:row.update(observation='目标说明旧实现和原文风险及两项判据，先于业务写入建立',roles={k:P.locate(goal,q) for k,q in gq.items()})
    from test_ledger import parse_tests
    record=parse_tests((TR/'TEST.md').read_text(encoding='utf-8-sig'))[0];actual=(TR/ref).read_bytes()
    for row in r['tests']:row.update(observation='子进程实际输出两项行为断言通过且退出0，只证明当前有限示例',actual_selection=P.locate(record['_prose'],record['actual']),evidence=[{'path':ref,'sha256':digest(actual),'excerpt':'两项行为断言通过'}])
    for u in r['explanation_coverage']:u.update(importance='core',takeaway_indexes=[0],reason='结果与真实宿主未测限制都会影响读者判断，应在关键要点保留')
    r['takeaways']=[{'sha256':digest(parts[6].encode()),'source_units':['E001','E002'],'observation':'该要点保留实际数值与模型／外部工具没有核验的边界'}]
    r['section_observations']={str(i):'本节只描述当前有限行为示例、实际结果和没有进行的外部验证，未声称独立语义认证' for i in range(10)}
    private_json(TR/'evidence/prose-review.json',r)
    G.prepare(TR,report_target,'review');assert validate_report(report,TR)==[],validate_report(report,TR)
    # Negative at actual report gate, even when the rest of the input is valid.
    bad=report.replace('- **交付门禁（Gate）**','  - **交付门禁（Gate）**')
    assert validate_report(bad,TR),'nested glossary must be rejected by the actual report gate'
    # Read full authority on actual routing path; short preparation did not forge this receipt.
    run('route_context.py','--turn-dir',TR,'--phase','scope','--phase','tools','--phase','verification','--phase','finalization','--capability','human-readable')
    targets=A.managed_targets(TR)
    A.record_semantic_review(TR,{x:'逐项核对本轮实际对象；当前示例的修改和断言已由独立子进程确认，未声明其他业务效果' for x in targets},[ref])
    for rel in dict.fromkeys([*targets,report_target,*[(TR/n).relative_to(ROOT).as_posix() for n in ('CHECKLIST.md','TEST.md')]]):
     A.record_content_review(TR,rel,['human-readable'],[ref],[{'line':1,'criterion':'本轮配置任务与实际结果对应','observed':'实际两项行为断言通过，定义、要点和限制的具体定位已另外记录','result':'PASS'}],method='deterministic-fixture-review')
    run('finalize_turn.py',TR)
    output=TR/'evidence/final-readable.md';E.emit(TR,request,output)
    assert '<!-- APCF-' not in output.read_text(encoding='utf-8-sig')
    E.emit(TR,request,output,observed=True)
    assert '<!-- APCF-FACTS' in (TR/'TURN.md').read_text(encoding='utf-8-sig')
    assert original.read_text(encoding='utf-8')==final_body
    print('INTEGRATION_PASS:'+json.dumps({'turn':str(TR),'scenario':scenario,'assertions':2,'finalized':True,'comments_preserved_in_source':True,'comments_absent_in_output':True,'scope':'finite real subprocess and actual gates; no real model, Windows, remote publish'},ensure_ascii=False))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--project',required=True);p.add_argument('--scenario',choices=['success','repair'],required=True);p.add_argument('--worker',action='store_true',help=argparse.SUPPRESS);a=p.parse_args()
    root=Path(a.project).absolute()
    if any(x.is_symlink() for x in (root,*root.parents)):raise SystemExit('Linked example path refused')
    root=root.resolve()
    if a.worker:return worker(root,a.scenario)
    if root.exists() and (not root.is_dir() or any(root.iterdir())):raise SystemExit('Use a new or empty self-owned example directory')
    source=Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable,'-B',str(source/'.agent-project-control/scripts/bootstrap.py'),str(root)],check=True)
    subprocess.run([sys.executable,'-B',str(Path(__file__).resolve()),'--project',str(root),'--scenario',a.scenario,'--worker'],cwd=root,check=True)
if __name__=='__main__':main()
