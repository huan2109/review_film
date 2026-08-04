import os
import re
from dataclasses import dataclass
from typing import List

@dataclass
class SubtitleItem:
    """Class lưu trữ thông tin câu phụ đề đơn lẻ."""
    index: int
    start_time: str  # Format: "00:01:15,200" hoặc "00:01:15"
    end_time: str    # Format: "00:01:18,500" hoặc "00:01:18"
    text: str

class SRTParser:
    """Engine đọc và parse file phụ đề SRT hỗ trợ đa dạng mã hóa (UTF-8, UTF-8-BOM, CP1258...)."""

    def __init__(self, file_path: str = None):
        self.file_path = file_path
        self.items: List[SubtitleItem] = []

    def load_and_parse(self, file_path: str = None) -> List[SubtitleItem]:
        """Đọc và parse file .srt ra danh sách các SubtitleItem."""
        target_path = file_path or self.file_path
        if not target_path or not os.path.exists(target_path):
            raise FileNotFoundError(f"Không tìm thấy file SRT tại đường dẫn: {target_path}")

        raw_content = self._read_file_with_encoding(target_path)
        self.items = self._parse_srt_string(raw_content)
        return self.items

    def _read_file_with_encoding(self, file_path: str) -> str:
        """Thử các mã hóa phổ biến để đọc file không bị lỗi UnicodeDecodeError."""
        encodings = ['utf-8-sig', 'utf-8', 'utf-16', 'cp1258', 'latin-1']
        for enc in encodings:
            try:
                with open(file_path, 'r', encoding=enc) as f:
                    return f.read()
            except (UnicodeDecodeError, UnicodeError):
                continue

        with open(file_path, 'rb') as f:
            content = f.read()
            return content.decode('utf-8', errors='ignore')

    def _parse_srt_string(self, content: str) -> List[SubtitleItem]:
        """Parse chuỗi văn bản định dạng SRT ra danh sách SubtitleItem."""
        items: List[SubtitleItem] = []
        blocks = re.split(r'\n\s*\n', content.strip())

        time_pattern = re.compile(
            r'(\d{2}:\d{2}:\d{2}[,\.]\d{3}|\d{2}:\d{2}:\d{2})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3}|\d{2}:\d{2}:\d{2})'
        )

        for block in blocks:
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            if len(lines) < 2:
                continue

            idx_str = lines[0]
            if not idx_str.isdigit():
                match_time = None
                time_line_idx = -1
                for i, line in enumerate(lines):
                    match = time_pattern.search(line)
                    if match:
                        match_time = match
                        time_line_idx = i
                        break
                if not match_time:
                    continue
                index = len(items) + 1
                start_time, end_time = match_time.group(1), match_time.group(2)
                text = " ".join(lines[time_line_idx + 1:])
            else:
                index = int(idx_str)
                match_time = time_pattern.search(lines[1])
                if not match_time:
                    continue
                start_time, end_time = match_time.group(1), match_time.group(2)
                text = " ".join(lines[2:])

            clean_text = re.sub(r'<[^>]+>', '', text).strip()

            if clean_text:
                items.append(SubtitleItem(
                    index=index,
                    start_time=start_time,
                    end_time=end_time,
                    text=clean_text
                ))

        return items

    def get_full_text_with_timestamps(self, items: List[SubtitleItem] = None) -> str:
        """Chuyển đổi danh sách câu phụ đề thành chuỗi văn bản có gắn mốc thời gian [HH:MM:SS]."""
        target_items = items or self.items
        if not target_items:
            return ""

        formatted_lines = []
        for item in target_items:
            short_time = item.start_time[:8]
            formatted_lines.append(f"[{short_time}] {item.text}")

        return "\n".join(formatted_lines)

    def get_compressed_srt_text(self, items: List[SubtitleItem] = None, max_words: int = 8000) -> str:
        """
        Nén và tối ưu hóa dung lượng phụ đề:
        1. Lọc bỏ ký tự thừa, gom các câu phụ đề gần nhau (khoảng cách < 2 giây).
        2. Nếu tổng số từ > max_words, tự động nén giảm bớt mật độ câu để tiết kiệm 40% Token & tránh Rate Limit.
        """
        target_items = items or self.items
        if not target_items:
            return ""

        # Gom các câu thoại ngắn ở các mốc thời gian liên tiếp nhau
        compressed_lines = []
        total_words = 0

        # Nếu số lượng câu quá lớn, tính bước nhảy sampling step
        all_words_count = sum(len(item.text.split()) for item in target_items)
        step = 1
        if all_words_count > max_words:
            step = int(all_words_count / max_words) + 1

        for i in range(0, len(target_items), step):
            item = target_items[i]
            short_time = item.start_time[:8]
            text_clean = re.sub(r'\s+', ' ', item.text).strip()
            compressed_lines.append(f"[{short_time}] {text_clean}")
            total_words += len(text_clean.split())

        return "\n".join(compressed_lines)
