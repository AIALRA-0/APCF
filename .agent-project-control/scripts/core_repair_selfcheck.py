# APCF-META {"schema":1,"visibility":"public"}
"""Deterministic repair regression suite. Synthetic fixtures, not a real-host obedience claim."""
from __future__ import annotations
import contextlib
import copy
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE=Path(__file__).resolve().parents[2]
SCRIPTS=SOURCE/'.agent-project-control/scripts'
import test_ledger as ledger
import narrative_contract as narrative
import prose_review as prose
import repair_io

PUBLIC='<!-- APCF-META {"schema":1,"visibility":"public"} -->\n'
GOAL='在项目重复读取配置时，旧状态可能遮盖最新输入并造成错误结果，因此必须保存后重新读取原值，以两次读取的内容一致作为完成判据'
GQUOTES={'context':'在项目重复读取配置时','problem':'旧状态可能遮盖最新输入','consequence':'造成错误结果',
         'requirement':'必须保存后重新读取原值','criterion':'两次读取的内容一致'}
HEAD={'status':'PASS','id':'TEST-01','refs':['CL-01'],'object':'配置重新读取'}

def test_record(status='PASS', actual='读回值为 after', evidence='evidence/check.json'):
    sentence=f'为验证配置读取的承诺，我在当前隔离目录中保存配置后重新打开；预期读到 after，实际{actual}，因而本次读取检查'+('通过' if status=='PASS' else '仍未完成')+f'，对应证据保存在 {evidence}'
    return ledger.serialize_v3(dict(HEAD,status=status),sentence,{
        'purpose':'为验证配置读取的承诺','context':'当前隔离目录','action':'保存配置后重新打开',
        'expected':'预期读到 after','actual':'实际'+actual,
        'conclusion':'本次读取检查'+('通过' if status=='PASS' else '仍未完成'), 'evidence':evidence})

def goal_doc(status='已完成'):
    return PUBLIC+'# 1. 当前目标\n\n'+narrative.GOAL_MARKER+'\n\n'+ledger.serialize_goal(
        {'id':'CL-01','status':status,'object':'保存与读回'},GOAL,GQUOTES)+'\n'

def test_doc(status='PASS',actual='读回值为 after',evidence='evidence/check.json'):
    return PUBLIC+'# 1. 当前验收\n\n'+narrative.TEST_MARKER+'\n\n'+test_record(status,actual,evidence)+'\n'

@contextlib.contextmanager
def fixture():
    # Clone only the explicit source tree; no runtime leftovers or real repo history.
    with tempfile.TemporaryDirectory(prefix='apcf-repair-fixture-') as d:
        # Windows 临时目录可能采用短路径，夹具根与被测入口须使用同一真实路径
        root=(Path(d)/'project').resolve()
        from distribution_policy import copy_core
        root.mkdir()
        copy_core(SOURCE,root,install_only=True)
        control=root/'.agent-project-control'
        for name in ['testbed','runs','tmp','cache','large','downloads','distribution']:
            p=control/'runtime'/name;p.mkdir(parents=True,exist_ok=True)
            (p/'.apcf-dir.yaml').write_text('# APCF-META {"schema":1,"visibility":"private"}\nschema: 1\nvisibility: private\n')
        (control/'runtime/.apcf-dir.yaml').write_text('# APCF-META {"schema":1,"visibility":"private"}\nschema: 1\nvisibility: private\n')
        modules=['common','route_context','routing_receipt','routing_activity','audit_routes','gate_kernel','gate_enforce',
                 'gate_check','finalize_turn','state_integrity','design_contract','standards_contract','execution_session','bootstrap','sync_skills']
        loaded=[importlib.import_module(name) for name in modules]
        saved=[]
        for mod in loaded:
            for attr,value in list(vars(mod).items()):
                if isinstance(value,Path) and value.is_absolute() and value.is_relative_to(SOURCE):
                    saved.append((mod,attr,value));setattr(mod,attr,root/value.relative_to(SOURCE))
        try:
            turn=control/'iterations/IT-0001_20261009T000000+0000_fixture/turns/TR-0001_20261009T000000+0000_first'
            (turn/'evidence').mkdir(parents=True);(turn/'parallel').mkdir()
            (turn.parents[1]/'ITERATION.md').write_text(PUBLIC+'# 1. 合成目标\n\n- **Status**：ACTIVE\n')
            for file,content in [('REQUEST.md',PUBLIC+'# 1. 请求\n\n核验隔离配置的读取'),('CHECKLIST.md',goal_doc()),('TEST.md',test_doc()),
                                 ('TURN.md',PUBLIC+'# 1. 执行轮次\n\n- **Status**：IN_PROGRESS\n\n## 1.1. USER REPORT\n\n尚未收口\n')]:
                (turn/file).write_text(content)
            (root/'src').mkdir();(root/'src/value.txt').write_text('before')
            yield root,turn
        finally:
            for mod,attr,value in reversed(saved):setattr(mod,attr,value)

