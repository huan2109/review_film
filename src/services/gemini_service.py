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
        Hàm parse kịch bản có sẵn (JSON / Bảng Markdown / Text) - GIỮ NGUYÊN TIMECODE GỐC 100%.
        """
        cleaned = raw_content.strip()
        scenes = self._parse_and_validate_json(cleaned)
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

        scenes = self._parse_and_validate_json(response.text)
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
            # Nếu scene đã có timecode chuẩn (không phải 00:00:00) -> Giữ nguyên
            if in_tc and in_tc != "00:00:00.000" and in_tc != "00:00:00":
                continue

            # Tìm đoạn Sub SRT có độ tương đồng từ ngữ cao nhất
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

            # Gán Timecode khớp nhất từ Sub SRT vào Shot
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
        cleaned = raw_text.strip()

        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)

        data = None

        start_idx = cleaned.find('[')
        end_idx = cleaned.rfind(']')
        json_str = cleaned[start_idx:end_idx + 1] if (start_idx != -1 and end_idx != -1 and end_idx > start_idx) else cleaned

        try:
            data = json.loads(json_str)
        except Exception:
            try:
                fixed_str = re.sub(r",\s*([\]}])", r"\1", json_str)
                data = json.loads(fixed_str)
            except Exception:
                pass

        if not data and "|" in cleaned and any(k in cleaned for k in ["STT", "Voice", "Timecode", "Lời thoại"]):
            data = self._parse_markdown_table_script(cleaned)

        if not data:
            data = self._build_plain_text_fallback_scenes(raw_text)

        if isinstance(data, dict):
            if "scenes" in data and isinstance(data["scenes"], list):
                data = data["scenes"]
            elif "data" in data and isinstance(data["data"], list):
                data = data["data"]
            else:
                data = [data]

        if not isinstance(data, list):
            data = [data]

        total_items = len(data)
        validated_scenes = []

        for idx, item in enumerate(data, start=1):
            if not isinstance(item, dict):
                review_str = str(item).strip()
                item = {"review_text": review_str}

            scene_id = item.get("scene_id", idx)
            section_type = str(item.get("section_type", "BODY")).upper()

            if section_type not in ["HOOK", "BODY", "STORYTELLING", "ANALYSIS", "OUTRO"]:
                pct = idx / total_items
                if pct <= 0.10:
                    section_type = "HOOK"
                elif pct <= 0.70:
                    section_type = "STORYTELLING"
                elif pct <= 0.85:
                    section_type = "ANALYSIS"
                else:
                    section_type = "OUTRO"

            review_text = str(
                item.get(
                    "review_text", item.get("Voice lời bình", item.get("review", ""))
                )
            ).strip()

            in_time = str(item.get("in_time", item.get("start_time", ""))).strip()
            out_time = str(item.get("out_time", item.get("end_time", ""))).strip()
            srt_range = str(item.get("original_srt_range", ""))

            visual_suggestion = str(
                item.get(
                    "visual_suggestion",
                    "Cảnh quay diễn biến nhân vật.",
                )
            ).strip()

            word_count = len(review_text.split())
            estimated_duration = item.get("estimated_duration_sec")

            if not estimated_duration or not isinstance(estimated_duration, (int, float)):
                estimated_duration = round(max(2.5, min(10.0, word_count / 3.5)), 1)
            else:
                estimated_duration = float(min(10.0, max(2.5, estimated_duration)))

            validated_scenes.append(
                {
                    "scene_id": scene_id,
                    "section_type": section_type,
                    "in_time": in_time,
                    "out_time": out_time,
                    "original_srt_range": srt_range,
                    "review_text": review_text,
                    "visual_suggestion": visual_suggestion,
                    "estimated_duration_sec": estimated_duration,
                }
            )

        return validated_scenes

    def _parse_markdown_table_script(
        self, markdown_text: str
    ) -> List[Dict[str, Any]]:
        scenes = []
        lines = markdown_text.strip().split("\n")

        for line in lines:
            line_str = line.strip()
            if not line_str.startswith("|") or "---" in line_str or ("STT" in line_str and "Voice" in line_str):
                continue

            parts = [p.strip() for p in line_str.split("|")]
            if len(parts) >= 4:
                stt_str = parts[1]
                voice_text = parts[2]
                tc_str = parts[3]

                tc_matches = re.findall(
                    r"\d{1,2}:\d{2}:\d{2}(?:\.\d{1,3})?", tc_str
                )
                in_tc = tc_matches[0] if len(tc_matches) > 0 else "00:00:00.000"
                out_tc = (
                    tc_matches[1] if len(tc_matches) > 1 else in_tc
                )

                scenes.append(
                    {
                        "scene_id": len(scenes) + 1,
                        "section_type": "BODY",
                        "in_time": in_tc,
                        "out_time": out_tc,
                        "review_text": voice_text,
                        "visual_suggestion": f"B-Roll phân cảnh {len(scenes) + 1}",
                        "estimated_duration_sec": 5.0,
                    }
                )

        return scenes

    @staticmethod
    def _tc_to_sec(tc_str: str) -> float:
        if not tc_str:
            return 0.0
        tc_clean = tc_str.replace(',', '.')
        timecodes = re.findall(r'\d{1,2}:\d{2}:\d{2}(?:\.\d{1,3})?', tc_clean)
        if timecodes:
            parts = timecodes[0].split(':')
            if len(parts) == 3:
                return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        return 0.0

    @staticmethod
    def _sec_to_tc(seconds: float) -> str:
        hrs = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int(round((seconds - int(seconds)) * 1000))
        if millis >= 1000:
            secs += 1
            millis = 0
        return f"{hrs:02d}:{mins:02d}:{secs:02d}.{millis:03d}"

    def _build_plain_text_fallback_scenes(self, raw_text: str) -> List[Dict[str, Any]]:
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        scenes = []

        total_lines = len(lines)
        curr = 5.0
        for idx, line in enumerate(lines, start=1):
            pct = idx / total_lines
            if pct <= 0.10:
                sec_type = "HOOK"
            elif pct <= 0.70:
                sec_type = "STORYTELLING"
            elif pct <= 0.85:
                sec_type = "ANALYSIS"
            else:
                sec_type = "OUTRO"

            words = len(line.split())
            dur = round(min(10.0, max(3.0, words / 3.5)), 1)
            end_sec = curr + dur

            scenes.append({
                "scene_id": idx,
                "section_type": sec_type,
                "in_time": self._sec_to_tc(curr),
                "out_time": self._sec_to_tc(end_sec),
                "original_srt_range": f"{self._sec_to_tc(curr)[:8]} - {self._sec_to_tc(end_sec)[:8]}",
                "review_text": line,
                "visual_suggestion": "Cảnh băm B-Roll chi tiết.",
                "estimated_duration_sec": dur
            })
            curr = end_sec

        return scenes if scenes else [{
            "scene_id": 1,
            "section_type": "HOOK",
            "in_time": "00:00:05.000",
            "out_time": "00:00:10.000",
            "original_srt_range": "00:00:05 - 00:00:10",
            "review_text": raw_text.strip(),
            "visual_suggestion": "Cảnh quay cận cảnh mở đầu kịch tính.",
            "estimated_duration_sec": 5.0
        }]
