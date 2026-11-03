
import csv
import json
import math
import sys
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from PySide6.QtCore import Qt, QRect, QTime
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox,
    QFileDialog, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPushButton, QSpinBox,
    QTableWidget, QTableWidgetItem, QTimeEdit,
    QVBoxLayout, QWidget
)

STELLARIUM_URL = "http://127.0.0.1:8090"

SCRIPTS_DIR = (
    Path.home() / "AppData" / "Roaming"
    / "Stellarium" / "scripts"
)

TELESCOPES = {
    "Seestar S30 Pro": (4.60, 2.59),
    "Seestar S50 Pro": (2.80, 1.575),
}

PANEL_ROTATION = 90.0
MAX_PANELS = 400


# ============================================================
# Stellarium
# ============================================================

def get_stellarium_center():
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
    step_x = width * (1-overlap/100)
    step_y = height * (1-overlap/100)

    panels = []

    for row in range(rows):
        for col in range(cols):
            x = (col-(cols-1)/2)*step_x
            y = ((rows-1)/2-row)*step_y

            dx, dy = rotate_offset(
                x, y, PANEL_ROTATION
            )
            pra, pdec = offset_coordinate(
                ra, dec, dx, dy
            )
            panels.append((row+1, col+1, pra, pdec))

    return panels


def calculate_panel_corners(ra, dec, width, height):
    corners = [
        ( width/2, -height/2),
        (-width/2, -height/2),
        (-width/2,  height/2),
        ( width/2,  height/2)
    ]

    result = []
    for x, y in corners:
        dx, dy = rotate_offset(
            x, y, PANEL_ROTATION
        )
        result.append(
            offset_coordinate(ra, dec, dx, dy)
        )
    return result


def create_frame_png(path, number, width, height):
    w = 800
    h = max(100, round(w*height/width))

    image = QImage(w, h, QImage.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))

    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)

    painter.setPen(QPen(QColor(255, 235, 30), 6))
    painter.setBrush(Qt.NoBrush)
    painter.drawRect(5, 5, w-11, h-11)

    painter.setPen(QColor(255, 255, 80))
    font = QFont("Arial")
    font.setPixelSize(48)
    font.setBold(True)
    painter.setFont(font)

    painter.drawText(
        QRect(24, 16, 200, 75),
        Qt.AlignLeft | Qt.AlignTop,
        str(number)
    )
    painter.end()

    if not image.save(str(path), "PNG"):
        raise OSError(f"PNG保存失敗: {path}")


# ============================================================
# Seestar
# ============================================================

def normalize_model(model):
    """検出された機種名を画角設定のキーへ変換。"""
    s = str(model).upper().replace(" ", "").replace("-", "")

    if "S30PRO" in s:
        return "Seestar S30 Pro"
    if "S50PRO" in s:
        return "Seestar S50 Pro"
    return None


def discover_seestars():
    """
    seestarpyによる検索。
    戻り値: [(表示名, IP, 機種名), ...]
    """
    from seestarpy import connection

    connection.discover()
    found = []

    for sn, info in connection.DISCOVERED.items():
        if not isinstance(info, dict):
            continue

        ip = info.get("ip")
        model = info.get("model", "")
        if not ip:
            continue

        label = f"{model} / {ip} / {sn}"
        found.append((label, ip, str(model)))

    return found


def create_seestar_plan(
    plan_name, panels, start_min, duration_min
):
    """
    Seestar撮影PLANのJSONデータを作成する。

    RA: Stellariumの度単位 → Seestarの時単位
    Dec: 度単位
    start_min: 現地時刻の午前0時からの経過分
    duration_min: 各パネルの撮影時間（分）
    """

    targets = []

    # 9桁のターゲットID
    base_id = (
        100000000
        + uuid.uuid4().int % 800000000
    )

    if base_id + len(panels) > 999999999:
        base_id = 100000000

    for i, (row, col, ra, dec) in enumerate(
        panels, start=1
    ):
        target = {
            "target_id": base_id + i,
            "target_name": f"SMP-P{i}",
            "alias_name": (
                f"{plan_name}-R{row}C{col}"
            ),
            "target_ra_dec": [
                round((ra / 15.0) % 24.0, 9),
                round(dec, 9)
            ],
            "lp_filter": False,
            "camera_mode": "tele",
            "skip": False,
            "start_min": (

                start_min
                + (i - 1) * duration_min
            ),
            "duration_min": duration_min
        }

        targets.append(target)

    return {
        "plan_name": plan_name,
        "update_time_seestar": (
            datetime.now().strftime("%Y.%m.%d")
        ),
        "list": targets
    }