def make_report(turn):
    from report_contract import SECTION_TITLES,meaningful_file_lines
    sections=[
        '- **IT / TR**：IT-0001 / TR-0001\n- **Checklist 摘要**：已完成 1\n- **Test 摘要**：PASS 1',
        '此前隔离项目已有原始配置，但没有证明重复读取保持一致\n\n本轮保存新值并读回，以实际读取输出判断本次配置路径是否通过',
        '- **配置**：程序读取的输入状态，本轮通过保存和读取比较检查其持久化行为',
        '\n'.join(meaningful_file_lines(turn/'CHECKLIST.md')),
        '\n'.join(meaningful_file_lines(turn/'TEST.md')),
        '配置读回为 after，符合本次隔离输入的预期\n\n这里没有调用真实业务服务，不代表线上部署已经通过',
        '- **读回内容符合隔离输入，线上行为仍未验收**：本次只验证了配置保存和读取，真实服务还需要现场测试',
        '- **当前无需用户参与合成检查**：这里只记录工具测试结果',
        '- **真实宿主多轮输出尚未核验**：不能把函数测试写成聊天通道已被强制接管',
        '- **将同一修订送入真实宿主验收**：复核第二轮请求和实际输出，避免从单轮函数通过推断长期行为',
    ]
    return '\n\n'.join(f'## {i}. {title}\n\n{sections[i]}' for i,title in enumerate(SECTION_TITLES))

def reviewed(turn,report):
    r=prose.draft(report,turn);r['reviewer']['identity']='synthetic selfcheck author; not a real-user confirmation'
    for note in r['goals']:
        note['observation']='目标正文实际解释了旧状态风险和两次读回判据；没有把实现结果冒充原始目标'
        note['roles']={k:prose.locate(GOAL,q) for k,q in GQUOTES.items()}
    raw=b'{"observed":"after","comparison":"equal"}\n';(turn/'evidence/check.json').write_bytes(raw)
    for note in r['tests']:
        source_row=next(row for row in ledger.parse_tests((turn/'TEST.md').read_text()) if row['id']==note['id'])
        note['actual_selection']=prose.locate(source_row['_prose'],source_row['actual'])
        note['observation']='检查文件实际记录 after 和 equal，仅用于证明当前隔离读取'
        note['evidence']=[{'path':'evidence/check.json','sha256':repair_io.digest(raw),'excerpt':'"comparison":"equal"'}]
    from report_contract import split_sections
    _,s=split_sections(report);bullet=s[6][1]
    r['takeaways']=[{'sha256':repair_io.digest(bullet.encode()),'observation':'总结包含配置读回的结果，也保留线上尚未验证的限制','source_units':['E001','E002']}]
    for u in r['explanation_coverage']:
        u.update(importance='core',takeaway_indexes=[0],reason='该段是本次结果或影响判断的重要边界，必须出现在关键要点')
    r['section_observations']={str(i):'本区直接围绕隔离配置的请求、测试和未验证范围；未把工具测试扩大为真实宿主保证' for i in range(10)}
    return r

