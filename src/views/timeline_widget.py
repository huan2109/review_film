from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class BRollTimelineBlock(QWidget):
    """Mỗi khối đại diện cho 1 Shot B-Roll trên Timeline"""

    clicked = pyqtSignal(int)  # Phát ra scene_id khi click

    def __init__(
        self, scene_id, in_time, out_time, duration, text, parent=None
    ):
        super().__init__(parent)
        self.scene_id = scene_id
        self.in_time = in_time
        self.out_time = out_time
        self.duration = duration
        self.text = text

        # Tính chiều rộng khối theo thời lượng (Ví dụ: 1 giây = 25px, tối thiểu 90px)
        width = max(int(duration * 25), 90)
        self.setFixedSize(width, 50)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        # Style đẹp mắt như track V1
        self.setStyleSheet("""
            QWidget {
                background-color: #2E7D32;
                border: 1px solid #81C784;
                border-radius: 4px;
                color: white;
            }
            QWidget:hover {
                background-color: #388E3C;
                border: 2px solid #FFFFFF;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)

        lbl_id = QLabel(f"<b>Shot #{scene_id}</b> [{duration:.1f}s]")
        lbl_id.setFont(QFont("Arial", 8))
        lbl_id.setStyleSheet("color: #E8F5E9; border: none;")

        lbl_tc = QLabel(f"{in_time}")
        lbl_tc.setFont(QFont("Arial", 7))
        lbl_tc.setStyleSheet("color: #C8E6C9; border: none;")

        layout.addWidget(lbl_id)
        layout.addWidget(lbl_tc)

    def mousePressEvent(self, event):
        self.clicked.emit(self.scene_id)


class BRollTimelineView(QScrollArea):
    """Cửa sổ cuộn ngang chứa toàn bộ Timeline B-Roll"""

    shot_selected = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFixedHeight(95)
        self.setStyleSheet(
            "QScrollArea { background-color: #1E1E1E; border: 1px solid"
            " #333; }"
        )

        self.container = QWidget()
        self.container_layout = QHBoxLayout(self.container)
        self.container_layout.setContentsMargins(10, 10, 10, 10)
        self.container_layout.setSpacing(4)
        self.container_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)

        self.setWidget(self.container)

    def set_scenes(self, scenes):
        """Xóa Timeline cũ và vẽ lại danh sách Shots mới"""
        # Clear cũ
        while self.container_layout.count():
            item = self.container_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Thêm các khối Shot mới
        for scene in scenes:
            scene_id = scene.get("scene_id", 1)
            in_tc = scene.get("in_time", "00:00:00")
            out_tc = scene.get("out_time", "00:00:00")
            duration = float(scene.get("estimated_duration_sec", 5.0))
            text = scene.get("review_text", "")

            block = BRollTimelineBlock(
                scene_id, in_tc, out_tc, duration, text
            )
            block.clicked.connect(self._on_block_clicked)
            self.container_layout.addWidget(block)

    def _on_block_clicked(self, scene_id):
        self.shot_selected.emit(scene_id)
