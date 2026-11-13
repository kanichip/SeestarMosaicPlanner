
import json
from pathlib import Path


def save_project(path, settings):
    """モザイク構図の設定をJSON形式で保存"""
    data = {
        "version": 1,
        "name": settings.get("name", "MosaicPlan"),
        "telescope": settings["telescope"],
        "fov_width": settings["fov_width"],
        "fov_height": settings["fov_height"],
        "center_ra": settings["center_ra"],
        "center_dec": settings["center_dec"],
        "cols": settings["cols"],
        "rows": settings["rows"],
        "overlap": settings["overlap"],
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_project(path):
    """保存したモザイク構図の設定を読み込む"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if data.get("version") != 1:
        raise ValueError("未対応のモザイク構図ファイルです")

    required = (
        "telescope", "fov_width", "fov_height",
        "center_ra", "center_dec",
        "cols", "rows", "overlap"
    )
    for key in required:
        if key not in data:
            raise ValueError(f"設定項目がありません: {key}")

    return data