class NarrativeTests(unittest.TestCase):
    def test_roundtrip_complete_sentence(self):
        t=test_doc();self.assertEqual([],ledger.validate_text(t,goal_doc()))
        row=ledger.parse_tests(t)[0];self.assertEqual(row['evidence'],'evidence/check.json');self.assertIn('为验证',row['_prose'])
        self.assertNotIn('版本／环境／前提：',row['_prose'])
    def test_tamper_prose_rejected(self):self.assertTrue(ledger.validate_text(test_doc().replace('实际读回值为 after','实际读回值为 wrong'),goal_doc()))
    def test_missing_map_rejected(self):self.assertTrue(ledger.validate_text(test_doc().split(narrative.FACT_PREFIX)[0],goal_doc()))
    def test_wrong_unicode_offset(self):
        t=test_doc();m=json.loads(t.split(narrative.FACT_PREFIX)[1].split(' -->')[0]);m['spans']['actual']=[True,100]
        self.assertRaises(ValueError,narrative.validate_map,ledger.parse_tests(t)[0]['_prose'],m)
    def test_unknown_metadata_value_rejected(self):
        t=test_doc();m=json.loads(t.split(narrative.FACT_PREFIX)[1].split(' -->')[0]);m['actual']='a hidden richer result'
        self.assertRaises(ValueError,narrative.validate_map,ledger.parse_tests(t)[0]['_prose'],m)
    def test_duplicate_id_rejected(self):self.assertTrue(ledger.validate_text(test_doc()+test_record()+'\n',goal_doc()))
    def test_missing_cl_rejected(self):self.assertTrue(ledger.validate_text(test_doc().replace('对应 CL-01','对应 CL-02'),goal_doc()))
    def test_completed_goal_with_pending(self):self.assertTrue(ledger.validate_text(test_doc('未执行','尚未读取文件'),goal_doc()))
    def test_goal_retrospective_rejected(self):
        bad=goal_doc().replace(GOAL,'代码已经改完，测试已通过');self.assertFalse(ledger.parse_checklist(bad))
    def test_v2_still_parses(self):
        row=dict(HEAD,context='明确合成环境',action='执行输入检查',expected='结果一致',actual='实际一致',evidence='evidence/old.json')
        old=ledger.serialize_v2(row);self.assertEqual(2,ledger.parse_tests(old)[0]['format_version'])
    def test_mixed_new_marker_rejected(self):
        row=dict(HEAD,context='明确合成环境',action='执行输入检查',expected='结果一致',actual='实际一致',evidence='evidence/old.json')
        self.assertTrue(ledger.validate_text('# 1. TEST\n'+narrative.TEST_MARKER+'\n'+ledger.serialize_v2(row)))
    def test_crlf_roundtrip(self):self.assertFalse(ledger.validate_text(test_doc().replace('\n','\r\n'),goal_doc().replace('\n','\r\n')))
    def test_new_requires_causal_goals(self):self.assertTrue(ledger.validate_text(test_doc(),'- 【已完成】【CL-01】【对象】：代码已经改完，测试已通过'))
    def test_quotes_semicolons_and_emoji_preserved(self):
        record=test_record(actual='读回值为 after；附带 🙂 与中文分号');rows=ledger.parse_tests('# 1. T\n'+narrative.TEST_MARKER+'\n'+record);self.assertEqual(len(rows),1);self.assertIn('🙂',rows[0]['actual'])

class ReviewTests(unittest.TestCase):
    def test_valid_review_has_variable_takeaway_count(self):
        with fixture() as (_,tr):
            report=make_report(tr);r=reviewed(tr,report);self.assertEqual([],prose.validate(report,tr,r))
    def test_empty_semantic_booleans_do_not_suffice(self):
        with fixture() as (_,tr):
            report=make_report(tr);r=prose.draft(report,tr);r['semantic_review_completed']=True
            self.assertTrue(prose.validate(report,tr,r))
    def test_omitted_core_limitation_rejected(self):
        with fixture() as (_,tr):
            report=make_report(tr);r=reviewed(tr,report);r['explanation_coverage'][1]['takeaway_indexes']=[]
            self.assertTrue(prose.validate(report,tr,r))
    def test_title_only_provenance_rejected(self):
        with fixture() as (_,tr):
            report=make_report(tr);r=reviewed(tr,report);r['tests'][0]['evidence'][0]['excerpt']='nonexistent evidence'
            self.assertTrue(prose.validate(report,tr,r))
    def test_deleted_source_rejected(self):
        with fixture() as (_,tr):
            report=make_report(tr);r=reviewed(tr,report);(tr/'evidence/check.json').unlink();self.assertTrue(prose.validate(report,tr,r))
    def test_report_modified_review_stale(self):
        with fixture() as (_,tr):
            report=make_report(tr);r=reviewed(tr,report);self.assertTrue(prose.validate(report.replace('线上部署','全部功能'),tr,r))
    def test_forged_human_identity_rejected(self):
        with fixture() as (_,tr):
            report=make_report(tr);r=reviewed(tr,report);r['reviewer']['method']='human_confirmation';self.assertTrue(prose.validate(report,tr,r))
    def test_review_json_cannot_replace_visible_test_evidence(self):
        with fixture() as (_,tr):
            report=make_report(tr);r=reviewed(tr,report);r['tests'][0]['evidence'][0]['path']='evidence/other.json';(tr/'evidence/other.json').write_bytes((tr/'evidence/check.json').read_bytes());self.assertTrue(prose.validate(report,tr,r))
    def test_actual_report_contract_accepts_bound_review(self):
        with fixture() as (_,tr):
            report=make_report(tr);r=reviewed(tr,report);repair_io.private_json(tr/'evidence/prose-review.json',r)
            from report_contract import validate_report
            self.assertEqual([],validate_report(report,tr))
    def test_report_contract_rejects_swapped_test_or_missing_map(self):
        with fixture() as (_,tr):
            report=make_report(tr);r=reviewed(tr,report);repair_io.private_json(tr/'evidence/prose-review.json',r)
            from report_contract import validate_report
            self.assertTrue(validate_report(report.replace('实际读回值为 after','实际任意值'),tr))

