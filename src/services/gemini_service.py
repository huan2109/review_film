import json
import os
import re
import time
import sys
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

try:
    import google.generativeai as genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

from src.services.script_parser_service import ScriptParserService


@dataclass
class DynamicPromptConfig:
    """Đối tượng chứa thông tin metadata và cấu hình kịch bản review với giá trị mặc định an toàn."""
    api_key: str = ""
    movie_title: str = ""
    genre: str = ""
    main_characters: List[str] = field(default_factory=list)
    target_duration_minutes: float = 6.0
    writing_style: str = "Kịch tính, Dồn dập"
    selected_model: str = "gemini-2.5-flash"
    words_per_second: float = 3.5
    analysis_context: str = ""


class GeminiService:
    """Service Gemini AI - Tinh gọn luồng nạp kịch bản thô & sinh 100 Shots siêu tốc (GIỮ NGUYÊN TIMECODE GỐC)."""

    PREFERRED_TEXT_MODELS = [
        "gemini-2.5-flash",
        "gemini-flash-latest",
        "gemini-1.5-flash",
        "gemini-1.5-pro",
        "gemini-2.0-flash-exp",
        "gemini-2.0-flash"
    ]

    def __init__(self, api_key: str = "", model_name: str = "gemini-2.5-flash"):
        self.api_key = api_key
        self.model_name = self._sanitize_model_name(model_name)
        if HAS_GENAI and api_key:
            genai.configure(api_key=api_key)

    def _sanitize_model_name(self, model_name: str) -> str:
        if not model_name:
            return "gemini-2.5-flash"
        clean_name = model_name.replace("models/", "").strip()
        if "-tts" in clean_name or "-audio" in clean_name:
            return "gemini-2.5-flash"
        return clean_name

    def parse_external_script_content(self, raw_content: str, srt_path: str = "") -> List[Dict[str, Any]]:
        """
        Hàm parse kịch bản linh hoạt (JSON / Bảng Pipe / Seconds / Timecode / Text) qua ScriptParserService - GIỮ NGUYÊN TIMECODE GỐC 100%.
        """
        scenes = ScriptParserService.parse_raw_script(raw_content)
        if srt_path and os.path.exists(srt_path):
            scenes = self._match_voice_to_srt_timecodes(scenes, srt_path)
        return scenes

    def generate_review_script(
        self,
        config: Optional[DynamicPromptConfig] = None,
        timestamped_srt_text: str = "",
        srt_path: str = ""
    ) -> List[Dict[str, Any]]:
        """Sinh kịch bản review từ Sub SRT và khớp mốc Timecode thực tế."""
        if config is None:
            config = DynamicPromptConfig(
                api_key=self.api_key,
                movie_title="",
                genre="",
                main_characters=[],
                selected_model=self.model_name
            )

        if not HAS_GENAI or not config.api_key:
            raise RuntimeError("Chưa cấu hình Gemini API Key!")

        genai.configure(api_key=config.api_key)

        generation_config = {
            "response_mime_type": "application/json",
            "temperature": 0.3,
            "top_p": 0.95,
            "max_output_tokens": 6144
        }

        candidate_models = self._build_candidate_models(config.selected_model)

        prompt_content = f"""
Bạn là một Biên kịch review phim triệu view. Hãy đọc file Phụ đề Sub SRT dưới đây và xuất ra KỊCH BẢN REVIEW VÀ DANH SÁCH SHOTS CẮT B-ROLL.

---
[DỮ LIỆU SUB SRT PHIM GỐC]
{timestamped_srt_text}

---
### QUY TẮC BẮT BUỘC:
1. Lời thoại thuyết minh (review_text): TỐI THIỂU 3.500 KÝ TỰ TRỞ LÊN.
2. Danh sách Shots (scene_id): Phủ hết nội dung phim.
3. Thời lượng mỗi Shot (estimated_duration_sec): TỐI ĐA KHÔNG QUÁ 10 GIÂY (<= 10.0s).
4. Timecode (in_time, out_time): LẤY CHÍNH XÁC MỐC TIMECODE GỐC TỪ SUB SRT DƯỚI ĐÂY GIÚP CẮT B-ROLL ĐÚNG DIỄN BIẾN.

---
### OUTPUT FORMAT (STRICT JSON ARRAY NGUYÊN BẢN):
[
  {{
    "scene_id": 1,
    "section_type": "HOOK",
    "in_time": "00:00:05.000",
    "out_time": "00:00:12.000",
    "review_text": "Lời thoại thuyết minh đoạn 1...",
    "visual_suggestion": "Mô tả cảnh B-Roll tương ứng",
    "estimated_duration_sec": 7.0
  }}
]
"""

        response = None
        last_error = None
        for model_name in candidate_models:
            for attempt in range(2):
                try:
                    model = genai.GenerativeModel(model_name=model_name)
                    response = model.generate_content(
                        prompt_content,
                        generation_config=generation_config,
                        request_options={"timeout": 60.0}
                    )
                    if response and response.text:
                        break
                except Exception as e:
                    print(f"Model {model_name} (attempt {attempt+1}) error: {e}", file=sys.stderr)
                    last_error = e
                    time.sleep(1.5)

            if response and response.text:
                break

        if not response or not response.text:
            raise RuntimeError(f"Không thể tạo kịch bản từ Gemini API: {str(last_error)}")

        scenes = ScriptParserService.parse_raw_script(response.text)
        if srt_path and os.path.exists(srt_path):
            scenes = self._match_voice_to_srt_timecodes(scenes, srt_path)
        return scenes

    def _match_voice_to_srt_timecodes(
        self, scenes: List[Dict[str, Any]], srt_path: str
    ) -> List[Dict[str, Any]]:
        """Đối chiếu ngữ cảnh câu Voice với Sub SRT gốc để trích xuất đúng hình ảnh minh họa"""
        if not srt_path or not os.path.exists(srt_path):
            return scenes

        try:
            from src.services.srt_parser import SRTParser
            parser = SRTParser(srt_path)
            srt_items = parser.load_and_parse()
        except Exception:
            srt_items = []

        if not srt_items:
            return scenes

        for scene in scenes:
            voice_text = str(scene.get("review_text", "")).lower()
            if not voice_text:
                continue

            in_tc = str(scene.get("in_time", ""))
            if in_tc and in_tc != "00:00:00.000" and in_tc != "00:00:00":
                continue

            best_match = None
            max_score = 0

            words_voice = set(re.findall(r"\w+", voice_text))

            for item in srt_items:
                srt_text = item.text.lower()
                words_srt = set(re.findall(r"\w+", srt_text))
                common_words = words_voice.intersection(words_srt)
                score = len([w for w in common_words if len(w) > 2])

                if score > max_score:
                    max_score = score
                    best_match = item

            if best_match and max_score >= 2:
                scene["in_time"] = best_match.start_time.replace(',', '.')
                scene["out_time"] = best_match.end_time.replace(',', '.')

        return scenes

    def _build_candidate_models(self, selected_model: str) -> List[str]:
        clean_selected = self._sanitize_model_name(selected_model)
        candidates = [clean_selected]
        for m in self.PREFERRED_TEXT_MODELS:
            if m not in candidates:
                candidates.append(m)
        return candidates

    def _parse_and_validate_json(self, raw_text: str) -> List[Dict[str, Any]]:
        return ScriptParserService.parse_raw_script(raw_text)
