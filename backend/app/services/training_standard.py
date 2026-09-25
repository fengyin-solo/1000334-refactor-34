"""培训考核口径：全系统唯一一份，成绩列表、开班入口、结业登记、导出都从这里取数。

历史问题：平均考核成绩、开班条件、结业判定曾分散在多个入口各自实现，
本地演示环境与正式环境算出来的结果对不上，改一次口径要逐个入口核对。
现在口径只在本文件维护：

- 两个环境部署同一份代码，算出来的就是同一份结果；
- 全部用 Decimal 按固定规则舍入，不依赖运行环境的浮点行为；
- 检查不依赖当前时间等外部状态，同一批数据重复计算结果不变；
- GET /api/training/standard 能直接读出当前口径，部署新口径后核对这一处即可。
"""
from __future__ import annotations

from decimal import InvalidOperation, ROUND_HALF_UP, Decimal
from typing import Any, Iterable

# 口径版本：每次调整口径必须同步更新，便于两个环境核对部署的是否是同一份。
STANDARD_VERSION = "training-standard/2026.09.1"

PASS_SCORE = Decimal("60")          # 结业合格线：成绩达到该分数判定为合格
MIN_SCORE = Decimal("0")
MAX_SCORE = Decimal("100")
MIN_ROSTER_SIZE = 1                 # 开班名单最少人数
AVERAGE_QUANT = Decimal("0.1")      # 平均考核成绩统一保留 1 位小数（ROUND_HALF_UP）

REQUIRED_FIELDS = ["培训编号", "培训主题", "培训对象"]
ROSTER_SEPARATORS = ("、", "，", ",", "；", ";", "/", " ", "\n")


def parse_score(raw: Any) -> Decimal | None:
    """把「考核成绩」统一解析成 0-100 的 Decimal；空值、非数字、越界一律视为未录入。"""
    if raw is None or isinstance(raw, bool):
        return None
    text = str(raw).strip()
    for suffix in ("分", "%"):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    if not text:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    if not value.is_finite() or value < MIN_SCORE or value > MAX_SCORE:
        return None
    return value


def graduation_result(score: Decimal | None) -> str:
    """结业判定：有有效成绩按合格线判定，没有有效成绩一律「未评定」。"""
    if score is None:
        return "未评定"
    return "合格" if score >= PASS_SCORE else "不合格"


def average_score(scores: Iterable[Decimal]) -> Decimal | None:
    """平均考核成绩：只对有效成绩取平均，统一 ROUND_HALF_UP 保留 1 位小数。

    用 Decimal 而不是 float，保证任何环境下逐位一致；没有有效成绩时返回 None。
    """
    values = list(scores)
    if not values:
        return None
    mean = sum(values, Decimal("0")) / len(values)
    return mean.quantize(AVERAGE_QUANT, rounding=ROUND_HALF_UP)


def build_roster(audience: Any) -> list[str]:
    """从「培训对象」自动拆出开班名单：统一分隔符、去空白、去重且保持原顺序。

    名单由口径自动生成，不再依赖人工核对；同一输入在任何环境都会得到同一份名单。
    """
    text = str(audience or "").strip()
    if not text:
        return []
    parts = [text]
    for separator in ROSTER_SEPARATORS:
        parts = [piece for part in parts for piece in part.split(separator)]
    roster: list[str] = []
    for piece in parts:
        name = piece.strip()
        if name and name not in roster:
            roster.append(name)
    return roster


def check(step: str, ok: bool, message: str) -> dict[str, Any]:
    """一步口径检查的结果：步骤名、是否通过、可读说明。"""
    return {"step": step, "ok": ok, "message": message}


def opening_checks(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """确认开班前的口径检查：每一步都有明确结论，失败能定位到具体步骤。"""
    status = str(entry.get("status") or "")
    status_text = status or "未知"
    missing = [field for field in REQUIRED_FIELDS if not str(entry.get(field) or "").strip()]
    roster = build_roster(entry.get("培训对象"))
    return [
        check(
            "状态检查",
            status == "待开班",
            "状态为「待开班」，可以确认开班"
            if status == "待开班"
            else f"当前状态为「{status_text}」，仅「待开班」的培训计划可以确认开班",
        ),
        check(
            "资料完整性",
            not missing,
            "必填资料齐全" if not missing else f"缺少必填字段：{'、'.join(missing)}",
        ),
        check(
            "开班名单",
            len(roster) >= MIN_ROSTER_SIZE,
            f"已按口径生成开班名单 {len(roster)} 人"
            if len(roster) >= MIN_ROSTER_SIZE
            else "培训对象为空，无法生成开班名单",
        ),
    ]


def completion_checks(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """登记结业前的口径检查。"""
    status = str(entry.get("status") or "")
    status_text = status or "未知"
    score = parse_score(entry.get("考核成绩"))
    return [
        check(
            "状态检查",
            status == "培训中",
            "状态为「培训中」，可以登记结业"
            if status == "培训中"
            else f"当前状态为「{status_text}」，仅「培训中」的培训计划可以登记结业",
        ),
        check(
            "成绩检查",
            score is not None,
            "考核成绩已录入且有效"
            if score is not None
            else "考核成绩未录入或不是 0-100 的有效成绩，无法按口径判定结业结果",
        ),
    ]


def cancellation_checks(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """取消培训前的口径检查：已结业、已取消的计划不允许再取消。"""
    status = str(entry.get("status") or "")
    status_text = status or "未知"
    cancellable = status in ("待开班", "培训中")
    return [
        check(
            "状态检查",
            cancellable,
            "状态允许取消"
            if cancellable
            else f"当前状态为「{status_text}」，已结业或已取消的培训计划不能再取消",
        ),
    ]


def standard_description() -> dict[str, Any]:
    """当前口径的完整描述：部署核对、前端展示都读这一份，保证两边看到的是同一口径。"""
    return {
        "version": STANDARD_VERSION,
        "pass_score": str(PASS_SCORE),
        "score_range": [str(MIN_SCORE), str(MAX_SCORE)],
        "min_roster_size": MIN_ROSTER_SIZE,
        "average_rule": "仅对 0-100 的有效成绩取平均，ROUND_HALF_UP 保留 1 位小数；无有效成绩时不计",
        "graduation_rule": f"有效成绩达到 {PASS_SCORE} 判定合格，否则不合格；未录入有效成绩为未评定",
        "roster_rule": "培训对象按 、 ， , ； ; / 空格 换行 拆分，去空白去重后即为开班名单",
        "opening_steps": ["状态检查", "资料完整性", "开班名单"],
        "completion_steps": ["状态检查", "成绩检查"],
    }