def transfer_plan(ip, data):
    """
    Seestarに撮影PLANを転送する。

    ip: SeestarのIPアドレス
    data: PLAN JSONの辞書
    """
    from seestarpy import raw

    print(f"接続先: {ip}")

    # 1. 接続確認
    response = raw.test_connection(ips=ip)

    if not isinstance(response, dict):
        raise RuntimeError(
            f"接続応答が不正です: {response}"
        )

    if response.get("code") != 0:
        raise RuntimeError(
            f"Seestar接続失敗: {response}"
        )

    print("Seestar接続確認 OK")

    # 2. PLANの基本検証
    if not data.get("list"):
        raise ValueError("PLANに撮影対象がありません")

    for target in data["list"]:
        ra, dec = target["target_ra_dec"]

        if not (0 <= ra < 24 and -90 <= dec <= 90):
            raise ValueError(
                f"座標が不正です: {target}"
            )

    print(
        f"PLAN: {data['plan_name']} "
        f"({len(data['list'])}パネル)"
    )

    # Seestar本体の現在の露出設定を使用
    # 撮影PLAN転送
    from seestarpy import connection, plan

    # 送信先を接続済みのSeestarに固定
    connection.DEFAULT_IP = ip

    # 念のため送信先を確認
    target_ip = connection.current_ip()

    if target_ip != ip:
        raise RuntimeError(
            f"送信先IPが一致しません: {target_ip}"
        )

    print(f"PLAN転送先: {target_ip}")
    print("PLAN転送中...")

    result = plan.set_view_plan(data)

    print("PLAN転送応答:", result)

    if not isinstance(result, dict):
        raise RuntimeError(f"不正な応答: {result}")

    if result.get("code") != 0:
        raise RuntimeError(f"PLAN転送失敗: {result}")

    return result


# ============================================================
# GUI
# ============================================================

