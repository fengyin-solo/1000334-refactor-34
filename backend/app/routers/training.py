"""培训考核接口：维护培训计划，覆盖确认开班、登记结业、取消培训等动作。

平均成绩、开班条件、开班名单、结业判定统一走 services.training_standard 的口径。
注意：/summary、/standard、/export 必须注册在 /{entry_id} 之前，
否则会被详情路由截获，返回 422 而不是预期数据。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services import training_standard as standard
from app.services.training import TrainingService

router = APIRouter(prefix="/api/training", tags=["培训考核"])

service = TrainingService()

LIST_FIELDS = ["培训编号", "培训主题", "培训对象", "培训方式", "计划课时", "考核成绩", "培训日期", "培训状态", "开班名单", "结业结果"]
STATUSES = ["待开班", "培训中", "已结业", "已取消"]


@router.get("/summary")
def summary() -> dict[str, Any]:
    """成绩列表的汇总口径：平均考核成绩只在这里算一份，前端直接展示不重算。"""
    return service.summary()


@router.get("/standard")
def standard_info() -> dict[str, Any]:
    """当前生效的培训考核口径：部署新口径后，两个环境各自打开这里比对即可。"""
    return standard.standard_description()


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出培训考核清单：返回当前过滤条件下的全量数据，与列表走同一份口径。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "training", "total": total, "口径版本": standard.STANDARD_VERSION, "items": items}


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按培训编号检索"),
    status: str | None = Query(default=None, description="待开班、培训中、已结业、已取消"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按培训编号与状态过滤培训考核列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条培训计划明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"培训计划 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条培训计划，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="培训计划已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条培训计划执行确认开班、登记结业、取消培训。

    每个动作都先过统一口径的逐步检查：不通过时 ok=false 且 checks 里
    标出具体是哪一步、什么原因，流程不会改了一半数据才报错。
    """
    action = str(payload.values.get("action") or "").strip()
    entry, message, checks = service.run_action(entry_id, action, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message, checks=checks)
    return ActionResult(ok=True, message=message, entry=entry, checks=checks)
