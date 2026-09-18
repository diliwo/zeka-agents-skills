"""Consume normalized evidence references; never execute or invent test results."""

from common import require


def evaluate(evidence, cfg, head):
    require(evidence.get("repository") == cfg["repository"] and evidence.get("pr") == cfg["pr"],
            "evidence belongs to a different PR")
    require(evidence.get("head_sha") == head, "evidence belongs to a different SHA")
    statuses, passed = {}, True
    for name in ("focused", "regression", "protected_ci"):
        item = evidence.get(name) or {}
        status = item.get("status", "missing")
        require(status in ("passed", "failed", "pending", "missing", "unavailable", "not_required"),
                "invalid evidence status")
        valid = (status == "passed" and item.get("head_sha") == head and bool(item.get("ref")))
        # Waivers must be explicit Chief decisions; they cannot excuse regression/focused failures.
        if name == "protected_ci" and status == "not_required":
            waiver = item.get("waiver") or {}
            valid = (waiver.get("by") == "Chief" and bool(waiver.get("ref"))
                     and bool(waiver.get("reason")) and waiver.get("head_sha") == head)
        statuses[name] = {**item, "valid": bool(valid), "status": status}
        passed = passed and valid
    return {"passed": bool(passed), **statuses}
