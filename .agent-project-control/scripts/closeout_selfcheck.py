# APCF-META {"schema":1,"visibility":"public"}
"""Exercise the live TEST parser and report contract without changing history."""
import unittest
from test_ledger import TEST_FORMAT_MARKER, parse_tests, serialize_v2, validate_text
from report_contract_selfcheck import main as check_reports

LEGACY = ('- 【PASS】【TEST-01】【对应 CL-01】【文件回读】：在【当前候选 / 隔离环境】下，'
          '执行【写入并回读】，必须观察到【字节一致】；实际观察到【字节一致】，证据为【evidence/readback.json】')
CHECKLIST = '- 【已完成】【CL-01】【文件回读】：当保存文件时，因写入成功不能证明回读一致，必须比较字节并以原值一致确认通过\n'


def document(rows, marker=True):
    return '# 1. 当前验收记录\n\n' + (TEST_FORMAT_MARKER + '\n\n' if marker else '') + '\n'.join(rows) + '\n'


class AcceptanceMigration(unittest.TestCase):
    def setUp(self):
        self.row = parse_tests(LEGACY)[0]
        self.line = serialize_v2(self.row)
        self.good = document([self.line])

    def reject(self, text, checklist=CHECKLIST):
        self.assertNotEqual(text, self.good, 'negative mutation must actually change the fixture')
        self.assertTrue(validate_text(text, checklist), text)

    def test_v1_bytes_and_v2_fields(self):
        original = LEGACY.encode('utf-8')
        self.assertFalse(validate_text(document([LEGACY], False), CHECKLIST))
        self.assertFalse(validate_text(self.good, CHECKLIST))
        old, new = parse_tests(LEGACY)[0], parse_tests(self.good)[0]
        self.assertEqual({k:v for k,v in old.items() if k != 'format_version'},
                         {k:v for k,v in new.items() if k != 'format_version'})
        self.assertEqual(original, LEGACY.encode('utf-8'))

    def test_completed_cl_requires_all_applicable_passes(self):
        for state in ['未执行', '进行中', 'FAIL', 'BLOCKED', '不适用']:
            with self.subTest(state=state):
                self.reject(self.good.replace('【PASS】', f'【{state}】'))

    def test_ids_and_cl_coverage(self):
        cases = [self.good + self.line + '\n',
                 self.good.replace('对应 CL-01', '对应 CL-99'),
                 self.good.replace('对应 CL-01', '对应 CL-01、CL-01'),
                 self.good.replace('TEST-01', 'TEST-'),
                 self.good.replace('【PASS】', '【SUCCESS】')]
        for case in cases:
            with self.subTest(case=case): self.reject(case)
        extra = CHECKLIST + CHECKLIST.replace('CL-01', 'CL-02')
        self.assertTrue(validate_text(self.good, extra), 'uncovered CL must fail')
        self.assertTrue(validate_text(self.good, CHECKLIST + CHECKLIST), 'duplicate CL must fail')

    def test_every_field_missing_or_empty(self):
        labels = ['版本／环境／前提', '操作', '预期', '实际', '证据']
        values = ['当前候选 / 隔离环境', '写入并回读', '字节一致', '字节一致', 'evidence/readback.json']
        for label, value in zip(labels, values):
            with self.subTest(label=label):
                self.reject(self.good.replace(label+'：'+value, label+'：', 1))
                self.reject(self.good.replace(label+'：', '不合法字段：', 1))

    def test_strict_marker_and_mixed_history(self):
        for marker in [TEST_FORMAT_MARKER + '\n' + TEST_FORMAT_MARKER,
                       '<!-- APCF-TEST-FORMAT v3 -->', '<!-- APCF-TEST-FORMAT v2 --> trailing',
                       '<!-- APCF-TEST-FORMAT v2 --']:
            with self.subTest(marker=marker): self.reject(self.good.replace(TEST_FORMAT_MARKER, marker))
        self.reject(document([LEGACY]))
        self.reject(document([self.line, LEGACY.replace('TEST-01', 'TEST-02')]))
        self.reject(document([self.line], False) + TEST_FORMAT_MARKER + '\n')
        self.assertFalse(validate_text(document([self.line, LEGACY.replace('TEST-01','TEST-02')], False), CHECKLIST))

    def test_escaping_and_repeated_fields(self):
        row = dict(self.row)
        row['actual'] = r'保存 C:\file；证据：是原始文本；操作：仍属实际值'
        line = serialize_v2(row)
        self.assertFalse(validate_text(document([line]), CHECKLIST))
        self.assertEqual(parse_tests(line)[0]['actual'], row['actual'])
        for bad in [self.good.replace('；实际：', r'；实际：\q', 1),
                    self.good.replace('；实际：', '；预期：重复；实际：', 1),
                    self.good.replace('；实际：', '；实际：重复；实际：', 1),
                    self.good.replace('；证据：', '；证据：重复；证据：', 1),
                    self.good.replace('；预期：', '；实际：错序；预期：', 1),
                    self.good.rstrip() + '\\\n']:
            with self.subTest(bad=bad): self.reject(bad)

    def test_multiple_dimensions_and_shared_cl(self):
        second = self.line.replace('TEST-01', 'TEST-02')
        self.assertFalse(validate_text(document([self.line, second]), CHECKLIST))
        row = dict(self.row, refs=['CL-01','CL-02'])
        self.assertFalse(validate_text(document([serialize_v2(row)]), CHECKLIST + CHECKLIST.replace('CL-01','CL-02')))

    def test_actual_report_contract_v1_v2(self):
        check_reports()

    def test_publication_allows_only_private_runtime_scaffolds(self):
        from publish_guard import RUNTIME_SCAFFOLD, _metadata_errors, _empty_state_errors
        marker = b'# APCF-META {"schema":1,"visibility":"private"}\nschema: 1\nvisibility: private\n'
        for rel in sorted(RUNTIME_SCAFFOLD):
            with self.subTest(rel=rel):
                self.assertEqual(_metadata_errors(rel, {rel: {}}, lambda _: marker), [])
                for bad in (marker.replace(b'private', b'public'), marker + b'payload: execution data\n',
                            marker + b'# private execution material\n', marker.split(b'\n', 1)[0]):
                    self.assertTrue(_metadata_errors(rel, {rel: {}}, lambda _: bad))
        private_path = '.agent-project-control/runtime/runs/actual-log.json'
        self.assertTrue(_metadata_errors(private_path, {private_path: {}}, lambda _: marker))
        import tempfile
        from pathlib import Path
        from publish_guard import OPERATIONAL_INDEXES
        with tempfile.TemporaryDirectory(prefix='runtime-publication-contract-') as temporary:
            root = Path(temporary)
            files = {'CURRENT.md': '尚未开始项目执行轮次\nLatest TR：不适用\n',
                     '.agent-project-control/framework.yaml': 'template_source: false\n'}
            files.update({base+'/INDEX.md': '# Empty operational index\n' for base in OPERATIONAL_INDEXES})
            records = {}
            for rel, body in files.items():
                path = root/rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(body, encoding='utf-8')
                records[rel] = {'file': path}
            self.assertEqual(_empty_state_errors(records), [])
            records[private_path] = {'file': None, 'bytes': 0, 'sha256': '0'*64}
            self.assertEqual(_empty_state_errors(records),
                             [private_path + ': runtime artifact is not allowed in a fresh candidate'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