class MosaicPlanner(QMainWindow):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("Seestar Mosaic Planner v0.4")
        self.resize(980, 780)

        self.center_ra = None
        self.center_dec = None
        self.panels = []
        self.drawn_count = 0
        self.calculation_settings = None

        self.connected_ip = None
        self.plan_data = None
        self.plan_settings = None

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        # ===== 望遠鏡 =====
        group = QGroupBox("望遠鏡")
        g = QGridLayout(group)

        self.telescope = QComboBox()
        self.telescope.addItems(TELESCOPES.keys())
        self.telescope.setCurrentIndex(-1)  # 起動時は未選択。手動選択は従来どおり可能
        self.telescope.currentTextChanged.connect(
            self.update_fov
        )

        self.connect_button = QPushButton("Seestar接続")
        self.connect_button.clicked.connect(self.connect_seestar)

        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(180)
        self.device_combo.setPlaceholderText("未検出")
        self.device_combo.currentIndexChanged.connect(
            self.device_changed
        )

        self.connection_label = QLabel("未接続")

        self.fov_width = self.double_spin(
            0.01, 90, 4.60, 3
        )
        self.fov_height = self.double_spin(
            0.01, 90, 2.59, 3
        )

        g.addWidget(QLabel("機種"), 0, 0)
        g.addWidget(self.telescope, 0, 1)
        g.addWidget(self.connect_button, 0, 2)
        g.addWidget(self.connection_label, 0, 3)
        g.addWidget(QLabel("検出機器"), 1, 0)
        g.addWidget(self.device_combo, 1, 1, 1, 3)
        g.addWidget(QLabel("水平画角 (°)"), 2, 0)
        g.addWidget(self.fov_width, 2, 1)
        g.addWidget(QLabel("垂直画角 (°)"), 2, 2)
        g.addWidget(self.fov_height, 2, 3)

        layout.addWidget(group)

        # ===== 星図中心 =====
        group = QGroupBox("Stellarium 星図中心")
        h = QHBoxLayout(group)

        self.coord_label = QLabel("未取得")
        self.coord_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse
        )

        button = QPushButton("星図中心を取得")
        button.clicked.connect(self.get_center)

        h.addWidget(self.coord_label, 1)
        h.addWidget(button)
        layout.addWidget(group)

        # ===== モザイク設定 =====
        group = QGroupBox("モザイク設定")
        g = QGridLayout(group)

        self.cols = QSpinBox()
        self.cols.setRange(1, 20)
        self.cols.setValue(4)

        self.rows = QSpinBox()
        self.rows.setRange(1, 20)
        self.rows.setValue(2)

        self.overlap = self.double_spin(
            0, 90, 20, 1
        )

        g.addWidget(QLabel("列数"), 0, 0)
        g.addWidget(self.cols, 0, 1)
        g.addWidget(QLabel("行数"), 0, 2)
        g.addWidget(self.rows, 0, 3)
        g.addWidget(QLabel("重複率 (%)"), 1, 0)
        g.addWidget(self.overlap, 1, 1)

        layout.addWidget(group)

        # ===== 操作ボタン =====
        buttons = QHBoxLayout()

        actions = [
            ("モザイク計算", self.calculate),
            ("Stellariumに表示", self.show_on_stellarium),
            ("撮影枠を消去", self.clear_stellarium),
            ("CSV保存", self.save_csv),
        ]

        for title, callback in actions:
            button = QPushButton(title)
            button.clicked.connect(callback)
            buttons.addWidget(button)

        layout.addLayout(buttons)

        # ===== PLAN作成 =====
        group = QGroupBox("PLAN作成")
        g = QGridLayout(group)

        self.plan_name = QLineEdit("MosaicPlan")

        self.start_time = QTimeEdit()
        self.start_time.setDisplayFormat("HH:mm")
        self.start_time.setTime(QTime(21, 0))

        self.next_day = QCheckBox("翌日未明の開始")

        self.duration = QSpinBox()
        self.duration.setRange(1, 1440)
        self.duration.setValue(40)
        self.duration.setSuffix(" 分")

        self.plan_button = QPushButton("PLAN作成（JSON）")
        self.plan_button.clicked.connect(self.make_plan)

        self.transfer_button = QPushButton("Seestar転送")
        self.transfer_button.clicked.connect(
            self.send_plan_to_seestar
        )

        g.addWidget(QLabel("プラン名"), 0, 0)
        g.addWidget(self.plan_name, 0, 1)
        g.addWidget(QLabel("開始時間"), 0, 2)
        g.addWidget(self.start_time, 0, 3)
        g.addWidget(self.next_day, 1, 3)
        g.addWidget(QLabel("1パネル撮影時間"), 1, 0)
        g.addWidget(self.duration, 1, 1)
        g.addWidget(self.plan_button, 2, 0, 1, 2)
        g.addWidget(self.transfer_button, 2, 2, 1, 2)

        layout.addWidget(group)


        # ===== 一覧 =====
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels([
            "行", "列", "RA (J2000 °)", "Dec (J2000 °)"
        ])

        self.table.setColumnWidth(0, 70)
        self.table.setColumnWidth(1, 70)
        self.table.setColumnWidth(2, 220)
        self.table.setColumnWidth(3, 220)

        layout.addWidget(self.table, 1)

        self.statusBar().showMessage("準備完了")

    @staticmethod
    def double_spin(low, high, value, decimals):
        spin = QDoubleSpinBox()
        spin.setRange(low, high)
        spin.setDecimals(decimals)
        spin.setValue(value)
        return spin

    def get_settings(self):
        return (
            self.center_ra,
            self.center_dec,
            self.fov_width.value(),
            self.fov_height.value(),
            self.cols.value(),
            self.rows.value(),
            self.overlap.value()
        )

    def reset_calculation(self):
        self.panels = []
        self.calculation_settings = None
        self.table.setRowCount(0)
        self.plan_data = None
        self.plan_settings = None

    def update_fov(self, name):
        if name not in TELESCOPES:
            return
        width, height = TELESCOPES[name]
        self.fov_width.setValue(width)
        self.fov_height.setValue(height)
        self.reset_calculation()

    # ===== Seestar検出・接続 =====

    def connect_seestar(self):
        self.connected_ip = None
        self.device_combo.clear()
        self.connection_label.setText("検索中...")
        self.connect_button.setEnabled(False)

        try:
            QApplication.processEvents()
            devices = discover_seestars()

            if not devices:
                raise RuntimeError(
                    "Seestarが見つかりません。\n"
                    "ステーションモードとLAN接続を確認してください。"
                )

            # 検出機器をコンボボックスに登録
            self.device_combo.blockSignals(True)

            try:
                for label, ip, model in devices:
                    self.device_combo.addItem(
                        label, (ip, model)
                    )

                # 最初の機器を自動選択
                self.device_combo.setCurrentIndex(0)

            finally:
                self.device_combo.blockSignals(False)

            # 選択した機器に自動接続
            self.device_changed()

        except Exception as e:
            self.connection_label.setText("未接続")
            QMessageBox.warning(
                self, "Seestar検索エラー", str(e)
            )
        finally:
            self.connect_button.setEnabled(True)

    def device_changed(self, *_):
        selected = self.device_combo.currentData()
        self.connected_ip = None

        if not selected:
            self.connection_label.setText("未接続")
            return

        ip, model = selected

        try:
            from seestarpy import raw

            response = raw.test_connection(ips=ip)

            if not isinstance(response, dict):
                raise RuntimeError(
                    f"接続応答を確認できません: {response}"
                )

            if response.get("code") != 0:
                raise RuntimeError(
                    f"接続失敗: {response}"
                )

            self.connected_ip = ip
            self.connection_label.setText(
                f"接続済み: {ip}"
            )

            model_key = normalize_model(model)
            if model_key in TELESCOPES:
                self.telescope.setCurrentText(model_key)
            else:
                QMessageBox.information(
                    self,
                    "未登録機種",
                    f"検出機種: {model}\n"
                    "この機種の画角は未登録です。"
                )

        except Exception as e:
            self.connection_label.setText("未接続")
            QMessageBox.warning(
                self, "接続失敗", str(e)
            )

    # ===== 撮影枠削除 =====

    def remove_drawn_frames(self):
        if self.drawn_count == 0:
            return

        for start in range(1, self.drawn_count+1, 8):
            end = min(start+8, self.drawn_count+1)
            code = "\n".join(
                f'core.removeSkyImage("smp_{i}");'
                for i in range(start, end)
            )
            send_stellarium_script(code)

        self.drawn_count = 0

    # ===== 星図中心 =====

    def get_center(self):
        try:
            ra, dec = get_stellarium_center()
            self.remove_drawn_frames()

            self.center_ra = ra
            self.center_dec = dec
            self.coord_label.setText(
                f"RA: {ra:.8f}°  Dec: {dec:+.8f}°"
            )
            self.reset_calculation()

            self.statusBar().showMessage(
                "星図中心を取得・撮影枠を消去しました"
            )
        except Exception as e:
            QMessageBox.warning(
                self, "Stellariumエラー", str(e)
            )

    # ===== モザイク計算 =====

    def calculate(self):
        if self.center_ra is None:
            QMessageBox.warning(
                self, "確認",
                "星図中心を取得してください"
            )
            return

        self.reset_calculation()

        self.panels = calculate_mosaic(
            self.center_ra,
            self.center_dec,
            self.fov_width.value(),
            self.fov_height.value(),
            self.cols.value(),
            self.rows.value(),
            self.overlap.value()
        )

        self.calculation_settings = self.get_settings()
        self.table.setRowCount(len(self.panels))

        for i, (row, col, ra, dec) in enumerate(
            self.panels
        ):
            for j, value in enumerate([
                str(row), str(col),
                f"{ra:.8f}", f"{dec:+.8f}"
            ]):
                self.table.setItem(
                    i, j, QTableWidgetItem(value)
                )

        self.statusBar().showMessage(
            f"{len(self.panels)}パネルを計算しました"
        )

    def valid_calculation(self):
        if not self.panels:
            QMessageBox.warning(
                self, "確認",
                "先にモザイク計算してください"
            )
            return False

        if self.get_settings() != self.calculation_settings:
            QMessageBox.warning(
                self, "確認",
                "設定が変更されています。\n"
                "再計算してください。"
            )
            return False

        return True

    # ===== Stellarium撮影枠表示 =====

    def show_on_stellarium(self):
        if not self.valid_calculation():
            return

        try:
            SCRIPTS_DIR.mkdir(
                parents=True, exist_ok=True
            )

            width = self.fov_width.value()
            height = self.fov_height.value()
            run_id = uuid.uuid4().hex[:12]

            filenames = []

            for i in range(1, len(self.panels)+1):
                filename = (
                    f"smp_frame_{run_id}_{i:03d}.png"
                )
                create_frame_png(
                    SCRIPTS_DIR / filename,
                    i, width, height
                )
                filenames.append(filename)

            self.remove_drawn_frames()

            for start in range(0, len(self.panels), 8):
                lines = []
                batch = self.panels[start:start+8]

                for j, panel in enumerate(
                    batch, start=start+1
                ):
                    _, _, ra, dec = panel

                    corners = calculate_panel_corners(
                        ra, dec, width, height
                    )

                    values = [
                        coordinate
                        for corner in corners
                        for coordinate in corner
                    ]
                    args = ", ".join(
                        f"{v:.12f}" for v in values
                    )

                    lines.append(
                        f'core.loadSkyImage('
                        f'"smp_{j}", '
                        f'"{filenames[j-1]}", '
                        f'{args}, 2.5, 14, true, '
                        f'"EqJ2000", false);'
                    )

                send_stellarium_script(
                    "\n".join(lines)
                )
                self.drawn_count = start+len(batch)

            self.statusBar().showMessage(
                f"{len(self.panels)}枚の撮影枠を送信しました"
            )

        except Exception as e:
            QMessageBox.critical(
                self, "描画エラー", str(e)
            )

    def clear_stellarium(self):
        try:
            self.remove_drawn_frames()
            self.statusBar().showMessage(
                "撮影枠を消去しました"
            )
        except Exception as e:
            QMessageBox.warning(
                self, "削除エラー", str(e)
            )

    # ===== PLAN作成 =====

    def current_plan_settings(self):
        return (
            self.calculation_settings,
            self.plan_name.text().strip(),
            self.start_time.time().toString("HH:mm"),
            self.next_day.isChecked(),
            self.duration.value()
        )

    def make_plan(self):
        if not self.valid_calculation():
            return

        name = self.plan_name.text().strip()
        if not name:
            QMessageBox.warning(
                self, "確認",
                "プラン名を入力してください"
            )
            return

        t = self.start_time.time()
        start_min = t.hour()*60 + t.minute()

        if self.next_day.isChecked():
            start_min += 1440

        duration = self.duration.value()

        if start_min + duration*len(self.panels) > 2880:
            QMessageBox.warning(
                self, "時刻エラー",
                "プラン終了時刻が開始日の翌日24時を"
                "超えています。\n"
                "開始時刻か撮影時間を変更してください。"
            )
            return

        data = create_seestar_plan(
            name,
            self.panels,
            start_min,
            duration
        )

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Seestar PLAN JSON保存",
            f"{name}.json",
            "JSON Files (*.json)"
        )
        if not path:
            return

        try:
            with open(
                path, "w", encoding="utf-8"
            ) as f:
                json.dump(
                    data, f,
                    ensure_ascii=False,
                    indent=2
                )

            self.plan_data = data
            self.plan_settings = self.current_plan_settings()

            self.statusBar().showMessage(
                f"PLAN作成完了: {path}"
            )

        except Exception as e:
            QMessageBox.critical(
                self, "PLAN保存失敗", str(e)
            )

    # ===== Seestar転送 =====

    def send_plan_to_seestar(self):
        if not self.connected_ip:
            QMessageBox.warning(
                self, "確認",
                "先にSeestarへ接続してください"
            )
            return

        if not self.valid_calculation():
            return

        if self.plan_data is None:
            QMessageBox.warning(
                self, "確認",
                "先にPLAN作成を実行してください"
            )
            return

        if self.current_plan_settings() != self.plan_settings:
            QMessageBox.warning(
                self, "確認",
                "PLAN作成後に設定が変更されています。\n"
                "PLANを作り直してください。"
            )
            return

        plan_name = self.plan_data["plan_name"]
        count = len(self.plan_data["list"])

        answer = QMessageBox.question(
            self,
            "Seestar転送確認",
            f"接続先: {self.connected_ip}\n"
            f"プラン: {plan_name}\n"
            f"パネル数: {count}\n"
            f"1パネル: {self.duration.value()}分\n"
            "露出時間: Seestar本体の設定を使用\n\n"
            "この操作はSeestarへの撮影プラン設定・"
            "実行予約を行います。\n"
            "すでに動作中の撮影にも影響する"
            "可能性があります。\n\n"
            "転送しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if answer != QMessageBox.Yes:
            return

        self.transfer_button.setEnabled(False)

        try:
            QApplication.processEvents()

            result = transfer_plan(
                self.connected_ip,
                self.plan_data
            )

            QMessageBox.information(
                self,
                "転送結果",
                "SeestarへのPLAN送信が完了しました。\n"
                f"応答: {result}\n\n"
                "撮影予約・実行状態をSeestar側でも"
                "確認してください。"
            )

        except Exception as e:
            QMessageBox.critical(
                self, "Seestar転送エラー", str(e)
            )
        finally:
            self.transfer_button.setEnabled(True)

    # ===== CSV保存 =====

    def save_csv(self):
        if not self.valid_calculation():
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "CSV保存",
            "mosaic_plan.csv",
            "CSV Files (*.csv)"
        )

        if not path:
            return

        try:
            with open(
                path, "w", newline="",
                encoding="utf-8-sig"
            ) as f:
                writer = csv.writer(f)
                writer.writerow([
                    "Row", "Column",
                    "RA_J2000", "Dec_J2000"
                ])
                writer.writerows(self.panels)

            self.statusBar().showMessage(
                "CSVを保存しました"
            )

        except Exception as e:
            QMessageBox.critical(
                self, "CSV保存失敗", str(e)
            )


# ============================================================
# 起動
# ============================================================

if __name__ == "__main__":
    app = QApplication(sys.argv)

    window = MosaicPlanner()
    window.show()

    sys.exit(app.exec())
