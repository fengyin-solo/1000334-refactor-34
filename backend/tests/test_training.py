"""培训考核口径的回归测试。

开班入口与成绩列表共用 app.services.training 里的同一份逻辑，
这份测试把口径钉住：以后调整口径只需改一处、跑一遍这里，
不用再到各个入口逐个核对。运行：cd backend && .venv/bin/python -m unittest tests.test_training -v
"""
from __future__ import annotations

import copy
import unittest
from decimal import Decimal

from app.services.training import (
    PASS_SCORE,
    TrainingService,
    action_checks,
    average_score,
    class_ready,
    parse_score,
)
from app.store import store

MODULE = "training"


class ParseScoreTest(unittest.TestCase):
    def test_numeric_inputs(self) -> None:
        self.assertEqual(parse_score(85), Decimal("85"))
        self.assertEqual(parse_score(85.5), Decimal("85.5"))
        self.assertEqual(parse_score("85"), Decimal("85"))
        self.assertEqual(parse_score(" 90分 "), Decimal("90"))

    def test_non_numeric_inputs(self) -> None:
        for raw in (None, "", "   ", "培训考核样例1", "未录入", True):
            self.assertIsNone(parse_score(raw), msg=f"raw={raw!r}")


class AverageScoreTest(unittest.TestCase):
    def test_average_ignores_rows_without_valid_score(self) -> None:
        rows = [{"考核成绩": "80"}, {"考核成绩": "培训考核样例"}, {"考核成绩": "90"}]
        self.assertEqual(average_score(rows), 85.0)

    def test_average_rounds_half_up_to_one_decimal(self) -> None:
        rows = [{"考核成绩": "85.2"}, {"考核成绩": "85.3"}]  # 均值 85.25，四舍五入到 85.3
        self.assertEqual(average_score(rows), 85.3)

    def test_average_is_none_without_valid_scores(self) -> None:
        self.assertIsNone(average_score([{"考核成绩": "培训考核样例1"}]))
        self.assertIsNone(average_score([]))

    def test_average_is_deterministic(self) -> None:
        rows = [{"考核成绩": "61.25"}, {"考核成绩": "77.5"}, {"考核成绩": "88"}]
        self.assertEqual(average_score(rows), average_score([dict(row) for row in rows]))


class StoreTestCase(unittest.TestCase):
    """每个用例前后还原内存数据，保证用例互不影响、已有数据不被改动。"""

    def setUp(self) -> None:
        self.rows = store.rows(MODULE)
        self._snapshot = copy.deepcopy(self.rows)

    def tearDown(self) -> None:
        self.rows[:] = self._snapshot

    def _row(self, entry_id: int) -> dict:
        row = store.find(MODULE, entry_id)
        self.assertIsNotNone(row)
        return row  # type: ignore[return-value]


class ActionChecksTest(StoreTestCase):
    def test_seed_row_one_passes_class_start_checks(self) -> None:
        checks = action_checks("确认开班", self._row(1))
        self.assertTrue(all(check.passed for check in checks))
        self.assertTrue(class_ready(self._row(1)))

    def test_class_start_rejects_wrong_status(self) -> None:
        checks = action_checks("确认开班", self._row(2))  # 培训中
        self.assertEqual(checks[0].step, "状态检查")
        self.assertFalse(checks[0].passed)
        self.assertFalse(class_ready(self._row(2)))

    def test_graduation_requires_recorded_score(self) -> None:
        service = TrainingService()
        entry, message = service.run_action(2, "登记结业")  # 培训中，但成绩是占位文本
        self.assertIsNone(entry)
        self.assertIn("【成绩录入】", message)

    def test_graduation_rejects_score_below_pass_line(self) -> None:
        service = TrainingService()
        entry, missing = service.create_entry({
            "培训编号": "TRAI-9002",
            "培训主题": "安全规程",
            "培训对象": "新入职员工",
            "考核成绩": "45",
            "培训日期": "2026-09-21",
        })
        self.assertEqual(missing, [])
        assert entry is not None
        entry, message = service.run_action(entry["id"], "确认开班")
        self.assertIsNotNone(entry, message)
        entry, message = service.run_action(entry["id"], "登记结业")
        self.assertIsNone(entry)
        self.assertIn("【成绩合格】", message)
        self.assertIn(str(PASS_SCORE), message)

    def test_cancel_after_graduation_is_rejected(self) -> None:
        service = TrainingService()
        entry, message = service.run_action(3, "取消培训")  # 已结业
        self.assertIsNone(entry)
        self.assertIn("【状态检查】", message)

    def test_unknown_action_is_rejected(self) -> None:
        service = TrainingService()
        entry, message = service.run_action(1, "直接发证")
        self.assertIsNone(entry)
        self.assertIn("不属于培训考核可执行范围", message)

    def test_full_flow_with_shared_policy(self) -> None:
        service = TrainingService()
        entry, missing = service.create_entry({
            "培训编号": "TRAI-9001",
            "培训主题": "逆变器运维",
            "培训对象": "运维班组",
            "考核成绩": "90",
            "培训日期": "2026-09-20",
        })
        self.assertEqual(missing, [])
        assert entry is not None
        entry, message = service.run_action(entry["id"], "确认开班")
        self.assertIsNotNone(entry, message)
        assert entry is not None
        self.assertEqual(entry["status"], "培训中")
        self.assertTrue(entry["pending"])
        entry, message = service.run_action(entry["id"], "登记结业")
        self.assertIsNotNone(entry, message)
        assert entry is not None
        self.assertEqual(entry["status"], "已结业")
        self.assertFalse(entry["pending"])  # 结业后不再挂在待处理里


class SummaryTest(StoreTestCase):
    def test_summary_matches_seed_and_is_stable(self) -> None:
        service = TrainingService()
        first = service.summary()
        second = service.summary()
        self.assertEqual(first, second)  # 重新打开页面结果不能变
        stats = {item["label"]: item["value"] for item in first["stats"]}
        self.assertEqual(stats["待开班培训"], 1)
        self.assertEqual(stats["培训中课程"], 1)
        self.assertIsNone(stats["平均考核成绩"])  # 种子成绩都是占位文本，显示「—」
        self.assertEqual([item["培训编号"] for item in first["开班名单"]], ["TRAI-0001"])

    def test_summary_reflects_recorded_scores(self) -> None:
        service = TrainingService()
        service.create_entry({
            "培训编号": "TRAI-9003",
            "培训主题": "组件清洗",
            "培训对象": "保洁班组",
            "考核成绩": "80",
            "培训日期": "2026-09-22",
        })
        stats = {item["label"]: item["value"] for item in service.summary()["stats"]}
        self.assertEqual(stats["平均考核成绩"], 80.0)

    def test_reads_do_not_mutate_existing_rows(self) -> None:
        service = TrainingService()
        before = copy.deepcopy(self.rows)
        service.summary()
        service.list_entries()
        service.get_entry(1)
        self.assertEqual(self.rows, before)  # 已有培训数据、成绩与结业结果保持一致


if __name__ == "__main__":
    unittest.main()
