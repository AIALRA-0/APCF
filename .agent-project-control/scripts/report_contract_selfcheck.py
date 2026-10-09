# APCF-META {"schema":1,"visibility":"public"}
import tempfile
from pathlib import Path
from report_contract import validate_report
from common import FRAMEWORK_ROOT, dir_marker
from test_ledger import TEST_FORMAT_MARKER, parse_tests, serialize_v2

CHECKLIST = '''<!-- APCF-META {"schema":1,"visibility":"public"} -->
# 1. 当前执行清单

- 【已完成】【CL-01】【规则加载】：当新的执行轮次开始时，因旧上下文可能导致规则漂移，必须重新读取当前作用域适用规则，并以规则入口和当前范围均已核对确认通过
- 【已完成】【CL-02】【合成结果】：当本轮需要产出可验证结果时，因只执行命令不能证明结果正确，必须生成并检查合成结果，并以结果存在且内容符合判据确认通过
'''

TEST = '''<!-- APCF-META {"schema":1,"visibility":"public"} -->
# 1. 当前验收记录

- 【PASS】【TEST-001】【对应 CL-01】【规则入口存在】：在【当前候选 / 合成环境 / 规则文件可读】下，执行【读取规则入口并核对作用域】，必须观察到【规则入口存在且适用范围可确定】；实际观察到【规则入口存在且当前作用域已确定】，证据为【synthetic-rule-read】
- 【PASS】【TEST-002】【对应 CL-02】【结果文件存在】：在【当前候选 / 合成环境 / 输出目录可写】下，执行【生成并读取结果文件】，必须观察到【结果文件存在】；实际观察到【结果文件存在】，证据为【synthetic-result-file】
- 【PASS】【TEST-003】【对应 CL-02】【结果内容正确】：在【当前候选 / 合成环境 / 结果文件已生成】下，执行【比较结果内容与预期值】，必须观察到【内容与预期一致】；实际观察到【内容与预期一致】，证据为【synthetic-result-content】
'''

VALID = '''## 0. 精确状态头

- **结果状态**：合成验证通过
- **IT / TR**：IT-0001 / TR-0001
- **Checklist 摘要**：2 项已完成
- **Test 摘要**：3 个 TEST-ID 当前 PASS 3，FAIL 0，BLOCKED 0，未执行 0，不适用 0

## 1. 承上启下

上一状态已经具备可运行的合成项目和当前规则入口，但报告合同还需要验证新的单行 TEST 表单与多测试覆盖同一 Checklist 的关系。

本轮因此建立两个 Checklist 条目，并让 CL-02 同时由“结果文件存在”和“结果内容正确”两个独立 TEST 验收，从而验证一项要求可以由多个验收维度共同证明。

当前三个 TEST-ID 都已经通过，报告中的执行清单和验收记录与源文件一致，因此可以继续验证完整讲解、关键要点和后续行动结构。

## 2. 术语表

- **当前验收表单（Current Acceptance Form）**：当前 Turn 中用于证明当前候选是否满足当前 Checklist 的验收集合；每个 TEST-ID 只保留当前有效结论，不承载历史运行流水

## 3. 执行清单

- 【已完成】【CL-01】【规则加载】：当新的执行轮次开始时，因旧上下文可能导致规则漂移，必须重新读取当前作用域适用规则，并以规则入口和当前范围均已核对确认通过
- 【已完成】【CL-02】【合成结果】：当本轮需要产出可验证结果时，因只执行命令不能证明结果正确，必须生成并检查合成结果，并以结果存在且内容符合判据确认通过

## 4. 验收记录

- 【PASS】【TEST-001】【对应 CL-01】【规则入口存在】：在【当前候选 / 合成环境 / 规则文件可读】下，执行【读取规则入口并核对作用域】，必须观察到【规则入口存在且适用范围可确定】；实际观察到【规则入口存在且当前作用域已确定】，证据为【synthetic-rule-read】
- 【PASS】【TEST-002】【对应 CL-02】【结果文件存在】：在【当前候选 / 合成环境 / 输出目录可写】下，执行【生成并读取结果文件】，必须观察到【结果文件存在】；实际观察到【结果文件存在】，证据为【synthetic-result-file】
- 【PASS】【TEST-003】【对应 CL-02】【结果内容正确】：在【当前候选 / 合成环境 / 结果文件已生成】下，执行【比较结果内容与预期值】，必须观察到【内容与预期一致】；实际观察到【内容与预期一致】，证据为【synthetic-result-content】

## 5. 完整讲解

本轮验证报告十区块结构、Checklist 与 TEST 的完整展示，以及一条 Checklist 由多个独立 TEST 共同验收的映射。TEST 只记录当前候选的有效验收结论，失败过程若有长期价值应进入证据或 REG，而不是累积到当前表单。

## 6. 关键要点

- **当前 TEST 只表达本轮当前候选的有效验收结果**：验收表单与执行日志分离以后，用户可以直接看到现在是否通过，而历史调试过程不会不断堆进后续报告；需要长期保留的失败仍可通过 evidence 或 REG 追溯。
- **一个 Checklist 可以由多个 TEST 从不同失效面共同证明**：CL-02 同时检查结果是否存在和内容是否正确，因此完成状态不依赖单个弱检查，TEST 与 Checklist 的关系由验收需要决定而不是机械一一对应。

## 7. 用户需要执行

- **当前无需用户额外操作**：合成报告合同由脚本完成验证

## 8. 需要继续讨论、搜索或决策

- **当前没有需要外部决策的事项**：所有合成输入都已经在当前环境闭环

## 9. 下一步推荐

- **报告合同通过后进入真实项目验证这一结构是否保持清晰**：确定性检查能够证明格式和映射关系正确，但真实项目仍需要验证 Agent 是否会正确拆分 Checklist 与 TEST，并保持报告对用户可读。
'''

