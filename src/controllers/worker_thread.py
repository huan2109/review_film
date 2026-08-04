import os
import re
import traceback
from typing import List, Dict, Any
from PyQt6.QtCore import QThread, pyqtSignal

from src.services.srt_parser import SRTParser
from src.services.gemini_service import GeminiService, DynamicPromptConfig
from src.services.video_editor_service import VideoEditorService
from src.exporters.srt_exporter import SRTExporter


class ScriptParseWorker(QThread):
    """
    Worker Thread chạy ngầm bóc tách dữ liệu kịch bản thô & đối chiếu thông minh với Sub SRT gốc
    GIỮ NGUYÊN 100% TIMECODE GỐC CỦA KỊCH BẢN / PHIM.
    """

    finished_signal = pyqtSignal(list)
    error_signal = pyqtSignal(str)

    def __init__(
        self,
        raw_script: str,
        srt_path: str = "",
        gemini_service: GeminiService = None,
        parent=None,
    ):
        super().__init__(parent)
        self.raw_script = raw_script
        self.srt_path = srt_path
        self.gemini_service = gemini_service or GeminiService()

    def run(self):
        try:
            # 1. Bóc tách kịch bản thô (JSON / Bảng Markdown 3 cột / Text)
            scenes = self.gemini_service._parse_and_validate_json(self.raw_script)

            # 2. Nếu người dùng chọn file Sub SRT gốc, đối chiếu thông minh giữ nguyên timecode chuẩn
            if self.srt_path and os.path.exists(self.srt_path):
                scenes = self.gemini_service._match_voice_to_srt_timecodes(scenes, self.srt_path)

            if not scenes:
                raise ValueError("Không bóc tách được phân cảnh nào từ kịch bản thô.")

            self.finished_signal.emit(scenes)

        except Exception as e:
            self.error_signal.emit(str(e))


class GeminiSrtGenWorker(QThread):
    """
    Worker Thread sinh kịch bản review tự động 100 Shots qua Gemini AI từ Sub SRT gốc.
    """

    finished_signal = pyqtSignal(list)
    error_signal = pyqtSignal(str)

    def __init__(
        self,
        srt_path: str,
        api_key: str,
        model_name: str,
        gemini_service: GeminiService = None,
        parent=None,
    ):
        super().__init__(parent)
        self.srt_path = srt_path
        self.api_key = api_key
        self.model_name = model_name
        self.gemini_service = gemini_service or GeminiService(api_key=api_key, model_name=model_name)

    def run(self):
        try:
            parser = SRTParser(self.srt_path)
            items = parser.load_and_parse()
            if not items:
                raise ValueError("File Sub SRT rỗng hoặc không đúng định dạng.")

            compressed_text = parser.get_compressed_srt_text(items, max_words=8000)
            config = DynamicPromptConfig(
                api_key=self.api_key,
                movie_title="",
                genre="",
                main_characters=[],
                selected_model=self.model_name
            )

            service = GeminiService(api_key=self.api_key, model_name=self.model_name)
            scenes = service.generate_review_script(config=config, timestamped_srt_text=compressed_text, srt_path=self.srt_path)

            if not scenes:
                raise ValueError("Gemini AI không trả về phân cảnh kịch bản nào.")

            self.finished_signal.emit(scenes)

        except Exception as e:
            self.error_signal.emit(str(e))


class GeminiAnalysisWorker(QThread):
    """
    Worker Thread Bước 1: Đọc SRT và thực hiện Phân tích Timeline & Cốt truyện chuyên sâu (NotebookLM Mode).
    """

    status_updated = pyqtSignal(str)
    analysis_finished = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, api_key: str, model_name: str, srt_file_path: str, parent=None):
        super().__init__(parent)
        self.api_key = api_key
        self.model_name = model_name
        self.srt_file_path = srt_file_path

    def run(self):
        try:
            self.status_updated.emit("📄 Đang đọc và tối ưu dung lượng Token file SRT...")
            parser = SRTParser(self.srt_file_path)
            items = parser.load_and_parse()

            if not items:
                self.error_occurred.emit("File phụ đề SRT rỗng hoặc không đúng cấu trúc.")
                return

            compressed_srt_text = parser.get_compressed_srt_text(items, max_words=8000)
            self.status_updated.emit(f"🧠 Đang gửi {len(items)} câu thoại tới Gemini AI ({self.model_name}) để phân tích Timeline...")

            service = GeminiService(api_key=self.api_key, model_name=self.model_name)
            analysis_result = service.analyze_srt_structure(compressed_srt_text, model_name=self.model_name)

            self.status_updated.emit("🎉 Hoàn tất Phân tích Timeline Sub SRT!")
            self.analysis_finished.emit(analysis_result)

        except Exception as e:
            error_msg = f"Lỗi trong quá trình Phân tích Timeline SRT: {str(e)}\n\nChi tiết:\n{traceback.format_exc()}"
            self.error_occurred.emit(error_msg)


