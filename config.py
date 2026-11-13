
from pathlib import Path

# Stellarium Remote Control API
STELLARIUM_URL = "http://127.0.0.1:8090"

# Stellarium スクリプト保存先
SCRIPTS_DIR = (
    Path.home() / "AppData" / "Roaming"
    / "Stellarium" / "scripts"
)

# Seestar 機種別画角（水平・垂直、度）
TELESCOPES = {
    #"Seestar S30 Pro": (4.60, 2.59),
    "Seestar S30 Pro": (4.009, 2.256),
    #"Seestar S50 Pro": (2.80, 1.575),
    "Seestar S50 Pro": (2.45, 1.38),
    "Seestar S30": (2.45, 1.38),
    "Seestar S50": (2.45, 1.38),
}

# モザイク設定
PANEL_ROTATION = 90.0
MAX_PANELS = 400