BAD_GENERIC = VALID.replace('**当前 TEST 只表达本轮当前候选的有效验收结果**', '**总结**', 1)
BAD_FLAT_NUMBER = VALID.replace('- **当前无需用户额外操作**：合成报告合同由脚本完成验证', '7.1. 当前无需用户额外操作')
BAD_CHECKLIST = VALID.replace('- 【已完成】【CL-02】【合成结果】：当本轮需要产出可验证结果时，因只执行命令不能证明结果正确，必须生成并检查合成结果，并以结果存在且内容符合判据确认通过\n', '', 1)
BAD_HANDOFF_ONE_PARAGRAPH = VALID.replace(
    '上一状态已经具备可运行的合成项目和当前规则入口，但报告合同还需要验证新的单行 TEST 表单与多测试覆盖同一 Checklist 的关系。\n\n本轮因此建立两个 Checklist 条目，并让 CL-02 同时由“结果文件存在”和“结果内容正确”两个独立 TEST 验收，从而验证一项要求可以由多个验收维度共同证明。\n\n当前三个 TEST-ID 都已经通过，报告中的执行清单和验收记录与源文件一致，因此可以继续验证完整讲解、关键要点和后续行动结构。',
    '上一状态具备合成项目，本轮验证单行 TEST 和多个验收维度，当前已经通过并可以继续。'
)