class SessionTests(unittest.TestCase):
    def setup_plan(self,root,tr,request='req-1'):
        import routing_activity as a,execution_session as e
        a.init_baseline(tr);e.begin(tr,request)
        (tr/'evidence/investigation.md').write_text('已核对隔离配置的原值 before 和目标 after')
        a.record_plan(tr,['src/value.txt'],['evidence/investigation.md'],['TEST-01'])
        return a,e
    def test_no_git_real_baseline_supported(self):
        with fixture() as (root,tr):
            a,e=self.setup_plan(root,tr);self.assertEqual(a.git_head(),'NO_PROJECT_GIT');self.assertFalse((root/'.git').exists())
    def test_cannot_plan_after_business_edit(self):
        with fixture() as (root,tr):
            import routing_activity as a,execution_session as e
            a.init_baseline(tr);e.begin(tr,'req-1');(root/'src/value.txt').write_text('after')
            (tr/'evidence/investigation.md').write_text('late investigation')
            self.assertRaises(a.ActivityError,a.record_plan,tr,['src/value.txt'],['evidence/investigation.md'],['TEST-01'])
    def test_resume_keeps_same_request(self):
        with fixture() as (root,tr):
            a,e=self.setup_plan(root,tr);self.assertEqual(e.resume(tr,'req-1')['session']['request_id'],'req-1')
    def test_old_request_ticket_rejected(self):
        with fixture() as (root,tr):
            a,e=self.setup_plan(root,tr);e.authorize(tr,'req-1');self.assertRaises(ValueError,e.load,tr,'req-0')
    def test_guarded_write_succeeds(self):
        with fixture() as (root,tr):
            a,e=self.setup_plan(root,tr);e.authorize(tr,'req-1');e.apply_file(tr,'req-1','src/value.txt',b'after',repair_io.digest(b'before'));self.assertEqual((root/'src/value.txt').read_bytes(),b'after')
    def test_out_of_scope_write_rejected(self):
        with fixture() as (root,tr):
            a,e=self.setup_plan(root,tr);e.authorize(tr,'req-1');self.assertRaises(ValueError,e.apply_file,tr,'req-1','outside.txt',b'data',None)
    def test_external_edit_preserved(self):
        with fixture() as (root,tr):
            a,e=self.setup_plan(root,tr);e.authorize(tr,'req-1');(root/'src/value.txt').write_bytes(b'user edit')
            self.assertRaises(ValueError,e.apply_file,tr,'req-1','src/value.txt',b'after',repair_io.digest(b'before'));self.assertEqual((root/'src/value.txt').read_bytes(),b'user edit')
    def test_authority_drift_rejected(self):
        with fixture() as (root,tr):
            a,e=self.setup_plan(root,tr);(root/'AGENTS.md').write_text('different instructions');self.assertRaises(ValueError,e.load,tr,'req-1')
    def test_refresh_invalidates_ticket(self):
        with fixture() as (root,tr):
            a,e=self.setup_plan(root,tr);e.authorize(tr,'req-1');e.refresh(tr,'req-1','实际重新读取当前规则后刷新')
            self.assertRaises(ValueError,e.apply_file,tr,'req-1','src/value.txt',b'after',repair_io.digest(b'before'))
    def test_goal_rewrite_needs_amendment(self):
        with fixture() as (root,tr):
            a,e=self.setup_plan(root,tr);(tr/'CHECKLIST.md').write_text(goal_doc().replace('保存与读回','新目标'))
            self.assertRaises(a.ActivityError,a.record_plan,tr,['src/value.txt'],['evidence/investigation.md'],['TEST-01'])
    def test_framing_as_old_ledger_cannot_reuse_session(self):
        with fixture() as (root,tr):
            a,e=self.setup_plan(root,tr);(tr/'TEST.md').write_text('legacy')
            self.assertTrue(a.workflow_errors(tr))
    def test_output_prepared_and_exact_text_compared(self):
        with fixture() as (root,tr):
            a,e=self.setup_plan(root,tr);report=make_report(tr);r=reviewed(tr,report);repair_io.private_json(tr/'evidence/prose-review.json',r)
            (tr/'TURN.md').write_text(PUBLIC+'# 1. 当前轮次\n- **Status**：IN_PROGRESS\n\n## 1.1. USER REPORT\n\n'+report)
            out=tr/'evidence/final-response.md';receipt=e.emit(tr,'req-1',out);self.assertEqual(receipt['status'],'PREPARED_FOR_DELIVERY')
            self.assertEqual(e.emit(tr,'req-1',out,observed=True)['status'],'OBSERVED_TEXT_MATCH')
            out.write_text('全部完成，略');self.assertRaises(ValueError,e.emit,tr,'req-1',out,observed=True)

