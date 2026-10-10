# APCF-META {"schema":1,"visibility":"public"}
"""Finite regression cases derived from observed failures; not model-quality certification."""
from __future__ import annotations
import contextlib,copy,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import writing_guard as G
import core_repair_selfcheck as OLD
from repair_io import private_json,digest

TITLE='交付门禁（Gate）'
DEFINITION='在交付前检查当前证据和验收是否满足要求的步骤'
ROLE='本例用于区分检查通过与状态已保存'
ANALOGY='直观来说，它像出厂前的检验关卡，不负责代替实际归档'
TERM=f'- **{TITLE}**：{DEFINITION}；{ROLE}；{ANALOGY}'
CITITLE='CI 持续集成（Continuous Integration）'
CIDEF='经常集成代码并自动运行已配置检查的开发实践'
CIROLE='本例只检查同一提交的已配置测试'
CIANALOGY='直观来说，它像每次更新后运行的检验流水线，不是所有功能正确的保证'
CITERM=f'- **{CITITLE}**：{CIDEF}；{CIROLE}；{CIANALOGY}'

def small(terms=TERM,opening='本例需要检查当前交付条件',body='本例没有实际发布'):
    return f'## 0. 精确状态头\n\n- 当前目标：`IT-0001`\n\n## 1. 承上启下\n\n{opening}\n\n## 2. 术语表\n\n{terms}\n\n## 5. 完整讲解\n\n{body}\n'

def review(terms='Gate'):
    if terms=='Gate':name,zh,full,kind,dd,rr,aa=TITLE,'交付门禁','Gate','proper_name',DEFINITION,ROLE,ANALOGY
    else:name,zh,full,kind,dd,rr,aa=CITITLE,'持续集成','Continuous Integration','abbreviation',CIDEF,CIROLE,CIANALOGY
    return {'items':[{'term':terms,'meanings':[{'display_name':name,'chinese_name':zh,'verified_full_name':full,'term_kind':kind,'name_status':'VERIFIED','decision':'EXPLAINED','definition':dd,'context_relevance':rr,'analogy':aa,'analogy_basis':'类比只对应放行前的检查关系，不把检查等同于保存或全部业务正确'}]}],'manual_terms':[]}

@contextlib.contextmanager
def fixture():
    with OLD.fixture() as (root,tr):
        with patch.object(G,'ROOT',root),patch.object(G,'CONTROL',root/'.agent-project-control'):
            import routing_activity as A,execution_session as E
            A.init_baseline(tr);E.begin(tr,'writer-fixture');G.bind(tr)
            yield root,tr

def prepare(tr,target,phase):
    import io
    with contextlib.redirect_stdout(io.StringIO()) as output:
        row=G.prepare(tr,target,phase)
    assert 'W05' in output.getvalue() and '- **交付门禁（Gate）**' in output.getvalue()
    return row

class FlatGlossary(unittest.TestCase):
    def test_single_bp_is_valid(self):self.assertEqual(G.glossary(small())[1],[])
    def test_original_indented_example_rejected(self):
        text='本轮需要区分交付前检查与正式收口两个动作：\n\n  '+TERM+'\n\n  - 正式收口（Finalize）：保存报告'
        self.assertTrue(G.glossary(small(text))[1])
    def test_nested_without_intro_rejected(self):self.assertTrue(G.glossary(small('  '+TERM))[1])
    def test_tab_indentation_rejected(self):self.assertTrue(G.glossary(small('\t'+TERM))[1])
    def test_bare_list_not_bp(self):self.assertTrue(G.glossary(small('- CI：持续集成，自动测试'))[1])
    def test_combined_identifiers_rejected(self):self.assertTrue(G.glossary(small('- **IT / TR**：同类记录'))[1])
    def test_combined_gate_finalize_rejected(self):self.assertTrue(G.glossary(small('- **Gate／Finalize**：检查和保存'))[1])
    def test_parent_item_rejected(self):self.assertTrue(G.glossary(small('- **工作流程**：本轮说明\n  '+TERM))[1])
    def test_table_rejected(self):self.assertTrue(G.glossary(small('| Gate | 检查 |'))[1])
    def test_fenced_output_is_not_a_glossary(self):self.assertTrue(G.glossary(small('```markdown\n'+TERM+'\n```'))[1])
    def test_duplicate_rejected(self):self.assertTrue(G.glossary(small(TERM+'\n'+TERM))[1])
    def test_separate_objects_valid(self):self.assertEqual(G.glossary(small(TERM+'\n'+CITERM))[1],[])
    def test_crlf_bom_same(self):self.assertEqual(G.glossary('\ufeff'+small().replace('\n','\r\n'))[1],[])
    def test_placeholder_refused(self):self.assertTrue(G.glossary(small(f'- **{TITLE}**：略'))[1])
    def test_mini_fields_refused(self):self.assertTrue(G.glossary(small(f'- **{TITLE}**：定义：检查；用途：测试'))[1])

