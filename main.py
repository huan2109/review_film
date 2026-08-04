import json
import os
import re
import sys
import traceback
from typing import Any, Dict, List

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QUrl
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QSplitter,
    QProgressBar
)

try:
    from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
    from PyQt6.QtMultimediaWidgets import QVideoWidget
    HAS_MULTIMEDIA = True
except ImportError:
    HAS_MULTIMEDIA = False

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from src.controllers.worker_thread import ScriptParseWorker, GeminiSrtGenWorker, FFmpegRenderWorker


# ==========================================
# 0. TIMELINE WIDGET COMPONENT
# ==========================================
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

        width = max(int(duration * 25), 90)
        self.setFixedSize(width, 50)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

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
            "QScrollArea { background-color: #1E1E1E; border: 1px solid #333; }"
        )

        self.container = QWidget()
        self.container_layout = QHBoxLayout(self.container)
        self.container_layout.setContentsMargins(10, 10, 10, 10)
        self.container_layout.setSpacing(4)
        self.container_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)

        self.setWidget(self.container)

    def set_scenes(self, scenes):
        """Xóa Timeline cũ và vẽ lại danh sách Shots mới"""
        while self.container_layout.count():
            item = self.container_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for scene in scenes:
            if isinstance(scene, dict):
                scene_id = scene.get("scene_id", 1)
                in_tc = scene.get("in_time", "00:00:00")
                out_tc = scene.get("out_time", "00:00:00")
                duration = float(scene.get("estimated_duration_sec", 5.0))
                text = scene.get("review_text", "")
            else:
                raw_str = str(scene)
                match = re.search(r'"review_text"\s*:\s*"([^"]+)"', raw_str, re.DOTALL)
                text = match.group(1).strip() if match else raw_str
                scene_id = 1
                in_tc = "00:00:00"
                out_tc = "00:00:05"
                duration = 5.0

            block = BRollTimelineBlock(
                scene_id, in_tc, out_tc, duration, text
            )
            block.clicked.connect(self._on_block_clicked)
            self.container_layout.addWidget(block)

    def _on_block_clicked(self, scene_id):
        self.shot_selected.emit(scene_id)


