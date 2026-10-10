# APCF-META {"schema":1,"visibility":"public"}
"""Finite supervisor control-point regressions in disposable real-file fixtures.

These tests exercise actual source reads and guarded writes; they do not certify
model comprehension, desktop interception or a tamper-proof independent reviewer.
"""
from __future__ import annotations
import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import core_repair_selfcheck as base
import supervisor as S
from repair_io import canonical, digest, private_json

@contextlib.contextmanager
def scene():
    with base.fixture() as (root,tr):
        old=(S.ROOT,S.CONTROL,S.SCRIPTS)
        S.ROOT=root;S.CONTROL=root/'.agent-project-control';S.SCRIPTS=S.CONTROL/'scripts'
        # The fixture excludes source historical instances. Use a coherent,
        # fixture-owned initial CURRENT rather than copying a dangling source TURN.
        # Dedicated cases below retain source-TURN completeness and drift checks.
        (root/'CURRENT.md').write_text(base.PUBLIC+'# 1. 当前状态\n\n- **状态**：尚未开始项目执行轮次\n- **Latest TR**：不适用\n',encoding='utf-8',newline='\n')
        base.SessionTests().setup_plan(root,tr,'req-1')
        try:
            yield root,tr
        finally:
            S.ROOT,S.CONTROL,S.SCRIPTS=old

