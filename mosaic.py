import math

from config import PANEL_ROTATION

# ============================================================
# モザイク計算
# ============================================================

def offset_coordinate(ra, dec, dx, dy):
    a = math.radians(ra)
    d = math.radians(dec)

    center = (
        math.cos(d)*math.cos(a),
        math.cos(d)*math.sin(a),
        math.sin(d)
    )
    east = (-math.sin(a), math.cos(a), 0)
    north = (
        -math.sin(d)*math.cos(a),
        -math.sin(d)*math.sin(a),
        math.cos(d)
    )

    x = math.tan(math.radians(dx))
    y = math.tan(math.radians(dy))

    v = [
        center[i] + x*east[i] + y*north[i]
        for i in range(3)
    ]

    length = math.sqrt(sum(t*t for t in v))
    v = [t/length for t in v]

    return (
        math.degrees(math.atan2(v[1], v[0])) % 360,
        math.degrees(
            math.atan2(v[2], math.hypot(v[0], v[1]))
        )
    )


def rotate_offset(x, y, angle):
    t = math.radians(angle)
    return (
        x*math.cos(t) - y*math.sin(t),
        x*math.sin(t) + y*math.cos(t)
    )


def calculate_mosaic(
    ra, dec, width, height, cols, rows, overlap
):
    step_x = width * (1 - overlap / 100)
    step_y = height * (1 - overlap / 100)

    panels = []

    for row in range(rows):
        for col in range(cols):
            x = (col - (cols - 1) / 2.0) * step_x
            y = ((rows - 1) / 2.0 - row) * step_y

            dx, dy = rotate_offset(x, y, PANEL_ROTATION)
            pra, pdec = offset_coordinate(ra, dec, dx, dy)
            panels.append((row + 1, col + 1, pra, pdec))

    return panels


def calculate_panel_corners(ra, dec, width, height):
    corners = [
        ( width / 2.0, -height / 2.0),
        (-width / 2.0, -height / 2.0),
        (-width / 2.0,  height / 2.0),
        ( width / 2.0,  height / 2.0)
    ]

    result = []
    for x, y in corners:
        dx, dy = rotate_offset(x, y, PANEL_ROTATION)
        result.append(offset_coordinate(ra, dec, dx, dy))
    return result
