import os
import re
import random
import subprocess
import shutil
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Tuple

try:
    import imageio_ffmpeg
    HAS_IMAGEIO_FFMPEG = True
except ImportError:
    HAS_IMAGEIO_FFMPEG = False


@dataclass
class SubShot:
    """Đại diện cho một vết cắt hình ngắn (2.0s - 4.5s) tịnh tiến từ video gốc cho 1 câu thoại."""
    shot_id: int
    source_start_sec: float
    source_end_sec: float
    duration_sec: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "shot_id": self.shot_id,
            "start": self.source_start_sec,
            "end": self.source_end_sec,
            "duration": self.duration_sec
        }


class VideoEditorService:
    """Engine Audio-Lead B-Roll Chopper (FFmpeg Safe Cut, -nostdin, timeout=30 & Clean Concat - KHÔNG HARDCODE SUB)."""

    def __init__(self, fps: float = 30.0):
        self.fps = fps
        self.ffmpeg_bin = self.get_ffmpeg_exe_path()

    @classmethod
    def get_ffmpeg_exe_path(cls) -> str:
        if HAS_IMAGEIO_FFMPEG:
            try:
                exe_path = imageio_ffmpeg.get_ffmpeg_exe()
                if exe_path and os.path.exists(exe_path):
                    return os.path.abspath(exe_path)
            except Exception:
                pass

        system_path = shutil.which("ffmpeg")
        if system_path and os.path.exists(system_path):
            return os.path.abspath(system_path)

        common_locations = [
            os.path.join(os.getcwd(), "ffmpeg.exe"),
            os.path.join(os.getcwd(), "bin", "ffmpeg.exe"),
            "C:\\ffmpeg\\bin\\ffmpeg.exe",
            "C:\\Program Files\\ffmpeg\\bin\\ffmpeg.exe",
            "C:\\Program Files (x86)\\ffmpeg\\bin\\ffmpeg.exe"
        ]

        for loc in common_locations:
            if os.path.exists(loc):
                return os.path.abspath(loc)

        raise FileNotFoundError(
            "❌ KHÔNG TÌM THẤY FILE THỰC THI FFMPEG.EXE!\n\n"
            "Vui lòng chạy lệnh sau trong Terminal/Cmd để tự động cài đặt FFmpeg cho Python:\n"
            "py -m pip install imageio-ffmpeg"
        )

    def generate_subshots_for_scene(
        self,
        in_time_str: str,
        out_time_str: str,
        voice_duration_sec: float,
        min_shot_len: float = 2.0,
        max_shot_len: float = 4.5
    ) -> List[SubShot]:
        """
        Tự động chia nhỏ mốc in_time -> out_time thành các Sub-Shots tịnh tiến liên tục (Strict Monotonic),
        không bị giật lùi timecode làm lặp hình video B-Roll.
        """
        start_orig = self._tc_to_sec(in_time_str)
        end_orig = self._tc_to_sec(out_time_str)

        if end_orig <= start_orig:
            end_orig = start_orig + voice_duration_sec

        subshots: List[SubShot] = []
        accumulated_dur = 0.0
        shot_count = 0
        current_source_sec = start_orig

        while accumulated_dur < voice_duration_sec:
            shot_count += 1
            remaining = voice_duration_sec - accumulated_dur

            if remaining <= max_shot_len:
                cur_len = round(remaining, 2)
            else:
                cur_len = round(random.uniform(min_shot_len, max_shot_len), 2)
                cur_len = min(cur_len, remaining)

            shot_start = round(current_source_sec, 2)
            shot_end = round(shot_start + cur_len, 2)

            subshots.append(SubShot(
                shot_id=shot_count,
                source_start_sec=shot_start,
                source_end_sec=shot_end,
                duration_sec=cur_len
            ))

            accumulated_dur += cur_len
            current_source_sec += cur_len

        return subshots

    def attach_subshots_to_scenes(self, scenes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Gán trước danh sách subshots tịnh tiến liên tục vào từng phân cảnh kịch bản."""
        for scene in scenes:
            in_tc = scene.get("in_time", "")
            out_tc = scene.get("out_time", "")
            dur_sec = float(scene.get("estimated_duration_sec", 5.0))

            subshots = self.generate_subshots_for_scene(in_tc, out_tc, dur_sec)
            scene["subshots"] = [s.to_dict() for s in subshots]
        return scenes

    def render_full_review_video(
        self,
        source_video_path: str,
        scenes: List[Dict[str, Any]],
        srt_file_path: str = "",
        output_mp4_path: str = "output.mp4",
        progress_callback=None
    ) -> str:
        """
        Ghép tất cả các vết cắt sub-shots B-Roll ra file MP4 HOÀN TOÀN SẠCH SẼ (KHÔNG HARDCODE SUB)
        SỬ DỤNG -nostdin, timeout=30 VÀ CHỐNG ĐƠ / TREO TIẾN TRÌNH UI.
        """
        if not source_video_path or not os.path.exists(source_video_path):
            raise FileNotFoundError("Chưa chọn file Video gốc để render!")

        ffmpeg_executable = self.ffmpeg_bin or self.get_ffmpeg_exe_path()

        os.makedirs(os.path.dirname(os.path.abspath(output_mp4_path)), exist_ok=True)
        temp_dir = os.path.join(os.path.dirname(os.path.abspath(output_mp4_path)), "temp_render")
        os.makedirs(temp_dir, exist_ok=True)

        try:
            concat_list_path = os.path.join(temp_dir, "concat_list.txt")
            clip_paths = []
            global_shot_idx = 0

            for scene_idx, scene in enumerate(scenes, start=1):
                if progress_callback:
                    progress_callback(f"🎬 Đang băm B-Roll Shot {scene_idx}/{len(scenes)}...")

                in_tc = scene.get("in_time", "")
                out_tc = scene.get("out_time", "")
                dur_sec = float(scene.get("estimated_duration_sec", 5.0))

                subshots_dict = scene.get("subshots")
                if subshots_dict:
                    subshots = [SubShot(s["shot_id"], s["start"], s["end"], s["duration"]) for s in subshots_dict]
                else:
                    subshots = self.generate_subshots_for_scene(in_tc, out_tc, dur_sec)

                for shot in subshots:
                    global_shot_idx += 1
                    clip_out_path = os.path.join(temp_dir, f"shot_{global_shot_idx:04d}.mp4")

                    # LỆNH CẮT SHOT CHỐNG ĐƠ / TREO PROGRESS: THÊM -nostdin, -loglevel error, timeout=30
                    cmd_cut = [
                        ffmpeg_executable,
                        "-y",
                        "-nostdin",  # Ngăn FFmpeg chờ input từ stdin làm treo tiến trình
                        "-loglevel", "error",
                        "-ss", str(shot.source_start_sec),
                        "-i", str(source_video_path),
                        "-t", str(shot.duration_sec),
                        "-an",  # Tắt Audio gốc
                        "-r", "30",  # Ép 30 FPS cố định
                        "-c:v", "libx264",
                        "-preset", "ultrafast",
                        "-crf", "22",
                        "-sn",  # Tắt toàn bộ Subtitle Stream
                        "-dn",
                        str(clip_out_path)
                    ]

                    try:
                        res_cut = subprocess.run(
                            cmd_cut,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            timeout=30  # Giới hạn 30 giây cho 1 shot, tránh bị đơ vĩnh viễn
                        )

                        if res_cut.returncode == 0 and os.path.exists(clip_out_path) and os.path.getsize(clip_out_path) > 0:
                            clip_paths.append(clip_out_path)
                        else:
                            print(f"⚠️ Cảnh báo: Shot #{global_shot_idx} bị lỗi FFmpeg cut (code {res_cut.returncode}), bỏ qua!")

                    except subprocess.TimeoutExpired:
                        print(f"⚠️ Cảnh báo: Shot #{global_shot_idx} bị timeout (quá 30s), tự động bỏ qua!")
                    except Exception as e:
                        print(f"⚠️ Cảnh báo: Shot #{global_shot_idx} gặp ngoại lệ {e}, bỏ qua!")

            if not clip_paths:
                raise RuntimeError("Không cắt được clip B-Roll hợp lệ nào từ video gốc!")

            with open(concat_list_path, "w", encoding="utf-8") as f:
                for cp in clip_paths:
                    escaped = cp.replace("\\", "/")
                    f.write(f"file '{escaped}'\n")

            if progress_callback:
                progress_callback("⚡ Đang ghép các vết cắt B-Roll thuần (Clean Video)...")

            # LỆNH CONCAT TOÀN BỘ SHOTS THUẦN (HOÀN TOÀN KHÔNG DÙNG -vf subtitles)
            cmd_concat = [
                ffmpeg_executable, "-y",
                "-nostdin",
                "-loglevel", "error",
                "-f", "concat", "-safe", "0",
                "-i", concat_list_path,
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "22",
                "-an",
                "-sn",
                "-dn",
                str(output_mp4_path)
            ]

            try:
                res_concat = subprocess.run(
                    cmd_concat,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=300  # Timeout 5 phút cho bước concat toàn bộ
                )
                if res_concat.returncode != 0:
                    raise RuntimeError(f"FFmpeg Clean Concat Error: {res_concat.stderr}")
            except subprocess.TimeoutExpired:
                raise RuntimeError("FFmpeg Clean Concat bị timeout (quá 5 phút)!")

            return output_mp4_path

        finally:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)

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
