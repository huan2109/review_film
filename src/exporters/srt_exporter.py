import os
from typing import List, Dict, Any


class SRTExporter:
    """Exporter chịu trách nhiệm tạo file kịch bản thuyết minh (SRT liên tục & TXT cho TTS/Voice Talent)."""

    def __init__(self, fps: float = 29.97):
        self.fps = fps

    def export(self, scenes: List[Dict[str, Any]], output_path: str) -> str:
        """
        Xuất kịch bản thuyết minh liên tục không có khoảng lặng (no gaps) với mã hóa UTF-8 with BOM.
        Nếu extension là .txt thì xuất văn bản đọc thuần cho Voice Talent / TTS.
        """
        if not scenes:
            raise ValueError("Danh sách phân cảnh kịch bản rỗng, không thể xuất file.")

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        ext = os.path.splitext(output_path)[1].lower()

        if ext == ".txt":
            return self.export_plain_text(scenes, output_path)

        srt_blocks = []
        current_sec = 0.0

        for idx, scene in enumerate(scenes, start=1):
            review_text = scene.get("review_text", "").strip()
            if not review_text:
                continue

            duration_sec = float(scene.get("estimated_duration_sec", 5.0))
            if duration_sec <= 0:
                word_count = len(review_text.split())
                duration_sec = max(2.0, round(word_count / 3.5, 2))

            end_sec = current_sec + duration_sec

            start_tc = self._format_srt_timestamp(current_sec)
            end_tc = self._format_srt_timestamp(end_sec)

            block = f"{idx}\n{start_tc} --> {end_tc}\n{review_text}\n"
            srt_blocks.append(block)

            current_sec = end_sec

        content = "\n".join(srt_blocks)
        with open(output_path, "w", encoding="utf-8-sig") as f:
            f.write(content)

        return output_path

    def export_plain_text(self, scenes: List[Dict[str, Any]], output_path: str) -> str:
        """Xuất file .txt văn bản thuần cho Voice Talent đọc thu âm hoặc nạp vào TTS."""
        lines = []
        for idx, scene in enumerate(scenes, start=1):
            sec_type = scene.get("section_type", "BODY")
            text = scene.get("review_text", "").strip()
            if text:
                lines.append(f"[{sec_type} - Đoạn {idx}] {text}")

        content = "\n\n".join(lines)
        with open(output_path, "w", encoding="utf-8-sig") as f:
            f.write(content)

        return output_path

    @staticmethod
    def _format_srt_timestamp(seconds: float) -> str:
        """Đổi số giây float thành định dạng timecode SRT: HH:MM:SS,mmm."""
        if seconds < 0:
            seconds = 0.0

        hrs = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int(round((seconds - int(seconds)) * 1000))

        if millis >= 1000:
            secs += 1
            millis = 0
        if secs >= 60:
            mins += 1
            secs = 0
        if mins >= 60:
            hrs += 1
            mins = 0

        return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"
