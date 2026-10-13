# APCF-META {"schema":1,"visibility":"public"}
"""Finite synthetic regressions for the native report-quality boundary."""
from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import re
from pathlib import Path
import sys
import unittest
import uuid
from unittest.mock import patch


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import core_repair_selfcheck as core
import execution_session
from repair_io import private_json
from report14.bindings import TURN_MARKER
from report_bridge import native
from report_bridge.binding import assert_same_authority
from report_bridge.contract import ContractError, digest, validate
from report_bridge.ports import emit as emit_summary
from report_bridge.quality import assess
from report_bridge.render import chat_digest, render
from report_bridge.repair import apply_patch
from report_bridge.repair_packet import build_packet, hash_value


CASE_RESULTS: list[dict[str, str]] = []


def _case(test: unittest.TestCase, name: str, actual, expected) -> None:
    passed = actual == expected
    CASE_RESULTS.append({"case": name, "result": "PASS" if passed else "FAIL"})
    test.assertEqual(actual, expected, name)


def _reject(test: unittest.TestCase, name: str, action, expected: str,
            error_type=ValueError) -> None:
    observed = "NO_ERROR"
    try:
        action()
    except error_type as exc:
        observed = str(exc)
    except Exception as exc:  # an unexpected failure is not an expected rejection
        observed = "UNEXPECTED_" + type(exc).__name__ + ":" + str(exc)
    passed = expected in observed
    CASE_RESULTS.append({"case": name, "result": "PASS" if passed else "FAIL"})
    test.assertTrue(passed, f"{name}: expected {expected!r}, observed {observed!r}")