def main():
    with tempfile.TemporaryDirectory(dir=FRAMEWORK_ROOT/"runtime/testbed") as td:
        tr = Path(td)
        dir_marker(tr,"private")
        (tr / 'CHECKLIST.md').write_text(CHECKLIST, encoding='utf-8')
        (tr / 'TEST.md').write_text(TEST, encoding='utf-8')
        assert validate_report(VALID, tr) == [], validate_report(VALID, tr)
        nested = VALID.replace('## 5. 完整讲解', '## 5. 完整讲解\n\n### 5.1. 实际机制\n\n### 5.2. 证据边界')
        assert not validate_report(nested, tr), 'legitimate R20 subordinate headings must pass'
        assert validate_report(nested.replace('### 5.1.', '### 7.1.'), tr), 'wrong parent heading must fail'
        assert validate_report(nested.replace('### 5.2.', '### 5.3.'), tr), 'skipped subordinate heading must fail'
        assert validate_report(nested.replace('### 5.2.', '### 5.1.'), tr), 'duplicate subordinate heading must fail'
        assert validate_report(VALID.replace('用户可以直接看到现在是否通过','用户看到当前状态 → 再看历史'),tr), 'arrow BP must fail'
        assert validate_report(BAD_GENERIC, tr), 'generic BP title should fail'
        assert validate_report(BAD_FLAT_NUMBER, tr), 'flat 7.1 numbering should fail'
        assert validate_report(BAD_CHECKLIST, tr), 'incomplete checklist section should fail'
        assert validate_report(BAD_HANDOFF_ONE_PARAGRAPH, tr), 'handoff must use 2-4 prose paragraphs'
        bad_test=VALID.replace('- 【PASS】【TEST-003】【对应 CL-02】【结果内容正确】：在【当前候选 / 合成环境 / 结果文件已生成】下，执行【比较结果内容与预期值】，必须观察到【内容与预期一致】；实际观察到【内容与预期一致】，证据为【synthetic-result-content】\n', '', 1)
        assert validate_report(bad_test,tr), 'incomplete test section should fail'
        assert validate_report(VALID.replace('## 9. 下一步推荐','## 8. 下一步推荐'),tr), 'wrong section order should fail'
        assert validate_report(VALID.replace('- **IT / TR**：IT-0001 / TR-0001','- **编号**：none'),tr), 'missing IT/TR should fail'
        legacy_bytes = (tr/'TEST.md').read_bytes()
        current_rows = [serialize_v2(row) for row in parse_tests(TEST)]
        v2_test = '<!-- APCF-META {"schema":1,"visibility":"public"} -->\n# 1. 当前验收记录\n\n' + TEST_FORMAT_MARKER + '\n\n' + '\n'.join(current_rows) + '\n'
        v2_report = VALID
        for old, new in zip([line for line in TEST.splitlines() if line.startswith('- ')], current_rows):
            v2_report = v2_report.replace(old, new)
        (tr/'TEST.md').write_text(v2_test, encoding='utf-8')
        assert not validate_report(v2_report, tr), validate_report(v2_report, tr)
        nested_v2 = v2_report.replace('## 5. 完整讲解', '## 5. 完整讲解\n\n### 5.1. 实际机制\n\n### 5.2. 证据边界')
        assert not validate_report(nested_v2, tr), 'v2 TEST with legitimate R20 hierarchy must pass'
        marked_report = v2_report.replace('## 4. 验收记录\n\n', '## 4. 验收记录\n\n' + TEST_FORMAT_MARKER + '\n\n')
        assert not validate_report(marked_report, tr), validate_report(marked_report, tr)
        for label, bad in [
            ('missing line', v2_report.replace(current_rows[-1]+'\n', '', 1)),
            ('changed status', v2_report.replace('【PASS】【TEST-002】', '【FAIL】【TEST-002】', 1)),
            ('changed actual', v2_report.replace('；实际：内容与预期一致', '；实际：不一致', 1)),
            ('changed evidence', v2_report.replace('；证据：synthetic-result-content', '；证据：different', 1)),
            ('reordered records', v2_report.replace('\n'.join(current_rows), '\n'.join(reversed(current_rows)), 1)),
            ('additional record', v2_report.replace(current_rows[-1], current_rows[-1]+'\n'+current_rows[-1].replace('TEST-003','TEST-004'), 1)),
        ]:
            assert bad != v2_report, label + ' mutation did not run'
            assert validate_report(bad, tr), label + ' must fail'
        (tr/'TEST.md').write_bytes(legacy_bytes)
        assert not validate_report(VALID, tr), 'historical v1 must remain readable'
    print('PASS: v0.2.3 report contract structural selfcheck')


if __name__ == '__main__':
    main()