# ==========================================
# 1. MAIN APPLICATION WINDOW (GIAO DIỆN CHÍNH)
# ==========================================
class AutoReviewLiteApp(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("AutoReview Lite - Master Clean JSON & Text Grid Version")
        self.resize(1450, 900)
        self.script_data = []

        try:
            from src.services.gemini_service import GeminiService

            self.gemini_service = GeminiService()
        except Exception:
            self.gemini_service = None

        self._init_ui()
        self._init_player()

    def _init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # 0. API CONFIG BAR AT TOP
        api_config_frame = QFrame()
        api_config_frame.setFrameShape(QFrame.Shape.StyledPanel)
        api_config_frame.setLayout(self._build_api_config_layout())
        main_layout.addWidget(api_config_frame)

        # SPLITTER CHÍNH BỐ TRÍ DÒNG CHẢY BÊN TRÁI & KHU PREVIEW BÊN PHẢI
        main_splitter = QSplitter(Qt.Orientation.Horizontal)

        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # ----- PHẦN 1: NGUỒN ĐẦU VÀO (3 INPUTS) -----
        input_group = QFrame()
        input_group.setFrameShape(QFrame.Shape.StyledPanel)
        input_layout = QVBoxLayout(input_group)

        # 1. Source Video Input
        row_video = QHBoxLayout()
        row_video.addWidget(QLabel("🎬 <b>Source Video:</b>"))
        self.txt_video_path = QLineEdit()
        self.txt_video_path.setPlaceholderText("Đường dẫn file video gốc...")
        row_video.addWidget(self.txt_video_path)
        btn_browse_video = QPushButton("📁 Chọn Video")
        btn_browse_video.clicked.connect(self._browse_video)
        row_video.addWidget(btn_browse_video)
        input_layout.addLayout(row_video)

        # 2. Sub SRT Input
        row_srt = QHBoxLayout()
        row_srt.addWidget(QLabel("📝 <b>Sub SRT Gốc:</b>"))
        self.txt_srt_path = QLineEdit()
        self.txt_srt_path.setPlaceholderText(
            "Đường dẫn file phụ đề (.srt)..."
        )
        row_srt.addWidget(self.txt_srt_path)
        btn_browse_srt = QPushButton("📁 Chọn Sub SRT")
        btn_browse_srt.clicked.connect(self._browse_srt)
        row_srt.addWidget(btn_browse_srt)
        input_layout.addLayout(row_srt)

        # 3. Kịch Bản Thô Text Area
        input_layout.addWidget(
            QLabel(
                "📋 <b>Kịch Bản Thô (Dán Bảng 3 Cột STT | Voice | Timecode hoặc"
                " JSON):</b>"
            )
        )
        self.txt_script_input = QTextEdit()
        self.txt_script_input.setPlaceholderText(
            "Dán kịch bản 26 shots dạng bảng Markdown hoặc JSON vào đây..."
        )
        self.txt_script_input.setMaximumHeight(100)
        input_layout.addWidget(self.txt_script_input)

        left_layout.addWidget(input_group)

        # ----- PHẦN 2: CÁC NÚT THỰC THI CHÍNH (4 BUTTONS BAO GỒM GEMINI AI) -----
        btn_action_layout = QHBoxLayout()

        self.btn_run = QPushButton("🚀 RUN (Tạo Kịch Bản Realtime)")
        self.btn_run.setStyleSheet(
            "background-color: #2E86C1; color: white; font-weight: bold;"
            " font-size: 13px; padding: 10px;"
        )
        self.btn_run.clicked.connect(self._on_btn_run_clicked)
        btn_action_layout.addWidget(self.btn_run)

        self.btn_gen_srt = QPushButton("🤖 Tạo Kịch Bản Từ Sub SRT (Gemini AI)")
        self.btn_gen_srt.setStyleSheet(
            "background-color: #8E44AD; color: white; font-weight: bold;"
            " font-size: 13px; padding: 10px;"
        )
        self.btn_gen_srt.clicked.connect(self._on_generate_script_from_srt_clicked)
        btn_action_layout.addWidget(self.btn_gen_srt)

        self.btn_export_txt = QPushButton("🔊 Xuất File Thuyết Minh (.txt)")
        self.btn_export_txt.setStyleSheet(
            "background-color: #E67E22; color: white; font-weight: bold;"
            " font-size: 13px; padding: 10px;"
        )
        self.btn_export_txt.clicked.connect(
            self._on_export_voiceover_txt_clicked
        )
        btn_action_layout.addWidget(self.btn_export_txt)

        self.btn_render = QPushButton("🎬 Render Video MP4 (Clean)")
        self.btn_render.setStyleSheet(
            "background-color: #00E676; color: black; font-weight: bold;"
            " font-size: 13px; padding: 10px;"
        )
        self.btn_render.clicked.connect(self._on_render_video_clicked)
        btn_action_layout.addWidget(self.btn_render)

        left_layout.addLayout(btn_action_layout)

        # ----- PHẦN 3: BẢNG SCRIPT GRID DISPLAY VỚI CỘT TIMELINE B-ROLL -----
        self.table_grid = QTableWidget()
        self.table_grid.setColumnCount(6)
        self.table_grid.setHorizontalHeaderLabels(
            ["ID", "Timecode In", "Timecode Out", "Timeline & Thời Lượng", "Lời Thuyết Minh", "Gợi Ý B-Roll"]
        )
        self.table_grid.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.Stretch
        )
        self.table_grid.cellClicked.connect(self._on_table_item_clicked)
        left_layout.addWidget(self.table_grid)

        # ----- PHẦN 4: TIMELINE B-ROLL TRỰC QUAN (VISUAL TIMELINE WIDGET) -----
        left_layout.addWidget(QLabel("🎬 <b>Cửa Sổ Timeline B-Roll Trực Quan (CapCut/Premiere Style):</b>"))
        self.timeline_view = BRollTimelineView()
        self.timeline_view.shot_selected.connect(self._on_timeline_shot_selected)
        left_layout.addWidget(self.timeline_view)

        # ----- PHẦN 5: MÀN HÌNH PREVIEW VIDEO BÊN PHẢI -----
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        right_layout.addWidget(QLabel("📺 <b>Màn Hình Preview B-Roll Video:</b>"))

        if HAS_MULTIMEDIA:
            self.video_widget = QVideoWidget()
            self.video_widget.setStyleSheet("background-color: #000000; border-radius: 6px;")
            right_layout.addWidget(self.video_widget, stretch=1)
        else:
            lbl_no_media = QLabel("🎥 Cần PyQt6.QtMultimedia để phát Preview Video")
            lbl_no_media.setAlignment(Qt.AlignmentFlag.AlignCenter)
            right_layout.addWidget(lbl_no_media, stretch=1)

        self.txt_inspector = QTextEdit()
        self.txt_inspector.setReadOnly(True)
        self.txt_inspector.setPlaceholderText("Click vào 1 khối Shot trên Timeline hoặc Bảng Grid để tự động xem trước Video...")
        self.txt_inspector.setMaximumHeight(150)
        right_layout.addWidget(self.txt_inspector)

        main_splitter.addWidget(left_widget)
        main_splitter.addWidget(right_widget)
        main_splitter.setSizes([870, 580])

        main_layout.addWidget(main_splitter)

        # Status Bar
        self.status_label = QLabel("⚪ Trạng thái: Sẵn sàng")
        main_layout.addWidget(self.status_label)

    def _build_api_config_layout(self) -> QHBoxLayout:
        layout = QHBoxLayout()

        layout.addWidget(QLabel("🔑 <b>Gemini API Key:</b>"))

        self.txt_api_key = QLineEdit()
        self.txt_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_api_key.setPlaceholderText("Dán API Key Gemini vào đây...")
        self.txt_api_key.setText(os.getenv("GEMINI_API_KEY", ""))
        layout.addWidget(self.txt_api_key, stretch=2)

        self.btn_toggle_key = QPushButton("👁️")
        self.btn_toggle_key.setFixedWidth(35)
        self.btn_toggle_key.clicked.connect(self._toggle_api_key_visibility)
        layout.addWidget(self.btn_toggle_key)

        layout.addWidget(QLabel("🤖 <b>Model:</b>"))
        self.cbo_model = QComboBox()
        self.cbo_model.addItems([
            "gemini-2.5-flash",
            "gemini-1.5-flash",
            "gemini-1.5-pro",
            "gemini-flash-latest",
        ])
        layout.addWidget(self.cbo_model, stretch=1)

        return layout

    def _toggle_api_key_visibility(self):
        if self.txt_api_key.echoMode() == QLineEdit.EchoMode.Password:
            self.txt_api_key.setEchoMode(QLineEdit.EchoMode.Normal)
            self.btn_toggle_key.setText("🔒")
        else:
            self.txt_api_key.setEchoMode(QLineEdit.EchoMode.Password)
            self.btn_toggle_key.setText("👁️")

    def _init_player(self):
        if HAS_MULTIMEDIA:
            self.media_player = QMediaPlayer()
            self.audio_output = QAudioOutput()
            self.media_player.setAudioOutput(self.audio_output)
            self.media_player.setVideoOutput(self.video_widget)

    # ----- CÁC HÀM XỬ LÝ SỰ KIỆN -----
    def _browse_video(self):
        f, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn Source Video",
            "",
            "Video Files (*.mp4 *.mkv *.avi);;All Files (*)",
        )
        if f:
            self.txt_video_path.setText(f)
            if HAS_MULTIMEDIA and hasattr(self, "media_player"):
                self.media_player.setSource(QUrl.fromLocalFile(f))

    def _browse_srt(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "Chọn Sub SRT", "", "Subtitles (*.srt);;All Files (*)"
        )
        if f:
            self.txt_srt_path.setText(f)

    def _on_btn_run_clicked(self):
        raw_script = self.txt_script_input.toPlainText().strip()
        if not raw_script:
            QMessageBox.warning(
                self, "Cảnh báo", "Vui lòng dán Kịch bản thô vào ô văn bản!"
            )
            return

        self.btn_run.setEnabled(False)
        self.status_label.setText(
            "🟡 Đang tạo kịch bản realtime & đối chiếu timecode..."
        )

        self.parse_worker = ScriptParseWorker(
            raw_script=raw_script,
            srt_path=self.txt_srt_path.text().strip(),
            gemini_service=self.gemini_service,
        )
        self.parse_worker.finished_signal.connect(self._on_run_success)
        self.parse_worker.error_signal.connect(self._on_run_error)
        self.parse_worker.start()

    def _on_run_success(self, scenes):
        self.btn_run.setEnabled(True)
        self.script_data = scenes
        self._populate_table()
        self.status_label.setText(
            f"🟢 Đã tạo kịch bản realtime thành công với {len(scenes)} Shots!"
        )
        QMessageBox.information(
            self,
            "Thành công",
            f"Đã đối chiếu Timecode & nạp {len(scenes)} Shots kịch bản lên Bảng Grid!",
        )

    def _on_run_error(self, err_msg):
        self.btn_run.setEnabled(True)
        self.status_label.setText("🔴 Lỗi đối chiếu kịch bản!")
        QMessageBox.critical(
            self, "Lỗi đối chiếu", f"Không thể xử lý kịch bản: {err_msg}"
        )

    def _on_generate_script_from_srt_clicked(self):
        srt_path = self.txt_srt_path.text().strip()
        api_key = self.txt_api_key.text().strip()
        selected_model = self.cbo_model.currentText()

        if not api_key:
            QMessageBox.warning(
                self,
                "Thiếu API Key",
                "Vui lòng nhập Gemini API Key trước khi gọi AI!",
            )
            return

        if not srt_path or not os.path.exists(srt_path):
            QMessageBox.warning(
                self,
                "Thiếu File SRT",
                "Vui lòng chọn file Sub SRT gốc để Gemini phân tích!",
            )
            return

        self.btn_gen_srt.setEnabled(False)
        self.status_label.setText(
            f"🤖 Gemini ({selected_model}) đang đọc Sub SRT và phân tích kịch"
            " bản..."
        )

        self.srt_ai_worker = GeminiSrtGenWorker(
            srt_path=srt_path,
            api_key=api_key,
            model_name=selected_model,
            gemini_service=self.gemini_service,
        )
        self.srt_ai_worker.finished_signal.connect(self._on_srt_ai_success)
        self.srt_ai_worker.error_signal.connect(self._on_srt_ai_error)
        self.srt_ai_worker.start()

    def _on_srt_ai_success(self, scenes):
        self.btn_gen_srt.setEnabled(True)
        self.script_data = scenes
        self._populate_table()

        self.status_label.setText(
            f"🟢 Gemini đã tạo thành công kịch bản {len(scenes)} Shots từ Sub SRT!"
        )
        QMessageBox.information(
            self,
            "Thành công",
            f"Đã phân tích Sub SRT & tạo {len(scenes)} Shots kịch bản!",
        )

    def _on_srt_ai_error(self, err_msg):
        self.btn_gen_srt.setEnabled(True)
        self.status_label.setText("🔴 Lỗi tạo kịch bản từ Sub SRT!")
        QMessageBox.critical(
            self, "Lỗi Gemini API", f"Không thể tạo kịch bản từ SRT: {err_msg}"
        )

    # ----- 1. SỬA HÀM NẠP DỮ LIỆU LÊN BẢNG GRID (_populate_table) -----
    def _populate_table(self):
        self.table_grid.setRowCount(0)

        for row_idx, scene in enumerate(self.script_data):
            self.table_grid.insertRow(row_idx)

            # Xử lý lấy review_text sạch
            voice_text = ""
            if isinstance(scene, dict):
                voice_text = str(scene.get("review_text", "")).strip()
            else:
                # Trường hợp scene bị dính chuỗi String JSON
                raw_str = str(scene)
                match = re.search(
                    r'"review_text"\s*:\s*"([^"]+)"', raw_str, re.DOTALL
                )
                if match:
                    voice_text = match.group(1).strip()
                else:
                    voice_text = raw_str

            # Làm sạch tuyệt đối các ký tự JSON thừa còn sót
            voice_text = re.sub(
                r'^"?review_text"?:?\s*"?', "", voice_text, flags=re.IGNORECASE
            )
            voice_text = voice_text.strip(' "',)

            # Lấy các trường thông tin
            scene_id = (
                scene.get("scene_id", row_idx + 1)
                if isinstance(scene, dict)
                else (row_idx + 1)
            )
            in_tc = str(scene.get("in_time", "")) if isinstance(scene, dict) else ""
            out_tc = str(scene.get("out_time", "")) if isinstance(scene, dict) else ""
            visual = (
                str(scene.get("visual_suggestion", ""))
                if isinstance(scene, dict)
                else ""
            )

            dur_sec = float(scene.get("estimated_duration_sec", 5.0)) if isinstance(scene, dict) else 5.0
            timeline_str = f"{in_tc[:8]} ➜ {out_tc[:8]} ({dur_sec:.1f}s)" if in_tc and out_tc else f"({dur_sec:.1f}s)"

            # Gán lên từng ô chuẩn xác
            self.table_grid.setItem(row_idx, 0, QTableWidgetItem(str(scene_id)))
            self.table_grid.setItem(row_idx, 1, QTableWidgetItem(in_tc))
            self.table_grid.setItem(row_idx, 2, QTableWidgetItem(out_tc))
            self.table_grid.setItem(row_idx, 3, QTableWidgetItem(timeline_str))
            self.table_grid.setItem(row_idx, 4, QTableWidgetItem(voice_text))
            self.table_grid.setItem(row_idx, 5, QTableWidgetItem(visual))

        if hasattr(self, "timeline_view"):
            self.timeline_view.set_scenes(self.script_data)

    def _on_timeline_shot_selected(self, scene_id: int):
        for row_idx, scene in enumerate(self.script_data):
            sc_id = scene.get("scene_id") if isinstance(scene, dict) else (row_idx + 1)
            if sc_id == scene_id:
                self.table_grid.selectRow(row_idx)
                self._on_table_item_clicked(row_idx, 0)
                break

    def _on_table_item_clicked(self, row: int, column: int):
        if row < len(self.script_data):
            scene = self.script_data[row]
            if isinstance(scene, dict):
                in_tc = scene.get("in_time", "00:00:00.000")
                out_tc = scene.get("out_time", "00:00:05.000")
                dur = scene.get("estimated_duration_sec", 5.0)
                voice_text = scene.get("review_text", "")
                visual_sug = scene.get("visual_suggestion", "")
                scene_id = scene.get("scene_id", row + 1)
            else:
                in_tc = "00:00:00.000"
                out_tc = "00:00:05.000"
                dur = 5.0
                voice_text = str(scene)
                visual_sug = ""
                scene_id = row + 1

            clean_voice = re.sub(r'^"?review_text"?:?\s*"?', "", str(voice_text), flags=re.IGNORECASE).strip(' "',)

            ms = self._timecode_to_milliseconds(in_tc)
            video_p = self.txt_video_path.text().strip()

            if HAS_MULTIMEDIA and hasattr(self, "media_player") and video_p and os.path.exists(video_p):
                self.media_player.setSource(QUrl.fromLocalFile(video_p))
                self.media_player.setPosition(ms)
                self.media_player.play()

            info = f"📌 SHOT #{scene_id}\n"
            info += f"• Mốc Timecode: {in_tc} -> {out_tc} ({dur}s)\n"
            info += f"💬 Lời Thuyết Minh:\n{clean_voice}\n\n"
            info += f"🎬 Cảnh B-Roll:\n{visual_sug}"
            self.txt_inspector.setText(info)

    def _timecode_to_milliseconds(self, tc_str: str) -> int:
        try:
            parts = tc_str.replace(",", ".").split(":")
            h = int(parts[0])
            m = int(parts[1])
            s_parts = parts[2].split(".")
            s = int(s_parts[0])
            ms = int(s_parts[1]) if len(s_parts) > 1 else 0
            return ((h * 3600) + (m * 60) + s) * 1000 + ms
        except Exception:
            return 0

    # ----- 2. SỬA HÀM XUẤT FILE THUYẾT MINH (.TXT) - CHỈ LẤY LỜI NÓI THUẦN TEXT -----
    def _on_export_voiceover_txt_clicked(self):
        if not hasattr(self, "script_data") or not self.script_data:
            QMessageBox.warning(
                self, "Cảnh báo", "Chưa có dữ liệu kịch bản trên Grid để xuất!"
            )
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Lưu File Thuyết Minh Thuần Text",
            "LoiThuyetMinh_Clean.txt",
            "Text Files (*.txt)",
        )

        if file_path:
            try:
                clean_texts = []
                for scene in self.script_data:
                    voice_text = ""
                    if isinstance(scene, dict):
                        voice_text = str(scene.get("review_text", "")).strip()
                    else:
                        raw_str = str(scene)
                        match = re.search(
                            r'"review_text"\s*:\s*"([^"]+)"', raw_str, re.DOTALL
                        )
                        if match:
                            voice_text = match.group(1).strip()
                        else:
                            voice_text = raw_str

                    clean_str = re.sub(
                        r'^"?review_text"?:?\s*"?', "", voice_text, flags=re.IGNORECASE
                    )
                    clean_str = clean_str.strip(' "',)

                    if clean_str:
                        clean_texts.append(clean_str)

                full_voice_content = "\n\n".join(clean_texts)

                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(full_voice_content)

                QMessageBox.information(
                    self,
                    "Thành công",
                    f"Đã xuất File Thuyết Minh Thuần Text sạch 100% ra:\n{file_path}",
                )
            except Exception as e:
                QMessageBox.critical(
                    self, "Lỗi", f"Không thể xuất file thuyết minh: {str(e)}"
                )

    def _on_render_video_clicked(self):
        if not self.script_data:
            QMessageBox.warning(
                self, "Cảnh báo", "Vui lòng bấm RUN để tạo kịch bản trước khi Render!"
            )
            return
        video_p = self.txt_video_path.text().strip()
        if not video_p or not os.path.exists(video_p):
            QMessageBox.warning(
                self, "Cảnh báo", "Vui lòng chọn file Source Video hợp lệ!"
            )
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Lưu Video Review (Clean Video)", "AutoReview_Clean_Render.mp4", "Video Files (*.mp4)"
        )

        if file_path:
            self.btn_run.setEnabled(False)
            self.btn_render.setEnabled(False)
            self.status_label.setText("🎬 Đang Render Video MP4 thuần (Sạch sẽ, KHÔNG SUB)...")

            try:
                from src.controllers.worker_thread import FFmpegRenderWorker
                self.render_worker = FFmpegRenderWorker(
                    source_video_path=video_p,
                    scenes=self.script_data,
                    output_mp4_path=file_path
                )
                self.render_worker.status_updated.connect(lambda msg, pct: self.status_label.setText(f"🎬 {msg}"))
                self.render_worker.render_finished.connect(self._on_render_success)
                self.render_worker.error_occurred.connect(self._on_render_error)
                self.render_worker.start()
            except Exception as e:
                self.btn_run.setEnabled(True)
                self.btn_render.setEnabled(True)
                QMessageBox.critical(self, "Lỗi Render", f"Không thể tạo worker render: {str(e)}")

    def _on_render_success(self, rendered_mp4_path: str):
        self.btn_run.setEnabled(True)
        self.btn_render.setEnabled(True)
        self.status_label.setText("🎉 Render Video MP4 Hoàn Tất (Clean Video, KHÔNG SUB)!")
        QMessageBox.information(
            self, "🎉 Render MP4 Thành Công",
            f"🎬 Đã xuất thành công Video Review MP4 thuần (Sạch sẽ, KHÔNG SUB) tại:\n{rendered_mp4_path}"
        )

    def _on_render_error(self, error_msg: str):
        self.btn_run.setEnabled(True)
        self.btn_render.setEnabled(True)
        self.status_label.setText("🔴 Lỗi Render Video MP4!")
        QMessageBox.critical(
            self, "Lỗi Render Video", f"Không thể Render MP4:\n\n{error_msg}"
        )


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = AutoReviewLiteApp()
    window.show()
    sys.exit(app.exec())