class NamesAndMeaning(unittest.TestCase):
    def test_real_name_and_visible_content(self):self.assertEqual(G.content_errors(small(),review()),[])
    def test_ci_canonical_order(self):self.assertEqual(G.content_errors(small(CITERM),review('CI')),[])
    def test_missing_full_name(self):
        r=review('CI');r['items'][0]['meanings'][0]['display_name']='CI 持续集成'
        self.assertTrue(G.content_errors(small(CITERM.replace(CITITLE,'CI 持续集成')),r))
    def test_wrong_name_order(self):
        r=review('CI');r['items'][0]['meanings'][0]['display_name']='CI（Continuous Integration，持续集成）'
        self.assertTrue(G.content_errors(small(CITERM.replace(CITITLE,r['items'][0]['meanings'][0]['display_name'])),r))
    def test_titlecase_english_not_silently_missed(self):self.assertTrue(G.content_errors(small(body='本次 Pilot 还没有运行'),review()))
    def test_inline_code_not_a_blanket_concept_exemption(self):self.assertTrue(G.content_errors(small(opening='先用 `Gate` 检查'),review()))
    def test_early_acronym_without_expansion(self):self.assertTrue(G.content_errors(small(CITERM,opening='先运行 CI'),review('CI')))
    def test_early_expansion_then_short_alias_is_valid(self):self.assertEqual(G.content_errors(small(CITERM,opening=CITITLE+'将核对代码',body='后续 CI 使用同一概念'),review('CI')),[])
    def test_unknown_title_not_reviewed(self):self.assertTrue(G.content_errors(small(TERM+'\n'+CITERM),review()))
    def test_hidden_rich_definition_cannot_replace_thin_body(self):self.assertTrue(G.content_errors(small(TERM.replace(DEFINITION,'略')),review()))
    def test_analogy_must_be_visible(self):self.assertTrue(G.content_errors(small(TERM.replace(ANALOGY,'')),review()))
    def test_analogy_word_alone_not_a_review(self):
        r=review();r['items'][0]['meanings'][0]['analogy_basis']=''
        self.assertTrue(G.content_errors(small(),r))
    def test_unknown_is_not_not_applicable(self):
        r=review('CI');r['items'][0]['meanings'][0]['name_status']='NOT_APPLICABLE'
        self.assertTrue(G.content_errors(small(CITERM),r))
    def test_internal_id_without_invented_full_name(self):
        r=review();m=r['items'][0]['meanings'][0];r['items'][0]['term']='IT';m.update(display_name='IT 迭代单元',chinese_name='迭代单元',verified_full_name='',term_kind='internal_identifier',name_status='UNVERIFIED',name_limit='当前没有确认英文全称')
        body=f"- **IT 迭代单元**：{DEFINITION}；{ROLE}；当前没有确认英文全称；{ANALOGY}"
        self.assertEqual(G.content_errors(small(body),r),[])
    def test_protected_code_source_does_not_need_translation(self):self.assertEqual(G.content_errors(small(body='```python\nfrom SomeLibrary import thing\n```'),review()),[])
    def test_compact_state_fields_not_forced_dictionary(self):self.assertEqual(G.content_errors(small().replace('- 当前目标','- CI／API／IT／TR 状态\n- 当前目标'),review()),[])
    def test_source_links_not_unknown_words(self):self.assertEqual(G.content_errors(small(body='查看[来源](https://example.invalid/whatever)'),review()),[])

class ReproducedRegression(unittest.TestCase):
    def test_no_space_titlecase_token_detected(self):
        self.assertTrue(G.content_errors(small(body='本次Pilot没有运行'),review()))
    def test_no_space_first_abbreviation_detected(self):
        self.assertTrue(G.content_errors(small(CITERM,opening='本次CI会检查'),review('CI')))
    def test_exact_reported_termlist_is_rejected(self):
        bad="- APCF 智能体项目控制框架（Agent Project Control Framework）：规则与记录机制\n- IT / TR：本地编号\n- Core：核心发行包\n- Writing / Style / Design：正式规则\n- 派生索引：精简集合\n- Pilot：现有完整回归链\n- CI：持续集成，即远端自动检查\n- SHA-256：文件字节摘要\n- Gate：收口门禁"
        entries,errors=G.glossary(small(bad));self.assertFalse(entries);self.assertEqual(len(errors),9)
    def test_booleans_without_real_visible_review_rejected(self):
        r=review();r['items'][0]['meanings'][0].update(analogy='',analogy_basis='')
        r['semantic_review_completed']=True;r['attestations']={'everything':True}
        self.assertTrue(G.content_errors(small(),r))
    def test_single_official_slash_acronym_not_merged_objects(self):
        r=review('CI');r['items'][0]['term']='I/O';m=r['items'][0]['meanings'][0]
        m.update(display_name='I/O 输入输出（Input/Output）',chinese_name='输入输出',verified_full_name='Input/Output')
        self.assertEqual(G.content_errors(small(CITERM.replace(CITITLE,m['display_name'])),r),[])