class GeminiScriptWorker(QThread):
    """
    Worker Thread Bước 2: Kế thừa 100% Phân tích từ Bước 1 (hoặc NotebookLM Context) để sinh kịch bản review 100 shots.
    """

    status_updated = pyqtSignal(str)
    script_generated = pyqtSignal(list)
    error_occurred = pyqtSignal(str)

    def __init__(self, config: DynamicPromptConfig, srt_file_path: str = "", parent=None):
        super().__init__(parent)
        self.config = config
        self.srt_file_path = srt_file_path

    def run(self):
        try:
            service = GeminiService(
                api_key=self.config.api_key,
                model_name=self.config.selected_model
            )

            if self.config.analysis_context and self.config.analysis_context.strip():
                self.status_updated.emit(f"🚀 BƯỚC 2: Kế thừa Bản phân tích (không gửi lại SRT thô)... Đang sinh kịch bản {self.config.selected_model}...")
                scenes = service.generate_review_script_from_analysis(
                    config=self.config,
                    analysis_text_from_step1=self.config.analysis_context.strip()
                )
            else:
                self.status_updated.emit("📄 Đang đọc file SRT gốc...")
                parser = SRTParser(self.srt_file_path)
                items = parser.load_and_parse()

                if not items:
                    self.error_occurred.emit("File phụ đề SRT rỗng hoặc không đúng cấu trúc.")
                    return

                compressed_srt_text = parser.get_compressed_srt_text(items, max_words=8000)
                self.status_updated.emit(f"🚀 Đang gửi dữ liệu tới Gemini ({self.config.selected_model}) để sinh kịch bản review...")

                scenes = service.generate_review_script(
                    config=self.config,
                    timestamped_srt_text=compressed_srt_text,
                    srt_path=self.srt_file_path
                )

            self.status_updated.emit(f"🎉 Hoàn tất BƯỚC 2! Đã tạo xong {len(scenes)} phân cảnh kịch bản review.")
            self.script_generated.emit(scenes)

        except Exception as e:
            error_msg = f"Lỗi trong quá trình tạo kịch bản AI: {str(e)}\n\nChi tiết:\n{traceback.format_exc()}"
            self.error_occurred.emit(error_msg)


class FFmpegRenderWorker(QThread):
    """
    Worker Thread chịu trách nhiệm chạy FFmpeg băm cắt B-Roll và Render Video MP4 ngầm.
    """

    status_updated = pyqtSignal(str, int)
    render_finished = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, source_video_path: str, scenes: List[Dict[str, Any]], output_mp4_path: str, parent=None):
        super().__init__(parent)
        self.source_video_path = source_video_path
        self.scenes = scenes
        self.output_mp4_path = output_mp4_path

    def run(self):
        try:
            self.status_updated.emit("📝 Đang tạo file phụ đề thuyết minh tạm thời...", 5)
            temp_srt = os.path.join(os.path.dirname(os.path.abspath(self.output_mp4_path)), "temp_voiceover.srt")
            SRTExporter().export(self.scenes, temp_srt)

            total_scenes = len(self.scenes)

            def progress_cb(msg: str):
                pct = 10
                if "băm B-Roll" in msg:
                    try:
                        idx_match = re.search(r'Shot (\d+)/(\d+)', msg)
                        if idx_match:
                            cur_i = int(idx_match.group(1))
                            tot_i = int(idx_match.group(2))
                            pct = int(10 + (cur_i / tot_i) * 75)
                    except Exception:
                        pct = 50
                elif "ghép các vết cắt" in msg:
                    pct = 90

                self.status_updated.emit(msg, pct)

            editor = VideoEditorService()
            rendered_mp4 = editor.render_full_review_video(
                source_video_path=self.source_video_path,
                scenes=self.scenes,
                srt_file_path=temp_srt,
                output_mp4_path=self.output_mp4_path,
                progress_callback=progress_cb
            )

            self.status_updated.emit("🎉 Render Video Review MP4 Hoàn Tất!", 100)
            self.render_finished.emit(rendered_mp4)

        except Exception as e:
            error_msg = f"Lỗi trong quá trình Render MP4: {str(e)}\n\nChi tiết:\n{traceback.format_exc()}"
            self.error_occurred.emit(error_msg)