class SupervisorTests(unittest.TestCase):
    def enter(self,root,tr,load=True):
        row=S.inspect(tr,'req-1',project=root)
        if load:S.load_rules(tr,'req-1','scope')
        return row
    def test_records_real_current_bytes(self):
        with scene() as (root,tr):
            row=self.enter(root,tr,False)
            self.assertEqual(row['facts']['files']['CURRENT.md'],digest((root/'CURRENT.md').read_bytes()))
            self.assertEqual(row['facts']['project'],str(root.resolve()))
    def prior_state(self,root,tr):
        prior=tr.parent/'TR-0000_20261009T000000+0000_previous'
        prior.mkdir()
        report=base.make_report(tr)
        (prior/'TURN.md').write_text(base.PUBLIC+'# 1. 已完成合成轮次\n\n- **Status**：FINALIZED\n\n## 1.1. USER REPORT\n\n'+report,encoding='utf-8')
        for name in ('CHECKLIST.md','TEST.md'):
            (prior/name).write_bytes((tr/name).read_bytes())
        (root/'.agent-project-control/iterations/INDEX.md').write_text(base.PUBLIC+'# 1. 合成索引\n\n'+tr.parents[1].name+'\n',encoding='utf-8')
        (root/'CURRENT.md').write_text(base.PUBLIC+'# 1. 当前状态\n\n- **Latest TR**：TR-0000\n- **Source TURN**：`'+prior.relative_to(root).as_posix()+'`\n\n## 1.1. 最新完整用户报告\n\n'+report,encoding='utf-8')
        return prior
    def test_prior_turn_bytes_are_actually_inspected(self):
        with scene() as (root,tr):
            prior=self.prior_state(root,tr)
            row=S.inspect(tr,'req-1',project=root)
            key=(prior/'TURN.md').relative_to(root).as_posix()
            self.assertEqual(row['facts']['files'][key],digest((prior/'TURN.md').read_bytes()))
    def test_dangling_current_source_turn_is_refused(self):
        with scene() as (root,tr):
            self.prior_state(root,tr)
            (root/'CURRENT.md').write_text((root/'CURRENT.md').read_text().replace('TR-0000_','TR-9876_'),encoding='utf-8')
            self.assertRaisesRegex(ValueError,'durable file missing',S.inspect,tr,'req-1',project=root)
    def test_current_report_drift_from_durable_source_is_refused(self):
        with scene() as (root,tr):
            self.prior_state(root,tr)
            S.inspect(tr,'req-1',project=root)
            f=root/'CURRENT.md';f.write_text(f.read_text().replace('配置读回为 after','配置读回为 wrong'),encoding='utf-8')
            self.assertRaisesRegex(ValueError,'differs from Source TURN',S.inspect,tr,'req-1',project=root)
    def test_wrong_project_rejected(self):
        with scene() as (root,tr):self.assertRaises(ValueError,S.inspect,tr,'req-1',project=root.parent)
    def test_unrelated_cwd_requires_explicit_project(self):
        with scene() as (_,tr):self.assertRaises(ValueError,S.inspect,tr,'req-1')
    def test_current_request_not_old_id(self):
        with scene() as (root,tr):self.assertRaises(ValueError,S.inspect,tr,'req-old',project=root)
    def test_read_before_inspect_rejected(self):
        with scene() as (_,tr):self.assertRaises(ValueError,S.load_rules,tr,'req-1','scope')
    def test_authorize_before_real_read_rejected(self):
        with scene() as (root,tr):
            self.enter(root,tr,False);self.assertRaises(ValueError,S.authorize,tr,'req-1')
    def test_two_active_objectives_refused(self):
        with scene() as (root,tr):
            other=root/'.agent-project-control/iterations/IT-9999_other/ITERATION.md';other.parent.mkdir()
            other.write_text('# Other\n- **Status**：ACTIVE\n')
            self.assertRaises(ValueError,S.inspect,tr,'req-1',project=root)
    def test_nonactive_objective_refused(self):
        with scene() as (root,tr):
            f=tr.parents[1]/'ITERATION.md';f.write_text(f.read_text().replace('ACTIVE','PAUSED'))
            self.assertRaises(ValueError,S.inspect,tr,'req-1',project=root)
    def test_current_missing_refused(self):
        with scene() as (root,tr):
            (root/'CURRENT.md').unlink();self.assertRaises((ValueError,OSError),S.inspect,tr,'req-1',project=root)
    def test_program_code_drift_invalidates_inspection(self):
        with scene() as (root,tr):
            self.enter(root,tr,False);f=S.SCRIPTS/'supervisor.py';f.write_text(f.read_text()+'\n# changed\n')
            self.assertRaises(ValueError,S._require_context,tr,'req-1')
    def test_normative_source_drift_invalidates_inspection(self):
        with scene() as (root,tr):
            self.enter(root,tr,False);f=root/'AGENTS.md';f.write_text(f.read_text()+'\nChanged\n')
            self.assertRaises(ValueError,S._require_context,tr,'req-1')
    def test_guarded_write_and_actual_file_match(self):
        with scene() as (root,tr):
            self.enter(root,tr);S.authorize(tr,'req-1')
            r=S.write_file(tr,'req-1','src/value.txt',b'after',digest(b'before'))
            self.assertEqual((root/'src/value.txt').read_bytes(),b'after')
            self.assertEqual(r['facts']['after_sha256'],digest(b'after'))
    def test_write_before_authorization_is_rejected(self):
        with scene() as (root,tr):
            self.enter(root,tr);self.assertRaises(ValueError,S.write_file,tr,'req-1','src/value.txt',b'after',digest(b'before'))
            self.assertEqual((root/'src/value.txt').read_bytes(),b'before')
    def test_outside_scope_rejected(self):
        with scene() as (root,tr):
            self.enter(root,tr);S.authorize(tr,'req-1')
            self.assertRaises(ValueError,S.write_file,tr,'req-1','src/other.txt',b'x',None)
            self.assertFalse((root/'src/other.txt').exists())
    def test_external_edit_is_not_overwritten(self):
        with scene() as (root,tr):
            self.enter(root,tr);S.authorize(tr,'req-1');(root/'src/value.txt').write_bytes(b'user')
            self.assertRaises(ValueError,S.write_file,tr,'req-1','src/value.txt',b'after',digest(b'before'))
            self.assertEqual((root/'src/value.txt').read_bytes(),b'user')
    def test_interrupt_blocks_then_recovery_requires_new_read(self):
        with scene() as (root,tr):
            self.enter(root,tr);S.interrupt(tr,'req-1','user cancelled')
            self.assertRaises(ValueError,S.authorize,tr,'req-1')
            S.inspect(tr,'req-1',project=root)
            self.assertRaises(ValueError,S.authorize,tr,'req-1')
            S.load_rules(tr,'req-1','scope');S.authorize(tr,'req-1')
    def test_receipt_removed_does_not_claim_read(self):
        with scene() as (root,tr):
            self.enter(root,tr);(tr/'evidence/routing.jsonl').unlink()
            self.assertRaises(ValueError,S.authorize,tr,'req-1')
    def test_event_chain_tamper_rejected(self):
        with scene() as (root,tr):
            self.enter(root,tr,False);f=tr/'evidence/supervision.json';j=json.loads(f.read_text());j['events'][0]['facts']['cwd']='fake';private_json(f,j)
            self.assertRaises(ValueError,S.events,tr)
    def test_fake_committed_turn_not_accepted(self):
        with scene() as (_,tr):self.assertRaises((ValueError,OSError,RuntimeError),S._committed,tr)
    def test_read_phase_requires_real_registered_route(self):
        with scene() as (root,tr):
            self.enter(root,tr,False);self.assertRaises(ValueError,S.load_rules,tr,'req-1','fictional')
    def test_status_reports_unobserved_not_pass(self):
        with scene() as (root,tr):
            self.enter(root,tr,False);before=(tr/'evidence/supervision.json').read_bytes()
            status=S.status(tr,'req-1');self.assertEqual(status['checks']['captured_output']['result'],'NOT_OBSERVED')
            self.assertEqual(status['checks']['committed_turn']['result'],'NOT_VERIFIED')
            self.assertEqual((tr/'evidence/supervision.json').read_bytes(),before)
    def test_unwrapped_write_is_explicitly_not_intercepted(self):
        with scene() as (root,tr):
            self.enter(root,tr,False);(root/'src/value.txt').write_bytes(b'unwrapped shell can write')
            self.assertEqual(S.LIMITS['unwrapped_tools'],'NOT_INTERCEPTED')
            self.assertEqual((root/'src/value.txt').read_bytes(),b'unwrapped shell can write')
    def test_begin_inside_parent_git_is_rejected_by_inspection(self):
        with scene() as (root,tr):
            # This test initializes only its private temporary parent.
            subprocess.run(['git','init','-q',str(root.parent)],check=True)
            self.assertRaises(ValueError,S.inspect,tr,'req-1',project=root)
    def test_existing_empty_target_directory_not_replaced(self):
        with scene() as (root,tr):
            import bootstrap
            target=root.parent/'empty-target';target.mkdir();before=target.stat().st_ino
            result=bootstrap.install_clean_shell(str(target))
            self.assertEqual(result,target);self.assertEqual(target.stat().st_ino,before)
            self.assertTrue((target/'AGENTS.md').is_file())


    def test_git_probe_failure_is_not_no_repository(self):
        with scene() as (root,tr):
            failed=subprocess.CompletedProcess(['git'],128,'','fatal: Filename too long')
            with patch.object(S.subprocess,'run',return_value=failed):
                self.assertRaisesRegex(ValueError,'cannot verify Git ownership',S.inspect,tr,'req-1',project=root)
            self.assertFalse((tr/'evidence/supervision.json').exists())
    def test_git_failure_with_existing_parent_is_rejected_without_writes(self):
        with scene() as (root,tr):
            git_dir=root.parent/'.git';git_dir.mkdir();(git_dir/'HEAD').write_bytes(b'ref: refs/heads/test\n')
            before={p.relative_to(git_dir).as_posix():p.read_bytes() for p in git_dir.rglob('*') if p.is_file()}
            failed=subprocess.CompletedProcess(['git'],128,'','fatal: not a git repository')
            with patch.object(S.subprocess,'run',return_value=failed):
                self.assertRaisesRegex(ValueError,'cannot verify Git ownership',S.inspect,tr,'req-1',project=root)
            self.assertEqual(before,{p.relative_to(git_dir).as_posix():p.read_bytes() for p in git_dir.rglob('*') if p.is_file()})
            self.assertEqual((root/'src/value.txt').read_bytes(),b'before')
    def failed_new_turn(self,root,fail):
        import new_turn
        with patch.object(new_turn,'FRAMEWORK_ROOT',root/'.agent-project-control'),patch.object(new_turn,'enforce_entrypoint',side_effect=fail),patch.object(sys,'argv',['new_turn.py','--title','rollback case','--request-text','真实失败回滚夹具请求']):
            self.assertRaises((RuntimeError,SystemExit),new_turn._main)
    def test_failed_new_turn_restores_previous_session_bytes(self):
        with scene() as (root,tr):
            pointer=root/'.agent-project-control/runtime/runs/current-session.json';meta=pointer.with_name(pointer.name+'.apcf-meta.yaml')
            before=(pointer.read_bytes(),meta.read_bytes());turns=set(tr.parent.iterdir())
            self.failed_new_turn(root,RuntimeError('bootstrap failed'))
            self.assertEqual((pointer.read_bytes(),meta.read_bytes()),before)
            self.assertEqual(set(tr.parent.iterdir()),turns)
            import execution_session as session
            self.assertEqual(session.load(tr,'req-1')['request_id'],'req-1')
    def test_failed_first_turn_removes_only_its_session_pointer(self):
        with scene() as (root,tr):
            pointer=root/'.agent-project-control/runtime/runs/current-session.json';meta=pointer.with_name(pointer.name+'.apcf-meta.yaml')
            pointer.unlink();meta.unlink();turns=set(tr.parent.iterdir())
            self.failed_new_turn(root,RuntimeError('bootstrap failed'))
            self.assertFalse(pointer.exists());self.assertFalse(meta.exists())
            self.assertEqual(set(tr.parent.iterdir()),turns)
    def test_failed_turn_preserves_superseding_session_pointer(self):
        with scene() as (root,tr):
            pointer=root/'.agent-project-control/runtime/runs/current-session.json';meta=pointer.with_name(pointer.name+'.apcf-meta.yaml')
            other={'schema':1,'request_id':'another-owner','turn':tr.relative_to(root).as_posix(),'project_root':str(root)}
            observed={}
            def fail(**kwargs):
                private_json(pointer,other);observed.update(pointer=pointer.read_bytes(),meta=meta.read_bytes())
                raise RuntimeError('bootstrap failed after supersession')
            self.failed_new_turn(root,fail)
            self.assertEqual(pointer.read_bytes(),observed['pointer']);self.assertEqual(meta.read_bytes(),observed['meta'])

if __name__=='__main__':unittest.main(verbosity=2)