class ExemptionBoundaries(unittest.TestCase):
    def test_fake_literal_does_not_hide_prose(self):
        r=review();r['items'].append({'term':'Pilot','meanings':[{'decision':'LITERAL_FORMAT','reason':'称为机器字段'}]})
        self.assertTrue(G.content_errors(small(body='Pilot未运行'),r))
    def test_fake_out_of_scope_does_not_hide_prose(self):
        r=review();r['items'].append({'term':'Pilot','meanings':[{'decision':'OUT_OF_SCOPE','reason':'称为旁支概念'}]})
        self.assertTrue(G.content_errors(small(body='Pilot未运行'),r))
    def test_known_reader_still_needs_name(self):
        r=review();r['items'].append({'term':'CI','meanings':[{'decision':'KNOWN_TO_AUDIENCE','reason':'用户已经熟悉','term_kind':'abbreviation','name_status':'VERIFIED','chinese_name':'持续集成','verified_full_name':'Continuous Integration'}]})
        self.assertTrue(G.content_errors(small(body='CI将检查提交'),r))
    def test_known_reader_inline_full_name_can_skip_long_glossary(self):
        r=review();r['items'].append({'term':'CI','meanings':[{'decision':'KNOWN_TO_AUDIENCE','reason':'用户已经熟悉','term_kind':'abbreviation','name_status':'VERIFIED','chinese_name':'持续集成','verified_full_name':'Continuous Integration'}]})
        self.assertEqual(G.content_errors(small(body=CITITLE+'将检查提交'),r),[])
    def test_actual_protected_source_remains_exempt(self):
        r=review();r['items'].append({'term':'Pilot','meanings':[{'decision':'LITERAL_FORMAT','reason':'实际原文位于受保护代码块'}]})
        self.assertEqual(G.content_errors(small(body='```text\nPilot failed\n```'),r),[])

class ReaderTransport(unittest.TestCase):
    def mapping(self):
        return '<!-- APCF-GOAL '+json.dumps({'schema':1,'sha256':'1'*64,'spans':{'context':[0,1]}})+' -->'
    def test_only_transport_comments_removed(self):
        inp=TERM+'\n'+self.mapping()+'\n'+CITERM
        self.assertEqual(G.reader_view(inp),TERM+'\n'+CITERM+'\n')
    def test_quoted_machine_source_remains(self):
        x='```text\n'+self.mapping()+'\n```';self.assertEqual(G.reader_view(x),x+'\n')
    def test_other_comments_not_deleted(self):self.assertEqual(G.reader_view('<!-- keep -->'), '<!-- keep -->\n')
    def test_inline_metadata_refused(self):self.assertRaises(ValueError,G.reader_view,TERM+' '+self.mapping())
    def test_malformed_mapping_refused(self):self.assertRaises(ValueError,G.reader_view,'<!-- APCF-GOAL {} -->')
    def test_unknown_mapping_refused(self):self.assertRaises(ValueError,G.reader_view,'<!-- APCF-OTHER {} -->')
    def test_reader_view_idempotent(self):
        x=G.reader_view(TERM+'\n'+self.mapping());self.assertEqual(G.reader_view(x),x)

