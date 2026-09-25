"""培训考核业务规则：状态流转、字段校验与筛选口径都收在这里。

考核成绩的解析、及格线、开班/结业条件在全模块只有这一份口径：
开班入口（确认开班）与成绩列表（统计卡片、开班名单）都调用这里的函数。
口径只依赖标准库 Decimal，不读环境变量、不依赖运行环境，
本地演示环境与正式环境跑同一份代码，算出来的自然是同一份结果。
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from app.store import store

MODULE = "training"
REQUIRED_FIELDS = ["培训编号", "培训主题", "培训对象"]
OPTIONAL_FIELDS = ["培训方式", "计划课时", "考核成绩", "培训日期"]
STATUS_ORDER = ["待开班", "培训中", "已结业", "已取消"]
TERMINAL_STATUSES = ["已结业", "已取消"]
ACTION_RULES = {"确认开班": "培训中", "登记结业": "已结业", "取消培训": "已取消"}
NEGATIVE_ACTIONS = ["取消培训"]

# ---- 考核成绩口径：全模块唯一出处，调整口径只改这一段 ----
SCORE_FIELD = "考核成绩"
PASS_SCORE = Decimal("60")  # 及格线：成绩达到该分数才算考核合格，方可登记结业
AVERAGE_QUANT = Decimal("0.1")  # 平均成绩统一保留 1 位小数，四舍五入


def parse_score(raw: Any) -> Decimal | None:
    """把考核成绩解析成分数；未录入、占位文本或不是数字时返回 None。

    兼容「85」「85.5」「90分」与数值本身；同样的输入在任何环境下结果一致。
    """
    if raw is None or isinstance(raw, bool):
        return None
    text = str(raw).strip()
    if text.endswith("分"):
        text = text[:-1].strip()
    if not text:
        return None
    try:
        score = Decimal(text)
    except InvalidOperation:
        return None
    return score if score.is_finite() else None


def average_score(rows: list[dict[str, Any]]) -> float | None:
    """已录入有效成绩的平均分；没有有效成绩时返回 None，页面显示「—」。"""
    scores = [score for row in rows if (score := parse_score(row.get(SCORE_FIELD))) is not None]
    if not scores:
        return None
    mean = (sum(scores) / len(scores)).quantize(AVERAGE_QUANT, rounding=ROUND_HALF_UP)
    return float(mean)


@dataclass(frozen=True)
class Check:
    """流程里的一步校验：不通过时能指名是哪一步、卡在哪。"""

    step: str
    passed: bool
    detail: str


def _has_text(entry: dict[str, Any], field: str) -> bool:
    return bool(str(entry.get(field) or "").strip())


def action_checks(action: str, entry: dict[str, Any]) -> list[Check]:
    """按动作给出分步校验清单，开班入口与开班名单共用同一套判断。"""
    status = str(entry.get("status") or "")
    if action == "确认开班":
        return [
            Check("状态检查", status == "待开班", f"当前状态为「{status}」，只有「待开班」才能确认开班"),
            Check("必填字段", all(_has_text(entry, field) for field in REQUIRED_FIELDS),
                  "培训编号、培训主题、培训对象需填写完整"),
            Check("培训日期", _has_text(entry, "培训日期"), "培训日期未排定"),
        ]
    if action == "登记结业":
        score = parse_score(entry.get(SCORE_FIELD))
        return [
            Check("状态检查", status == "培训中", f"当前状态为「{status}」，只有「培训中」才能登记结业"),
            Check("成绩录入", score is not None, "考核成绩未录入或不是有效数字"),
            Check("成绩合格", score is not None and score >= PASS_SCORE,
                  "考核成绩未录入" if score is None else f"考核成绩 {score} 未达到及格线 {PASS_SCORE} 分"),
        ]
    if action == "取消培训":
        return [
            Check("状态检查", status in ("待开班", "培训中"),
                  f"当前状态为「{status}」，已结业或已取消的培训不能再取消"),
        ]
    return []


def class_ready(entry: dict[str, Any]) -> bool:
    """开班名单口径：确认开班的全部分步校验都通过，无需人工再核对。"""
    return all(check.passed for check in action_checks("确认开班", entry))


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
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def summary(self) -> dict[str, Any]:
        """成绩列表的统计卡片与开班名单：和开班入口共用同一份考核口径。

        统计基于全量培训数据，不受列表筛选条件影响，重复读取结果不变。
        """
        rows = store.rows(MODULE)
        stats = [
            {"label": "待开班培训", "value": sum(1 for row in rows if row.get("status") == "待开班")},
            {"label": "培训中课程", "value": sum(1 for row in rows if row.get("status") == "培训中")},
            {"label": "平均考核成绩", "value": average_score(rows)},
        ]
        roster = [
            {
                "id": row.get("id"),
                "培训编号": row.get("培训编号"),
                "培训主题": row.get("培训主题"),
                "培训日期": row.get("培训日期"),
            }
            for row in rows
            if class_ready(row)
        ]
        return {"module": MODULE, "stats": stats, "开班名单": roster}

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        for field in OPTIONAL_FIELDS:
            if values.get(field) is not None:
                entry[field] = values.get(field)
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"培训计划 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于培训考核可执行范围"
        for check in action_checks(action, entry):
            if not check.passed:
                return None, f"{action}未通过【{check.step}】：{check.detail}"
        target = ACTION_RULES[action]
        entry["status"] = target
        entry["pending"] = target not in TERMINAL_STATUSES
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"培训计划已{action}"
