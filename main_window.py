import csv
import json
import math
import sys
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

# ============================================================
# Seestar認証キーの最優先設定
# ============================================================
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = Path(__file__).resolve().parent

PEM_PATH = BASE_DIR / "seestar.pem"

try:
    from seestarpy import auth
    if PEM_PATH.exists():
        auth.set_key_path(str(PEM_PATH))
except Exception as e:
    print(f"警告: 認証キー設定失敗: {e}")

from PySide6.QtCore import Qt, QRect, QTime
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox,
    QFileDialog, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPushButton, QSpinBox,
    QTableWidget, QTableWidgetItem, QTimeEdit,
    QVBoxLayout, QWidget, QSlider
)

from mosaic import calculate_mosaic, calculate_panel_corners
from frame_renderer import create_frame_png
from stellarium import (
    get_stellarium_selected,
    send_stellarium_script,
    remove_stellarium_frames,
    load_stellarium_frames,
)
from seestar import (
    normalize_model,
    discover_seestars,
    transfer_plan,
)
from plan import create_seestar_plan

from config import (
    STELLARIUM_URL,
    SCRIPTS_DIR,
    TELESCOPES,
    PANEL_ROTATION,
    MAX_PANELS,
)



# ============================================================
# GUI
# ============================================================

class MosaicPlanner(QMainWindow):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("Seestar Mosaic Planner v0.5")
        self.resize(450, 400)

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
        self.telescope.setCurrentIndex(-1)
        self.telescope.currentTextChanged.connect(self.update_fov)

        self.connect_button = QPushButton("Seestar接続")
        self.connect_button.clicked.connect(self.connect_seestar)

        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(180)
        self.device_combo.setPlaceholderText("未検出")
        self.device_combo.currentIndexChanged.connect(self.device_changed)

        self.connection_label = QLabel("未接続")

        self.fov_width = self.double_spin(0.01, 90, 4.60, 3)
        self.fov_height = self.double_spin(0.01, 90, 2.59, 3)

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

        # ===== 基準座標 =====
        group = QGroupBox("基準座標（選択天体 / 星図中心）")
        h = QHBoxLayout(group)

        self.coord_label = QLabel("未取得")
        self.coord_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        button = QPushButton("選択天体/中心を取得")
        button.clicked.connect(self.get_center)

        h.addWidget(self.coord_label, 1)
        h.addWidget(button)
        layout.addWidget(group)

        # ===== モザイク設定 =====
        group = QGroupBox("モザイク設定")
        g = QGridLayout(group)

        self.cols = QSpinBox()
        self.cols.setRange(1, 20)
        self.cols.setValue(3)

        self.rows = QSpinBox()
        self.rows.setRange(1, 20)
        self.rows.setValue(3)

        self.overlap = self.double_spin(0, 90, 20, 1)

        g.addWidget(QLabel("南北方向"), 0, 0)
        g.addWidget(self.cols, 0, 1)
        g.addWidget(QLabel("東西方向"), 0, 2)
        g.addWidget(self.rows, 0, 3)
        g.addWidget(QLabel("重複率 (%)"), 0, 4)
        g.addWidget(self.overlap, 0, 5)

        # 撮影枠の明るさ
        self.frame_brightness = QSlider(Qt.Horizontal)
        self.frame_brightness.setRange(0, 100)
        self.frame_brightness.setValue(30)
        self.frame_brightness.setTickInterval(10)
        self.frame_brightness.setTickPosition(QSlider.TicksBelow)

        self.brightness_label = QLabel("30%")
        self.frame_brightness.valueChanged.connect(
            lambda value: self.brightness_label.setText(f"{value}%")
        )

        g.addWidget(QLabel("撮影枠の明るさ"), 1, 0)
        g.addWidget(self.frame_brightness, 1, 1, 1, 4)
        g.addWidget(self.brightness_label, 1, 5)

        layout.addWidget(group)

        # ===== 操作ボタン =====
        buttons = QHBoxLayout()

        actions = [
            ("モザイク計算", self.calculate),
            ("Stellariumに表示", self.show_on_stellarium),
            ("撮影枠を消去", self.clear_stellarium),
            ("構図保存", self.save_mosaic),
            ("構図読込", self.load_mosaic),
        ]

        for title, callback in actions:
            btn = QPushButton(title)
            btn.clicked.connect(callback)
            buttons.addWidget(btn)

        g.addLayout(buttons, 2, 0, 1, 6)

        #layout.addLayout(buttons)
        layout.addWidget(group)

        # ===== PLAN作成 =====
        group = QGroupBox("PLAN作成")
        g = QGridLayout(group)

        self.plan_name = QLineEdit("MosaicPlan")

        self.start_time = QTimeEdit()
        self.start_time.setDisplayFormat("HH:mm")
        self.start_time.setTime(QTime(21, 0))

        self.lp_filter = QCheckBox("LP_Filter")

        self.duration = QSpinBox()
        self.duration.setRange(1, 1440)
        self.duration.setValue(40)
        self.duration.setSuffix(" 分")

        self.repeat_count = QSpinBox()
        self.repeat_count.setRange(1, 99)
        self.repeat_count.setValue(1)
        self.repeat_count.setSuffix(" 回")

        self.plan_button = QPushButton("PLAN作成（JSON）")
        self.plan_button.clicked.connect(self.make_plan)

        self.transfer_button = QPushButton("Seestar転送")
        self.transfer_button.clicked.connect(self.send_plan_to_seestar)
        """
        g.addWidget(QLabel("プラン名"), 0, 0)
        g.addWidget(self.plan_name, 0, 1)
        g.addWidget(QLabel("開始時間"), 0, 2)
        g.addWidget(self.start_time, 0, 3)
        g.addWidget(self.lp_filter, 2, 1)
        g.addWidget(QLabel("繰り返し回数"), 1, 2)
        g.addWidget(self.repeat_count, 1, 3)

        g.addWidget(QLabel("1パネル撮影時間"), 1, 0)
        g.addWidget(self.duration, 1, 1)
        g.addWidget(self.plan_button, 2, 0, 1, 2)
        g.addWidget(self.transfer_button, 2, 2, 1, 2)
        """
        # 0行目：プラン名・LP_Filter
        g.addWidget(QLabel("プラン名"), 0, 0)
        g.addWidget(self.plan_name, 0, 1, 1, 3)
        g.addWidget(self.lp_filter, 0, 4, 1, 2)

        # 1行目：開始時間・撮影時間・繰り返し回数
        g.addWidget(QLabel("開始時間"), 1, 0)
        g.addWidget(self.start_time, 1, 1)
        g.addWidget(QLabel("撮影時間"), 1, 2)
        g.addWidget(self.duration, 1, 3)
        g.addWidget(QLabel("繰り返し回数"), 1, 4)
        g.addWidget(self.repeat_count, 1, 5)

        # 2行目：操作ボタン
        g.addWidget(self.plan_button, 2, 0, 1, 3)
        g.addWidget(self.transfer_button, 2, 3, 1, 3)

        layout.addWidget(group)

        # ===== 一覧 =====
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels([
            "南北", "東西", "RA (J2000 °)", "Dec (J2000 °)"
        ])

        self.table.setColumnWidth(0, 70)
        self.table.setColumnWidth(1, 70)
        self.table.setColumnWidth(2, 120)
        self.table.setColumnWidth(3, 120)

        layout.addWidget(self.table, 1)
        self.statusBar().showMessage("準備完了")
        self.cleanup_all_potential_frames()

    def save_mosaic(self):
        """現在のモザイク構図を保存"""
        from project_io import save_project

        if self.center_ra is None or self.center_dec is None:
            QMessageBox.warning(
                self, "確認", "先に基準座標を取得してください"
            )
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "モザイク構図を保存",
            "mosaic.smp",
            "Seestar Mosaic Planner (*.smp)"
        )
        if not path:
            return

        settings = {
            "telescope": self.telescope.currentText(),
            "fov_width": self.fov_width.value(),
            "fov_height": self.fov_height.value(),
            "center_ra": self.center_ra,
            "center_dec": self.center_dec,
            "cols": self.cols.value(),
            "rows": self.rows.value(),
            "overlap": self.overlap.value(),
        }

        try:
            save_project(path, settings)
            self.statusBar().showMessage(f"構図保存完了: {path}")
        except Exception as e:
            QMessageBox.critical(self, "保存エラー", str(e))

    def load_mosaic(self):
        """保存したモザイク構図を読み込む"""
        from project_io import load_project

        path, _ = QFileDialog.getOpenFileName(
            self,
            "モザイク構図を読み込む",
            "",
            "Seestar Mosaic Planner (*.smp)"
        )
        if not path:
            return

        try:
            data = load_project(path)

            # 古い撮影枠と計算結果を消去
            self.remove_drawn_frames()
            self.reset_calculation()

            # 機種・画角を復元
            self.telescope.setCurrentText(data["telescope"])
            self.fov_width.setValue(data["fov_width"])
            self.fov_height.setValue(data["fov_height"])

            # 基準座標を復元
            self.center_ra = float(data["center_ra"])
            self.center_dec = float(data["center_dec"])
            self.coord_label.setText(
                f"[読込構図] RA: {self.center_ra:.6f}° "
                f"({self.center_ra / 15.0:.4f}h)  "
                f"Dec: {self.center_dec:+.6f}°"
            )

            # モザイク設定を復元
            self.cols.setValue(data["cols"])
            self.rows.setValue(data["rows"])
            self.overlap.setValue(data["overlap"])

            self.statusBar().showMessage(f"構図読込完了: {path}")

        except Exception as e:
            QMessageBox.critical(self, "読込エラー", str(e))

    def cleanup_all_potential_frames(self):
        """前回のセッションで残った撮影枠を消去"""
        try:
            for start in range(1, MAX_PANELS + 1, 50):
                end = min(start + 49, MAX_PANELS)
                remove_stellarium_frames(start, end)
        except Exception:
            pass  # Stellarium未起動の場合は無視

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

            self.device_combo.blockSignals(True)
            try:
                for label, ip, model in devices:
                    self.device_combo.addItem(label, (ip, model))
                self.device_combo.setCurrentIndex(0)
            finally:
                self.device_combo.blockSignals(False)

            self.device_changed()

        except Exception as e:
            self.connection_label.setText("未接続")
            QMessageBox.warning(self, "Seestar検索エラー", str(e))
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

            if not isinstance(response, dict) or response.get("code") != 0:
                raise RuntimeError(f"接続失敗: {response}")

            self.connected_ip = ip
            self.connection_label.setText(f"接続済み: {ip}")

            model_key = normalize_model(model)
            if model_key in TELESCOPES:
                self.telescope.setCurrentText(model_key)
            else:
                QMessageBox.information(
                    self, "未登録機種",
                    f"検出機種: {model}\nこの機種の画角は未登録です。"
                )

        except Exception as e:
            self.connection_label.setText("未接続")
            QMessageBox.warning(self, "接続失敗", str(e))

    # ===== 撮影枠消去 =====

    def remove_drawn_frames(self):
        if self.drawn_count == 0:
            return

        for start in range(1, self.drawn_count + 1, 8):
            end = min(start + 7, self.drawn_count)
            remove_stellarium_frames(start, end)

        self.drawn_count = 0

    # ===== 基準座標取得 =====

    def get_center(self):
        try:
            ra, dec, name = get_stellarium_selected()
            self.remove_drawn_frames()

            self.center_ra = ra
            self.center_dec = dec
            self.coord_label.setText(
                f"[{name}] RA: {ra:.6f}° ({ra/15.0:.4f}h)  Dec: {dec:+.6f}°"
            )
            self.reset_calculation()

            self.statusBar().showMessage(
                f"{name} の座標を取得・撮影枠を消去しました"
            )
        except Exception as e:
            QMessageBox.warning(self, "Stellariumエラー", str(e))

    # ===== モザイク計算 =====

    def calculate(self):
        if self.center_ra is None:
            QMessageBox.warning(self, "確認", "基準座標を取得してください")
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

        for i, (row, col, ra, dec) in enumerate(self.panels):
            for j, value in enumerate([
                str(row), str(col), f"{ra:.8f}", f"{dec:+.8f}"
            ]):
                self.table.setItem(i, j, QTableWidgetItem(value))

        self.statusBar().showMessage(
            f"{len(self.panels)}パネルを計算しました"
        )

    def valid_calculation(self):
        if not self.panels:
            QMessageBox.warning(self, "確認", "先にモザイク計算してください")
            return False

        if self.get_settings() != self.calculation_settings:
            QMessageBox.warning(
                self, "確認",
                "設定が変更されています。\n再計算してください。"
            )
            return False

        return True

    # ===== Stellarium撮影枠表示 =====

    def show_on_stellarium(self):
        if not self.valid_calculation():
            return

        try:
            SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

            width = self.fov_width.value()
            height = self.fov_height.value()
            run_id = uuid.uuid4().hex[:12]

            filenames = []

            for i in range(1, len(self.panels) + 1):
                filename = f"smp_frame_{run_id}_{i:03d}.png"
                create_frame_png(
                    SCRIPTS_DIR / filename,
                    i, width, height,
                    self.frame_brightness.value()
                )
                filenames.append(filename)

            self.remove_drawn_frames()
            load_stellarium_frames(self.panels, filenames, width, height)
            self.drawn_count = len(self.panels)

            self.statusBar().showMessage(
                f"{len(self.panels)}枚の撮影枠を送信しました"
            )

        except Exception as e:
            QMessageBox.critical(self, "描画エラー", str(e))

    def clear_stellarium(self):
        try:
            self.remove_drawn_frames()
            self.statusBar().showMessage("撮影枠を消去しました")
        except Exception as e:
            QMessageBox.warning(self, "削除エラー", str(e))

    # ===== PLAN作成 =====

    def current_plan_settings(self):
        return (
            self.calculation_settings,
            self.plan_name.text().strip(),
            self.start_time.time().toString("HH:mm"),
            self.lp_filter.isChecked(),
            self.duration.value(),
            self.repeat_count.value()
        )

    def make_plan(self):
        if not self.valid_calculation():
            return

        name = self.plan_name.text().strip()
        if not name:
            QMessageBox.warning(self, "確認", "プラン名を入力してください")
            return

        t = self.start_time.time()
        start_min = t.hour() * 60 + t.minute()

        duration = self.duration.value()

        if start_min + duration * len(self.panels) * self.repeat_count.value() > 2880:
            QMessageBox.warning(
                self, "時刻エラー",
                "プラン終了時刻が開始日の翌日24時を超えています。\n"
                "開始時刻か撮影時間を変更してください。"
            )
            return

        data = create_seestar_plan(
            name, self.panels, start_min, duration,
            self.lp_filter.isChecked(),
            self.repeat_count.value()
        )

        path, _ = QFileDialog.getSaveFileName(
            self, "Seestar PLAN JSON保存", f"{name}.json", "JSON Files (*.json)"
        )
        if not path:
            return

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            self.plan_data = data
            self.plan_settings = self.current_plan_settings()
            self.statusBar().showMessage(f"PLAN作成完了: {path}")

        except Exception as e:
            QMessageBox.critical(self, "PLAN保存失敗", str(e))

    # ===== Seestar転送 =====

    def send_plan_to_seestar(self):
        if not self.connected_ip:
            QMessageBox.warning(self, "確認", "先にSeestarへ接続してください")
            return

        if not self.valid_calculation():
            return

        if self.plan_data is None:
            QMessageBox.warning(self, "確認", "先にPLAN作成を実行してください")
            return

        if self.current_plan_settings() != self.plan_settings:
            QMessageBox.warning(
                self, "確認",
                "PLAN作成後に設定が変更されています。\nPLANを作り直してください。"
            )
            return

        plan_name = self.plan_data["plan_name"]
        count = len(self.plan_data["list"])

        # 撮影終了予定時刻
        start = self.start_time.time()
        start_min = start.hour() * 60 + start.minute()
        total_min = self.duration.value() * count
        end_min = start_min + total_min

        end_time = f"{(end_min // 60) % 24:02d}:{end_min % 60:02d}"
        if end_min >= 1440:
            end_time = "翌日 " + end_time

        answer = QMessageBox.question(
            self,
            "Seestar転送確認",
            f"接続先: {self.connected_ip}\n"
            f"プラン: {plan_name}\n"
            f"パネル数: {len(self.panels)}\n"
            f"繰り返し回数: {self.repeat_count.value()}回\n"
            f"総撮影ターゲット数: {len(self.panels) * self.repeat_count.value()}\n"  
            f"1パネル: {self.duration.value()}分\n"
            f"開始時刻: {start.toString('HH:mm')}\n"
            f"終了予定: {end_time}\n"
            "露出時間: Seestar本体の設定を使用\n\n"
            "この操作はSeestarへの撮影プラン設定・実行予約を行います。\n"
            "すでに動作中の撮影にも影響する可能性があります。\n\n"
            "転送しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if answer != QMessageBox.Yes:
            return

        self.transfer_button.setEnabled(False)

        try:
            QApplication.processEvents()
            result = transfer_plan(self.connected_ip, self.plan_data)

            QMessageBox.information(
                self, "転送結果",
                "SeestarへのPLAN送信が完了しました。\n"
                f"応答: {result}\n\n"
                "撮影予約・実行状態をSeestar側でも確認してください。"
            )

        except Exception as e:
            QMessageBox.critical(self, "Seestar転送エラー", str(e))
        finally:
            self.transfer_button.setEnabled(True)

    # ===== CSV保存 =====

    def save_csv(self):
        if not self.valid_calculation():
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "CSV保存", "mosaic_plan.csv", "CSV Files (*.csv)"
        )
        if not path:
            return

        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["Row", "Column", "RA_J2000", "Dec_J2000"])
                writer.writerows(self.panels)

            self.statusBar().showMessage("CSVを保存しました")

        except Exception as e:
            QMessageBox.critical(self, "CSV保存失敗", str(e))