class ParallelEvidenceTests(unittest.TestCase):
    def test_current_parallel_evidence_is_neutral_and_tools_route_remains(self):
        with fixture() as (root,tr):
            import audit_routes as audit,routing_activity as activity
            pa=tr/'parallel/PA-0001_20261009T000000+0000_fixture'
            evidence=(pa/'evidence/check.json').relative_to(root).as_posix()
            main=(tr/'evidence/check.json').relative_to(root).as_posix()
            classified=audit.classify_activity(tr,activity.load_audit_contract(),
                {'changed_paths':[evidence,main],'new_parallel_units':[pa.relative_to(root).as_posix()]})
            self.assertEqual(classified['target_paths'],[])
            self.assertTrue(all(f['disposition']=='neutral' for f in classified['facts'] if f['kind']=='path-change'))
            self.assertIn('tools',classified['required_phases'])
            self.assertTrue(any(f['kind']=='parallel-agent' for f in classified['facts']))
    def test_business_historical_and_non_evidence_paths_stay_targets(self):
        with fixture() as (root,tr):
            import audit_routes as audit,routing_activity as activity
            current=tr.relative_to(root).as_posix()
            paths=['src/business.py',current+'/parallel/PA-0001_fixture/notes.md',
                current+'/parallel/not-a-pa/evidence/check.json',
                current+'/parallel/PA-0001_fixture/src/implementation.py',
                current.replace('TR-0001_','TR-0002_')+'/parallel/PA-0001_fixture/evidence/check.json']
            classified=audit.classify_activity(tr,activity.load_audit_contract(),{'changed_paths':paths})
            self.assertEqual(classified['target_paths'],sorted(paths))
    def test_parallel_evidence_does_not_invalidate_existing_plan(self):
        with fixture() as (root,tr):
            a,e=SessionTests().setup_plan(root,tr)
            previous=json.loads((tr/'evidence/workflow.json').read_text())
            session=json.loads((tr/'evidence/execution-session.json').read_text())
            p=tr/'parallel/PA-0001_fixture/evidence/check.json';p.parent.mkdir(parents=True);p.write_text('actual PA evidence')
            revised=a.record_plan(tr,['src/value.txt'],['evidence/investigation.md'],['TEST-01'])
            self.assertEqual(revised['targets'],previous['targets'])
            self.assertEqual(json.loads((tr/'evidence/execution-session.json').read_text()),session)
            self.assertEqual(json.loads((tr/'evidence/plan-revision-000001.json').read_text()),previous)
            self.assertEqual(p.read_text(),'actual PA evidence')
    def test_parallel_evidence_cannot_hide_unplanned_business_change(self):
        with fixture() as (root,tr):
            a,e=SessionTests().setup_plan(root,tr)
            p=tr/'parallel/PA-0001_fixture/evidence/check.json';p.parent.mkdir(parents=True);p.write_text('actual PA evidence')
            (root/'src/unplanned.txt').write_text('not authorized')
            changed=goal_doc().replace('保存与读回','新目标');(tr/'CHECKLIST.md').write_text(changed)
            old=json.loads((tr/'evidence/workflow.json').read_text())
            repair_io.private_json(tr/'evidence/goal-amendment.json',{'previous_digest':old['contract_digest'],
                'current_digest':a._contract_digest(tr),'reason':'明确修订测试目标，但不得补授权已经发生的未计划业务修改'})
            with self.assertRaisesRegex(a.ActivityError,'new targets changed before amendment'):
                a.record_plan(tr,['src/value.txt','src/unplanned.txt'],['evidence/investigation.md'],['TEST-01'])

