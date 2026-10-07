from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from crud import dashboard as crud


async def get_summary(db: AsyncSession, activity_limit: int = 10) -> dict:
    now = datetime.now(timezone.utc)
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    if now.month == 12:
        next_month_start = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        next_month_start = datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)

    return {
        "equipment_stats": await crud.get_equipment_stats(db),
        "work_order_stats": await crud.get_work_order_stats(
            db,
            now,
            month_start,
            next_month_start,
        ),
        "failure_stats": await crud.get_failure_stats(db),
        "recent_activity": await crud.get_recent_activity(db, activity_limit),
    }
