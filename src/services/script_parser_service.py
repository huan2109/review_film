import json
import re
from typing import List, Dict, Any


class ScriptParserService:
    """
    Service chuyên trách bóc tách kịch bản linh hoạt từ ô văn bản Kịch Bản Thô:
    Cấu trúc chuẩn: | ID | Lời Thuyết Minh | Timecode In -> Timecode Out |
    Ví dụ: | 46 | Trở về ngôi nhà xưa... | 3247.953 -> 3306.261 |
    hoặc JSON Object Array: [{"id": 1, "voice": "...", "in": 24.441, "out": 37.078}]
    """

    @classmethod
    def parse_raw_script(cls, raw_text: str) -> List[Dict[str, Any]]:
        cleaned = raw_text.strip()
        if not cleaned:
            return []

        # Xóa markdown code block markers nếu có
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)

        # 1. Thử parse dạng JSON Array
        data = cls._try_parse_json(cleaned)
        if not data and ("|" in cleaned or "->" in cleaned or "➜" in cleaned or " - " in cleaned):
            data = cls._parse_flexible_line_script(cleaned)

        if not data:
            data = cls._build_plain_text_fallback_scenes(cleaned)

        return cls._normalize_scenes(data)

    @classmethod
    def _try_parse_json(cls, text: str) -> Any:
        start_idx = text.find('[')
        end_idx = text.rfind(']')
        json_str = text[start_idx:end_idx + 1] if (start_idx != -1 and end_idx != -1 and end_idx > start_idx) else text

        try:
            return json.loads(json_str)
        except Exception:
            try:
                fixed_str = re.sub(r",\s*([\]}])", r"\1", json_str)
                return json.loads(fixed_str)
            except Exception:
                return None

    @classmethod
    def _parse_flexible_line_script(cls, text: str) -> List[Dict[str, Any]]:
        scenes = []
        lines = text.strip().splitlines()

        for line in lines:
            line_str = line.strip()
            if not line_str or line_str.startswith("---") or ("STT" in line_str and "Voice" in line_str) or ("ID" in line_str and "Thuyết Minh" in line_str):
                continue

            # Strip dấu | ở đầu và cuối dòng cùng khoảng trắng
            clean_line = line_str.strip().strip("|").strip()
            parts = [p.strip() for p in clean_line.split("|")]

            if len(parts) >= 3:
                # Phần tử 0: ID (Ví dụ: 46)
                stt_val = parts[0]
                try:
                    scene_id = int(re.sub(r"\D", "", stt_val)) if re.sub(r"\D", "", stt_val) else len(scenes) + 1
                except Exception:
                    scene_id = len(scenes) + 1

                # Phần tử 1: Lời Thuyết Minh
                voice_text = parts[1]

                # Phần tử 2: Timecode In -> Timecode Out (Ví dụ: 3247.953 -> 3306.261)
                tc_str = parts[2]

                in_tc, out_tc = cls._extract_timecodes_from_str(tc_str)

                scenes.append({
                    "scene_id": scene_id,
                    "section_type": "BODY",
                    "in_time": in_tc,
                    "out_time": out_tc,
                    "review_text": voice_text,
                    "visual_suggestion": f"Cảnh B-Roll phân cảnh {scene_id}",
                })
            elif len(parts) == 2:
                voice_text = parts[0]
                tc_str = parts[1]
                in_tc, out_tc = cls._extract_timecodes_from_str(tc_str)
                scene_id = len(scenes) + 1
                scenes.append({
                    "scene_id": scene_id,
                    "section_type": "BODY",
                    "in_time": in_tc,
                    "out_time": out_tc,
                    "review_text": voice_text,
                    "visual_suggestion": f"Cảnh B-Roll phân cảnh {scene_id}",
                })
            elif "->" in line_str or "➜" in line_str or " - " in line_str:
                tc_match = re.search(r"(\d+.*(?:->|➜|-).*)", line_str)
                if tc_match:
                    tc_part = tc_match.group(1)
                    voice_part = line_str.replace(tc_part, "").strip(" |:-")
                    in_tc, out_tc = cls._extract_timecodes_from_str(tc_part)
                    scenes.append({
                        "scene_id": len(scenes) + 1,
                        "section_type": "BODY",
                        "in_time": in_tc,
                        "out_time": out_tc,
                        "review_text": voice_part,
                        "visual_suggestion": f"Cảnh B-Roll phân cảnh {len(scenes) + 1}",
                    })

        return scenes

    @classmethod
    def _extract_timecodes_from_str(cls, tc_str: str) -> tuple[str, str]:
        tc_clean = tc_str.replace(",", ".")
        # 1. Tìm mốc HH:MM:SS.mmm
        tc_matches = re.findall(r"\d{1,2}:\d{2}:\d{2}(?:\.\d{1,3})?", tc_clean)
        if len(tc_matches) >= 2:
            return tc_matches[0], tc_matches[1]
        elif len(tc_matches) == 1:
            return tc_matches[0], tc_matches[0]

        # 2. Tìm mốc float theo Giây (ví dụ: 3247.953 -> 3306.261)
        sec_matches = re.findall(r"\b\d+(?:\.\d+)?\b", tc_clean)
        if len(sec_matches) >= 2:
            in_sec = float(sec_matches[0])
            out_sec = float(sec_matches[1])
            return cls._sec_to_tc(in_sec), cls._sec_to_tc(out_sec)
        elif len(sec_matches) == 1:
            in_sec = float(sec_matches[0])
            return cls._sec_to_tc(in_sec), cls._sec_to_tc(in_sec + 5.0)

        return "00:00:00.000", "00:00:05.000"

    @classmethod
    def _normalize_scenes(cls, data: Any) -> List[Dict[str, Any]]:
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

            scene_id = item.get("id", item.get("scene_id", item.get("stt", idx)))
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
                    "voice", item.get("review_text", item.get("text", item.get("Voice lời bình", item.get("review", ""))))
                )
            ).strip()

            in_val = item.get("in", item.get("in_time", item.get("start", item.get("start_time", ""))))
            out_val = item.get("out", item.get("out_time", item.get("end", item.get("end_time", ""))))

            in_time = cls._normalize_timecode_value(in_val)
            out_time = cls._normalize_timecode_value(out_val)
            srt_range = str(item.get("original_srt_range", ""))

            visual_suggestion = str(
                item.get(
                    "visual_suggestion",
                    f"Cảnh B-Roll minh họa phân cảnh {scene_id}.",
                )
            ).strip()

            word_count = len(review_text.split())
            estimated_duration = item.get("estimated_duration_sec")

            if not estimated_duration or not isinstance(estimated_duration, (int, float)):
                sec_in = cls._tc_to_sec(in_time)
                sec_out = cls._tc_to_sec(out_time)
                if sec_out > sec_in:
                    estimated_duration = round(sec_out - sec_in, 2)
                else:
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

    @classmethod
    def _normalize_timecode_value(cls, val: Any) -> str:
        if val is None or val == "":
            return "00:00:00.000"

        if isinstance(val, (int, float)):
            return cls._sec_to_tc(float(val))

        val_str = str(val).strip().replace(",", ".")
        if not val_str:
            return "00:00:00.000"

        if re.match(r"^\d+(?:\.\d+)?$", val_str):
            try:
                return cls._sec_to_tc(float(val_str))
            except Exception:
                pass

        tc_matches = re.findall(r"\d{1,2}:\d{2}:\d{2}(?:\.\d{1,3})?", val_str)
        if tc_matches:
            return tc_matches[0]

        return "00:00:00.000"

    @classmethod
    def _sec_to_tc(cls, seconds: float) -> str:
        hrs = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int(round((seconds - int(seconds)) * 1000))
        if millis >= 1000:
            secs += 1
            millis = 0
        return f"{hrs:02d}:{mins:02d}:{secs:02d}.{millis:03d}"

    @classmethod
    def _tc_to_sec(cls, tc_str: str) -> float:
        if not tc_str:
            return 0.0
        tc_clean = tc_str.replace(',', '.')
        timecodes = re.findall(r'\d{1,2}:\d{2}:\d{2}(?:\.\d{1,3})?', tc_clean)
        if timecodes:
            parts = timecodes[0].split(':')
            if len(parts) == 3:
                return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        return 0.0

    @classmethod
    def _build_plain_text_fallback_scenes(cls, raw_text: str) -> List[Dict[str, Any]]:
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
                "in_time": cls._sec_to_tc(curr),
                "out_time": cls._sec_to_tc(end_sec),
                "original_srt_range": f"{cls._sec_to_tc(curr)[:8]} - {cls._sec_to_tc(end_sec)[:8]}",
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