class SafetyTests(unittest.TestCase):
    def test_cleanup_is_never_an_implicit_delete(self):
        import retention_guard
        self.assertRaises(SystemExit,retention_guard.deny_blanket_cleanup)
    def test_plain_evidence_reference_is_retained(self):
        import retention_guard
        with fixture() as (root,tr):
            log=root/'.agent-project-control/runtime/runs/special-log.txt';log.write_text('unique output')
            (tr/'evidence/reference.md').write_text('.agent-project-control/runtime/runs/special-log.txt')
            rows=retention_guard.inventory(root)['objects'];self.assertTrue(any(r['path'].endswith('special-log.txt') and r['status']=='RETAIN_REFERENCED' for r in rows))
    def test_private_top_level_never_copied(self):
        from distribution_policy import copy_core
        with fixture() as (root,tr):
            (root/'.agent-project-control/private-synthetic.md').write_text('<!-- APCF-META {"schema":1,"visibility":"private"} -->\nsynthetic private')
            dest=root.parent/'out';dest.mkdir();copy_core(root,dest,install_only=True)
            self.assertFalse((dest/'.agent-project-control/private-synthetic.md').exists())
    def test_unknown_control_file_not_implicitly_copied(self):
        from distribution_policy import copy_core
        with fixture() as (root,tr):
            (root/'.agent-project-control/unknown.md').write_text(PUBLIC+'unregistered')
            dest=root.parent/'out';dest.mkdir();copy_core(root,dest,install_only=True);self.assertFalse((dest/'.agent-project-control/unknown.md').exists())
    def test_source_project_facts_reset(self):
        from distribution_policy import copy_core
        with fixture() as (root,tr):
            (root/'.agent-project-control/PROJECT.md').write_text(PUBLIC+'PRIVATE CUSTOMER PROJECT 47')
            dest=root.parent/'out';dest.mkdir();copy_core(root,dest,install_only=True)
            self.assertNotIn('CUSTOMER',(dest/'.agent-project-control/PROJECT.md').read_text())
    def test_unsafe_paths_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            for raw in ('../escape','/outside','C:/windows','a/../b','a\\b'):
                self.assertRaises(ValueError,repair_io.inside,Path(d),raw)
    def test_symlink_file_rejected(self):
        if not hasattr(os,'symlink'):self.skipTest('symlink not available')
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'external').write_text('data');(p/'link').symlink_to(p/'external')
            self.assertRaises(ValueError,repair_io.inside,p,'link',must_exist=True)

class TerminologyTests(unittest.TestCase):
    def sample(self,turn):
        import terminology_review as t
        text='## 0. 精确状态头\n\n当前读取 GPU\n\n## 2. 术语表\n\n- GPU 图形处理器（Graphics Processing Unit）：用于并行计算的处理器，本例负责图形绘制\n\n## 5. 完整讲解\n\nGPU 执行本例图形绘制\n'
        from report_contract import SECTION_TITLES
        bodies={0:'当前读取 GPU',2:'- GPU 图形处理器（Graphics Processing Unit）：用于并行计算的处理器，本例负责图形绘制',5:'GPU 执行本例图形绘制'}
        text='\n\n'.join(f'## {i}. {title}\n\n{bodies.get(i, "本节没有额外缩写")}' for i,title in enumerate(SECTION_TITLES))
        report=t.extract_user_report(text)
        record=t.initial_review(report);record['schema']=2;record['review_method']='author_self_review'
        from datetime import datetime,timezone
        date=datetime.now(timezone.utc).isoformat()
        record.update(reviewer='synthetic reviewer',reviewed_at=date,audience_context='没有预先学习 GPU 的中文读者',semantic_review_completed=True)
        record['attestations']={k:True for k in t.ATTESTATIONS}
        raw='Graphics Processing Unit 是用于并行计算的处理器；本例负责图形绘制'.encode();source=turn/'evidence/terms-source.txt';source.write_bytes(raw)
        definition='用于并行计算的处理器';relevance='本例负责图形绘制'
        excerpt='- GPU 图形处理器（Graphics Processing Unit）：用于并行计算的处理器，本例负责图形绘制'
        for item in record['items']:
            for m in item['meanings']:
                m.update(meaning_id='graphics',decision='EXPLAINED',reason='正文使用这个概念，需要理解其计算角色',
                         audience_context='中文首次使用者',domain_context='本例渲染任务',current_use='绘制图形',
                         context_relevance=relevance,source_or_basis='evidence/terms-source.txt 为本例合成来源，非真实外部检索',reviewer='synthetic reviewer',reviewed_at=date,
                         name_status='VERIFIED',verified_full_name='Graphics Processing Unit',definition=definition,
                         term_kind='abbreviation',visible_explanation=prose.locate(report,excerpt),
                         source_evidence={'path':'evidence/terms-source.txt','sha256':repair_io.digest(raw),'excerpt':'Graphics Processing Unit'})
        return t,report,record
    def test_visible_and_source_bound_explanation(self):
        with fixture() as (_,tr):
            t,report,r=self.sample(tr);self.assertEqual([],t.validate(report,r,turn_dir=tr))
    def test_rich_json_cannot_hide_thin_definition(self):
        with fixture() as (_,tr):
            t,report,r=self.sample(tr);bad=report.replace('用于并行计算的处理器','略');r['report_sha256']=t.sha256_text(bad)
            self.assertTrue(t.validate(bad,r,turn_dir=tr))
    def test_nonexistent_source_rejected(self):
        with fixture() as (_,tr):
            t,report,r=self.sample(tr);(tr/'evidence/terms-source.txt').unlink();self.assertTrue(t.validate(report,r,turn_dir=tr))
    def test_acronym_unknown_not_na(self):
        with fixture() as (_,tr):
            t,report,r=self.sample(tr);m=r['items'][0]['meanings'][0];m.update(name_status='NOT_APPLICABLE',verified_full_name='',name_limit='我没有查明')
            self.assertTrue(t.validate(report,r,turn_dir=tr))
    def test_caller_cannot_claim_human(self):
        with fixture() as (_,tr):
            t,report,r=self.sample(tr);r['review_method']='human';self.assertTrue(t.validate(report,r,turn_dir=tr))


