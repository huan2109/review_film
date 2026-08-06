import os
import re
import threading
from pathlib import Path
from typing import List, Dict, Any, Callable, Optional


def _sec_to_srt_timecode(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    millisec = int(round((seconds % 1) * 1000))
    total_sec = int(seconds)
    sec = total_sec % 60
    min_val = (total_sec // 60) % 60
    hrs = total_sec // 3600
    if millisec >= 1000:
        sec += 1
        millisec = 0
    if sec >= 60:
        min_val += 1
        sec = 0
    if min_val >= 60:
        hrs += 1
        min_val = 0
    return f"{hrs:02d}:{min_val:02d}:{sec:02d},{millisec:03d}"


def export_temp_srt_async(
    script_text: str,
    output_srt_path: str,
    callback_success: Optional[Callable[[str], None]] = None
):
    """Hàm chạy ngầm (Background Thread) để tạo file SRT tạm mà không làm treo giao diện GUI."""

    def worker():
        try:
            lines = script_text.strip().split("\n")
            subtitles = []

            for line in lines:
                line_clean = line.strip().strip("|").strip()
                if not line_clean:
                    continue

                parts = [p.strip() for p in line_clean.split("|")]

                if len(parts) >= 3:
                    text = parts[1]
                    timecode_raw = parts[2]

                    # 1. Tách mốc HH:MM:SS.mmm hoặc HH:MM:SS
                    match_hhmmss = re.findall(r"\d{1,2}:\d{2}:\d{2}(?:[,\.]\d{1,3})?", timecode_raw)
                    if len(match_hhmmss) >= 2:
                        start_tc = match_hhmmss[0].replace(".", ",")
                        end_tc = match_hhmmss[1].replace(".", ",")
                        if "," not in start_tc:
                            start_tc += ",000"
                        if "," not in end_tc:
                            end_tc += ",000"
                        subtitles.append((start_tc, end_tc, text))
                    else:
                        # 2. Tách mốc float seconds (3247.953 -> 3306.261)
                        sec_matches = re.findall(r"\b\d+(?:\.\d+)?\b", timecode_raw)
                        if len(sec_matches) >= 2:
                            in_sec = float(sec_matches[0])
                            out_sec = float(sec_matches[1])
                            subtitles.append((_sec_to_srt_timecode(in_sec), _sec_to_srt_timecode(out_sec), text))
                elif len(parts) == 2:
                    text = parts[0]
                    timecode_raw = parts[1]
                    sec_matches = re.findall(r"\b\d+(?:\.\d+)?\b", timecode_raw)
                    if len(sec_matches) >= 2:
                        in_sec = float(sec_matches[0])
                        out_sec = float(sec_matches[1])
                        subtitles.append((_sec_to_srt_timecode(in_sec), _sec_to_srt_timecode(out_sec), text))

            # Ghi file với utf-8 chuẩn
            os.makedirs(os.path.dirname(os.path.abspath(output_srt_path)), exist_ok=True)
            with open(output_srt_path, "w", encoding="utf-8") as f:
                for idx, (start, end, text) in enumerate(subtitles, 1):
                    f.write(f"{idx}\n")
                    f.write(f"{start} --> {end}\n")
                    f.write(f"{text}\n\n")

            print("✅ Đã tạo xong file SRT tạm!")
            if callback_success:
                callback_success(output_srt_path)

        except Exception as e:
            print(f"❌ Lỗi khi tạo file SRT: {e}")

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()


class SRTExporter:
    """Exporter chịu trách nhiệm tạo file kịch bản thuyết minh (SRT liên tục & TXT cho TTS/Voice Talent)."""

    def __init__(self, fps: float = 29.97):
        self.fps = fps

    def export(self, scenes: List[Dict[str, Any]], output_path: str) -> str:
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

            start_tc = _sec_to_srt_timecode(current_sec)
            end_tc = _sec_to_srt_timecode(end_sec)

            block = f"{idx}\n{start_tc} --> {end_tc}\n{review_text}\n"
            srt_blocks.append(block)

            current_sec = end_sec

        content = "\n".join(srt_blocks)
        with open(output_path, "w", encoding="utf-8-sig") as f:
            f.write(content)

        return output_path

    def export_plain_text(self, scenes: List[Dict[str, Any]], output_path: str) -> str:
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
        return _sec_to_srt_timecode(seconds)
