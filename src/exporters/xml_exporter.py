import os
import re
import xml.etree.ElementTree as ET
from xml.dom import minidom
from typing import List, Dict, Any
from urllib.parse import quote


class XMLExporter:
    """
    Exporter tạo file Final Cut Pro / Premiere Pro XML (XMEML v5)
    cho phép nhập trực tiếp cấu trúc Timeline cắt thô vào Adobe Premiere Pro.
    """

    def __init__(self, fps: float = 29.97, width: int = 1920, height: int = 1080):
        self.fps = fps
        self.width = width
        self.height = height
        self.timebase = int(round(fps))

    def export(self, scenes: List[Dict[str, Any]], video_file_path: str, output_path: str) -> str:
        """
        Tạo file .xml chứa Sequence Video Track và Subtitle/Marker Track tương thích Adobe Premiere Pro.
        
        :param scenes: Danh sách phân cảnh JSON (scene_id, section_type, original_srt_range, review_text, estimated_duration_sec)
        :param video_file_path: Đường dẫn file video gốc thực tế do người dùng chọn trên UI.
        :param output_path: Đường dẫn lưu file .xml đầu ra.
        """
        if not scenes:
            raise ValueError("Danh sách phân cảnh kịch bản rỗng, không thể xuất file XML.")

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        # LẤY ĐỘNG TÊN FILE VIDEO GỐC THỰC TẾ (TRÁNH HARDCODE)
        if video_file_path and os.path.exists(video_file_path):
            video_basename = os.path.basename(video_file_path)
            video_url = self._convert_path_to_url(video_file_path)
        else:
            video_basename = os.path.basename(video_file_path) if video_file_path else "Source_Video.mp4"
            video_url = self._convert_path_to_url(video_file_path or "C:/Videos/Source_Video.mp4")

        movie_title_clean = os.path.splitext(video_basename)[0]

        # 1. Root Element <xmeml version="5">
        root = ET.Element("xmeml", version="5")

        # 2. <sequence>
        sequence = ET.SubElement(root, "sequence", id="sequence-1")
        ET.SubElement(sequence, "name").text = f"AutoReview_{movie_title_clean}"

        # Rate Element
        rate_seq = ET.SubElement(sequence, "rate")
        ET.SubElement(rate_seq, "timebase").text = str(self.timebase)
        ET.SubElement(rate_seq, "ntsc").text = "TRUE" if abs(self.fps - 29.97) < 0.1 or abs(self.fps - 23.976) < 0.1 else "FALSE"

        media = ET.SubElement(sequence, "media")
        video_elem = ET.SubElement(media, "video")

        # Format Video
        fmt = ET.SubElement(video_elem, "format")
        sc = ET.SubElement(fmt, "samplecharacteristics")
        ET.SubElement(sc, "width").text = str(self.width)
        ET.SubElement(sc, "height").text = str(self.height)

        # 3. Track 1 (Video Cut Track)
        track_v1 = ET.SubElement(video_elem, "track")

        # 4. Track 2 (Subtitle & Voice Marker Track)
        track_v2 = ET.SubElement(video_elem, "track")

        current_timeline_frame = 0

        for idx, scene in enumerate(scenes, start=1):
            sec_type = str(scene.get("section_type", "BODY")).upper()
            srt_range = scene.get("original_srt_range", "")
            review_text = scene.get("review_text", "")
            duration_sec = float(scene.get("estimated_duration_sec", 5.0))

            # Tính toán In/Out frame từ SRT range
            in_frame, out_frame = self._parse_srt_range_to_frames(srt_range)
            clip_dur_frames = max(1, int(round(duration_sec * self.fps)))

            if out_frame <= in_frame:
                out_frame = in_frame + clip_dur_frames

            timeline_start = current_timeline_frame
            timeline_end = timeline_start + clip_dur_frames

            # --- TRACK 1: VIDEO CLIPITEM ---
            clip_v1 = ET.SubElement(track_v1, "clipitem", id=f"clipitem-v1-{idx}")
            ET.SubElement(clip_v1, "name").text = f"Scene_{idx:02d}_{sec_type}"
            ET.SubElement(clip_v1, "duration").text = str(clip_dur_frames)

            rate_v1 = ET.SubElement(clip_v1, "rate")
            ET.SubElement(rate_v1, "timebase").text = str(self.timebase)
            ET.SubElement(rate_v1, "ntsc").text = "TRUE" if abs(self.fps - 29.97) < 0.1 else "FALSE"

            ET.SubElement(clip_v1, "start").text = str(timeline_start)
            ET.SubElement(clip_v1, "end").text = str(timeline_end)
            ET.SubElement(clip_v1, "in").text = str(in_frame)
            ET.SubElement(clip_v1, "out").text = str(in_frame + clip_dur_frames)

            # File Element (Lấy tên động từ video_basename)
            file_elem = ET.SubElement(clip_v1, "file", id="file-1")
            ET.SubElement(file_elem, "name").text = video_basename
            ET.SubElement(file_elem, "pathurl").text = video_url
            rate_file = ET.SubElement(file_elem, "rate")
            ET.SubElement(rate_file, "timebase").text = str(self.timebase)
            ET.SubElement(rate_file, "ntsc").text = "TRUE" if abs(self.fps - 29.97) < 0.1 else "FALSE"

            # --- TRACK 2: SUBTITLE / MARKER CLIPITEM ---
            clip_v2 = ET.SubElement(track_v2, "clipitem", id=f"clipitem-v2-{idx}")
            ET.SubElement(clip_v2, "name").text = f"[{sec_type}] {review_text[:25]}..."
            ET.SubElement(clip_v2, "duration").text = str(clip_dur_frames)

            rate_v2 = ET.SubElement(clip_v2, "rate")
            ET.SubElement(rate_v2, "timebase").text = str(self.timebase)
            ET.SubElement(rate_v2, "ntsc").text = "TRUE" if abs(self.fps - 29.97) < 0.1 else "FALSE"

            ET.SubElement(clip_v2, "start").text = str(timeline_start)
            ET.SubElement(clip_v2, "end").text = str(timeline_end)
            ET.SubElement(clip_v2, "in").text = "0"
            ET.SubElement(clip_v2, "out").text = str(clip_dur_frames)

            # Marker chứa lời thoại review từ Gemini
            marker = ET.SubElement(clip_v2, "marker")
            ET.SubElement(marker, "name").text = f"[{sec_type}] Review Voice"
            ET.SubElement(marker, "comment").text = review_text
            ET.SubElement(marker, "in").text = "0"
            ET.SubElement(marker, "out").text = str(clip_dur_frames)

            current_timeline_frame = timeline_end

        # Tổng thời lượng sequence
        ET.SubElement(sequence, "duration").text = str(current_timeline_frame)

        # Ghi file XML với định dạng đẹp
        xml_string = ET.tostring(root, encoding="utf-8")
        parsed_xml = minidom.parseString(xml_string)
        pretty_xml = parsed_xml.toprettyxml(indent="  ", encoding="utf-8")

        with open(output_path, "wb") as f:
            f.write(pretty_xml)

        return output_path

    def _parse_srt_range_to_frames(self, srt_range: str) -> (int, int):
        """Đổi chuỗi timecode '00:01:15 - 00:02:40' ra (start_frame, end_frame)."""
        timecodes = re.findall(r'\d{2}:\d{2}:\d{2}(?:[,\.]\d{1,3})?', srt_range)
        if len(timecodes) >= 2:
            start_sec = self._tc_to_seconds(timecodes[0])
            end_sec = self._tc_to_seconds(timecodes[1])
            return int(round(start_sec * self.fps)), int(round(end_sec * self.fps))
        return 0, int(round(5.0 * self.fps))

    @staticmethod
    def _tc_to_seconds(tc_str: str) -> float:
        """Đổi string timecode HH:MM:SS,mmm ra float seconds."""
        parts = tc_str.replace(',', '.').split(':')
        if len(parts) == 3:
            h, m, s = float(parts[0]), float(parts[1]), float(parts[2])
            return h * 3600 + m * 60 + s
        return 0.0

    @staticmethod
    def _convert_path_to_url(file_path: str) -> str:
        """Chuyển đường dẫn file Windows C:\\... thành URL file://localhost/C:/... chuẩn FCPXML mã hóa UTF-8."""
        if not file_path:
            return "file://localhost/C:/Videos/Source_Video.mp4"

        clean_path = os.path.abspath(file_path).replace("\\", "/")
        if not clean_path.startswith("/"):
            clean_path = "/" + clean_path

        encoded_path = quote(clean_path, safe="/:")
        return f"file://localhost{encoded_path}"
