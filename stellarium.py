import json
import math
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config import STELLARIUM_URL


# ============================================================
# Stellarium
# ============================================================

def get_stellarium_center():
    """視線ベクトルの中心座標 (J2000 度) を取得"""
    url = STELLARIUM_URL + "/api/main/view?coord=j2000"

    with urlopen(url, timeout=5) as response:
        data = json.load(response)

    x, y, z = json.loads(data["j2000"])
    length = math.sqrt(x*x + y*y + z*z)

    if not length:
        raise ValueError("無効な視線ベクトル")

    x, y, z = x/length, y/length, z/length

    ra = math.degrees(math.atan2(y, x)) % 360
    dec = math.degrees(
        math.atan2(z, math.hypot(x, y))
    )
    return ra, dec


def get_stellarium_selected():
    """
    Stellariumで現在選択されている天体のJ2000座標 (度) と名前を取得。
    天体が選択されていない場合は画面中心を取得。
    """
    url_info = STELLARIUM_URL + "/api/objects/info?format=json"

    try:
        with urlopen(url_info, timeout=5) as response:
            data = json.load(response)
    except Exception:
        data = {}

    if data and "raJ2000" in data and "decJ2000" in data:
        ra = float(data["raJ2000"]) % 360.0
        dec = float(data["decJ2000"])
        name = data.get("name") or data.get("localized-name") or "選択天体"
        return ra, dec, name

    ra, dec = get_stellarium_center()
    return ra, dec, "星図中心（未選択）"


def send_stellarium_script(code):
    data = urlencode({"code": code}).encode("utf-8")
    request = Request(
        STELLARIUM_URL + "/api/scripts/direct",
        data=data,
        method="POST"
    )

    with urlopen(request, timeout=15) as response:
        return response.read().decode(
            "utf-8", errors="replace"
        )


def remove_stellarium_frames(start, end):
    """指定範囲の撮影枠をStellariumから削除する"""
    if start > end:
        return

    code = "\n".join(
        f'core.removeSkyImage("smp_{i}");'
        for i in range(start, end + 1)
    )
    send_stellarium_script(code)


def load_stellarium_frames(panels, filenames, width, height):
    """モザイク撮影枠をStellariumへ表示する"""
    from mosaic import calculate_panel_corners

    for start in range(0, len(panels), 8):
        lines = []
        batch = panels[start:start + 8]

        for j, panel in enumerate(batch, start=start + 1):
            _, _, ra, dec = panel

            corners = calculate_panel_corners(
                ra, dec, width, height
            )

            values = [
                coordinate
                for corner in corners
                for coordinate in corner
            ]
            args = ", ".join(f"{v:.12f}" for v in values)

            lines.append(
                f'core.loadSkyImage('
                f'"smp_{j}", '
                f'"{filenames[j-1]}", '
                f'{args}, 0, 360, true);'
            )

        send_stellarium_script("\n".join(lines))
