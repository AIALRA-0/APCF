# APCF-META {"schema":1,"visibility":"public"}
"""Fast installed-Core regression; full installer/fault suite is in the patch package."""
import json
import sys
import time
import unittest
from report14.contract import verify_authority,guidance,HOME
from report14.render import render,blank_model,set_body,record
from report14.validate import validate
from report14.repair import deliver
from report14.bindings import current_bytes,report_text,published_meta

class ContractChecks(unittest.TestCase):
    def test_authority(self):self.assertTrue(verify_authority())
    def test_blank(self):self.assertTrue(validate(render(blank_model())).ok)
    def test_windows(self):self.assertTrue(validate(render(blank_model(),crlf=True)).ok)
    def test_no_unknown_zero(self):self.assertNotIn('总数：0',render(blank_model()))
    def test_all_headings(self):self.assertEqual(render(blank_model()).count('\n## '),13)
    def test_missing(self):self.assertFalse(validate(render(blank_model()).replace('## 4. 执行清单','执行清单')).ok)
    def test_duplicate(self):self.assertFalse(validate(render(blank_model())+'\n## 4. 执行清单\n').ok)
    def test_wrong_heading(self):self.assertFalse(validate(render(blank_model()).replace('## 8. 结果状态','## 8. 结果')).ok)
    def test_fallback(self):self.assertTrue(validate(deliver('未完成的正文',budget_seconds=0).text).ok)
    def test_unchanged(self):
        s=render(blank_model());self.assertEqual(deliver(s).text,s)
    def test_metadata(self):
        t=render(blank_model());cur=current_bytes(t,None,kind='initial').decode('utf-8');self.assertEqual(report_text(cur),t);self.assertEqual(published_meta(cur)['kind'],'initial')
    def test_field_guidance(self):self.assertIn('失败原因',guidance(4,'失败原因')['example'])
    def test_reference_not_live(self):self.assertFalse(validate((HOME/'APPROVED-REFERENCE.md').read_text('utf-8-sig')).ok)
    def test_refs(self):
        f={'对应目标':'CL-888','实际成果':'已保留实际记录','结果判定':'原定判据尚需核对','交付情况':'当前未确认正式交付','关联记录':'CL-888','动态扩展':''}
        m=blank_model();set_body(m,8,record('RES','RES-01','当前成果',f));self.assertFalse(validate(render(m)).ok)
    def test_scalar_model_rejected(self):
        with self.assertRaises(ValueError):render({'contract_id':'wrong','sections':[]})

if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(ContractChecks)
    result=unittest.TextTestRunner(verbosity=1).run(suite)
    print(json.dumps({'suite':'report14-installed','run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'scope':'deterministic structure and repair only'}))
    raise SystemExit(0 if result.wasSuccessful() else 2)
