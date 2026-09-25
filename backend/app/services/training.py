"""培训考核业务规则：状态流转、字段校验与筛选口径都收在这里。

考核成绩解析、平均成绩、开班条件、开班名单、结业判定的口径统一在
app.services.training_standard，本文件只负责流程编排，不再各自实现计算逻辑，
保证开班入口与成绩列表、本地与正式环境跑出同一份结果。
"""
from __future__ import annotations

from typing import Any

from app.services import training_standard as standard
from app.store import store

MODULE = "training"
REQUIRED_FIELDS = standard.REQUIRED_FIELDS
STATUS_ORDER = ["待开班", "培训中", "已结业", "已取消"]
ACTION_RULES = {"确认开班": "培训中", "登记结业": "已结业", "取消培训": "已取消"}


class TrainingService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("培训编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [self.present(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return self.present(entry) if entry is not None else None

    def present(self, row: dict[str, Any]) -> dict[str, Any]:
        """列表/详情统一视图：结业结果按口径现算，不改动库里的原始记录。

        已结业的记录优先展示登记结业时按口径写入的结果；历史数据没有该字段时
        用同一份口径补算，保证两个环境、多次打开页面看到的都一致。
        """
        view = dict(row)
        if row.get("status") == "已结业":
            result = str(row.get("结业结果") or "").strip()
            if not result:
                result = standard.graduation_result(standard.parse_score(row.get("考核成绩")))
            view["结业结果"] = result
        return view

    def summary(self) -> dict[str, Any]:
        """成绩列表的汇总口径：平均考核成绩只在这里算一份，各入口直接引用。"""
        rows = store.rows(MODULE)
        scores = []
        for row in rows:
            score = standard.parse_score(row.get("考核成绩"))
            if score is not None:
                scores.append(score)
        average = standard.average_score(scores)
        return {
            "待开班培训": sum(1 for row in rows if row.get("status") == "待开班"),
            "培训中课程": sum(1 for row in rows if row.get("status") == "培训中"),
            "平均考核成绩": str(average) if average is not None else None,
            "有效成绩数": len(scores),
            "口径版本": standard.STANDARD_VERSION,
        }

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str, list[dict[str, Any]]]:
        """执行动作并返回逐步检查结果：失败时调用方能看出是哪一步不通过。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"培训计划 {entry_id} 不存在或已归档", []
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于培训考核可执行范围", []
        if action == "确认开班":
            return self._confirm_opening(entry)
        if action == "登记结业":
            return self._complete(entry, values or {})
        return self._cancel(entry)

    def _confirm_opening(self, entry: dict[str, Any]) -> tuple[dict[str, Any] | None, str, list[dict[str, Any]]]:
        checks = standard.opening_checks(entry)
        failed = next((item for item in checks if not item["ok"]), None)
        if failed is not None:
            return None, f"确认开班未通过「{failed['step']}」：{failed['message']}", checks
        roster = standard.build_roster(entry.get("培训对象"))
        entry["status"] = "培训中"
        entry["pending"] = True
        entry["abnormal"] = False
        # 名单按口径生成后落到记录上，重新打开页面看到的是同一份，不再人工核对
        entry["开班名单"] = "、".join(roster)
        entry["名单人数"] = len(roster)
        entry["口径版本"] = standard.STANDARD_VERSION
        return entry, f"培训计划已确认开班，开班名单 {len(roster)} 人", checks

    def _complete(
        self,
        entry: dict[str, Any],
        values: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str, list[dict[str, Any]]]:
        # 状态不满足时直接失败，不做任何修改，避免流程走一半改了数据
        status_check = standard.completion_checks(entry)[0]
        if not status_check["ok"]:
            return None, f"登记结业未通过「{status_check['step']}」：{status_check['message']}", [status_check]
        # 允许登记结业时补录成绩：先按口径校验，通过才落库
        if "考核成绩" in values:
            score = standard.parse_score(values.get("考核成绩"))
            if score is None:
                checks = [
                    status_check,
                    standard.check("成绩检查", False, f"补录的考核成绩「{values.get('考核成绩')}」不是 0-100 的有效成绩"),
                ]
                return None, f"登记结业未通过「成绩检查」：{checks[-1]['message']}", checks
            entry["考核成绩"] = str(score)
        checks = standard.completion_checks(entry)
        failed = next((item for item in checks if not item["ok"]), None)
        if failed is not None:
            return None, f"登记结业未通过「{failed['step']}」：{failed['message']}", checks
        score = standard.parse_score(entry.get("考核成绩"))
        entry["status"] = "已结业"
        entry["pending"] = False
        entry["abnormal"] = False
        # 结业结果按口径判定后落到记录上，重新打开页面结果不变
        entry["结业结果"] = standard.graduation_result(score)
        entry["口径版本"] = standard.STANDARD_VERSION
        return entry, f"培训计划已登记结业，结业结果：{entry['结业结果']}", checks

    def _cancel(self, entry: dict[str, Any]) -> tuple[dict[str, Any] | None, str, list[dict[str, Any]]]:
        checks = standard.cancellation_checks(entry)
        failed = next((item for item in checks if not item["ok"]), None)
        if failed is not None:
            return None, f"取消培训未通过「{failed['step']}」：{failed['message']}", checks
        entry["status"] = "已取消"
        entry["pending"] = False
        entry["abnormal"] = False
        return entry, "培训计划已取消", checks