class NativeHost:
    def __init__(self, root: Path, turn: Path, request_id: str):
        self.root = root
        self.turn = turn
        self.request_id = request_id

    def capture(self, revision: int = 1):
        return native.capture(self.root, self.turn, self.request_id, revision=revision)

    def writer(self, snapshot):
        return native.NativeReportWriter(self.root, self.turn, self.request_id, snapshot)

    def add_plan(self, target_preimages=None, name="plan-revision-000001.json") -> Path:
        path = self.turn / "evidence" / name
        row = {"target_preimages": target_preimages or [], "fixture_marker": "before"}
        path.write_text(json.dumps(row, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        return path


@contextlib.contextmanager
def native_host(*, pending=False, objective=None, request_text=None):
    """Build a disposable native Turn through the existing Core fixture."""
    baseline_root = execution_session.ROOT
    baseline_control = execution_session.CONTROL
    baseline_authority = execution_session.authority
    with core.fixture() as (root, turn):
        if objective is not None:
            iteration = turn.parents[1] / "ITERATION.md"
            source = iteration.read_text(encoding="utf-8-sig").rstrip()
            iteration.write_bytes((source + "\n\n- **Objective**：" + objective + "\n").encode("utf-8"))
        if pending:
            (turn / "CHECKLIST.md").write_text(core.goal_doc("进行中"), encoding="utf-8")
        if request_text is not None:
            (turn / "REQUEST.md").write_bytes(request_text.encode("utf-8"))
        evidence = turn / "evidence" / "check.json"
        evidence.write_bytes(b'{"fixture":"synthetic native evidence"}\n')
        if (turn / "TURN.md").read_text(encoding="utf-8").count(TURN_MARKER) != 1:
            raise AssertionError("fixture Turn must expose exactly one report slot")
        request_id = "report-quality-selfcheck-" + uuid.uuid4().hex
        execution_session.begin(turn, request_id)
        yield NativeHost(root, turn, request_id)
    if (execution_session.ROOT != baseline_root or execution_session.CONTROL != baseline_control
            or execution_session.authority is not baseline_authority):
        raise AssertionError("fixture did not restore execution-session authority")


def save(host: NativeHost, snapshot):
    writer = host.writer(snapshot)
    markdown = render(snapshot)
    receipt = writer.save_report(
        markdown=markdown,
        snapshot=snapshot,
        expected_source_digest=snapshot["source_digest"],
        report_digest=digest(snapshot),
        quality="unreviewed",
    )
    return writer, receipt


def _transport(host: NativeHost, sink):
    from report14.runtime import transport
    return transport(host.root, host.turn, None, sink, request_id=host.request_id)


def _write_capture(host: NativeHost, path: Path, text: str, binding: dict) -> None:
    path.write_text(text, encoding="utf-8")
    captured = {key: copy.deepcopy(binding[key]) for key in (
        "request_id", "identity", "revision", "source_digest", "report_digest", "chat_sha256"
    )}
    captured.update(stage="captured", surface="chat_summary", host_event_id="synthetic-fixture-capture")
    private_json(path.with_name(path.name + ".binding.json"), captured, create=True)


def _gate_content_findings(turn: Path, targets: list[str]) -> list[dict]:
    import gate_check
    with (patch.object(gate_check, "content_review_errors", return_value=[]),
          patch("route_context.matching_capabilities", return_value=({"writing"}, [])),
          patch("route_context.capability_closure", return_value=["writing"]),
          patch("standards_contract.validate", return_value=[])):
        return gate_check._content_findings(turn, targets)


def _write_private_plan_chain(turn: Path, target: str, target_sha256: str, count: int = 2) -> None:
    from repair_io import private_json
    from routing_activity import load_audit_contract, load_baseline
    baseline = load_baseline(turn, load_audit_contract())
    turn_rel = turn.relative_to(core.SOURCE).as_posix() if turn.is_relative_to(core.SOURCE) else None
    if turn_rel is None:
        import common
        turn_rel = turn.relative_to(common.ROOT).as_posix()
    latest = None
    for sequence in range(1, count + 1):
        row = {
            "schema": 1,
            "turn": turn_rel,
            "request_sha256": baseline["request_sha256"],
            "sequence": sequence,
            "target_preimages": [{"path": target, "state": "file", "sha256": target_sha256}],
        }
        private_json(turn / "evidence" / f"plan-revision-{sequence:06d}.json", row, create=True)
        latest = row
    if latest is None:
        raise AssertionError("fixture plan chain needs at least one revision")
    private_json(turn / "evidence" / "workflow.json", latest, create=True)


class ReportQualitySelfcheck(unittest.TestCase):
    def test_native_capture_binds_mixed_case_registry_keys_to_verified_definitions(self):
        objective = "SOURCE_OBJECTIVE_BINDING_FOR_NATIVE_HEADER"
        with native_host(objective=objective) as host:
            registry_path = host.root / ".agent-project-control/reporting/quality/term-registry.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8-sig"))
            entries = registry["entries"]
            source_keys = ("Windows", "Python", "Node.js", "Codex")
            supplied_keys = ("wINDOWS", "pYtHoN", "nOdE.Js", "cOdEx")
            terms = [
                {
                    "registry_key": supplied,
                    "abbreviation": source_key,
                    "english": "POLLUTED_ENGLISH_" + source_key,
                    "chinese": "污染定义_" + source_key,
                    "kind": "abbreviation",
                    "description": "合成术语输入",
                }
                for source_key, supplied in zip(source_keys, supplied_keys)
            ]
            baseline = host.capture()
            draft = copy.deepcopy(baseline)
            result_fields = {
                "对应目标": "CL-01 保存与读回",
                "实际成果": "AUTHORIZED_RES_SUMMARY_FROM_ALLOWED_SECTION",
                "结果判定": "合成检查通过",
                "交付情况": "仅用于确定性摘要绑定验收",
                "关联记录": "CL-01",
                "动态扩展": "",
            }
            def long_limit_value(prefix, suffix):
                return prefix + "；" + ("本项仍须结合原始证据逐项核对。" * 48) + "；" + suffix

            limit_records = [
                {
                    "id": "LIM-01", "title": "LIM-01 真实阻塞：尚待实际主机观察确认", "fields": {
                        "当前限制": long_limit_value("LIM01_CURRENT_DETAIL", "UNIQUE_CURRENT_BLOCKER_END"),
                        "实际影响": long_limit_value("LIM01_IMPACT_DETAIL", "UNIQUE_CURRENT_IMPACT_END"),
                        "解除条件": long_limit_value("LIM01_RELEASE_DETAIL", "UNIQUE_CURRENT_RELEASE_ACTION_END"),
                        "关联记录": "CL-01", "动态扩展": "",
                    },
                },
                {
                    "id": "LIM-02", "title": "LIM-02 重要未验证事实：保留原始观察缺口", "fields": {
                        "当前限制": long_limit_value("LIM02_CURRENT_DETAIL", "UNIQUE_UNVERIFIED_FACT_END"),
                        "实际影响": long_limit_value("LIM02_IMPACT_DETAIL", "UNIQUE_UNVERIFIED_IMPACT_END"),
                        "解除条件": long_limit_value("LIM02_RELEASE_DETAIL", "UNIQUE_UNVERIFIED_RELEASE_ACTION_END"),
                        "关联记录": "CL-01", "动态扩展": "保留这个未分类的原生扩展字段",
                    },
                },
                {
                    "id": "LIM-03", "title": "LIM-03 解除方向：取得凭证后完成正式归档", "fields": {
                        "当前限制": long_limit_value("LIM03_CURRENT_DETAIL", "UNIQUE_FINALIZE_LIMIT_END"),
                        "实际影响": long_limit_value("LIM03_IMPACT_DETAIL", "UNIQUE_FINALIZE_IMPACT_END"),
                        "解除条件": long_limit_value(
                            "LIM03_RELEASE_DETAIL", "UNIQUE_LONG_IMPORTANT_LIM_ACTION_PRESERVE_TO_END"),
                        "关联记录": "CL-01", "动态扩展": "",
                    },
                },
            ]
            draft["sections"][7] = {"number": 8, "records": [{
                "id": "RES-01", "title": "合成原生结果摘要", "fields": result_fields,
            }]}
            draft["sections"][8] = {"number": 9, "records": copy.deepcopy(limit_records)}

            def set_model_header_value(group_title, field_label, value):
                group = next(row for row in draft["sections"][0]["groups"]
                             if row["title"] == group_title)
                field = next(row for row in group["fields"] if row["label"] == field_label)
                field["text"] = value

            set_model_header_value("当前 TR", "用户具体要求", "FAKE_HEADER_REQUEST_SUMMARY")
            set_model_header_value("文件修改", "核心变化", "FAKE_HEADER_RES_SUMMARY")
            set_model_header_value("剩余限制", "当前情况", "FAKE_HEADER_LIM_SUMMARY")
            draft["sections"][2] = {"number": 3, "title": "术语", "terms": terms}

            captured = native.capture(host.root, host.turn, host.request_id, draft=draft)
            no_header_draft = copy.deepcopy(draft)
            no_header_draft["sections"][0] = {"number": 1, "title": "Header omitted"}
            without_header = native.capture(
                host.root, host.turn, host.request_id, draft=no_header_draft)
            observed_terms = captured["sections"][2]["terms"]
            self.assertEqual(len(source_keys), len(observed_terms))

            for source_key, supplied_key, observed in zip(source_keys, supplied_keys, observed_terms):
                source = entries[source_key]
                label = source_key.lower().replace(".", "_")
                _case(self, "native_capture_mixed_case_registry_key_resolves_" + label,
                      observed["definition_source"],
                      ".agent-project-control/reporting/quality/term-registry.json#" + source_key)
                _case(self, "native_capture_overwrites_polluted_english_" + label,
                      observed["english"], source["english"])
                _case(self, "native_capture_overwrites_polluted_chinese_" + label,
                      observed["chinese"], source["chinese"])
                _case(self, "native_capture_proper_name_not_acronym_expansion_" + label,
                      source["formal_acronym_expansion"] is False and observed["kind"] != "abbreviation", True)
                _case(self, "native_capture_verified_registry_definition_" + label,
                      captured["verified_term_registry"][supplied_key.upper()]["english"], source["english"])

            contract_path = host.root / ".agent-project-control/reporting/contract.json"
            contract = json.loads(contract_path.read_text(encoding="utf-8-sig"))
            header_spec = contract["sections"][0]
            expected_layout = [(group["title"], group["fields"]) for group in header_spec["groups"]]
            header = captured["sections"][0]
            captured_layout = [(group["title"], [field["label"] for field in group["fields"]])
                               for group in header["groups"]]
            header_values = {group["title"]: {field["label"]: field["text"] for field in group["fields"]}
                             for group in header["groups"]}
            from test_ledger import parse_checklist
            source_checklist = parse_checklist((host.turn / "CHECKLIST.md").read_text(encoding="utf-8-sig"))
            progress = header_values["当前 IT"]["当前进度"]
            task = header_values["当前 TR"]["用户具体要求"]
            scope = header_values["当前 TR"]["本轮处理范围"]
            request_body = (host.turn / "REQUEST.md").read_text(encoding="utf-8-sig").split(
                "## My request:", 1)[-1].strip()
            completed = [row for row in source_checklist if row["status"] == "已完成"]
            unfinished = [row for row in source_checklist if row["status"] != "已完成"]
            progress_matches_source = (
                f"已登记 {len(source_checklist)} 项目标" in progress
                and f"已完成 {len(completed)} 项" in progress
                and all(row["object"] in progress for row in completed + unfinished)
            )
            scope_matches_source = all(row["object"] in scope for row in source_checklist)
            def source_criterion(row):
                direct = row.get("criterion")
                if isinstance(direct, str):
                    return direct
                span = row.get("_spans", {}).get("criterion")
                prose = row.get("_prose", row.get("body", ""))
                if isinstance(span, list) and len(span) == 2:
                    return prose[span[0]:span[1]]
                return ""

            native_cl_facts = {
                row["id"]: captured["facts"]["native-" + row["id"]]["value"]
                for row in source_checklist
            }
            native_cl_records = {
                row["id"]: row for row in captured["sections"][3].get("records", [])
            }
            original_criteria_preserved = all(
                native_cl_facts[row["id"]].get("body") == row.get("body", row.get("_prose", ""))
                and native_cl_records[row["id"]]["fields"]["验收标准"] == source_criterion(row)
                for row in source_checklist
            )
            _case(self, "native_header_long_term_objective_uses_iteration_objective",
                  header_values["当前 IT"]["长期工作目标"], objective)
            _case(self, "native_header_task_scope_and_progress_follow_source_ledgers",
                  (task == request_body, scope_matches_source, progress_matches_source),
                  (True, True, True))
            _case(self, "native_header_original_CL_criteria_remain_in_native_facts_and_fields",
                  original_criteria_preserved, True)
            native_fact_bindings = all(
                captured["facts"]["native-" + row["id"]]["source_ref"]
                == host.turn.relative_to(host.root).as_posix() + "/CHECKLIST.md#" + row["id"]
                and captured["facts"]["native-" + row["id"]]["value"].get("status") == row["status"]
                and captured["facts"]["native-" + row["id"]]["value"].get("object") == row["object"]
                and native_cl_records[row["id"]]["fact_refs"] == ["native-" + row["id"]]
                for row in source_checklist
            )
            _case(self, "native_header_CL_facts_keep_original_source_bindings",
                  native_fact_bindings, True)
            cl_status_order = ("已完成", "失败", "阻塞", "进行中", "未开始")
            expected_cl_stats = "；".join(
                key + "：" + str(sum(row["status"] == key for row in source_checklist))
                for key in cl_status_order)
            _case(self, "native_header_CL_status_statistics_include_zero_counts",
                  header_values["执行清单"]["执行统计"], expected_cl_stats)
            cl_stats_from_facts = "；".join(
                key + "：" + str(sum(captured["facts"]["native-" + row["id"]]["value"].get("status") == key
                                     for row in source_checklist))
                for key in cl_status_order)
            _case(self, "native_header_CL_status_statistics_match_native_facts",
                  header_values["执行清单"]["执行统计"], cl_stats_from_facts)
            _case(self, "native_header_formal_contract_has_13_unique_groups",
                  (len(expected_layout), len({title for title, _ in expected_layout}),
                   len([title for title, _ in captured_layout]),
                   len({title for title, _ in captured_layout})), (13, 13, 13, 13))
            _case(self, "native_header_groups_and_required_fields_follow_contract_order",
                  captured_layout, expected_layout)
            _case(self, "native_header_all_formal_fields_have_text_values",
                  all(isinstance(value, str) for group in header_values.values() for value in group.values()), True)
            expected_derived_sections = {
                "result_summary": result_fields["实际成果"],
            }
            observed_derived_sections = {
                "result_summary": header_values["文件修改"]["核心变化"],
                "limit_current": header_values["剩余限制"]["当前情况"],
                "limit_impact": header_values["剩余限制"]["实际影响"],
                "limit_release": header_values["剩余限制"]["解除方向"],
            }
            source_limit_titles = [row["title"] for row in limit_records]
            limit_navigation_fields = {key: observed_derived_sections[key]
                                       for key in ("limit_current", "limit_impact", "limit_release")}
            current_titles_in_source_order = (
                all(title in limit_navigation_fields["limit_current"] for title in source_limit_titles)
                and [limit_navigation_fields["limit_current"].find(title) for title in source_limit_titles]
                == sorted(limit_navigation_fields["limit_current"].find(title) for title in source_limit_titles)
            )
            full_limit_bodies_not_copied = all(
                body not in value
                for value in limit_navigation_fields.values()
                for row in limit_records
                for body in (row["fields"]["当前限制"], row["fields"]["实际影响"], row["fields"]["解除条件"])
            )
            navigation_is_short = all(
                len(value) < min(len(row["fields"][field]) for row in limit_records
                                 for field in ("当前限制", "实际影响", "解除条件"))
                for value in limit_navigation_fields.values()
            )
            first_blocker_visible = (
                source_limit_titles[0] in limit_navigation_fields["limit_current"]
                and "真实阻塞" in limit_navigation_fields["limit_current"]
            )
            impact_and_release_point_to_section9 = (
                "第9章" in limit_navigation_fields["limit_impact"]
                and "第9章" in limit_navigation_fields["limit_release"]
                and "业务门禁" in limit_navigation_fields["limit_release"]
                and "Finalize" not in limit_navigation_fields["limit_release"]
            )
            _case(self, "native_header_RES_and_LIM_summaries_are_exactly_source_derived",
                  (observed_derived_sections["result_summary"] == expected_derived_sections["result_summary"],
                   current_titles_in_source_order, full_limit_bodies_not_copied,
                   navigation_is_short, first_blocker_visible, impact_and_release_point_to_section9),
                  (True, True, True, True, True, True))
            _case(self, "native_section9_preserves_all_three_LIM_records_and_fields",
                  captured["sections"][8], draft["sections"][8])
            _case(self, "native_section9_preserves_long_unique_LIM_action_tail",
                  captured["sections"][8]["records"][2]["fields"]["解除条件"].endswith(
                      "UNIQUE_LONG_IMPORTANT_LIM_ACTION_PRESERVE_TO_END"), True)
            _case(self, "native_header_model_values_are_ignored_with_same_allowed_sections",
                  (captured["sections"][0]["groups"], captured["source_digest"]),
                  (without_header["sections"][0]["groups"], without_header["source_digest"]))
            _case(self, "native_header_change_keeps_machine_facts_and_source_bindings",
                  (captured["facts"], captured["native_sources"], captured["identity"],
                   captured["source_digest"]),
                  (without_header["facts"], without_header["native_sources"], without_header["identity"],
                   without_header["source_digest"]))

            source_paths = {
                (host.turn / "REQUEST.md").relative_to(host.root).as_posix(): hashlib.sha256(
                    (host.turn / "REQUEST.md").read_bytes()).hexdigest(),
                (host.turn.parents[1] / "ITERATION.md").relative_to(host.root).as_posix():
                    hashlib.sha256((host.turn.parents[1] / "ITERATION.md").read_bytes()).hexdigest(),
                ".agent-project-control/framework.yaml": hashlib.sha256(
                    (host.root / ".agent-project-control/framework.yaml").read_bytes()).hexdigest(),
                ".agent-project-control/reporting/contract.json": hashlib.sha256(contract_path.read_bytes()).hexdigest(),
            }
            _case(self, "native_header_capture_binds_iteration_framework_and_contract_bytes",
                  {path: captured["native_sources"].get(path) for path in source_paths}, source_paths)
            native_manifest = captured["facts"]["native-manifest"]["value"]
            _case(self, "native_header_source_digest_covers_captured_source_bytes",
                  captured["source_digest"], digest({"identity": captured["identity"],
                      "sources": captured["native_sources"], "facts": captured["facts"],
                      "manifest": native_manifest}))

            from test_ledger import parse_tests
            source_tests = parse_tests((host.turn / "TEST.md").read_text(encoding="utf-8-sig"))
            observed_counts = {key: sum(row["status"] == key for row in source_tests)
                               for key in ("PASS", "FAIL", "BLOCKED", "未执行")}
            _case(self, "native_header_fixture_retains_zero_TEST_status_counts",
                  observed_counts, {"PASS": 1, "FAIL": 0, "BLOCKED": 0, "未执行": 0})
            _case(self, "native_header_summary_renders_zero_TEST_status_counts",
                  header_values["验收摘要"]["状态统计"],
                  "TEST 总数：1；通过：1；失败：0；阻塞：0；未执行：0")
            native_test_records = {
                row["id"]: row for row in captured["sections"][5].get("records", [])
            }
            native_test_fact_bindings = all(
                captured["facts"]["native-" + row["id"]]["source_ref"]
                == host.turn.relative_to(host.root).as_posix() + "/TEST.md#" + row["id"]
                and captured["facts"]["native-" + row["id"]]["value"].get("status") == row["status"]
                and native_test_records[row["id"]]["fact_refs"] == ["native-" + row["id"]]
                for row in source_tests
            )
            _case(self, "native_header_TEST_facts_keep_original_source_bindings",
                  native_test_fact_bindings, True)
            test_status_from_facts = {
                key: sum(captured["facts"]["native-" + row["id"]]["value"].get("status") == key
                         for row in source_tests)
                for key in ("PASS", "FAIL", "BLOCKED", "未执行")
            }
            _case(self, "native_header_TEST_status_summary_matches_native_facts",
                  header_values["验收摘要"]["状态统计"],
                  "TEST 总数：" + str(len(source_tests)) + "；" + "；".join(
                      {"PASS": "通过", "FAIL": "失败", "BLOCKED": "阻塞", "未执行": "未执行"}[key]
                      + "：" + str(value) for key, value in test_status_from_facts.items()))

            session_path = host.turn / "evidence" / "execution-session.json"
            session = json.loads(session_path.read_text(encoding="utf-8-sig"))
            session_fact = captured["facts"]["native-session"]
            _case(self, "native_header_snapshot_created_at_matches_execution_session",
                  (session_fact["value"], session_fact["source_ref"]),
                  ({"created_at": session["created_at"]},
                   host.turn.relative_to(host.root).as_posix() + "/evidence/execution-session.json#created_at"))

            current_path = host.root / "CURRENT.md"
            turn_path = host.turn / "TURN.md"
            expected_entries = (
                f"[当前完整报告](<{current_path.as_posix()}>)",
                f"[本轮源报告](<{turn_path.as_posix()}>)",
            )
            observed_entries = (header_values["入口"]["主要入口"], header_values["入口"]["次要入口"])
            _case(self, "native_header_entries_bind_two_existing_local_report_paths",
                  (observed_entries, current_path.is_file() and turn_path.is_file()),
                  (expected_entries, True))

            schema_match = re.search(
                r"^schema_version:\s*[\"']?([^\"'\s]+)",
                (host.root / ".agent-project-control/framework.yaml").read_text(encoding="utf-8-sig"), re.M)
            schema_version = schema_match.group(1) if schema_match else ""
            formal_version = header_values["版本"]["正式版本"]
            candidate_version = header_values["版本"]["候选版本"]
            current_commit = header_values["生产提交"]["当前生产提交"]
            candidate_commit = header_values["生产提交"]["本轮候选提交"]
            deployment = header_values["生产提交"]["本轮部署情况"]
            production_identity_checks = (
                any(token in formal_version for token in ("未知", "未核对", "未取得")),
                any(token in current_commit for token in ("未知", "未核对", "未取得")),
                bool(schema_version) and schema_version in candidate_version
                and candidate_version != formal_version
                and any(token in candidate_version for token in ("结构", "模式", "框架")),
                not re.search(r"(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])", candidate_commit, re.I),
                not re.search(r"(?:已经部署|已部署|部署完成|已上线|正式发布)", deployment),
            )
            _case(self, "native_header_does_not_invent_release_commit_or_deployment",
                  production_identity_checks, (True, True, True, True, True))
            limit_text = header_values["剩余限制"]["当前情况"]
            source_limits = captured["sections"][8].get("records", [])
            if source_limits:
                limits_match_source = all(row["title"] in limit_text for row in source_limits)
            elif unfinished:
                limits_match_source = "未完成" in limit_text or "仍在推进" in limit_text
            else:
                limits_match_source = (
                    any(token in limit_text for token in ("无未完成", "没有未完成", "尚无未完成"))
                    and any(token in limit_text for token in ("未验证", "当前正文", "其他限制"))
                )
            _case(self, "native_header_deployment_and_limits_are_conditionally_scoped",
                  (not re.search(r"(?:已经部署|已部署|部署完成|已上线|正式发布)", deployment),
                   limits_match_source), (True, True))
            _case(self, "native_capture_ignores_model_supplied_header_contamination",
                  (header["groups"], captured["source_digest"]),
                  (without_header["sections"][0]["groups"], without_header["source_digest"]))

            candidate = copy.deepcopy(captured)
            candidate_group = next(row for row in candidate["sections"][0]["groups"]
                                   if row["title"] == "剩余限制")
            candidate_field = next(row for row in candidate_group["fields"]
                                   if row["label"] == "当前情况")
            candidate_field["text"] = "FAKE_HEADER_LIM_POST_CAPTURE_MUTATION"
            _reject(self, "native_header_model_contamination_fails_same_authority",
                    lambda: assert_same_authority(candidate, captured), "MACHINE_FACTS_CHANGED")
            candidate_identity = copy.deepcopy(captured)
            candidate_identity["identity"]["turn_id"] = "foreign-turn"
            _reject(self, "native_header_identity_mutation_fails_same_authority",
                    lambda: assert_same_authority(candidate_identity, captured), "MACHINE_FACTS_CHANGED")

            from report_bridge.render import verify_artifact
            rendered = render(baseline)
            rendered_header = rendered.split("\n## 2.", 1)[0]
            rendered_layout = []
            current_group = None
            for line in rendered_header.splitlines():
                group_match = re.fullmatch(r"\*\*(.+?)\*\*：", line)
                if group_match:
                    current_group = {"title": group_match.group(1), "fields": []}
                    rendered_layout.append(current_group)
                    continue
                field_match = re.match(r"^- (.+?)：", line)
                if field_match and current_group is not None:
                    current_group["fields"].append(field_match.group(1))
            rendered_layout = [(group["title"], group["fields"]) for group in rendered_layout]
            _case(self, "native_render_preserves_all_13_contract_groups_and_fields_in_order",
                  rendered_layout, expected_layout)
            _case(self, "native_render_matches_verified_artifact_and_excludes_model_header_text",
                  (verify_artifact(rendered, baseline), "FAKE_HEADER_" not in rendered), (True, True))

    def test_ports_reviewer_sends_byte_bound_source_excerpt_and_rejects_drift(self):
        from report14.storage import Store
        from report_bridge import ports

        objective = "BYTE_BOUND_REVIEWER_SOURCE_EXCERPT_FIXTURE"
        with native_host(objective=objective) as host:
            snapshot = host.capture()
            iteration_path = host.turn.parents[1] / "ITERATION.md"
            iteration_rel = iteration_path.relative_to(host.root).as_posix()
            source_bytes = iteration_path.read_bytes()
            source_text = source_bytes.decode("utf-8-sig")
            source_sha = hashlib.sha256(source_bytes).hexdigest()
            _case(self, "reviewer_fixture_snapshot_binds_iteration_bytes",
                  snapshot["native_sources"].get(iteration_rel), source_sha)

            seen = []

            def payload_only_model(command, request, budget):
                pointer = request["required_pointers"][0] if request["required_pointers"] else "/"
                response = {
                    "source_digest": request["source_digest"],
                    "report_digest": request["report_digest"],
                    "rubric_digest": request["rubric_digest"],
                    "model_id": "synthetic-payload-only-stub",
                    "assessed_pointers": request["required_pointers"],
                    "quality": "needs_revision",
                    "issues": [{"pointer": pointer, "reason": "deterministic fixture payload probe"}],
                }
                seen.append({"command": command, "request": copy.deepcopy(request),
                             "budget": budget, "response": response})
                return response

            reviewer = ports._reviewer(
                ["synthetic-payload-only-stub"], ports.reference_index(host.root), Store(host.root))
            with patch.object(ports, "model_command", payload_only_model):
                issues = reviewer(snapshot, 155)

            request = seen[0]["request"]
            material = next(row for row in request["verified_materials"] if row["path"] == iteration_rel)
            excerpt = "".join(part["text"] for part in material["excerpts"])
            _case(self, "reviewer_payload_contains_exact_source_hash_and_excerpt",
                  (material["sha256"], material["characters"], material["complete"], objective in excerpt),
                  (source_sha, len(source_text), True, True))
            _case(self, "reviewer_mock_receives_verified_source_excerpt_without_quality_claim",
                  (len(seen), issues[0].code, seen[0]["response"]["quality"], objective in excerpt),
                  (1, "SEMANTIC_CONTENT", "needs_revision", True))

            iteration_path.write_bytes(source_bytes + b"\nfixture source drift\n")
            with patch.object(ports, "model_command", payload_only_model):
                _reject(self, "reviewer_rejects_byte_bound_source_drift_before_model_call",
                        lambda: reviewer(snapshot, 155), "REVIEW_SOURCE_CHANGED", ContractError)
            _case(self, "reviewer_source_drift_prevents_second_model_call", len(seen), 1)

    def test_native_snapshot_rejects_saved_request_source_change(self):
        with native_host() as host:
            snapshot = host.capture()
            writer = host.writer(snapshot)
            request = host.turn / "REQUEST.md"
            request.write_bytes(request.read_bytes() + b"\nfixture source changed\n")
            _reject(self, "native_saved_request_source_change", lambda: writer.save_report(
                markdown=render(snapshot), snapshot=snapshot,
                expected_source_digest=snapshot["source_digest"], report_digest=digest(snapshot),
                quality="unreviewed"), "NATIVE_SOURCE_CHANGED")

    def test_native_snapshot_rejects_plan_revision_change(self):
        with native_host() as host:
            plan = host.add_plan()
            snapshot = host.capture()
            writer = host.writer(snapshot)
            row = json.loads(plan.read_text(encoding="utf-8"))
            row["fixture_marker"] = "after"
            plan.write_text(json.dumps(row, ensure_ascii=False, sort_keys=True), encoding="utf-8")
            _reject(self, "native_plan_revision_change", lambda: writer.save_report(
                markdown=render(snapshot), snapshot=snapshot,
                expected_source_digest=snapshot["source_digest"], report_digest=digest(snapshot),
                quality="unreviewed"), "NATIVE_SOURCE_CHANGED")

    def test_native_validation_normalizes_finalize_report_carriers(self):
        from report14.bridge import native_validation

        with native_host() as host:
            snapshot = host.capture()
            save(host, snapshot)
            report = render(snapshot)
            canonical_errors = native_validation(report, host.turn)

            stripped_errors = native_validation(report.strip(), host.turn)
            _case(self, "native_validation_accepts_finalize_stripped_report_body",
                  stripped_errors, canonical_errors)

            crlf_errors = native_validation(report.replace("\n", "\r\n"), host.turn)
            _case(self, "native_validation_accepts_crlf_report_carrier",
                  crlf_errors, canonical_errors)

            marker = "本轮无相关事项：当前原生记录没有登记这类事项"
            self.assertIn(marker, report)
            changed = report.replace(marker, marker + "（报告正文被修改）", 1)
            changed_errors = native_validation(changed, host.turn)
            _case(self, "native_validation_rejects_changed_report_body",
                  "report14 native source/review unavailable: ContractError" in changed_errors, True)

            section_start = report.index("## 2. ")
            section_end = report.index("\n## 3. ", section_start)
            section_paragraphs = [paragraph.strip() for paragraph in report[section_start:section_end].split("\n\n")
                                  if paragraph.strip() and not paragraph.lstrip().startswith("## 2. ")]
            self.assertTrue(section_paragraphs, "fixture must render a native section paragraph")
            dropped = report.replace(section_paragraphs[0], "", 1)
            dropped_errors = native_validation(dropped, host.turn)
            _case(self, "native_validation_rejects_dropped_report_paragraph",
                  "report14 native source/review unavailable: ContractError" in dropped_errors, True)

    def test_gate_masks_only_verified_report14_request_field_spans(self):
        import gate_check
        from repair_io import private_json
        from routing_activity import init_baseline

        request = ('<!-- APCF-META {"schema":1,"visibility":"private"} -->\n'
                   '# 1. 请求\n\n## My request:\n\n'
                   '原始请求包含中文句号。请按原范围继续核对。\n\n保留第二段原文。')
        request_body = request.split('## My request:', 1)[1].strip()
        with native_host(request_text=request) as host:
            init_baseline(host.turn)
            snapshot = host.capture()
            save(host, snapshot)
            turn_rel = host.turn.relative_to(host.root).as_posix()
            current_target = 'CURRENT.md'
            turn_target = turn_rel + '/TURN.md'
            for label, target in (("CURRENT", current_target), ("TURN", turn_target)):
                path = host.root / Path(target)
                text = path.read_text(encoding="utf-8")
                spans = gate_check._source_bound_request_spans(host.turn, target, text)
                _case(self, "gate_verified_" + label.lower() + "_request_has_exact_bound_spans",
                      len(spans) >= 2, True)
                masked = gate_check._mask_source_spans(text, spans)
                hits = [(number, prose) for number, prose in gate_check._markdown_prose(masked)
                        if '。' in prose and re.search(r'[\u3400-\u9fff]', prose)]
                _case(self, "gate_verified_" + label.lower() + "_request_punctuation_is_source_bound",
                      hits, [])

            fake = gate_check._source_bound_request_spans(host.turn, "nested/CURRENT.md",
                                                         (host.root / "CURRENT.md").read_text(encoding="utf-8"))
            _case(self, "gate_rejects_a_fake_report_target_path", fake, [])

            current = host.root / "CURRENT.md"
            current.write_text(current.read_text(encoding="utf-8") + "\n作者新增说明。仍须检查。\n",
                               encoding="utf-8")
            appended = current.read_text(encoding="utf-8")
            appended_spans = gate_check._source_bound_request_spans(host.turn, current_target, appended)
            _case(self, "gate_does_not_mask_appended_report_author_prose", appended_spans, [])
            appended_findings = _gate_content_findings(host.turn, [current_target])
            _case(self, "gate_scans_appended_report_author_full_stops",
                  any("Writing v0.1 §1 editable Chinese full stop" in row["message"]
                      for row in appended_findings), True)

        with native_host(request_text=request) as host:
            init_baseline(host.turn)
            save(host, host.capture())
            current = host.root / "CURRENT.md"
            request_path = host.turn / "REQUEST.md"
            request_path.write_bytes(request_path.read_bytes() + "\n来源漂移。\n".encode("utf-8"))
            spans = gate_check._source_bound_request_spans(
                host.turn, "CURRENT.md", current.read_text(encoding="utf-8"))
            _case(self, "gate_rejects_request_sha_or_activity_baseline_drift", spans, [])
            findings = _gate_content_findings(host.turn, ["CURRENT.md"])
            _case(self, "gate_scans_report_quote_when_request_source_drifts",
                  any("Writing v0.1 §1 editable Chinese full stop" in row["message"]
                      for row in findings), True)

        with native_host(request_text=request) as host:
            init_baseline(host.turn)
            save(host, host.capture())
            receipt_path = host.turn / "evidence/report-quality-publication.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["request_id"] = "forged-request-identity"
            private_json(receipt_path, receipt)
            spans = gate_check._source_bound_request_spans(
                host.turn, "CURRENT.md", (host.root / "CURRENT.md").read_text(encoding="utf-8"))
            _case(self, "gate_rejects_report_receipt_identity_mismatch", spans, [])

    def test_gate_masks_only_stable_private_one_level_pa_request_preimages(self):
        import gate_check
        from repair_io import private_json
        from routing_activity import init_baseline

        pa_text = ('<!-- APCF-META {"schema":1,"visibility":"private"} -->\n'
                   '# 1. 并行任务原始请求\n\n原始 PA 请求。继续核验该独立范围。')

        with native_host() as host:
            pa = host.turn / "parallel" / "PA-9001_fixture"
            pa.mkdir()
            request_path = pa / "REQUEST.md"
            request_path.write_text(pa_text, encoding="utf-8")
            init_baseline(host.turn)
            target = request_path.relative_to(host.root).as_posix()
            target_sha = hashlib.sha256(request_path.read_bytes()).hexdigest()
            _write_private_plan_chain(host.turn, target, target_sha)
            spans = gate_check._source_bound_request_spans(
                host.turn, target, request_path.read_text(encoding="utf-8"))
            _case(self, "gate_accepts_stable_private_one_level_pa_preimage", len(spans), 1)
            masked = gate_check._mask_source_spans(request_path.read_text(encoding="utf-8"), spans)
            hits = [(number, prose) for number, prose in gate_check._markdown_prose(masked)
                    if '。' in prose and re.search(r'[\u3400-\u9fff]', prose)]
            _case(self, "gate_pa_source_body_punctuation_is_preimage_bound", hits, [])
            findings = _gate_content_findings(host.turn, [target])
            _case(self, "gate_content_scan_accepts_only_verified_pa_original_body",
                  any("Writing v0.1 §1 editable Chinese full stop" in row["message"]
                      for row in findings), False)
            _case(self, "gate_rejects_nested_or_fake_pa_request_path",
                  gate_check._source_bound_request_spans(host.turn,
                      target.replace("/REQUEST.md", "/nested/REQUEST.md"), pa_text), [])

        with native_host() as host:
            pa = host.turn / "parallel" / "PA-9002_fixture"
            pa.mkdir()
            request_path = pa / "REQUEST.md"
            request_path.write_text(pa_text, encoding="utf-8")
            init_baseline(host.turn)
            target = request_path.relative_to(host.root).as_posix()
            _write_private_plan_chain(host.turn, target, hashlib.sha256(request_path.read_bytes()).hexdigest())
            request_path.write_text(pa_text + "\n新增段落。必须检查。", encoding="utf-8")
            spans = gate_check._source_bound_request_spans(
                host.turn, target, request_path.read_text(encoding="utf-8"))
            _case(self, "gate_rejects_appended_pa_request_suffix", spans, [])
            findings = _gate_content_findings(host.turn, [target])
            _case(self, "gate_scans_changed_pa_request_original_and_suffix",
                  any("Writing v0.1 §1 editable Chinese full stop" in row["message"]
                      for row in findings), True)

        with native_host() as host:
            pa = host.turn / "parallel" / "PA-9003_fixture"
            pa.mkdir()
            request_path = pa / "REQUEST.md"
            request_path.write_text(pa_text, encoding="utf-8")
            init_baseline(host.turn)
            target = request_path.relative_to(host.root).as_posix()
            _write_private_plan_chain(host.turn, target, hashlib.sha256(request_path.read_bytes()).hexdigest())
            plan_path = host.turn / "evidence/plan-revision-000002.json"
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["target_preimages"][0]["sha256"] = "0" * 64
            private_json(plan_path, plan)
            spans = gate_check._source_bound_request_spans(
                host.turn, target, request_path.read_text(encoding="utf-8"))
            _case(self, "gate_rejects_conflicting_plan_revision_preimages", spans, [])

        with native_host() as host:
            pa = host.turn / "parallel" / "PA-9004_fixture"
            pa.mkdir()
            request_path = pa / "REQUEST.md"
            request_path.write_text(pa_text, encoding="utf-8")
            init_baseline(host.turn)
            target = request_path.relative_to(host.root).as_posix()
            _write_private_plan_chain(host.turn, target, hashlib.sha256(request_path.read_bytes()).hexdigest())
            sidecar = host.turn / "evidence/plan-revision-000001.json.apcf-meta.yaml"
            sidecar.write_text("spoofed private metadata\n", encoding="utf-8")
            spans = gate_check._source_bound_request_spans(
                host.turn, target, request_path.read_text(encoding="utf-8"))
            _case(self, "gate_rejects_plan_revision_without_valid_private_metadata", spans, [])

    def test_manifest_uses_turn_start_dirty_baseline_over_later_plan_preimage(self):
        with native_host() as host:
            turn_rel = host.turn.relative_to(host.root).as_posix()
            baseline_path = host.turn / "evidence" / "activity-baseline.json"
            declared = "src/declared-dirty.txt"
            undeclared = "src/undeclared-dirty.txt"
            old_bytes = b"turn-start dirty bytes"
            intermediate_bytes = b"later plan preimage bytes"
            undeclared_old = b"other turn-start dirty bytes"
            undeclared_final = b"other dirty bytes after work"
            declared_path = host.root / declared
            undeclared_path = host.root / undeclared
            declared_path.write_bytes(old_bytes)
            undeclared_path.write_bytes(undeclared_old)
            baseline_row = {
                "schema": 1,
                "turn": turn_rel,
                "dirty_rows": [
                    {"path": declared, "state": "file",
                     "sha256": hashlib.sha256(old_bytes).hexdigest()},
                    {"path": undeclared, "state": "file",
                     "sha256": hashlib.sha256(undeclared_old).hexdigest()},
                ],
            }
            baseline_bytes = (json.dumps(baseline_row, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
            baseline_path.write_bytes(baseline_bytes)

            declared_path.write_bytes(intermediate_bytes)
            undeclared_path.write_bytes(undeclared_final)
            host.add_plan([{
                "path": declared,
                "state": "file",
                "sha256": hashlib.sha256(intermediate_bytes).hexdigest(),
            }])

            snapshot = host.capture()
            manifest = snapshot["facts"]["native-manifest"]["value"]
            row = next(item for item in manifest if item["path"] == declared)
            _case(self, "manifest_declared_existing_dirty_path_stays_modified", row["change"], "修改")
            _case(self, "manifest_before_uses_turn_start_dirty_hash",
                  row["before_sha256"], hashlib.sha256(old_bytes).hexdigest())
            _case(self, "manifest_after_uses_final_intermediate_hash",
                  row["after_sha256"], hashlib.sha256(intermediate_bytes).hexdigest())
            _case(self, "manifest_undeclared_dirty_path_is_excluded",
                  undeclared in {item["path"] for item in manifest}, False)

            baseline_rel = baseline_path.relative_to(host.root).as_posix()
            baseline_digest = hashlib.sha256(baseline_bytes).hexdigest()
            _case(self, "manifest_activity_baseline_hash_is_source_bound",
                  snapshot["native_sources"].get(baseline_rel), baseline_digest)
            writer = host.writer(snapshot)
            changed_baseline = dict(baseline_row, fixture_marker="changed after capture")
            baseline_path.write_text(json.dumps(changed_baseline, ensure_ascii=False, sort_keys=True) + "\n",
                                     encoding="utf-8")
            _reject(self, "manifest_activity_baseline_byte_drift_rejected", lambda: writer.save_report(
                markdown=render(snapshot), snapshot=snapshot,
                expected_source_digest=snapshot["source_digest"], report_digest=digest(snapshot),
                quality="unreviewed"), "NATIVE_SOURCE_CHANGED")

            foreign_baseline = dict(baseline_row, turn="foreign-fixture-turn")
            baseline_path.write_text(json.dumps(foreign_baseline, ensure_ascii=False, sort_keys=True) + "\n",
                                     encoding="utf-8")
            _reject(self, "manifest_foreign_turn_baseline_rejected", host.capture,
                    "FOREIGN_ACTIVITY_BASELINE")

    def test_native_snapshot_rejects_deleted_target_reappearing(self):
        with native_host() as host:
            target = "src/deleted-before-capture.txt"
            host.add_plan([{"path": target, "state": "file", "sha256": hashlib.sha256(b"prior").hexdigest()}])
            snapshot = host.capture()
            _case(self, "native_deleted_preimage_is_visible", snapshot["change_manifest"],
                  [{"path": target, "change": "删除"}])
            writer = host.writer(snapshot)
            (host.root / target).write_text("reappeared", encoding="utf-8")
            _reject(self, "native_deleted_preimage_reappears", lambda: writer.save_report(
                markdown=render(snapshot), snapshot=snapshot,
                expected_source_digest=snapshot["source_digest"], report_digest=digest(snapshot),
                quality="unreviewed"), "NATIVE_SOURCE_CHANGED")

    def test_preimage_conflict_preserves_external_history(self):
        with native_host() as host:
            snapshot = host.capture()
            writer = host.writer(snapshot)
            turn_before = (host.turn / "TURN.md").read_bytes()
            current = host.root / "CURRENT.md"
            external_current = b"external fixture edit\n"
            history = writer.store.home / "history"
            history.mkdir(parents=True, exist_ok=True)
            sentinel = history / "preexisting-history.json"
            sentinel_bytes = b'{"fixture":"keep"}\n'
            sentinel.write_bytes(sentinel_bytes)
            current.write_bytes(external_current)
            _reject(self, "preimage_conflict_is_rejected", lambda: writer.save_report(
                markdown=render(snapshot), snapshot=snapshot,
                expected_source_digest=snapshot["source_digest"], report_digest=digest(snapshot),
                quality="unreviewed"), "publication snapshot changed", ValueError)
            _case(self, "preimage_turn_preserved", (host.turn / "TURN.md").read_bytes(), turn_before)
            _case(self, "preimage_current_preserved", current.read_bytes(), external_current)
            _case(self, "preimage_history_preserved", sentinel.read_bytes(), sentinel_bytes)
            _case(self, "preimage_history_not_expanded", sorted(p.name for p in history.iterdir()), [sentinel.name])

    def test_archive_preimage_collision_does_not_publish(self):
        with native_host() as host:
            snapshot = host.capture()
            writer = host.writer(snapshot)
            turn_before = (host.turn / "TURN.md").read_bytes()
            current_path = host.root / "CURRENT.md"
            current_before = current_path.read_bytes() if current_path.exists() else None
            archive = writer.home / (digest(snapshot) + ".json")
            archive.parent.mkdir(parents=True, exist_ok=True)
            archive.write_bytes(b'{"fixture":"conflicting preimage"}')
            _reject(self, "archive_preimage_collision", lambda: writer.save_report(
                markdown=render(snapshot), snapshot=snapshot,
                expected_source_digest=snapshot["source_digest"], report_digest=digest(snapshot),
                quality="unreviewed"), "REVISION_COLLISION")
            _case(self, "archive_collision_turn_unchanged", (host.turn / "TURN.md").read_bytes(), turn_before)
            current_after = current_path.read_bytes() if current_path.exists() else None
            _case(self, "archive_collision_current_unchanged", current_after, current_before)

    def test_native_journal_recovers_partial_projection_writes(self):
        with native_host() as host:
            snapshot = host.capture()
            writer = host.writer(snapshot)
            turn_before = (host.turn / "TURN.md").read_bytes()
            current_path = host.root / "CURRENT.md"
            current_before = current_path.read_bytes() if current_path.exists() else None
            archive = writer.home / (digest(snapshot) + ".json")
            publish = writer.store.publish

            def interrupt_after_archive(*args, **kwargs):
                def fault(stage):
                    if stage == "after_write_2":
                        raise RuntimeError("fixture interruption after archive projection")
                return publish(*args, **kwargs, fault=fault)

            with patch.object(writer.store, "publish", side_effect=interrupt_after_archive):
                with self.assertRaisesRegex(RuntimeError, "after archive projection"):
                    markdown = render(snapshot)
                    writer.save_report(markdown=markdown, snapshot=snapshot,
                                       expected_source_digest=snapshot["source_digest"],
                                       report_digest=digest(snapshot), quality="unreviewed")
            _case(self, "journal_fault_reached_archive_projection", archive.is_file(), True)
            _case(self, "journal_fault_precedes_receipt_projection", writer.receipt_path.exists(), False)
            _case(self, "journal_fault_partially_changed_turn", (host.turn / "TURN.md").read_bytes() != turn_before, True)
            _case(self, "journal_fault_partially_changed_current", current_path.read_bytes() != current_before, True)
            _case(self, "journal_recovery_result", writer.store.recover(), "ROLLED_BACK")
            _case(self, "journal_rollback_turn", (host.turn / "TURN.md").read_bytes(), turn_before)
            _case(self, "journal_rollback_current", current_path.read_bytes(), current_before)
            _case(self, "journal_rollback_archive", archive.exists(), False)
            _case(self, "journal_rollback_receipt", writer.receipt_path.exists(), False)

    def test_late_revision_cannot_replace_newer_saved_revision(self):
        with native_host() as host:
            first = host.capture(revision=1)
            save(host, first)
            second = host.capture(revision=2)
            second["sections"][5]["records"][0]["fields"]["动态扩展"] = "newer fixture narrative"
            save(host, second)
            turn_after = (host.turn / "TURN.md").read_bytes()
            current_after = (host.root / "CURRENT.md").read_bytes()
            stale_writer = host.writer(first)
            _reject(self, "late_revision_rejected", lambda: stale_writer.save_report(
                markdown=render(first), snapshot=first,
                expected_source_digest=first["source_digest"], report_digest=digest(first),
                quality="unreviewed"), "LATE_REVISION")
            _case(self, "late_revision_keeps_turn", (host.turn / "TURN.md").read_bytes(), turn_after)
            _case(self, "late_revision_keeps_current", (host.root / "CURRENT.md").read_bytes(), current_after)
            _case(self, "late_revision_keeps_receipt_revision", stale_writer.last_report()["revision"], 2)

    def test_duplicate_revision_with_different_digest_conflicts(self):
        with native_host() as host:
            snapshot = host.capture(revision=1)
            save(host, snapshot)
            duplicate = copy.deepcopy(snapshot)
            duplicate["sections"][5]["records"][0]["fields"]["动态扩展"] = "different content at the same revision"
            writer = host.writer(snapshot)
            turn_before = (host.turn / "TURN.md").read_bytes()
            current_before = (host.root / "CURRENT.md").read_bytes()
            _reject(self, "same_revision_different_digest", lambda: writer.save_report(
                markdown=render(duplicate), snapshot=duplicate,
                expected_source_digest=duplicate["source_digest"], report_digest=digest(duplicate),
                quality="unreviewed"), "REVISION_COLLISION")
            _case(self, "duplicate_revision_turn_unchanged", (host.turn / "TURN.md").read_bytes(), turn_before)
            _case(self, "duplicate_revision_current_unchanged", (host.root / "CURRENT.md").read_bytes(), current_before)

    def test_native_titles_and_all_locked_source_fields_remain_bound(self):
        with native_host() as host:
            captured = host.capture()
            mutations = [
                ("title", lambda x: x["sections"][5]["records"][0].__setitem__("title", "changed fixture title")),
                ("CL_problem", lambda x: x["sections"][3]["records"][0]["fields"].__setitem__("任务缘由", "changed source problem")),
                ("CL_action", lambda x: x["sections"][3]["records"][0]["fields"].__setitem__("行动要求", "changed source action")),
                ("CL_criterion", lambda x: x["sections"][3]["records"][0]["fields"].__setitem__("验收标准", "changed source criterion")),
                ("TEST_task_refs", lambda x: x["sections"][5]["records"][0]["fields"].__setitem__("对应任务", "changed source refs")),
                ("TEST_context_action", lambda x: x["sections"][5]["records"][0]["fields"].__setitem__("验收方式", "changed source context/action")),
                ("TEST_expected", lambda x: x["sections"][5]["records"][0]["fields"].__setitem__("预期结果", "changed source expected")),
                ("TEST_actual", lambda x: x["sections"][5]["records"][0]["fields"].__setitem__("实际结果", "changed source actual")),
                ("TEST_evidence", lambda x: x["sections"][5]["records"][0]["fields"].__setitem__("关联证据", "changed source evidence")),
            ]
            for name, mutate in mutations:
                with self.subTest(source_field=name):
                    candidate = copy.deepcopy(captured)
                    mutate(candidate)
                    _reject(self, "source_binding_" + name,
                            lambda c=candidate: assert_same_authority(c, captured),
                            "MACHINE_FACTS_CHANGED")

    def test_pending_native_status_cannot_be_relabelled_failure(self):
        with native_host(pending=True) as host:
            captured = host.capture()
            _case(self, "pending_native_section_unverified", captured["sections"][3]["applicability"], "unverified")
            _case(self, "pending_native_source_status", captured["sections"][3]["pending_source"][0]["status"], "进行中")
            candidate = copy.deepcopy(captured)
            candidate["sections"][3]["pending_source"][0]["status"] = "失败"
            _reject(self, "pending_status_cannot_become_failure",
                    lambda: assert_same_authority(candidate, captured), "MACHINE_FACTS_CHANGED")

    def test_repair_packet_refuses_locked_acceptance_criteria(self):
        with native_host() as host:
            snapshot = host.capture()
            pointer = "/sections/3/records/0/fields/验收标准"
            _reject(self, "repair_packet_locked_criterion", lambda: build_packet(
                snapshot, [pointer], diagnostics=[{"code": "fixture"}],
                rule_index={"rules": []}, example_index={"examples": []},
                policy_capsule={"scope": "authorized-text-only"}), "immutable_source_field", ValueError)

    def test_duplicate_file_entries_are_rejected(self):
        with native_host() as host:
            target = "src/value.txt"
            (host.root / target).write_text("after", encoding="utf-8")
            host.add_plan([{"path": target, "state": "file", "sha256": hashlib.sha256(b"before").hexdigest()}])
            snapshot = host.capture()
            files = snapshot["sections"][4]["records"][0]["fields"]["修改对象"]
            _case(self, "single_native_change_entry", len(files), 1)
            files.append(copy.deepcopy(files[0]))
            codes = {issue.code for issue in validate(snapshot)}
            _case(self, "duplicate_file_entry_contract", "FILE_DUPLICATE" in codes, True)

    def test_short_field_basis_does_not_claim_semantic_quality(self):
        with native_host() as host:
            snapshot = host.capture()
            record = snapshot["sections"][3]["records"][0]
            record["fields"]["风险说明"] = "无特殊风险"
            record["short_field_basis"] = {
                "风险说明": {"fact_ref": record["fact_refs"][0], "reason": "原生来源未登记额外风险"}
            }
            issues = assess(snapshot, minimum=90)
            pointer = "/sections/3/records/0/fields/风险说明"
            short_pointers = {issue.pointer for issue in issues if issue.code == "QUALITY_SHORT"}
            _case(self, "source_bound_short_field_not_blanket_rejected", pointer in short_pointers, False)
            _case(self, "unbound_short_description_still_reviewed",
                  any(issue.code == "QUALITY_SHORT" for issue in issues), True)
            _case(self, "short_field_exception_is_not_quality_receipt", "quality" in snapshot, False)

    def test_semantic_header_issue_never_enters_local_repair_targets(self):
        from report_bridge.contract import Issue
        from report_bridge.repair import repair

        with native_host() as host:
            snapshot = host.capture()
            header_pointer = "/sections/0/groups/0/fields/0/text"
            header_before = copy.deepcopy(snapshot["sections"][0]["groups"][0]["fields"][0])
            source_digest_before = snapshot["source_digest"]
            reviewer_calls = []
            agent_requests = []

            def semantic_reviewer(current, _remaining):
                reviewer_calls.append(current["sections"][0]["groups"][0]["fields"][0]["text"])
                return [Issue("HEADER_REVIEW_REQUIRED", header_pointer,
                              "原生状态头字段只读，不能由语义修复改写", "review")]

            def fixture_agent(request, _remaining):
                agent_requests.append(copy.deepcopy(request))
                changes = [
                    {"pointer": target["pointer"], "before_digest": target["before_digest"],
                     "value": target["text"]}
                    for target in request["targets"] if target["pointer"] != header_pointer
                ]
                return {"base_digest": request["base_digest"], "changes": changes}

            result = repair(
                snapshot,
                fixture_agent,
                lambda pointer, _current: {"fixture": pointer},
                max_rounds=1,
                deadline_seconds=2,
                semantic_reviewer=semantic_reviewer,
            )

            seen_targets = [target["pointer"] for request in agent_requests for target in request["targets"]]
            _case(self, "header_semantic_reviewer_was_invoked", len(reviewer_calls) > 0, True)
            _case(self, "header_pointer_never_enters_repair_targets", header_pointer in seen_targets, False)
            _case(self, "header_native_group_fields_remain_unchanged",
                  result["report"]["sections"][0]["groups"][0]["fields"][0], header_before)
            _case(self, "header_repair_keeps_source_digest_unchanged",
                  result["report"]["source_digest"], source_digest_before)
            _case(self, "unresolved_header_issue_is_not_marked_reviewed",
                  result["quality"] == "reviewed", False)
            _case(self, "unresolved_header_issue_remains_needs_review", result["quality"], "needs_review")
            _case(self, "fixture_repair_agent_only_received_record_targets",
                  all("/records/" in pointer for pointer in seen_targets), True)

    def test_overlong_chat_keeps_unique_action_and_limitation(self):
        from report_bridge.publication import PreparedPublication

        with native_host() as host:
            snapshot = host.capture()
            action = "UNIQUE_ACTION_KEEP_NATIVE_VALIDATION"
            limitation = "UNIQUE_LIMIT_KEEP_REAL_HOST_UNVERIFIED"
            snapshot["chat"] = {"result": "result", "changes": "long-detail-" * 180,
                                "limits": limitation, "next_action": action}
            try:
                output = chat_digest(snapshot, "report.md", "unreviewed", limit=180)
            except ContractError as exc:
                _case(self, "overlong_chat_requires_bounded_repair", str(exc), "CHAT_REQUIRES_BOUNDED_REPAIR")
            else:
                _case(self, "overlong_chat_retains_unique_action", action in output, True)
                _case(self, "overlong_chat_retains_unique_limitation", limitation in output, True)
            _case(self, "overlong_chat_source_action_unchanged", snapshot["chat"]["next_action"], action)
            _case(self, "overlong_chat_source_limitation_unchanged", snapshot["chat"]["limits"], limitation)
            ident = snapshot["identity"]
            _reject(self, "publication_rejects_chat_over_900", lambda: PreparedPublication.prepare(
                project_id=ident["project_id"], turn_id=ident["turn_id"],
                revision=snapshot["revision"], source_digest=snapshot["source_digest"],
                full_report=render(snapshot), short_chat="x" * 901),
                "chat_payload_exceeds_digest_budget")

    def test_production_projection_checker_repairs_only_long_chat_field(self):
        from report_bridge.ports import publish

        with native_host() as host:
            seed = host.capture()
            result = "UNIQUE_RESULT_KEEP_REPORT_OUTCOME"
            limitation = "UNIQUE_LIMIT_KEEP_REAL_HOST_UNVERIFIED"
            action = "UNIQUE_ACTION_KEEP_NATIVE_VALIDATION"
            original_chat = {
                "result": result,
                "changes": "REPEATED_DETAIL " * 220,
                "limits": limitation,
                "next_action": action,
            }
            draft = {
                "schema": "apcf.report-observation/1",
                "sections": copy.deepcopy(seed["sections"]),
                "chat": copy.deepcopy(original_chat),
            }
            turn_before = (host.turn / "TURN.md").read_bytes()
            current_path = host.root / "CURRENT.md"
            current_before = current_path.read_bytes()

            with self.assertRaisesRegex(ContractError, "CHAT_REQUIRES_BOUNDED_REPAIR"):
                publish(host.root, host.turn, draft=draft, request_id=host.request_id,
                        budget_seconds=2, agent=None, reviewer=None)
            _case(self, "overlong_without_agent_turn_not_partially_saved",
                  (host.turn / "TURN.md").read_bytes(), turn_before)
            _case(self, "overlong_without_agent_current_not_partially_saved",
                  current_path.read_bytes(), current_before)
            for name in (
                "report-quality-publication.json",
                "report-quality-delivery.json",
                "report-quality-snapshot-r1.json",
            ):
                _case(self, "overlong_without_agent_no_report_artifact_" + name,
                      (host.turn / "evidence" / name).exists(), False)

            observed_targets = []
            agent_requests = []
            repaired_changes = "仅保留本轮已核验的必要变更"

            def deterministic_fixture_agent(request, _remaining):
                agent_requests.append(copy.deepcopy(request))
                chat_targets = [target for target in request["targets"]
                                if target["pointer"].startswith("/chat/")]
                if len(chat_targets) != 1:
                    return {"base_digest": request["base_digest"], "changes": []}
                target = chat_targets[0]
                observed_targets.append(target)
                return {
                    "base_digest": request["base_digest"],
                    "changes": [{
                        "pointer": target["pointer"],
                        "before_digest": target["before_digest"],
                        "value": repaired_changes,
                    }],
                }

            published = publish(host.root, host.turn, draft=draft, request_id=host.request_id,
                                budget_seconds=2, agent=deterministic_fixture_agent, reviewer=None)
            _case(self, "production_projection_checker_emits_one_chat_target", len(observed_targets), 1)
            _case(self, "production_projection_checker_target_code",
                  observed_targets[0]["issue"]["code"], "QUALITY_CHAT_TOO_LONG")
            _case(self, "production_projection_checker_targets_longest_field",
                  observed_targets[0]["pointer"], "/chat/changes")
            _case(self, "deterministic_fixture_agent_was_called", len(agent_requests) >= 1, True)
            repaired_chat = published["snapshot"]["chat"]
            expected_chat = dict(original_chat, changes=repaired_changes)
            _case(self, "bounded_repair_changes_only_authorized_chat_field", repaired_chat, expected_chat)
            _case(self, "bounded_repair_result_not_marked_reviewed",
                  published["quality"] == "reviewed", False)
            _case(self, "bounded_repair_receipt_not_marked_reviewed",
                  published["receipt"]["quality"] == "reviewed", False)
            _case(self, "bounded_repair_receipt_persisted", published["receipt"]["persisted"], True)
            _case(self, "bounded_repair_stayed_within_two_round_limit",
                  published["repair"]["rounds"] <= 2, True)
            applied = [row for row in published["repair"]["history"] if row.get("result") == "applied"]
            _case(self, "bounded_repair_applied_one_authorized_change", len(applied), 1)
            _case(self, "bounded_repair_history_names_only_changes",
                  applied[0]["changed"], ["/chat/changes"])
            summary = chat_digest(published["snapshot"], "report.md", published["quality"])
            _case(self, "bounded_repair_summary_within_production_limit", len(summary) <= 900, True)
            for name, value in (("result", result), ("limitation", limitation), ("action", action)):
                _case(self, "bounded_repair_summary_keeps_unique_" + name, value in summary, True)
            _case(self, "bounded_repair_summary_keeps_repaired_change", repaired_changes in summary, True)
            _case(self, "bounded_repair_report_has_native_saved_receipt",
                  native.NativeReportWriter(host.root, host.turn, host.request_id,
                                            published["snapshot"]).last_report()["persisted"], True)

    def test_unicode_canonical_repair_packet_binds_exact_text(self):
        with native_host() as host:
            snapshot = host.capture()
            pointer = "/sections/3/records/0/fields/风险说明"
            original = "路径标记：Cafe\u0301 / 中文 / 😀"
            replacement = "已修复：Café 与原始来源保持绑定 😀"
            snapshot["sections"][3]["records"][0]["fields"]["风险说明"] = original
            packet = build_packet(snapshot, [pointer], diagnostics=[{"code": "fixture"}],
                                  rule_index={"rules": []}, example_index={"examples": []},
                                  policy_capsule={"scope": "authorized-text-only"})
            target = packet["targets"][0]
            _case(self, "unicode_packet_keeps_exact_source_text", target["before"], original)
            _case(self, "unicode_packet_uses_exact_digest", target["before_digest"], digest(original))
            _case(self, "unicode_packet_binds_base_snapshot", packet["base_digest"], digest(snapshot))
            response = {"base_digest": packet["base_digest"], "changes": [
                {"pointer": pointer, "before_digest": hash_value(original), "value": replacement}]}
            updated = apply_patch(snapshot, response, {pointer})
            _case(self, "unicode_repair_applies_exact_target", updated["sections"][3]["records"][0]["fields"]["风险说明"], replacement)
            stale = copy.deepcopy(response)
            stale["changes"][0]["before_digest"] = digest("路径标记：Café / 中文 / 😀")
            _reject(self, "unicode_normalized_lookalike_is_stale", lambda: apply_patch(snapshot, stale, {pointer}), "STALE_FIELD")

    def test_ports_prepared_summary_cannot_be_reported_observed(self):
        from report_bridge.ports import publish
        with native_host() as host:
            prepared = publish(host.root, host.turn, request_id=host.request_id,
                               budget_seconds=2, agent=None, reviewer=None)
            chat_path = host.root / prepared['receipt']['chat_path']
            metadata = chat_path.with_name(chat_path.name + '.apcf-meta.yaml').read_text('utf-8')
            _case(self, 'stored_chat_metadata_is_private', 'visibility: private' in metadata, True)
            _case(self, 'stored_chat_metadata_binds_transport_bytes',
                  'sha256: ' + hashlib.sha256(chat_path.read_bytes()).hexdigest() in metadata, True)
            target = host.root / "prepared-summary.txt"
            receipt = emit_summary(host.root, host.turn, host.request_id, target, observed=False)
            _case(self, "ports_prepare_status", receipt["status"], "PREPARED_SUMMARY_FOR_DELIVERY")
            sidecar = json.loads(target.with_name(target.name + ".binding.json").read_text(encoding="utf-8"))
            _case(self, "ports_prepare_binding_stage", sidecar["stage"], "prepared")
            _case(self, "ports_prepare_saved_report", receipt["current_saved"], True)
            _reject(self, "prepared_summary_not_observed", lambda: emit_summary(
                host.root, host.turn, host.request_id, target, observed=True), "ACTUAL_HOST_BINDING_REQUIRED")
            _case(self, "prepared_summary_result_retains_revision", prepared["receipt"]["revision"], receipt["revision"])

    def test_observe_saved_requires_enabled_config_and_exact_ack(self):
        from types import SimpleNamespace
        from report_bridge import ports, transport

        with native_host() as host:
            config_path = host.root / ".agent-project-control/runtime/tmp/report14/quality-observer.json"
            outbox = host.root / "synthetic-observer-outbox.json"
            audits = []
            store = SimpleNamespace(audit=lambda row: audits.append(copy.deepcopy(row)))
            observer_dir = config_path.parent
            observer_dir.mkdir(parents=True, exist_ok=True)
            (observer_dir / ".apcf-dir.yaml").write_text(
                '# APCF-META {"schema":1,"visibility":"private"}\nschema: 1\nvisibility: private\n',
                encoding="utf-8")

            _case(self, "observer_fixture_starts_without_config", config_path.exists(), False)
            with patch.object(transport, "send_once") as sender:
                missing = ports.observe_saved(host.root, outbox, store)
            _case(self, "observer_missing_config_disabled", missing,
                  {"status": "disabled", "confirmed": False})
            _case(self, "observer_missing_config_never_calls_sender", sender.call_count, 0)

            private_json(config_path, {"enabled": False, "endpoint": "https://observer.invalid/v1",
                                        "binding_file": "synthetic-binding.json"}, create=True)
            with patch.object(transport, "send_once") as sender:
                disabled = ports.observe_saved(host.root, outbox, store)
            _case(self, "observer_disabled_config_disabled", disabled,
                  {"status": "disabled", "confirmed": False})
            _case(self, "observer_disabled_config_never_calls_sender", sender.call_count, 0)

            from report_bridge.storage import envelope as make_envelope
            payload = make_envelope(host.capture(), "unreviewed")
            ack = {
                "schema": "apcf.observation-ack/1",
                "projectId": "fixture-project",
                "identity": payload["identity"],
                "revision": payload["revision"],
                "reportDigest": payload["report_digest"],
                "envelopeDigest": payload["envelope_digest"],
                "authority": "observation_only",
                "status": "stored",
                "locator": "https://observer.invalid/v1/observations/fixture",
            }
            private_json(config_path, {"enabled": True, "endpoint": "https://observer.invalid/v1",
                                       "binding_file": "synthetic-binding.json"})
            with patch.object(transport, "send_once", return_value=ack) as sender:
                confirmed = ports.observe_saved(host.root, outbox, store)
            _case(self, "observer_exact_ack_confirms", confirmed,
                  {"status": "confirmed", "confirmed": True, "ack": ack})
            _case(self, "observer_enabled_sender_called_once", sender.call_count, 1)
            _case(self, "observer_sender_uses_fixture_outbox_and_enabled", sender.call_args.args,
                  (outbox, "https://observer.invalid/v1", "APCF_OBSERVER_TOKEN"))
            _case(self, "observer_sender_is_explicitly_enabled", sender.call_args.kwargs["enabled"], True)
            _case(self, "observer_sender_uses_configured_binding", sender.call_args.kwargs["binding_file"],
                  "synthetic-binding.json")
            _case(self, "observer_confirmed_has_no_internal_audit", audits, [])

            with patch.object(transport, "send_once", side_effect=OSError("synthetic sender failure detail")):
                failed = ports.observe_saved(host.root, outbox, store)
            _case(self, "observer_sender_failure_unconfirmed", failed,
                  {"status": "unconfirmed", "confirmed": False})
            _case(self, "observer_sender_failure_audits_internal_type", audits,
                  [{"phase": "observer_unconfirmed", "error_type": "OSError"}])
            _case(self, "observer_sender_failure_detail_not_exposed", "synthetic sender failure detail" in str(failed), False)

    def test_transport_aemp_ack_replay_is_idempotent_and_locator_absolute(self):
        import os
        import urllib.parse
        from report_bridge import ports, transport
        from report_bridge.storage import envelope as make_envelope

        module_value = os.environ.get("AEMP_NATIVE_CONTRACTS_MODULE", "")
        module_path = Path(module_value).resolve(strict=True) if module_value else None
        native_module_arg = str(module_path) if module_path else None
        digest_stub_inputs = []
        if module_path:
            digest_case = "aemp_sender_uses_current_contracts_digest_module"
            _case(self, "aemp_digest_module_filename", module_path.name, "index.js")
            _case(self, "aemp_digest_module_dist_layout",
                  tuple(module_path.parents[index].name for index in (0, 1, 2)),
                  ("dist", "contracts", "packages"))
            digest_context = contextlib.nullcontext()
        else:
            # Deterministic fixture only; this does not implement or claim the AEMP digest algorithm.
            digest_case = "aemp_sender_uses_test_only_deterministic_digest_stub"
            _case(self, "aemp_digest_module_optional_when_unconfigured", module_value, "")
            _case(self, "aemp_digest_default_native_module_argument_absent", native_module_arg, None)

            def deterministic_digest_value(value):
                encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")
                return hashlib.sha256(encoded).hexdigest()

            def deterministic_digest_stub(value, _module_path=None):
                digest_stub_inputs.append(copy.deepcopy(value))
                return deterministic_digest_value(value)

            digest_context = patch.object(
                transport, "_native_object_digest", side_effect=deterministic_digest_stub)

        class FixtureResponse:
            def __init__(self, status, body):
                self.status = status
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit):
                return self.body

        class AempFixtureOpener:
            """AEMP confirmation/observation contract; the opener never reaches a socket."""

            def __init__(self, identity, owner_id, base_url):
                self.identity = identity
                self.owner_id = owner_id
                self.base_url = base_url
                self.get_count = 0
                self.post_count = 0
                self.requests = []
                self.post_envelope = None
                self.post_ack = None
                self.replay_ack = None

            def ack_for(self, envelope, status):
                identity = envelope["identity"]
                observation_id = transport._native_object_digest(
                    [self.owner_id, identity["project_id"], identity["producer_id"],
                     identity["iteration_id"], identity["turn_id"]],
                    native_module_arg,
                )
                project_id = identity["project_id"]
                locator = "/?project=" + urllib.parse.quote(project_id, safe="")
                locator += "&observation=" + observation_id + "&tab=result"
                revision = envelope["revision"]
                return {
                    "schema": "apcf.observation-ack/1",
                    "identity": identity,
                    "projectId": project_id,
                    "revision": revision,
                    "reportDigest": envelope["report_digest"],
                    "envelopeDigest": envelope["envelope_digest"],
                    "locator": locator,
                    "artifactId": f"report-{observation_id[:36]}-{revision}",
                    "status": status,
                    "authority": "observation_only",
                }

            def open(self, request, timeout=10):
                method = request.get_method()
                raw = request.data or b""
                headers = {key.lower(): value for key, value in request.header_items()}
                row = {
                    "method": method,
                    "url": request.full_url,
                    "timeout": timeout,
                    "body_bytes": len(raw),
                    "body_sha256": hashlib.sha256(raw).hexdigest() if raw else None,
                    "idempotency_key": headers.get("idempotency-key"),
                    "native_object_digest": headers.get("x-aemp-object-digest"),
                }
                self.requests.append(row)
                if method == "GET":
                    self.get_count += 1
                    if self.get_count == 1:
                        row["fixture_status"] = 404
                        return FixtureResponse(404, b'{"error":"observation_not_found"}')
                    self.replay_ack = dict(self.post_ack)
                    self.replay_ack["status"] = "already_stored"
                    row["fixture_status"] = 200
                    row["response_ack"] = self.replay_ack
                    return FixtureResponse(
                        200, json.dumps(self.replay_ack, ensure_ascii=False).encode("utf-8"))
                if method != "POST":
                    raise AssertionError("fixture opener received an unexpected method")
                self.post_count += 1
                self.post_envelope = json.loads(raw.decode("utf-8"))
                self.post_ack = self.ack_for(self.post_envelope, "stored")
                row["fixture_status"] = 201
                row["response_ack"] = self.post_ack
                return FixtureResponse(
                    201, json.dumps(self.post_ack, ensure_ascii=False).encode("utf-8"))

        with native_host() as host, digest_context:
            identity = host.capture()["identity"]
            owner_id = "quality-selfcheck-observer-owner"
            endpoint = (
                "https://observer.invalid/machine/v1/report-observations/projects/"
                + urllib.parse.quote(identity["project_id"], safe="")
                + "/"
                + urllib.parse.quote(identity["producer_id"], safe="")
            )
            observer_dir = host.root / ".agent-project-control/runtime/tmp/report14"
            observer_dir.mkdir(parents=True, exist_ok=True)
            binding_path = observer_dir / "synthetic-observer-binding.json"
            binding = {
                "ownerId": owner_id,
                "projectId": identity["project_id"],
                "producerId": identity["producer_id"],
                "externalProjectId": identity["project_id"],
                "mode": "observe",
                "enabled": True,
                "iterationMappings": {
                    identity["iteration_id"]: {"externalIterationId": identity["iteration_id"]}
                },
                "turnMappings": {
                    identity["turn_id"]: {
                        "externalIterationId": identity["iteration_id"],
                        "externalTurnId": identity["turn_id"],
                    }
                },
            }
            private_json(binding_path, binding, create=True)
            config_path = observer_dir / "quality-observer.json"
            observer_config = {
                "enabled": True,
                "endpoint": endpoint,
                "token_env": "AEMP_SELFCHK_FIXTURE_TOKEN",
                "binding_file": str(binding_path),
                "timeout": 5,
            }
            if native_module_arg:
                observer_config["native_contracts_module"] = native_module_arg
            private_json(config_path, observer_config, create=True)

            opener = AempFixtureOpener(identity, owner_id, endpoint)
            with patch.dict(os.environ, {
                "AEMP_SELFCHK_FIXTURE_TOKEN": "aemp-report.synthetic-fixture-token",
                "AEMP_NATIVE_CONTRACTS_MODULE": native_module_arg or "",
            }), patch.object(transport.urllib.request, "build_opener", return_value=opener):
                published = ports.publish(
                    host.root, host.turn, request_id=host.request_id,
                    budget_seconds=30, agent=None, reviewer=None)

            receipt = published["receipt"]
            payload = make_envelope(published["snapshot"], published["quality"])
            outbox = (host.root / ".agent-project-control/runtime/tmp/report14/quality/outbox"
                      / (payload["envelope_digest"] + ".json"))
            ack_path = outbox.with_suffix(".ack.json")
            first_ack = receipt["observation"]["ack"]
            first_ack_bytes = ack_path.read_bytes()
            expected_absolute = urllib.parse.urljoin(endpoint, opener.post_ack["locator"])
            post = next(row for row in opener.requests if row["method"] == "POST")
            expected_post_digest = (
                transport._native_object_digest(opener.post_envelope, native_module_arg)
                if module_path else deterministic_digest_value(opener.post_envelope)
            )

            _case(self, "aemp_sender_first_post_confirmed",
                  (receipt["observation"]["status"], receipt["observation"]["confirmed"]),
                  ("confirmed", True))
            _case(self, "aemp_sender_first_call_method_order",
                  [row["method"] for row in opener.requests], ["GET", "POST"])
            _case(self, "aemp_sender_posts_exact_outbox_bytes",
                  post["body_sha256"], hashlib.sha256(outbox.read_bytes()).hexdigest())
            _case(self, "aemp_sender_posts_full_canonical_envelope",
                  post["body_bytes"], len(outbox.read_bytes()))
            if module_path:
                _case(self, digest_case, post["native_object_digest"], expected_post_digest)
            else:
                _case(self, digest_case,
                      ("test_only_sha256_over_sorted_compact_json", native_module_arg,
                       post["native_object_digest"], opener.post_envelope in digest_stub_inputs),
                      ("test_only_sha256_over_sorted_compact_json", None,
                       expected_post_digest, True))
            _case(self, "aemp_sender_initial_ack_status", first_ack["status"], "stored")
            _case(self, "aemp_sender_initial_locator_absolute_same_origin",
                  first_ack["locator"], expected_absolute)
            _case(self, "aemp_sender_ack_file_matches_first_ack_bytes",
                  first_ack_bytes, transport.canonical(first_ack))
            _case(self, "aemp_sender_first_chat_links_absolute_locator",
                  expected_absolute in published["chat"], True)
            _case(self, "aemp_sender_first_chat_does_not_link_relative_locator",
                  "](" + opener.post_ack["locator"] + ")" in published["chat"], False)

            # Recreate the exact legacy persistence shape before the AEMP GET replay.
            legacy_ack = copy.deepcopy(first_ack)
            legacy_ack["locator"] = opener.post_ack["locator"]
            legacy_ack_bytes = transport.canonical(legacy_ack)
            ack_path.write_bytes(legacy_ack_bytes)
            _case(self, "aemp_sender_legacy_ack_fixture_has_relative_locator",
                  json.loads(legacy_ack_bytes)["locator"].startswith("/"), True)

            with patch.dict(os.environ, {
                "AEMP_SELFCHK_FIXTURE_TOKEN": "aemp-report.synthetic-fixture-token",
                "AEMP_NATIVE_CONTRACTS_MODULE": native_module_arg or "",
            }), patch.object(transport.urllib.request, "build_opener", return_value=opener):
                replay_ack = transport.send_once(
                    outbox, endpoint, "AEMP_SELFCHK_FIXTURE_TOKEN", enabled=True,
                    binding_file=binding_path, native_contracts_module=native_module_arg, timeout=5)

            _case(self, "aemp_sender_replay_query_method_order",
                  [row["method"] for row in opener.requests], ["GET", "POST", "GET"])
            _case(self, "aemp_sender_replay_does_not_post_again", opener.post_count, 1)
            _case(self, "aemp_sender_accepts_stored_to_already_stored_replay",
                  replay_ack["status"], "already_stored")
            _case(self, "aemp_sender_replay_locator_is_absolute_same_origin",
                  replay_ack["locator"], expected_absolute)
            _case(self, "aemp_sender_replay_preserves_legacy_ack_file_bytes",
                  ack_path.read_bytes(), legacy_ack_bytes)
            persisted_after_replay = json.loads(ack_path.read_text(encoding="utf-8"))
            _case(self, "aemp_sender_replay_preserves_first_ack_status",
                  persisted_after_replay["status"], "stored")
            _case(self, "aemp_sender_replay_preserves_first_relative_locator",
                  persisted_after_replay["locator"], opener.post_ack["locator"])

            envelope = json.loads(outbox.read_text(encoding="utf-8"))
            bound = transport._binding(binding_path, envelope["identity"])
            ack_base = copy.deepcopy(replay_ack)
            mutations = [
                ("aemp_ack_wrong_identity_rejected", "ACK_BINDING_MISMATCH",
                 lambda value: value.update(identity={**value["identity"], "turn_id": "TR-foreign"})),
                ("aemp_ack_wrong_project_rejected", "ACK_BINDING_MISMATCH",
                 lambda value: value.update(projectId="foreign-project")),
                ("aemp_ack_wrong_report_digest_rejected", "ACK_BINDING_MISMATCH",
                 lambda value: value.update(reportDigest="0" * 64)),
                ("aemp_ack_wrong_envelope_digest_rejected", "ACK_BINDING_MISMATCH",
                 lambda value: value.update(envelopeDigest="1" * 64)),
                ("aemp_ack_wrong_revision_rejected", "ACK_BINDING_MISMATCH",
                 lambda value: value.update(revision=value["revision"] + 1)),
                ("aemp_ack_cross_origin_locator_rejected", "ACK_CROSS_ORIGIN",
                 lambda value: value.update(locator="https://foreign.invalid/?project=project")),
                ("aemp_ack_unknown_status_rejected", "ACK_SCOPE",
                 lambda value: value.update(status="pending")),
            ]
            for name, code, mutate in mutations:
                with self.subTest(ack_mutation=name):
                    changed = copy.deepcopy(ack_base)
                    mutate(changed)
                    _reject(self, name,
                            lambda changed=changed: transport._ack(changed, envelope, bound, endpoint), code)

            different_locator = copy.deepcopy(ack_base)
            parsed_locator = urllib.parse.urlsplit(different_locator["locator"])
            different_locator["locator"] = urllib.parse.urlunsplit((
                parsed_locator.scheme, parsed_locator.netloc, "/different-reader", parsed_locator.query, ""))
            _reject(self, "aemp_ack_same_origin_different_locator_rejected",
                    lambda: transport._persist_ack(outbox, different_locator), "ACK_COLLISION")
            different_artifact = copy.deepcopy(ack_base)
            different_artifact["artifactId"] += "-different"
            _reject(self, "aemp_ack_artifact_id_drift_rejected",
                    lambda: transport._persist_ack(outbox, different_artifact), "ACK_COLLISION")
            invalid_persisted_status = copy.deepcopy(ack_base)
            invalid_persisted_status["status"] = "pending"
            _reject(self, "aemp_ack_invalid_persisted_status_rejected",
                    lambda: transport._persist_ack(outbox, invalid_persisted_status), "ACK_COLLISION")
            _case(self, "aemp_ack_negative_cases_preserve_first_ack_bytes",
                  ack_path.read_bytes(), legacy_ack_bytes)

    def test_publication_enqueue_failure_keeps_saved_report_valid(self):
        from report_bridge.native import NativeReportWriter
        from report_bridge.ports import publish
        from report14.bindings import report_text

        with native_host() as host:
            with patch("report_bridge.ports.enqueue", side_effect=OSError("fixture observer offline")):
                published = publish(host.root, host.turn, request_id=host.request_id,
                                     budget_seconds=2, agent=None, reviewer=None)
            _case(self, "enqueue_failure_report_receipt_persisted",
                  published["receipt"]["persisted"], True)
            _case(self, "enqueue_failure_report_still_reads_as_saved",
                  NativeReportWriter(host.root, host.turn, host.request_id,
                                     published["snapshot"]).last_report()["report_digest"],
                  published["receipt"]["report_digest"])
            _case(self, "enqueue_failure_keeps_summary_available",
                  bool(published["chat"]), True)
            _case(self, "enqueue_failure_does_not_add_archive_warning",
                  "归档尚未确认" in published["chat"], False)
            _case(self, "enqueue_failure_current_and_turn_still_match",
                  report_text((host.root / "CURRENT.md").read_text(encoding="utf-8-sig")) ==
                  report_text((host.turn / "TURN.md").read_text(encoding="utf-8-sig")), True)

    def test_native_write_failure_is_not_reported_saved_or_leaked(self):
        from report_bridge.native import NativeReportWriter

        with native_host() as host:
            turn_before = (host.turn / "TURN.md").read_bytes()
            current_path = host.root / "CURRENT.md"
            current_before = current_path.read_bytes()
            delivered = []
            with patch.object(NativeReportWriter, "save_report",
                              side_effect=OSError("sensitive internal stack")):
                receipt = _transport(host, lambda text, binding: delivered.append((text, binding)))
            _case(self, "native_write_failure_reports_unsaved", receipt["saved"], False)
            _case(self, "native_write_failure_fallback_sent_once", len(delivered), 1)
            text, _binding = delivered[0]
            _case(self, "native_write_failure_hides_internal_error",
                  "sensitive internal stack" in text, False)
            _case(self, "native_write_failure_says_save_unconfirmed",
                  "尚未确认保存" in text, True)
            _case(self, "native_write_failure_preserves_turn", (host.turn / "TURN.md").read_bytes(), turn_before)
            _case(self, "native_write_failure_preserves_current", current_path.read_bytes(), current_before)
            for name in ("report-quality-publication.json", "report-quality-delivery.json",
                         "report-quality-snapshot-r1.json"):
                _case(self, "native_write_failure_no_partial_" + name,
                      (host.turn / "evidence" / name).exists(), False)

    def test_runtime_two_argument_sink_can_be_observed_in_fixture(self):
        from report14.bindings import report_text
        from report_bridge.publication import PreparedPublication

        with native_host() as host:
            delivered = []
            receipt = _transport(host, lambda text, binding: delivered.append((text, binding)))
            _case(self, "two_arg_transport_saved", receipt["saved"], True)
            _case(self, "two_arg_transport_binding_sent", receipt["host_binding_sent"], True)
            _case(self, "two_arg_transport_sink_called_once", len(delivered), 1)
            text, binding = delivered[0]
            _case(self, "two_arg_transport_sends_only_short_summary", len(text) < 900, True)
            _case(self, "two_arg_transport_does_not_send_full_report_heading", "## 1." in text, False)
            target = host.root / "synthetic-captured-summary.txt"
            _write_capture(host, target, text, binding)
            observed = emit_summary(host.root, host.turn, host.request_id, target, observed=True)
            _case(self, "synthetic_capture_observed_status", observed["status"], "OBSERVED_SUMMARY_MATCH")
            _case(self, "synthetic_capture_not_desktop_host", observed["business_finalized"], False)
            _case(self, "observed_summary_uses_same_revision", observed["revision"], binding["revision"])
            _case(self, "observed_summary_uses_same_source_digest",
                  observed["source_digest"], binding["source_digest"])
            full_report = report_text((host.root / "CURRENT.md").read_text(encoding="utf-8-sig"))
            _reject(self, "publication_rejects_full_report_as_chat", lambda: PreparedPublication.prepare(
                project_id=binding["identity"]["project_id"],
                turn_id=binding["identity"]["turn_id"], revision=binding["revision"],
                source_digest=binding["source_digest"], full_report=full_report,
                short_chat="## 1. a\n## 2. b\n## 3. c\n"),
                "full_report_cannot_be_chat_payload")

    def test_actual_capture_rejects_request_source_and_revision_drift(self):
        with native_host() as host:
            delivered = []
            _transport(host, lambda text, binding: delivered.append((text, binding)))
            text, binding = delivered[0]
            target = host.root / "synthetic-drift-capture.txt"
            _write_capture(host, target, text, binding)
            binding_path = target.with_name(target.name + ".binding.json")
            original = json.loads(binding_path.read_text(encoding="utf-8"))
            target.write_text(text + "\nfixture captured-text drift\n", encoding="utf-8")
            _reject(self, "capture_sent_text_drift", lambda: emit_summary(
                host.root, host.turn, host.request_id, target, observed=True),
                "sent_message_changed_after_validation")
            target.write_text(text, encoding="utf-8")
            _case(self, "capture_sent_text_restored", target.read_text(encoding="utf-8"), text)
            mutations = [
                ("capture_request_drift", "CAPTURE_IDENTITY_CHANGED", {"request_id": "wrong-fixture-request"}),
                ("capture_source_digest_drift", "sent_message_revision_mismatch", {"source_digest": "0" * 64}),
                ("capture_revision_drift", "sent_message_revision_mismatch", {"revision": original["revision"] + 1}),
                ("capture_stale_revision", "sent_message_revision_mismatch", {"revision": original["revision"] - 1}),
                ("capture_report_digest_drift", "CAPTURE_IDENTITY_CHANGED", {"report_digest": "0" * 64}),
            ]
            for name, code, update in mutations:
                with self.subTest(binding_mutation=name):
                    changed = dict(original);changed.update(update)
                    private_json(binding_path, changed)
                    _reject(self, name, lambda: emit_summary(
                        host.root, host.turn, host.request_id, target, observed=True), code)
            private_json(binding_path, original)
            good = emit_summary(host.root, host.turn, host.request_id, target, observed=True)
            _case(self, "capture_drift_restored_binding_observed", good["status"], "OBSERVED_SUMMARY_MATCH")

    def test_runtime_single_argument_sink_is_unverified(self):
        with native_host() as host:
            received = []
            receipt = _transport(host, lambda text: received.append(text))
            _case(self, "single_arg_transport_saved", receipt["saved"], True)
            _case(self, "single_arg_transport_has_no_binding", receipt["host_binding_sent"], False)
            _case(self, "single_arg_transport_scope_unverified", "unverified" in receipt["host_scope"], True)
            _case(self, "single_arg_transport_called_once", len(received), 1)

    def test_durable_report_survives_fixture_cache_cleanup_and_identity_readback(self):
        import shutil
        from report14.bindings import report_text
        from report14.bridge import state_errors
        from report_bridge.ports import prepared, publish

        with native_host() as host:
            iteration = host.turn.parents[1]
            index = host.root / ".agent-project-control/iterations/INDEX.md"
            index_text = index.read_text(encoding="utf-8-sig")
            if iteration.name not in index_text:
                index.write_text(index_text.rstrip() + "\n\n- `" + iteration.name + "`\n", encoding="utf-8")

            source_test = next(row for row in __import__("test_ledger").parse_tests(
                (host.turn / "TEST.md").read_text(encoding="utf-8-sig")) if row["id"] == "TEST-01")
            published = publish(host.root, host.turn, request_id=host.request_id,
                                budget_seconds=2, agent=None, reviewer=None)
            snapshot = published["snapshot"]
            receipt_path = host.turn / "evidence/report-quality-publication.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
            delivery = json.loads((host.turn / "evidence/report-quality-delivery.json").read_text(encoding="utf-8-sig"))
            durable_path = host.root / receipt["snapshot_path"]
            durable = json.loads(durable_path.read_text(encoding="utf-8-sig"))
            durable_snapshot = durable["snapshot"]

            current_path = host.root / "CURRENT.md"
            saved_current = current_path.read_bytes()
            current_path.write_bytes(saved_current + b"\nfixture CURRENT drift\n")
            writer = native.NativeReportWriter(host.root, host.turn, host.request_id, durable_snapshot)
            _reject(self, "saved_current_drift_rejected_on_readback",
                    lambda: writer.read_saved_report(receipt), "report presentation binding mismatch")
            current_path.write_bytes(saved_current)
            _case(self, "saved_current_restored_after_negative_readback",
                  current_path.read_bytes(), saved_current)

            actual = durable_snapshot["sections"][5]["records"][0]["fields"]["实际结果"]
            _case(self, "durable_actual_field_matches_source_TEST", actual, source_test["actual"])
            _case(self, "durable_native_TEST_fact_matches_source_actual",
                  durable_snapshot["facts"]["native-TEST-01"]["value"]["actual"], source_test["actual"])
            source_commitments = {key: source_test[key] for key in (
                "purpose", "context", "action", "expected", "actual", "evidence")}
            native_commitments = {key: durable_snapshot["facts"]["native-TEST-01"]["value"].get(key)
                                  for key in source_commitments}
            _case(self, "durable_native_TEST_commitments_match_original_ledger",
                  native_commitments, source_commitments)
            native_test_record = next(row for row in durable_snapshot["sections"][5]["records"]
                                      if row["id"] == "TEST-01")
            _case(self, "durable_rendered_TEST_preserves_original_method_and_expected_result",
                  (native_test_record["fields"]["验收方式"],
                   native_test_record["fields"]["预期结果"],
                   native_test_record["fields"]["实际结果"]),
                  (source_test["context"] + "；" + source_test["action"],
                   source_test["expected"], source_test["actual"]))
            _case(self, "durable_receipt_request_matches_fixture", durable["receipt"]["request_id"], host.request_id)
            _case(self, "durable_receipt_identity_matches_publication", durable["receipt"]["identity"], receipt["identity"])
            _case(self, "durable_delivery_identity_matches_publication", delivery["identity"], receipt["identity"])
            _case(self, "durable_snapshot_path_is_turn_owned",
                  receipt["snapshot_path"], durable_path.relative_to(host.root).as_posix())

            evidence_records = durable_snapshot["sections"][6]["records"]
            _case(self, "native_EV_derived_from_actual_TEST_evidence_count", len(evidence_records), 1)
            ev = evidence_records[0]
            _case(self, "native_EV_record_ref_is_actual_TEST", ev["record_refs"], ["TEST-01"])
            _case(self, "native_EV_fact_ref_is_actual_TEST", ev["fact_refs"], ["native-TEST-01"])
            expected_test_evidence_ref = ev["id"] + "；" + source_test["evidence"]
            _case(self, "native_TEST_backreferences_derived_EV_and_retains_original_path",
                  (native_test_record["fields"]["关联证据"],
                   native_test_record["locked"]["关联证据"]),
                  (expected_test_evidence_ref, expected_test_evidence_ref))
            _case(self, "native_EV_preserves_original_TEST_object_and_purpose",
                  ev["fields"]["关联事项"],
                  "TEST-01 " + source_test["object"] + "：" + source_test["purpose"])
            _case(self, "native_EV_proof_text_uses_source_actual",
                  ev["fields"]["证明内容"], "当前验收记录的实际观察为：" + source_test["actual"])

            cache_roots = [
                host.root / ".agent-project-control/runtime/cache",
                host.root / ".agent-project-control/runtime/tmp/report14",
            ]
            removed_count = 0
            fixture_root = host.root.resolve(strict=True)
            for cache_root in cache_roots:
                if not cache_root.exists():
                    continue
                if cache_root.is_symlink():
                    raise AssertionError("fixture cache root unexpectedly became a symlink")
                resolved_cache = cache_root.resolve(strict=True)
                if fixture_root not in resolved_cache.parents:
                    raise AssertionError("fixture cache cleanup target escaped synthetic host")
                for child in resolved_cache.rglob("*"):
                    if child.is_symlink():
                        raise AssertionError("fixture cache cleanup refuses nested symlinks")
                    resolved_child = child.resolve(strict=True)
                    if resolved_child != resolved_cache and resolved_cache not in resolved_child.parents:
                        raise AssertionError("fixture cache child escaped its owned tree")
                for child in list(resolved_cache.iterdir()):
                    if cache_root.name == "cache" and child.name == ".apcf-dir.yaml":
                        continue
                    if child.is_dir():
                        removed_count += sum(1 for _ in child.rglob("*")) + 1
                        shutil.rmtree(child)
                    else:
                        child.unlink()
                        removed_count += 1
            _case(self, "fixture_runtime_cache_material_removed_before_readback", removed_count > 0, True)

            reread = prepared(host.root, host.turn, host.request_id)
            _case(self, "prepared_report_readable_after_runtime_cache_cleanup",
                  report_text(reread["report"]) == report_text((host.root / "CURRENT.md").read_text(encoding="utf-8-sig")), True)
            reread_actual = reread["snapshot"]["sections"][5]["records"][0]["fields"]["实际结果"]
            _case(self, "prepared_field_matches_source_after_cache_cleanup", reread_actual, source_test["actual"])
            _case(self, "prepared_receipt_identity_matches_after_cache_cleanup",
                  reread["receipt"]["identity"], receipt["identity"])
            changed_field = copy.deepcopy(reread["snapshot"])
            changed_field["sections"][5]["records"][0]["fields"]["实际结果"] = "tampered fixture result"
            _reject(self, "durable_source_field_identity_drift_after_cache_cleanup", lambda: assert_same_authority(
                changed_field, reread["snapshot"]), "MACHINE_FACTS_CHANGED")
            foreign_receipt = copy.deepcopy(receipt)
            foreign_receipt["request_id"] = "foreign-fixture-request"
            writer = native.NativeReportWriter(host.root, host.turn, host.request_id, reread["snapshot"])
            _reject(self, "durable_receipt_identity_drift_after_cache_cleanup", lambda: writer.read_saved_report(
                foreign_receipt), "NATIVE_RECEIPT_IDENTITY_CHANGED")
            _case(self, "current_turn_state_valid_after_cache_cleanup", state_errors(host.root), [])

    def test_report14_keypoints_accept_only_complete_typed_or_legacy_blocks(self):
        from report14.bridge import keypoints

        legacy = (
            "## 11. 关键要点\n\n"
            "**旧式标题：**\n\n"
            "- 关键事实：旧格式事实\n"
            "- 实际含义：旧格式含义\n"
        )
        _case(self, "keypoints_legacy_colon_heading_remains_valid",
              len(keypoints(legacy)), 1)

        negative_reports = {
            "keypoints_ordinary_bold_paragraph_rejected": (
                "**普通说明段**\n\n这不是报告要点。\n"
            ),
            "keypoints_code_fence_fake_title_and_fields_rejected": (
                "```markdown\n**伪造标题**\n\n"
                "- 关键事实：代码示例中的事实\n"
                "- 实际含义：代码示例中的含义\n```\n"
            ),
            "keypoints_missing_required_field_rejected": (
                "**缺少字段**\n\n- 关键事实：事实\n"
            ),
            "keypoints_duplicate_required_field_rejected": (
                "**重复字段**\n\n- 关键事实：事实\n"
                "- 关键事实：重复事实\n- 实际含义：含义\n"
            ),
            "keypoints_wrong_field_order_rejected": (
                "**字段错序**\n\n- 实际含义：含义\n- 关键事实：事实\n"
            ),
            "keypoints_empty_required_field_rejected": (
                "**空字段**\n\n- 关键事实：   \n- 实际含义：含义\n"
            ),
            "keypoints_ordinary_bold_with_fenced_fake_fields_rejected": (
                "**普通说明段**\n\n```markdown\n"
                "- 关键事实：伪造事实\n- 实际含义：伪造含义\n```\n"
            ),
        }
        for name, body in negative_reports.items():
            with self.subTest(keypoint_case=name):
                report = "## 11. 关键要点\n\n" + body
                _case(self, name, keypoints(report), [])

    def test_rendered_native_keypoints_bind_variable_prose_review_takeaways(self):
        from prose_review import draft as draft_review, validate as validate_prose_review
        from repair_io import digest as byte_digest
        from report14.bridge import keypoints

        with native_host() as host:
            snapshot = host.capture()
            source_keypoints = [
                {"title": "原生要点甲", "fact": "保存结果来自当前原生事务",
                 "meaning": "读者可据此区分本地保存与外部接收"},
                {"title": "原生要点乙", "fact": "来源摘要绑定当前请求字节",
                 "meaning": "请求变化后旧报告不可复用"},
                {"title": "原生要点丙", "fact": "观察确认与业务收口保持分离",
                 "meaning": "确认接收不代表业务 Finalize"},
            ]
            snapshot["sections"][10] = {"number": 11, "keypoints": source_keypoints}
            report = render(snapshot)
            blocks = keypoints(report)
            _case(self, "native_render_emits_three_actual_keypoint_blocks",
                  len(blocks), 3)
            _case(self, "native_render_keypoint_titles_and_facts_are_preserved",
                  all(item["title"] in block and item["fact"] in block
                      for item, block in zip(source_keypoints, blocks)), True)

            review = draft_review(report, host.turn)
            review["reviewer"]["identity"] = "synthetic selfcheck fixture"
            _case(self, "prose_review_draft_starts_without_fabricated_takeaways",
                  review["takeaways"], [])
            missing_takeaway_errors = validate_prose_review(report, host.turn, review)
            _case(self, "prose_review_requires_each_actual_rendered_takeaway",
                  any("every actual takeaway needs evidence-bound review" in error
                      for error in missing_takeaway_errors), True)

            units = review["explanation_coverage"]
            for index, unit in enumerate(units):
                unit["importance"] = "core" if index == 0 else "supporting"
                unit["takeaway_indexes"] = list(range(len(blocks))) if index == 0 else []
                unit["reason"] = "synthetic fixture maps the actual report explanation to its displayed takeaways"
            review["takeaways"] = [
                {"sha256": byte_digest(block.encode("utf-8")),
                 "observation": "synthetic structure probe for rendered block " + str(index + 1),
                 "source_units": [units[0]["id"]]}
                for index, block in enumerate(blocks)
            ]
            complete_errors = validate_prose_review(report, host.turn, review)
            _case(self, "prose_review_accepts_exact_three_rendered_takeaway_bindings",
                  any("every actual takeaway needs evidence-bound review" in error
                      for error in complete_errors), False)
            review["takeaways"].pop()
            short_errors = validate_prose_review(report, host.turn, review)
            _case(self, "prose_review_rejects_a_missing_rendered_takeaway_binding",
                  any("every actual takeaway needs evidence-bound review" in error
                      for error in short_errors), True)

    def test_rendered_local_alias_and_internal_identifier_review_wiring(self):
        from report_bridge import native
        from report14.bindings import is14
        import terminology_review
        import writing_guard

        with native_host() as host:
            baseline = host.capture()
            draft = copy.deepcopy(baseline)
            tr_description = (
                "TR 用于标识一次独立执行轮次；本轮用它区分当前保存的执行记录；"
                "像一张按请求保存的工单档案；当前没有确认其英文官方全称"
            )
            draft["sections"][2] = {"number": 3, "terms": [{
                "registry_key": "TR", "abbreviation": "TR",
                "english": "POLLUTED_OFFICIAL_EXPANSION", "chinese": "污染的名称",
                "kind": "abbreviation", "description": tr_description,
            }]}
            draft["sections"][9] = {"number": 10, "subsections": [{
                "title": "本地编号说明",
                "paragraphs": ["TR 用于标识一次独立执行轮次；本轮用它区分当前保存的执行记录"],
            }]}
            snapshot = native.capture(host.root, host.turn, host.request_id, draft=draft)
            report = render(snapshot)
            term = snapshot["sections"][2]["terms"][0]
            registry_rel = ".agent-project-control/reporting/quality/term-registry.json"
            registry_bytes = (host.root / registry_rel).read_bytes()
            expected_sha = hashlib.sha256(registry_bytes).hexdigest()
            _case(self, "local_alias_metadata_is_overwritten_from_verified_registry",
                  (term["english"], term["chinese"], term["kind"], term["definition_source"]),
                  ("independent execution record for one user Turn",
                   "一次用户 Turn 的独立执行记录", "local_alias", registry_rel + "#TR"))
            _case(self, "local_alias_registry_source_bytes_are_bound",
                  snapshot["native_sources"].get(registry_rel), expected_sha)
            _case(self, "local_alias_title_uses_chinese_without_claiming_official_expansion",
                  "**TR 一次用户 Turn 的独立执行记录**" in report and
                  "independent execution record for one user Turn）" not in report, True)

            required = []
            for abbreviation, english, chinese, key in (
                    ("IT", "polluted IT expansion", "污染IT名称", "IT"),
                    ("EV", "polluted EV expansion", "污染EV名称", "EV")):
                required.append({"registry_key": key, "abbreviation": abbreviation,
                                 "english": english, "chinese": chinese,
                                 "kind": "abbreviation", "description": abbreviation + " 的合成说明"})
            required.append({"registry_key": "Codex", "abbreviation": "",
                             "english": "polluted Codex expansion", "chinese": "污染名称",
                             "kind": "proper_name", "description": "Codex 的合成说明"})
            draft["sections"][2] = {"number": 3, "terms": required + draft["sections"][2]["terms"]}
            full_snapshot = native.capture(host.root, host.turn, host.request_id, draft=draft)
            full_report = render(full_snapshot)
            _case(self, "formal_IT_and_EV_expansions_remain_visible",
                  ("**IT 迭代（Iteration）**" in full_report,
                   "**EV 证据（Evidence）**" in full_report), (True, True))
            _case(self, "proper_name_keeps_chinese_english_name_structure",
                  "**OpenAI Codex 编程代理（Codex）**" in full_report, True)
            _case(self, "registry_definition_metadata_remains_bound_without_title_expansion",
                  (full_snapshot["sections"][2]["terms"][0]["english"],
                   full_snapshot["sections"][2]["terms"][0]["chinese"],
                   full_snapshot["sections"][2]["terms"][0]["kind"]),
                  ("Iteration", "迭代", "abbreviation"))

            polluted = copy.deepcopy(full_snapshot)
            polluted["sections"][2]["terms"].append({
                "registry_key": "QX", "abbreviation": "QX", "english": "QX",
                "chinese": "合成缩写", "kind": "abbreviation", "description": "自展开负向用例",
            })
            term_issues = [issue.code for issue in validate(polluted)
                           if issue.pointer.endswith("/terms/4")]
            _case(self, "self_expanding_acronym_still_fails_real_contract_validation",
                  "TERM_SELF_EXPANSION" in term_issues, True)

            evidence_path = host.turn / "evidence" / "term-registry-fixture.json"
            evidence_path.write_bytes(registry_bytes)
            evidence_rel = evidence_path.relative_to(host.turn).as_posix()
            rendered_glossary = next(line for line in report.splitlines()
                                     if line.startswith("- **TR "))
            source_evidence = {
                "path": evidence_rel,
                "sha256": hashlib.sha256(registry_bytes).hexdigest(),
                "excerpt": "independent execution record for one user Turn",
            }
            tr_candidate = next(row for row in terminology_review.candidates(report)
                               if row["term"] == "TR")
            meaning = {
                "meaning_id": "synthetic-TR-internal-identifier",
                "line_numbers": tr_candidate["line_numbers"],
                "decision": "EXPLAINED",
                "reason": "fixture verifies the registered local identifier category",
                "audience_context": "a reader of this synthetic native report",
                "domain_context": "the current APCF report fixture",
                "current_use": "distinguishes the one saved execution record",
                "context_relevance": "本轮用它区分当前保存的执行记录",
                "source_or_basis": "evidence/term-registry-fixture.json#TR registry entry",
                "reviewer": "synthetic fixture, not a human reviewer",
                "reviewed_at": "2026-10-12T00:00:00Z",
                "term_kind": "internal_identifier",
                "name_status": "UNVERIFIED",
                "verified_full_name": "",
                "name_limit": "当前没有确认其英文官方全称",
                "definition": "用于标识一次独立执行轮次",
                "chinese_name": "一次用户 Turn 的独立执行记录",
                "display_name": "TR 一次用户 Turn 的独立执行记录",
                "analogy": "像一张按请求保存的工单档案",
                "analogy_basis": "它把本次请求与证据记录集中起来",
                "visible_explanation": __import__("prose_review").locate(report, rendered_glossary),
                "source_evidence": source_evidence,
            }
            term_review = {"review_method": "author_self_review", "items": [{
                "term": "TR", "meanings": [meaning],
            }], "manual_terms": []}
            _case(self, "terms_review_accepts_materialized_internal_identifier_source_and_visible_limit",
                  terminology_review._visible_review_errors(report, term_review, host.turn), [])

            writing_errors = writing_guard.content_errors(report, {
                "items": [{"term": "TR", "meanings": [meaning]}], "manual_terms": [],
            })
            parsed_glossary = writing_guard.glossary(report)[0]
            _case(self, "writing_guard_reads_report14_glossary_and_internal_identifier_shape",
                  (any(row["title"] == "TR 一次用户 Turn 的独立执行记录"
                       for row in parsed_glossary),
                   any("术语须准确名称" in error for error in writing_errors),
                   any("TR：未确认边界必须在正文中可见" in error for error in writing_errors),
                   any("TR：本地编号需直接附真实中文含义" in error for error in writing_errors)),
                  (True, False, False, False))
            _case(self, "writing_guard_uses_original_named_entrypoints_for_report14",
                  (writing_guard.glossary.__module__, writing_guard.glossary.__qualname__,
                   writing_guard.content_errors.__module__, writing_guard.content_errors.__qualname__,
                   is14(report)),
                  ("writing_guard", "glossary", "writing_guard", "content_errors", True))
            _case(self, "writing_guard_reads_actual_flat_report14_term_bullet",
                  (len(parsed_glossary), parsed_glossary[0]["raw"], parsed_glossary[0]["body"]),
                  (1, rendered_glossary, tr_description))

            legacy_report = (
                "## 0. 状态\n\n历史报告\n\n"
                "## 1. 承上启下\n\n历史内容\n\n"
                "## 2. 术语表\n\n"
                "- **TR 一次用户 Turn 的独立执行记录**：" + tr_description + "\n"
            )
            legacy_entries, legacy_errors = writing_guard.glossary(legacy_report)
            _case(self, "writing_guard_preserves_legacy_zero_to_nine_glossary_scope",
                  (len(legacy_entries), legacy_entries[0]["title"] if legacy_entries else "", legacy_errors),
                  (1, "TR 一次用户 Turn 的独立执行记录", []))

    def test_schema2_accepts_source_bound_single_word_verified_abbreviations(self):
        import terminology_review
        from prose_review import locate
        from report14.contract import SECTIONS

        with native_host() as host:
            registry_path = host.root / ".agent-project-control/reporting/quality/term-registry.json"
            registry_bytes = registry_path.read_bytes()
            registry = json.loads(registry_bytes.decode("utf-8"))
            approved = {term: registry["entries"][term]["english"] for term in ("IT", "EV")}
            _case(self, "schema2_fixture_uses_current_approved_IT_EV_names",
                  approved, {"IT": "Iteration", "EV": "Evidence"})

            proper_source = host.root / ".agent-project-control/scripts/report_quality_selfcheck.py"
            proper_bytes = proper_source.read_bytes()
            proper_text = proper_bytes.decode("utf-8-sig")
            proper_excerpt = next(
                line.strip() for line in proper_text.splitlines()
                if 'source_keys = ("Windows", "Python"' in line)
            registry_rel = "evidence/term-registry-review-fixture.json"
            registry_evidence = host.turn / registry_rel
            registry_evidence.write_bytes(registry_bytes)
            proper_rel = "evidence/proper-name-review-fixture.py"
            proper_evidence = host.turn / proper_rel
            proper_evidence.write_bytes(proper_bytes)

            definitions = {
                "IT": ("当前目标承载的工作迭代", "本轮用它标识稳定目标"),
                "EV": ("支撑判断的可核验材料", "本轮用它定位结果依据"),
                "Windows": ("本例涉及的平台名称", "本轮用它标识操作系统对象"),
                "Python": ("本例涉及的语言名称", "本轮用它标识执行环境"),
            }
            display_names = {
                "IT": lambda full: f"IT 迭代（{full}）",
                "EV": lambda full: f"EV 证据（{full}）",
                "Windows": lambda full: f"Windows（{full}）",
                "Python": lambda full: f"Python（{full}）",
            }

            def build_review(full_name_overrides=None, tag="valid"):
                full_names = {**approved, "Windows": "Windows", "Python": "Python"}
                full_names.update(full_name_overrides or {})
                glossary_lines_by_term = {}
                for term, full_name in full_names.items():
                    definition, relevance = definitions[term]
                    glossary_lines_by_term[term] = (
                        f"- **{display_names[term](full_name)}**：{definition}；{relevance}"
                    )
                body_line = "本例正文使用 IT 与 EV 作为框架缩写，也引用 Windows 与 Python 两个专名"
                bodies = {3: "\n".join(glossary_lines_by_term.values()), 6: body_line}
                report = "\n\n".join(
                    f"## {number}. {SECTIONS[number]['title']}\n\n{bodies.get(number, '')}"
                    for number in range(1, 15)
                ) + "\n"
                report = terminology_review.extract_user_report(report)
                candidate_rows = terminology_review.candidates(report)
                _case(self, "schema2_fixture_scans_only_its_two_abbreviation_candidates_" + tag,
                      [row["term"] for row in candidate_rows], ["EV", "IT"])
                line_by_term = {row["term"]: row["line_numbers"] for row in candidate_rows}
                body_line_number = next(
                    index for index, line in enumerate(report.splitlines(), 1) if line == body_line
                )

                def evidence_for(term, full_name):
                    if term in approved and full_name == approved[term]:
                        path, raw = registry_evidence, registry_bytes
                        excerpt = full_name
                    elif term in {"Windows", "Python"} and full_name == term:
                        path, raw = proper_evidence, proper_bytes
                        excerpt = proper_excerpt
                    else:
                        raw = (f"synthetic negative-claim source: {term} = {full_name}\n").encode("utf-8")
                        path = host.turn / "evidence" / f"{tag}-{term}-source.txt"
                        path.write_bytes(raw)
                        excerpt = full_name
                    return {
                        "path": path.relative_to(host.turn).as_posix(),
                        "sha256": hashlib.sha256(raw).hexdigest(),
                        "excerpt": excerpt,
                    }

                def meaning_for(term, line_numbers):
                    full_name = full_names[term]
                    definition, relevance = definitions[term]
                    visible_line = glossary_lines_by_term[term]
                    source_evidence = evidence_for(term, full_name)
                    return {
                        "meaning_id": f"meaning-{tag}-{term}",
                        "line_numbers": line_numbers,
                        "decision": "EXPLAINED",
                        "reason": "synthetic full-validator case binds the displayed name to current evidence",
                        "audience_context": "a reader of this synthetic report fixture",
                        "domain_context": "the schema-2 current-Turn validation path",
                        "current_use": "identifies the term used by the fixture report",
                        "context_relevance": relevance,
                        "source_or_basis": source_evidence["path"] + "#verified-name",
                        "reviewer": "synthetic selfcheck; not a human review",
                        "reviewed_at": "2026-10-12T00:00:00Z",
                        "term_kind": "abbreviation" if term in approved else "proper_name",
                        "name_status": "VERIFIED",
                        "verified_full_name": full_name,
                        "name_limit": "",
                        "definition": definition,
                        "visible_explanation": locate(report, visible_line),
                        "source_evidence": source_evidence,
                    }

                review = {
                    "schema": terminology_review.SCHEMA,
                    "report_sha256": terminology_review.sha256_text(report),
                    "review_method": "author_self_review",
                    "semantic_review_completed": True,
                    "reviewer": "synthetic full-validator fixture",
                    "audience_context": "a reader of the synthetic report fixture",
                    "reviewed_at": "2026-10-12T00:00:00Z",
                    "attestations": {name: True for name in terminology_review.ATTESTATIONS},
                    "items": [{
                        "term": row["term"],
                        "line_numbers": row["line_numbers"],
                        "observed_uses": row["observed_uses"],
                        "meanings": [meaning_for(row["term"], row["line_numbers"])],
                    } for row in candidate_rows],
                    "manual_terms": [{
                        "term": term,
                        "line_numbers": [body_line_number],
                        "meanings": [meaning_for(term, [body_line_number])],
                    } for term in ("Windows", "Python")],
                }
                return report, review

            report, valid_review = build_review()
            _case(self, "schema2_full_validator_accepts_source_bound_IT_EV_and_one_word_proper_names",
                  terminology_review.validate(report, valid_review, turn_dir=host.turn), [])
            _case(self, "schema2_full_validator_keeps_the_registered_single_word_expansions",
                  [row["meanings"][0]["verified_full_name"] for row in valid_review["items"]],
                  ["Evidence", "Iteration"])
            _case(self, "schema2_full_validator_keeps_Windows_Python_as_proper_name_self_names",
                  [(row["term"], row["meanings"][0]["verified_full_name"], row["meanings"][0]["term_kind"])
                   for row in valid_review["manual_terms"]],
                  [("Windows", "Windows", "proper_name"), ("Python", "Python", "proper_name")])

            legacy_review = copy.deepcopy(valid_review)
            legacy_review["schema"] = 1
            legacy_errors = terminology_review.validate(report, legacy_review, turn_dir=host.turn)
            _case(self, "schema1_full_validator_keeps_legacy_single_word_rejection",
                  all(any(f"{term} meaning 0: verified full name is a placeholder or incomplete phrase" in issue
                          for issue in legacy_errors) for term in ("IT", "EV")), True)

            def it_meaning(review):
                return next(row["meanings"][0] for row in review["items"] if row["term"] == "IT")

            missing_source = copy.deepcopy(valid_review)
            it_meaning(missing_source).pop("source_evidence")
            _case(self, "schema2_full_validator_rejects_missing_materialized_name_source",
                  any("source_evidence needs path, sha256 and exact excerpt" in issue
                      for issue in terminology_review.validate(report, missing_source, turn_dir=host.turn)), True)

            stale_source = copy.deepcopy(valid_review)
            it_meaning(stale_source)["source_evidence"]["sha256"] = "0" * 64
            _case(self, "schema2_full_validator_rejects_stale_name_source_digest",
                  any("term source digest mismatch" in issue
                      for issue in terminology_review.validate(report, stale_source, turn_dir=host.turn)), True)

            wrong_scope = copy.deepcopy(valid_review)
            it_meaning(wrong_scope)["source_evidence"]["path"] = "REQUEST.md"
            _case(self, "schema2_full_validator_rejects_name_source_outside_current_evidence",
                  any("term source must be materialized under current evidence/" in issue
                      for issue in terminology_review.validate(report, wrong_scope, turn_dir=host.turn)), True)

            missing_excerpt = copy.deepcopy(valid_review)
            it_meaning(missing_excerpt)["source_evidence"]["excerpt"] = "unsupported excerpt absent from bytes"
            _case(self, "schema2_full_validator_rejects_absent_name_source_excerpt",
                  any("term source excerpt absent from referenced evidence" in issue
                      for issue in terminology_review.validate(report, missing_excerpt, turn_dir=host.turn)), True)

            fake_name = copy.deepcopy(valid_review)
            it_meaning(fake_name)["verified_full_name"] = "Fabricated Official Expansion"
            _case(self, "schema2_full_validator_rejects_unbound_fake_official_name",
                  any("verified full name must be present in both visible explanation and actual source" in issue
                      for issue in terminology_review.validate(report, fake_name, turn_dir=host.turn)), True)

            wrong_kind = copy.deepcopy(valid_review)
            next(row["meanings"][0] for row in wrong_kind["manual_terms"] if row["term"] == "Windows")["term_kind"] = "concept"
            _case(self, "schema2_single_word_exception_is_not_granted_to_concepts",
                  any("verified full name is a placeholder or incomplete phrase" in issue
                      for issue in terminology_review.validate(report, wrong_kind, turn_dir=host.turn)), True)

            placeholder_report, placeholder_review = build_review({"IT": "placeholder"}, "placeholder")
            _case(self, "schema2_full_validator_rejects_same_word_placeholder_full_name",
                  any("verified full name is a placeholder or incomplete phrase" in issue
                      for issue in terminology_review.validate(placeholder_report, placeholder_review,
                                                               turn_dir=host.turn)), True)

            for variant, full_name in (("casefold", "it"), ("fullwidth", "ＩＴ")):
                variant_report, variant_review = build_review({"IT": full_name}, "self-expansion-" + variant)
                _case(self, "schema2_full_validator_rejects_normalized_self_expansion_" + variant,
                      any("abbreviation cannot use itself as its verified full name" in issue
                          for issue in terminology_review.validate(variant_report, variant_review,
                                                                   turn_dir=host.turn)), True)

    def test_writing_guard_accepts_native_report14_empty_glossary_only(self):
        import writing_guard

        with native_host() as host:
            report = render(host.capture())
            from report14.bindings import is14
            _case(self, "native_empty_glossary_fixture_is_report14", is14(report), True)
            _case(self, "native_empty_glossary_keeps_no_items_and_no_carrier_error",
                  writing_guard.glossary(report), ([], []))
            _case(self, "native_empty_glossary_does_not_fail_content_guard",
                  writing_guard.content_errors(report), [])

            fake_heading_report = report.replace(
                "## 3. 术语表\n",
                "```markdown\n## 3. 术语表\n\n"
                "- **FAKE 伪标题**：围栏中的假词条\n```\n\n"
                "## 3. 术语表\n", 1)
            fake_entries, fake_errors = writing_guard.glossary(fake_heading_report)
            _case(self, "writing_guard_ignores_fenced_fake_report14_section_heading",
                  (fake_entries, fake_errors), ([], []))

            mixed_report = report.replace(
                "## 3. 术语表\n\n本轮无相关事项：当前原生记录没有登记这类事项",
                "## 3. 术语表\n\n本轮无相关事项：当前原生记录没有登记这类事项\n\n"
                "- **IT 迭代（Iteration）**：IT 表示按目标归档的一轮工作", 1)
            mixed_entries, mixed_errors = writing_guard.glossary(mixed_report)
            _case(self, "writing_guard_does_not_treat_empty_marker_plus_term_as_empty",
                  (len(mixed_entries), any("必须直接使用 - **术语名称**" in error
                                           for error in mixed_errors)), (1, True))

            legacy_empty = (
                "## 0. 状态\n\n历史报告\n\n"
                "## 1. 承上启下\n\n历史内容\n\n"
                "## 2. 术语表\n\n本轮无相关事项：历史报告没有登记术语\n"
            )
            legacy_entries, legacy_errors = writing_guard.glossary(legacy_empty)
            _case(self, "legacy_empty_glossary_does_not_use_report14_exception",
                  (legacy_entries, bool(legacy_errors)), ([], True))


    def test_writing_guard_binds_native_report_prefixes_to_current_sources(self):
        import terminology_review
        import writing_guard
        from prose_review import locate
        from report14.contract import SECTIONS
        from test_ledger import serialize_v2

        with native_host() as host:
            session_path = host.turn / "evidence" / "execution-session.json"
            session = json.loads(session_path.read_text(encoding="utf-8-sig"))
            session["writing_contract"] = "writing-reliability-1"
            private_json(session_path, session)

            registry_path = host.root / ".agent-project-control/reporting/quality/term-registry.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8-sig"))
            registry["entries"]["ZZ"] = {
                "chinese": "未核验 LocalToken 标记",
                "english": "unverified LocalToken marker",
                "formal_acronym_expansion": False,
                "kind": "local_identifier",
                "sources": [{
                    "source_excerpt": "ZZ synthetic LocalToken source with unverified status",
                    "source_path": "synthetic/local-alias-fixture.txt",
                    "source_sha256": "0" * 64,
                }],
                "status": "UNVERIFIED",
            }
            registry_bytes = (json.dumps(registry, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
            registry_path.write_bytes(registry_bytes)
            registry_rel = ".agent-project-control/reporting/quality/term-registry.json"
            authority_bytes = (json.dumps({
                "schema": 1,
                "scope": "Read-only source quotation for current review; original registry and referenced norms remain authoritative",
                "registry_path": registry_rel,
                "registry_sha256": hashlib.sha256(registry_bytes).hexdigest(),
                "entries": registry["entries"],
            }, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
            authority_path = host.turn / "evidence" / "current-term-authority-quotations.json"
            authority_path.write_bytes(authority_bytes)
            proper_source = SCRIPT_DIR / "report_quality_selfcheck.py"
            proper_bytes = proper_source.read_bytes()
            proper_excerpt = next(
                line.strip() for line in proper_bytes.decode("utf-8-sig").splitlines()
                if 'source_keys = ("Windows", "Python"' in line
            )
            (host.turn / "evidence" / "proper-name-evidence.py").write_bytes(proper_bytes)
            (host.turn / "evidence" / "proof.json").write_bytes(b'{"observed":"current"}\n')

            checklist_body = "ChecklistBound 当前保存目标"
            (host.turn / "CHECKLIST.md").write_text(
                "# Current checklist\n\n- 【已完成】【CL-01】【保存读回目标】：" + checklist_body + "\n",
                encoding="utf-8")
            test_row = {
                "status": "PASS", "id": "TEST-01", "refs": ["CL-01"],
                "object": "保存后读回", "context": "ContextBound 当前临时目录",
                "action": "ActionBound 保存后重新读取", "expected": "ExpectedBound 内容一致",
                "actual": "保存内容与读回内容一致", "evidence": "evidence/proof.json",
            }
            (host.turn / "TEST.md").write_text(
                "# Current acceptance\n\n" + serialize_v2(test_row) + "\n", encoding="utf-8")

            report_bodies = {number: "" for number in range(1, 15)}
            local_terms = ("TR", "PA")
            proper_terms = ("Windows", "Python")
            term_titles = {}
            term_descriptions = {}
            for term in local_terms:
                source = registry["entries"][term]
                term_titles[term] = term + " " + source["chinese"]
                term_descriptions[term] = (
                    term + " 用于标识本轮保存记录；本轮用它关联当前验收结果；"
                    "像一份按请求保存的记录；本例没有确认其英文官方全称"
                )
            for term in proper_terms:
                source = registry["entries"][term]
                term_titles[term] = source["chinese"] + "（" + source["english"] + "）"
                term_descriptions[term] = (
                    source["chinese"] + "用于标识当前执行环境；本轮用它说明运行对象；"
                    "像一项可识别的平台或语言名称"
                )
            report_bodies[3] = "\n".join(
                f"- **{term_titles[term]}**：{term_descriptions[term]}"
                for term in (*local_terms, *proper_terms)
            )
            report_bodies[4] = (
                "- **【已完成】【CL-01】【保存读回目标】**：" + checklist_body
            )
            report_bodies[6] = (
                "**【通过】【TEST-01】【保存后读回】：**\n\n"
                "- 对应任务：CL-01\n"
                "- 验收方式：ContextBound 当前临时目录；ActionBound 保存后重新读取\n"
                "- 预期结果：ExpectedBound 内容一致\n"
                "- 实际结果：保存内容与读回内容一致\n"
                "- 关联证据：当前验收材料\n\n"
                "本轮依据：" + "；".join(term_titles[term] for term in (*local_terms, *proper_terms))
            )
            report_bodies[7] = (
                "**【EV-01】【验收证据】：**\n\n"
                "- 证据来源：evidence/proof.json\n"
                "- 证明内容：当前验收引用的材料已实际读取"
            )

            def make_report(bodies=None):
                selected = report_bodies if bodies is None else bodies
                return "\n\n".join(
                    f"## {number}. {SECTIONS[number]['title']}\n\n{selected[number]}"
                    for number in range(1, 15)
                ) + "\n"

            def make_review(report, title_overrides=None):
                title_overrides = title_overrides or {}
                candidates = terminology_review.candidates(report)

                def make_meaning(term, line_numbers):
                    source = registry["entries"][term]
                    is_local = term in local_terms
                    title = title_overrides.get(term, term_titles[term])
                    definition = term + " 用于标识本轮保存记录" if is_local else source["chinese"] + "用于标识当前执行环境"
                    relevance = "本轮用它关联当前验收结果" if is_local else "本轮用它说明运行对象"
                    analogy = "像一份按请求保存的记录" if is_local else "像一项可识别的平台或语言名称"
                    limit = "本例没有确认其英文官方全称" if is_local else ""
                    evidence_path = "evidence/current-term-authority-quotations.json" if is_local else "evidence/proper-name-evidence.py"
                    evidence_bytes = authority_bytes if is_local else proper_bytes
                    evidence_excerpt = source["sources"][0]["source_excerpt"] if is_local else proper_excerpt
                    meaning = {
                        "meaning_id": "source-bound-" + term,
                        "line_numbers": line_numbers,
                        "decision": "EXPLAINED",
                        "reason": "synthetic integration case binds visible names to the current registry source",
                        "audience_context": "a reader of the synthetic current-Turn report",
                        "domain_context": "the native report-quality integration fixture",
                        "current_use": "identifies the term in the current report",
                        "context_relevance": relevance,
                        "source_or_basis": evidence_path + "#" + term,
                        "reviewer": "synthetic selfcheck; not a human reviewer",
                        "reviewed_at": "2026-10-12T00:00:00Z",
                        "term_kind": "internal_identifier" if is_local else "proper_name",
                        "name_status": "UNVERIFIED" if is_local else "VERIFIED",
                        "verified_full_name": "" if is_local else source["english"],
                        "name_limit": limit,
                        "definition": definition,
                        "chinese_name": source["chinese"],
                        "display_name": title,
                        "analogy": analogy,
                        "analogy_basis": "the name identifies the source object used in this report",
                        "visible_explanation": locate(report, next(
                            line for line in report.splitlines()
                            if line.startswith("- **" + title + "**："))),
                        "source_evidence": {
                            "path": evidence_path,
                            "sha256": hashlib.sha256(evidence_bytes).hexdigest(),
                            "excerpt": evidence_excerpt,
                        },
                    }
                    return meaning

                items = [{
                        "term": term,
                        "line_numbers": candidate["line_numbers"],
                        "observed_uses": candidate["observed_uses"],
                        "meanings": [make_meaning(term, candidate["line_numbers"])],
                    } for candidate in candidates for term in [candidate["term"]]]
                report_lines = report.splitlines()
                name_use_line = next(index for index, line in enumerate(report_lines, 1)
                                     if line.startswith("本轮依据："))
                manual_terms = [{
                    "term": term,
                    "line_numbers": [name_use_line],
                    "meanings": [make_meaning(term, [name_use_line])],
                } for term in proper_terms]
                return {
                    "schema": terminology_review.SCHEMA,
                    "report_sha256": terminology_review.sha256_text(report),
                    "review_method": "author_self_review",
                    "semantic_review_completed": True,
                    "reviewer": "synthetic current-Turn integration fixture",
                    "audience_context": "a reader of the synthetic report fixture",
                    "reviewed_at": "2026-10-12T00:00:00Z",
                    "attestations": {name: True for name in terminology_review.ATTESTATIONS},
                    "items": items,
                    "manual_terms": manual_terms,
                }

            report = terminology_review.extract_user_report(make_report())
            review = make_review(report)
            _case(self, "writing_guard_integration_review_covers_expected_local_aliases_and_proper_names",
                  ([row["term"] for row in review["items"]],
                   [row["term"] for row in review["manual_terms"]]),
                  (["PA", "TR"], ["Windows", "Python"]))
            _case(self, "writing_guard_integration_full_schema2_validator_accepts_current_source_bound_report",
                  terminology_review.validate(report, review, turn_dir=host.turn), [])

            unknown_entry = registry["entries"]["ZZ"]
            unknown_title = "ZZ " + unknown_entry["chinese"]
            unknown_line = "- **" + unknown_title + "**：ZZ 用于标识测试夹具中的未核验本地编号；本例未核实 LocalToken 的官方含义"
            python_title_line = "- **" + term_titles["Python"] + "**：" + term_descriptions["Python"]
            unknown_report = terminology_review.extract_user_report(
                report.replace(python_title_line, python_title_line + "\n" + unknown_line, 1)
            )
            unknown_line_number = next(index for index, line in enumerate(unknown_report.splitlines(), 1)
                                       if line == unknown_line)
            unknown_meaning = {
                "meaning_id": "unverified-local-alias-ZZ",
                "line_numbers": [unknown_line_number],
                "decision": "EXPLAINED",
                "reason": "synthetic negative case: registry source status is unverified",
                "audience_context": "a reader of the synthetic current-Turn report",
                "domain_context": "the native report-quality integration fixture",
                "current_use": "identifies the unverified local alias in the fixture",
                "context_relevance": "checks that a registry quote alone does not authorize title fragments",
                "source_or_basis": "evidence/current-term-authority-quotations.json#ZZ",
                "reviewer": "synthetic selfcheck; not a human reviewer",
                "reviewed_at": "2026-10-12T00:00:00Z",
                "term_kind": "internal_identifier",
                "name_status": "UNVERIFIED",
                "verified_full_name": "",
                "name_limit": "本例未核实 LocalToken 的官方含义",
                "definition": "ZZ 用于标识测试夹具中的未核验本地编号",
                "chinese_name": unknown_entry["chinese"],
                "display_name": unknown_title,
                "analogy": "像一张等待来源核验的标签",
                "analogy_basis": "来源状态尚未核验时，不据标题中的英文片段推定正式名称",
                "visible_explanation": locate(unknown_report, unknown_line),
                "source_evidence": {
                    "path": "evidence/current-term-authority-quotations.json",
                    "sha256": hashlib.sha256(authority_bytes).hexdigest(),
                    "excerpt": unknown_entry["sources"][0]["source_excerpt"],
                },
            }
            unknown_review = copy.deepcopy(review)
            unknown_review["report_sha256"] = terminology_review.sha256_text(unknown_report)
            unknown_review["items"].append({
                "term": "ZZ",
                "line_numbers": [unknown_line_number],
                "observed_uses": 1,
                "meanings": [unknown_meaning],
            })
            unknown_errors = writing_guard.content_errors(
                unknown_report, unknown_review, turn_context=host.turn
            )
            _case(self, "writing_guard_does_not_exempt_local_alias_title_from_unverified_registry_entry",
                  any("未复核的英文或缩写 LocalToken" in error for error in unknown_errors), True)

            unbound_suffix = report.replace(checklist_body, checklist_body + " UnboundSuffix", 1)
            suffix_errors = writing_guard.content_errors(unbound_suffix, review, turn_context=host.turn)
            _case(self, "writing_guard_masks_only_the_exact_checklist_prefix",
                  any("UnboundSuffix" in error for error in suffix_errors), True)

            wrong_cl_id = report.replace("【CL-01】【保存读回目标】", "【CL-99】【保存读回目标】", 1)
            wrong_cl_errors = writing_guard.content_errors(wrong_cl_id, review, turn_context=host.turn)
            _case(self, "writing_guard_rejects_checklist_source_bound_to_the_wrong_record_id",
                  (any("第4章 CL-99" in error for error in wrong_cl_errors),
                   any("ChecklistBound" in error for error in wrong_cl_errors)), (True, True))

            wrong_field = report.replace(
                "- **【已完成】【CL-01】【保存读回目标】**：" + checklist_body,
                "- **【已完成】【CL-01】【保存读回目标】**：已记录目标\n\n- 风险说明：" + checklist_body,
                1,
            )
            wrong_field_errors = writing_guard.content_errors(wrong_field, review, turn_context=host.turn)
            _case(self, "writing_guard_does_not_protect_checklist_text_in_an_unbound_field",
                  any("ChecklistBound" in error for error in wrong_field_errors), True)

            actual_pollution = report.replace("保存内容与读回内容一致", "ActualUnbound 保存内容与读回内容一致", 1)
            actual_errors = writing_guard.content_errors(actual_pollution, review, turn_context=host.turn)
            _case(self, "writing_guard_does_not_protect_TEST_actual_observations",
                  any("ActualUnbound" in error for error in actual_errors), True)

            path_suffix = report.replace(
                "- 证据来源：evidence/proof.json",
                "- 证据来源：evidence/proof.json PathUnboundSuffix",
                1,
            )
            path_errors = writing_guard.content_errors(path_suffix, review, turn_context=host.turn)
            _case(self, "writing_guard_masks_only_current_evidence_path_in_section7",
                  any("PathUnboundSuffix" in error for error in path_errors), True)

            no_context_errors = writing_guard.content_errors(report, review)
            _case(self, "writing_guard_keeps_legacy_no_context_scan_unexempted",
                  any("ChecklistBound" in error for error in no_context_errors), True)

            wrong_context_errors = writing_guard.content_errors(report, review, turn_context=host.root)
            _case(self, "writing_guard_fails_closed_for_a_turn_outside_the_current_project",
                  (any("当前 Turn 的 Checklist／TEST 来源无法读取或解析" in error for error in wrong_context_errors),
                   any("ChecklistBound" in error for error in wrong_context_errors)), (True, True))

            tr_title = term_titles["TR"]
            tr_description = term_descriptions["TR"]
            description_report = report.replace(tr_description, tr_description + "；补充说明 Turn", 1)
            description_review = make_review(description_report)
            description_errors = terminology_review.validate(description_report, description_review,
                                                             turn_dir=host.turn)
            _case(self, "writing_guard_registry_title_binding_does_not_exempt_new_description_english",
                  any("未复核的英文或缩写 Turn" in error for error in description_errors), True)

            forged_title = "TR 一次用户 Turn 的伪造登记名称"
            forged_report = report.replace(tr_title, forged_title)
            forged_review = make_review(forged_report, {"TR": forged_title})
            forged_errors = terminology_review.validate(forged_report, forged_review, turn_dir=host.turn)
            _case(self, "writing_guard_does_not_exempt_a_forged_local_alias_title",
                  any("未复核的英文或缩写 Turn" in error for error in forged_errors), True)

            for label, mutate, expected in (
                ("missing", lambda row: row.pop("source_evidence"), "source_evidence needs path, sha256 and exact excerpt"),
                ("stale", lambda row: row["source_evidence"].update(sha256="0" * 64), "term source digest mismatch"),
                ("wrong_scope", lambda row: row["source_evidence"].update(path="REQUEST.md"), "term source must be materialized under current evidence/"),
                ("bad_excerpt", lambda row: row["source_evidence"].update(excerpt="not present in registry evidence"), "term source excerpt absent from referenced evidence"),
            ):
                bad_review = copy.deepcopy(review)
                tr_meaning = next(row["meanings"][0] for row in bad_review["items"] if row["term"] == "TR")
                mutate(tr_meaning)
                bad_errors = terminology_review.validate(report, bad_review, turn_dir=host.turn)
                _case(self, "writing_guard_local_alias_source_binding_rejects_" + label,
                      any(expected in error for error in bad_errors), True)


    def test_writing_guard_binds_v3_checklist_goal_spans_to_current_sources(self):
        import narrative_contract
        import report14.bindings as report_bindings
        import writing_guard
        from report14.contract import SECTIONS
        from test_ledger import parse_checklist, serialize_goal, serialize_v2

        with native_host() as host:
            facts = {
                "context": "保存目标位于当前隔离目录",
                "problem": "写入后的正文可能与提交前的正文不同",
                "consequence": "调用者可能把不一致内容当成已保存结果",
                "requirement": "保存后必须从当前目标重新读取正文",
                "criterion": "重新读取的正文须与原文逐字一致",
            }
            prose = "；".join(facts[key] for key in narrative_contract.GOAL_FIELDS)
            goal_row = {"id": "CL-41", "status": "已完成", "object": "原生目标来源绑定"}
            checklist_doc = (
                "# Current checklist\n\n"
                + narrative_contract.GOAL_MARKER + "\n\n"
                + serialize_goal(goal_row, prose, facts) + "\n"
            )
            (host.turn / "CHECKLIST.md").write_text(checklist_doc, encoding="utf-8")
            test_row = {
                "status": "PASS", "id": "TEST-41", "refs": ["CL-41"],
                "object": "当前目标重新读取", "context": "隔离目录已准备",
                "action": "保存后重新读取正文", "expected": "正文逐字一致",
                "actual": "重新读取的正文与原文一致", "evidence": "evidence/check.json",
            }
            (host.turn / "TEST.md").write_text(
                "# Current acceptance\n\n" + serialize_v2(test_row) + "\n",
                encoding="utf-8",
            )
            self.assertEqual(
                [row["id"] for row in parse_checklist(checklist_doc)], ["CL-41"]
            )

            def make_report(*, record_id="CL-41", field_values=None, native_target=False):
                values = {
                    "任务缘由": facts["problem"],
                    "行动要求": facts["requirement"],
                    "验收标准": facts["criterion"],
                }
                if field_values:
                    values.update(field_values)
                bodies = {number: "" for number in range(1, 15)}
                if native_target:
                    bodies[4] = (
                        "- **【已完成】【" + record_id + "】【原生目标来源】**："
                        + values["原生目标"]
                    )
                else:
                    bodies[4] = (
                        "**【已完成】【" + record_id + "】【原生目标来源】：**\n\n"
                        + "\n".join(
                            "- " + label + "：" + value
                            for label, value in values.items()
                            if label in {"任务缘由", "行动要求", "验收标准"}
                        )
                    )
                return "\n\n".join(
                    f"## {number}. {SECTIONS[number]['title']}\n\n{bodies[number]}"
                    for number in range(1, 15)
                ) + "\n"

            review = {"items": [], "manual_terms": []}
            valid_report = make_report()
            valid_view, valid_binding_errors = writing_guard._source_bound_view(
                valid_report, host.turn
            )
            _case(self, "writing_guard_v3_goal_roles_bind_to_validated_source_spans",
                  valid_binding_errors, [])
            _case(self, "writing_guard_v3_goal_report_passes_current_context_scan",
                  writing_guard.content_errors(valid_report, review, turn_context=host.turn), [])

            wrong_id_report = make_report(record_id="CL-99")
            _, wrong_id_errors = writing_guard._source_bound_view(wrong_id_report, host.turn)
            _case(self, "writing_guard_v3_goal_binding_rejects_wrong_checklist_identity",
                  any("第4章 CL-99" in error for error in wrong_id_errors), True)

            wrong_role_report = make_report(field_values={"任务缘由": facts["requirement"]})
            _, wrong_role_errors = writing_guard._source_bound_view(wrong_role_report, host.turn)
            _case(self, "writing_guard_v3_goal_binding_rejects_source_text_under_wrong_role",
                  any("第4章 CL-41 任务缘由" in error for error in wrong_role_errors), True)

            replaced_report = make_report(field_values={
                "任务缘由": "替换后的内容不再对应已登记问题",
            })
            _, replaced_errors = writing_guard._source_bound_view(replaced_report, host.turn)
            _case(self, "writing_guard_v3_goal_binding_rejects_replaced_source_slice",
                  any("第4章 CL-41 任务缘由" in error for error in replaced_errors), True)

            original_unchanged = report_bindings.unchanged
            drifted = [False]

            def drift_checklist_after_parse(root, snapshot):
                if not drifted[0]:
                    drifted[0] = True
                    (host.turn / "CHECKLIST.md").write_text(
                        checklist_doc + "\n\n<!-- source drift -->\n", encoding="utf-8"
                    )
                return original_unchanged(root, snapshot)

            with patch.object(report_bindings, "unchanged", drift_checklist_after_parse):
                _, drift_errors = writing_guard._source_bound_view(valid_report, host.turn)
            _case(self, "writing_guard_v3_goal_binding_rejects_source_digest_drift_during_scan",
                  any("当前 Turn 请求或清单／验收来源在检查期间发生变化" in error
                      for error in drift_errors), True)
            (host.turn / "CHECKLIST.md").write_text(checklist_doc, encoding="utf-8")

            suffix_report = make_report(field_values={
                "验收标准": facts["criterion"] + " UnboundV3AuthorSuffix",
            })
            suffix_errors = writing_guard.content_errors(
                suffix_report, review, turn_context=host.turn
            )
            _case(self, "writing_guard_v3_goal_masks_only_source_prefix_and_scans_new_english",
                  any("UnboundV3AuthorSuffix" in error for error in suffix_errors), True)

            valid_record = serialize_goal(goal_row, prose, facts).splitlines()
            map_start = len(narrative_contract.GOAL_PREFIX)
            mapping = json.loads(valid_record[1][map_start:-4])
            mapping["spans"]["problem"] = [0, len(prose) + 1]
            invalid_map_comment = (
                narrative_contract.GOAL_PREFIX
                + json.dumps(mapping, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                + " -->"
            )
            invalid_span_doc = (
                "# Current checklist\n\n" + narrative_contract.GOAL_MARKER + "\n\n"
                + valid_record[0] + "\n" + invalid_map_comment + "\n"
            )
            (host.turn / "CHECKLIST.md").write_text(invalid_span_doc, encoding="utf-8")
            invalid_rows = parse_checklist(invalid_span_doc)
            _, invalid_span_errors = writing_guard._source_bound_view(valid_report, host.turn)
            _case(self, "writing_guard_v3_goal_rejects_invalid_span_map_without_fallback",
                  (invalid_rows, any("来源缺少可解析记录" in error
                                     for error in invalid_span_errors)), ([], True))

            legacy_body = "旧格式单字段目标正文"
            legacy_doc = (
                "# Legacy checklist\n\n"
                "- 【已完成】【CL-41】【旧格式目标】：" + legacy_body + "\n"
            )
            (host.turn / "CHECKLIST.md").write_text(legacy_doc, encoding="utf-8")
            legacy_row = parse_checklist(legacy_doc)[0]
            legacy_report = make_report(
                field_values={"原生目标": legacy_body}, native_target=True
            )
            _, legacy_errors = writing_guard._source_bound_view(legacy_report, host.turn)
            _case(self, "writing_guard_legacy_checklist_keeps_existing_whole_body_binding",
                  (legacy_row.get("format_version"), legacy_errors), (None, []))

            legacy_split_report = make_report()
            _, legacy_split_errors = writing_guard._source_bound_view(
                legacy_split_report, host.turn
            )
            _case(self, "writing_guard_does_not_apply_v3_role_spans_to_legacy_checklist",
                  len([error for error in legacy_split_errors
                       if "第4章 CL-41" in error]), 3)


    def test_writing_guard_binds_section6_evidence_and_numeric_seconds_math(self):
        import writing_guard
        from report14.contract import SECTIONS
        from test_ledger import serialize_v2

        with native_host() as host:
            proof_path = host.turn / "evidence" / "proof.json"
            proof_path.write_bytes(b'{"observed":"current"}\n')
            (host.turn / "evidence" / "borrowed.json").write_bytes(b'{"observed":"other"}\n')
            (host.turn / "CHECKLIST.md").write_text(
                "# Current checklist\n\n- 【已完成】【CL-01】【保存读回目标】：ChecklistBound 当前保存目标\n",
                encoding="utf-8",
            )
            context = "ContextBound 当前临时目录"
            action = "ActionBound 保存后重新读取"
            expected = "ExpectedBound 内容一致"

            def make_report(*, record_id="TEST-01", ledger_evidence="evidence/proof.json",
                            cited_evidence=None, evidence_suffix="", formula=r"$970.735\,\mathrm{s}$"):
                test_row = {
                    "status": "PASS", "id": "TEST-01", "refs": ["CL-01"],
                    "object": "保存后读回", "context": context, "action": action,
                    "expected": expected, "actual": "保存内容与读回内容一致",
                    "evidence": ledger_evidence,
                }
                (host.turn / "TEST.md").write_text(
                    "# Current acceptance\n\n" + serialize_v2(test_row) + "\n", encoding="utf-8"
                )
                cited = ledger_evidence if cited_evidence is None else cited_evidence
                bodies = {number: "" for number in range(1, 15)}
                bodies[8] = "本轮记录实际耗时" + formula + "，源码状态可核对"
                bodies[6] = (
                    f"**【通过】【{record_id}】【保存后读回】：**\n\n"
                    "- 对应任务：CL-01\n"
                    f"- 验收方式：{context}；{action}\n"
                    f"- 预期结果：{expected}\n"
                    "- 实际结果：保存内容与读回内容一致\n"
                    f"- 关联证据：{cited}{evidence_suffix}"
                )
                return "\n\n".join(
                    f"## {number}. {SECTIONS[number]['title']}\n\n{bodies[number]}"
                    for number in range(1, 15)
                ) + "\n"

            review = {"items": [], "manual_terms": []}
            valid_report = make_report()
            valid_errors = writing_guard.content_errors(valid_report, review, turn_context=host.turn)
            _case(self, "writing_guard_accepts_current_TEST_section6_path_and_valid_numeric_seconds_math",
                  valid_errors, [])

            suffix_report = make_report(evidence_suffix=" ExtraUnreviewedEnglish")
            suffix_errors = writing_guard.content_errors(suffix_report, review, turn_context=host.turn)
            _case(self, "writing_guard_keeps_new_English_after_the_bound_section6_path_visible",
                  any("ExtraUnreviewedEnglish" in error for error in suffix_errors), True)

            borrowed_report = make_report(cited_evidence="evidence/borrowed.json")
            borrowed_errors = writing_guard.content_errors(borrowed_report, review, turn_context=host.turn)
            _case(self, "writing_guard_does_not_borrow_another_existing_TEST_evidence_path",
                  any("borrowed" in error.casefold() for error in borrowed_errors), True)

            missing_report = make_report(ledger_evidence="evidence/missing.json")
            missing_errors = writing_guard.content_errors(missing_report, review, turn_context=host.turn)
            _case(self, "writing_guard_rejects_a_missing_current_TEST_evidence_path",
                  any("证据文件缺失或越界" in error for error in missing_errors), True)

            wrong_record_report = make_report(record_id="TEST-99")
            wrong_record_errors = writing_guard.content_errors(
                wrong_record_report, review, turn_context=host.turn
            )
            _case(self, "writing_guard_rejects_a_section6_path_under_the_wrong_TEST_ID",
                  (any("第6章 TEST-99" in error for error in wrong_record_errors),
                   any("ContextBound" in error for error in wrong_record_errors)), (True, True))

            wrong_context_errors = writing_guard.content_errors(
                valid_report, review, turn_context=host.root
            )
            _case(self, "writing_guard_rejects_section6_path_binding_outside_the_current_project",
                  (any("当前 Turn 的 Checklist／TEST 来源无法读取或解析" in error
                       for error in wrong_context_errors),
                   any("evidence/proof" in error for error in wrong_context_errors)), (True, True))

            original_read_bytes = Path.read_bytes
            changed = [False]

            def drift_read_bytes(path):
                data = original_read_bytes(path)
                if path.resolve() == proof_path.resolve() and not changed[0]:
                    changed[0] = True
                    proof_path.write_bytes(b'{"observed":"changed"}\n')
                return data

            with patch.object(Path, "read_bytes", drift_read_bytes):
                drift_errors = writing_guard.content_errors(
                    valid_report, review, turn_context=host.turn
                )
            _case(self, "writing_guard_fails_closed_when_current_TEST_evidence_drifts_during_scan",
                  any("当前 TEST 引用的证据在检查期间发生变化" in error
                      for error in drift_errors), True)

            arbitrary_math_errors = writing_guard.content_errors(
                make_report(formula=r"$UnreviewedEnglish$"), review, turn_context=host.turn
            )
            _case(self, "writing_guard_does_not_hide_arbitrary_English_inside_dollar_delimiters",
                  any("UnreviewedEnglish" in error for error in arbitrary_math_errors), True)

            doubled_slash_errors = writing_guard.content_errors(
                make_report(formula=r"$970.735\\,\\mathrm{s}$"), review, turn_context=host.turn
            )
            _case(self, "writing_guard_does_not_accept_a_doubled_slash_as_numeric_seconds_math",
                  any("mathrm" in error for error in doubled_slash_errors), True)

            extended_math_errors = writing_guard.content_errors(
                make_report(formula=r"$970.735\,\mathrm{s}$ UnreviewedEnglish"),
                review, turn_context=host.turn
            )
            _case(self, "writing_guard_scans_English_appended_to_a_valid_math_carrier",
                  any("UnreviewedEnglish" in error for error in extended_math_errors), True)


def main() -> int:
    CASE_RESULTS.clear()
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    summary = {
        "suite": "report-quality-core-selfcheck",
        "run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "negative_cases_run": len(CASE_RESULTS),
        "negative_cases": CASE_RESULTS,
        "scope": "Synthetic native host from core_repair_selfcheck.fixture; not a real desktop host or business session. Reviewer coverage invokes the production adapter with a deterministic payload-only stub to verify byte-bound source excerpts and drift rejection; it does not certify semantic quality.",
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if result.wasSuccessful() else 2


if __name__ == "__main__":
    raise SystemExit(main())
