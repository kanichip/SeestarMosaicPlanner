
import sys

from PySide6.QtWidgets import QApplication
from main_window import MosaicPlanner


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MosaicPlanner()
    window.show()
    sys.exit(app.exec())
