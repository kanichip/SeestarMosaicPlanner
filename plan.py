import uuid
from datetime import datetime



def create_seestar_plan(
    plan_name, panels, start_min, duration_min, lp_filter,
    repeat_count
):
    targets = []

    base_id = (
        100000000
        + uuid.uuid4().int % 800000000
    )

    if base_id + len(panels) * repeat_count > 999999999:
        base_id = 100000000

    for i, (row, col, ra, dec) in enumerate(
            panels * repeat_count, start=1
    ):
        target = {
            "target_id": base_id + i,
            "target_name": f"SMP-P{i}",
            "alias_name": f"{plan_name}-P{i}",
            "target_ra_dec": [
                round((ra / 15.0) % 24.0, 9),
                round(dec, 9)
            ],
            "lp_filter": lp_filter,
            "camera_mode": "tele",
            "skip": False,
            "start_min": start_min + (i - 1) * duration_min,
            "duration_min": duration_min
        }
        targets.append(target)

    return {
        "plan_name": plan_name,
        "update_time_seestar": datetime.now().strftime("%Y.%m.%d"),
        "list": targets
    }

