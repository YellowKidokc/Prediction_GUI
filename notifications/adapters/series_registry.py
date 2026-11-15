"""GUI presentation adapter for David-OS-owned inference."""
from prediction.series_registry import *  # noqa: F401,F403
from notifications.contract import NotificationItem, NotificationTemplate

def submit(engine, names: list[str], desktop: bool = True) -> str:
    registry = records(); items = []
    for name in names:
        result = classify(name, registry)
        items.append(NotificationItem(name, result["code"], f"{result['status']}: {result['series_name']}",
            {"current_value":name, "confidence":result["confidence"], "risk_class":"canon_authority",
             "auto_approvable":False, "sidecar_lifecycle":"PD", "series_match":result}))
    return engine.submit(NotificationTemplate.APPROVAL_BATCH, "Series classification review",
        "Workbook matches are identified; unmatched names receive a proposed 3-4 character code.",
        f"series-registry:{locate()}", items, desktop=desktop)