class SessionBoundWriting(unittest.TestCase):
    def test_bound_session_present(self):
        with fixture() as (_,tr):self.assertTrue(G.enabled(tr))
    def test_missing_reading_blocks(self):
        with fixture() as (root,tr):self.assertTrue(G.context_errors(tr,(tr/'TURN.md').relative_to(root).as_posix()))
    def test_draft_and_review_are_distinct(self):
        with fixture() as (root,tr):
            rel=(tr/'TURN.md').relative_to(root).as_posix();prepare(tr,rel,'draft');self.assertTrue(G.context_errors(tr,rel))
    def test_current_reads_pass(self):
        with fixture() as (root,tr):
            rel=(tr/'TURN.md').relative_to(root).as_posix();prepare(tr,rel,'draft');prepare(tr,rel,'review');self.assertEqual(G.context_errors(tr,rel),[])
    def test_candidate_change_expires_review(self):
        with fixture() as (root,tr):
            rel=(tr/'TURN.md').relative_to(root).as_posix();prepare(tr,rel,'draft');prepare(tr,rel,'review');(tr/'TURN.md').write_text('changed');self.assertTrue(G.context_errors(tr,rel))
    def test_resume_nonce_requires_reading_again(self):
        with fixture() as (root,tr):
            import execution_session as E
            rel=(tr/'TURN.md').relative_to(root).as_posix();prepare(tr,rel,'draft');prepare(tr,rel,'review');E.refresh(tr,'writer-fixture','实际恢复后重读');self.assertTrue(G.context_errors(tr,rel))
    def test_card_changes_block_old_policy(self):
        with fixture() as (root,tr):
            p=root/G.CARD;p.write_text('changed');self.assertRaises(ValueError,G.policy)
    def test_existing_frozen_legacy_not_rewritten(self):
        with tempfile.TemporaryDirectory() as d:self.assertFalse(G.enabled(Path(d)))
    def test_invalid_new_contract_cannot_be_legacy(self):
        with fixture() as (_,tr):
            p=tr/'evidence/execution-session.json';r=json.loads(p.read_text(encoding='utf-8-sig'));r['writing_contract']='unknown';private_json(p,r)
            self.assertRaises(ValueError,G.enabled,tr)
    def test_controlled_document_write_needs_preparation(self):
        with fixture() as (root,tr):
            p=root/'src/note.md';p.write_text('before')
            self.assertRaises((ValueError,FileNotFoundError),G.before_write,tr,'src/note.md',b'before')
            prepare(tr,'src/note.md','draft');G.before_write(tr,'src/note.md',b'before')
    def test_changed_document_blocks_stale_preparation(self):
        with fixture() as (root,tr):
            p=root/'src/note.md';p.write_text('before');prepare(tr,'src/note.md','draft')
            self.assertRaises(ValueError,G.before_write,tr,'src/note.md',b'external change')
    def test_machine_data_does_not_need_writing_reading(self):
        with fixture() as (_,tr):G.before_write(tr,'src/data.json',b'{}')
    def test_new_session_does_not_reuse_previous_reads(self):
        with fixture() as (root,tr):
            import execution_session as E
            rel=(tr/'TURN.md').relative_to(root).as_posix();prepare(tr,rel,'draft');prepare(tr,rel,'review')
            pointer=root/'.agent-project-control/runtime/runs/current-session.json';v=json.loads(pointer.read_text(encoding='utf-8-sig'));v['request_id']='another';private_json(pointer,v)
            self.assertTrue(G.context_errors(tr,rel))


class DocumentedCheckCLI(unittest.TestCase):
    def report(self):
        from report_contract import SECTION_TITLES
        bodies={0:'- current: `IT-0001`',1:'本例说明当前检查',2:TERM}
        return '\n\n'.join('## '+str(i)+'. '+title+'\n\n'+bodies.get(i,'当前没有其他事项') for i,title in enumerate(SECTION_TITLES))+'\n'

    def invoke(self,text):
        import io
        with tempfile.TemporaryDirectory() as d:
            report=Path(d)/'TURN.md';record=Path(d)/'review.json'
            report.write_text(text,encoding='utf-8');record.write_text(json.dumps(review()),encoding='utf-8')
            args=['writing_guard.py','check','--report',str(report),'--review',str(record)]
            with patch.object(sys,'argv',args),contextlib.redirect_stdout(io.StringIO()) as output:
                code=G.main()
            return code,output.getvalue()

    def test_documented_turn_wrapper_uses_only_user_report(self):
        text='# 1. TR-0001\n\n- **Status**：IN_PROGRESS\n- **Started**：20261010\n\n## 1.1. USER REPORT\n\n'+self.report()
        code,output=self.invoke(text)
        self.assertEqual(code,0,output);self.assertNotIn('Status',output)

    def test_standalone_report_still_passes(self):
        code,output=self.invoke(self.report());self.assertEqual(code,0,output)

    def test_duplicate_report_marker_is_rejected(self):
        code,output=self.invoke('## 1.1. USER REPORT\n'+self.report()+'\n## 1.1. USER REPORT\n'+self.report())
        self.assertEqual(code,2);self.assertIn('exactly one',output)

    def test_visible_nested_term_is_not_hidden_by_wrapper(self):
        text='## 1.1. USER REPORT\n'+self.report().replace(TERM,'  '+TERM)
        code,output=self.invoke(text);self.assertEqual(code,2);self.assertIn('二次缩进',output)

def main():
    tests=unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]);r=unittest.TextTestRunner(verbosity=2).run(tests)
    print(json.dumps({'suite':'writing-reliability-1','run':r.testsRun,'failures':len(r.failures),'errors':len(r.errors),'skipped':len(r.skipped),'scope':'synthetic deterministic checks and bound sources; real model/Windows/release not implied'},ensure_ascii=False))
    return 0 if r.wasSuccessful() else 2
if __name__=='__main__':raise SystemExit(main())