class InfrastructureTests(unittest.TestCase):
    def test_id_reservations_concurrent_and_never_reused(self):
        with fixture() as (root,tr):
            code="from common import next_id,FRAMEWORK_ROOT;print(next_id('PA',FRAMEWORK_ROOT/'iterations'))"
            env=dict(os.environ,PYTHONPATH=str(root/'.agent-project-control/scripts'))
            workers=[subprocess.Popen([sys.executable,'-B','-c',code],cwd=root,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE) for _ in range(6)]
            identifiers=[]
            for proc in workers:
                out,err=proc.communicate(timeout=20);self.assertEqual(proc.returncode,0,err);identifiers.append(out.strip())
            self.assertEqual(len(set(identifiers)),6)
            last=subprocess.check_output([sys.executable,'-B','-c',code],cwd=root,env=env).strip();self.assertNotIn(last,identifiers)
    def test_private_creation_preflights_sidecar(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'receipt.json';p.with_name(p.name+'.apcf-meta.yaml').write_text('existing')
            self.assertRaises(FileExistsError,repair_io.private_json,p,{'schema':1},create=True);self.assertFalse(p.exists())
    def test_boolean_goal_schema_rejected(self):
        m=narrative.spans_for(GOAL,GQUOTES,narrative.GOAL_FIELDS);m['schema']=True
        self.assertRaises(ValueError,narrative.validate_map,GOAL,m,narrative.GOAL_FIELDS)
    def test_glossary_scanner_ignores_fact_metadata(self):
        import terminology_review as t
        with fixture() as (_,tr):
            terms=[x['term'] for x in t.candidates(make_report(tr))]
            self.assertNotIn('FACTS',terms);self.assertNotIn('APCF',terms)
    def test_goal_retrospective_even_with_fresh_mapping(self):
        prose='代码已经改完，测试已通过'
        self.assertRaises(ValueError,narrative.serialize,{'status':'已完成','id':'CL-01','object':'事后描述'},prose,{k:prose for k in narrative.GOAL_FIELDS},goal=True)
    def test_finalized_turn_rejects_business_writes(self):
        helper=SessionTests()
        with fixture() as (root,tr):
            a,e=helper.setup_plan(root,tr);e.authorize(tr,'req-1')
            p=tr/'TURN.md';p.write_text(p.read_text().replace('IN_PROGRESS','FINALIZED'))
            self.assertRaises(ValueError,e.apply_file,tr,'req-1','src/value.txt',b'after',repair_io.digest(b'before'))
    def test_superseded_turn_cannot_resume_old_request(self):
        helper=SessionTests()
        with fixture() as (root,tr):
            a,e=helper.setup_plan(root,tr)
            second=tr.parent/'TR-0002_20261009T000001+0000_next';shutil.copytree(tr,second)
            for name in ['execution-session.json','execution-session.json.apcf-meta.yaml']:(second/'evidence'/name).unlink()
            e.begin(second,'req-2')
            self.assertRaises(ValueError,e.load,tr,'req-1');self.assertEqual(e.load(second,'req-2')['request_id'],'req-2')
    def test_actual_review_cannot_only_select_title(self):
        with fixture() as (_,tr):
            report=make_report(tr);r=reviewed(tr,report);r['tests'][0]['actual_selection']=prose.locate(ledger.parse_tests(test_doc())[0]['_prose'],'为验证配置读取的承诺')
            self.assertTrue(prose.validate(report,tr,r))
    def skill_fixture(self,root):
        remote=root.parent/'remote';remote.mkdir();subprocess.run(['git','init','-q','-b','main',str(remote)],check=True)
        for k,v in [('user.name','Synthetic Test'),('user.email','synthetic@example.invalid')]:subprocess.run(['git','-C',str(remote),'config',k,v],check=True)
        (remote/'SKILL.md').write_text('approved original')
        subprocess.run(['git','-C',str(remote),'add','SKILL.md'],check=True);subprocess.run(['git','-C',str(remote),'commit','-qm','initial'],check=True)
        old=subprocess.check_output(['git','-C',str(remote),'rev-parse','HEAD'],text=True).strip()
        cache=root/'.codex/skills';cache.mkdir(parents=True,exist_ok=True);folder=cache/'fixture'
        subprocess.run(['git','clone','-q',str(remote),str(folder)],check=True)
        (remote/'SKILL.md').write_text('approved update');subprocess.run(['git','-C',str(remote),'commit','-qam','update'],check=True)
        lockfile=root/'.agent-project-control/skills/SKILLS.lock.yaml'
        lockfile.write_text('# APCF-META {"schema":1,"visibility":"public"}\nskills:\n  - id: fixture\n    source: synthetic/repo\n    requested_ref: main\n    resolved_commit: '+old+'\n')
        return remote,cache,folder,lockfile,dict(id='fixture',source='synthetic/repo',ref='main',commit=old,mode='git')
    def test_skill_failed_download_preserves_original(self):
        import sync_skills as skills
        with fixture() as (root,tr):
            remote,cache,folder,lockfile,spec=self.skill_fixture(root);before=lockfile.read_bytes()
            with patch.object(skills.subprocess,'run',side_effect=OSError('network unavailable')):
                self.assertRaises(OSError,skills.synchronize_one,spec,cache,lockfile,update_lock=True)
            self.assertEqual((folder/'SKILL.md').read_text(),'approved original');self.assertEqual(lockfile.read_bytes(),before)
    def test_skill_lock_commit_failure_restores_original(self):
        import sync_skills as skills
        with fixture() as (root,tr):
            remote,cache,folder,lockfile,spec=self.skill_fixture(root);before=lockfile.read_bytes();run=subprocess.run
            def local_run(args,**kw):
                if args[:2]==['git','clone']:args=[*args[:-2],str(remote),args[-1]]
                return run(args,**kw)
            with patch.object(skills.subprocess,'run',side_effect=local_run),patch('repair_io.atomic',side_effect=OSError('disk write failure')):
                self.assertRaises(OSError,skills.synchronize_one,spec,cache,lockfile,update_lock=True)
            self.assertEqual((folder/'SKILL.md').read_text(),'approved original');self.assertEqual(lockfile.read_bytes(),before)
    def test_skill_success_commits_new_tree_and_lock(self):
        import sync_skills as skills
        with fixture() as (root,tr):
            remote,cache,folder,lockfile,spec=self.skill_fixture(root);run=subprocess.run
            def local_run(args,**kw):
                if args[:2]==['git','clone']:args=[*args[:-2],str(remote),args[-1]]
                return run(args,**kw)
            with patch.object(skills.subprocess,'run',side_effect=local_run):self.assertEqual(skills.synchronize_one(spec,cache,lockfile,update_lock=True),'INSTALLED')
            self.assertEqual((folder/'SKILL.md').read_text(),'approved update')
            new=subprocess.check_output(['git','-C',str(folder),'rev-parse','HEAD'],text=True).strip();self.assertIn(new,lockfile.read_text())
    def test_skill_local_changes_refuse_replacement(self):
        import sync_skills as skills
        with fixture() as (root,tr):
            remote,cache,folder,lockfile,spec=self.skill_fixture(root);(folder/'SKILL.md').write_text('user local change')
            self.assertRaises(ValueError,skills.synchronize_one,spec,cache,lockfile,update_lock=True)
            self.assertEqual((folder/'SKILL.md').read_text(),'user local change')


def main():
    suite=unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    print(json.dumps({'suite':'core-repair-r1','run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),
                      'scope':'Synthetic real-function tests; not real host/session loading or independent semantic certification'},ensure_ascii=False))
    return 0 if result.wasSuccessful() else 2
if __name__=='__main__':raise SystemExit(main())
