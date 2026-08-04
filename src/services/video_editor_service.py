import os
import re
import time
import random
import logging
import subprocess
import shutil
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Any

try:
    import imageio_ffmpeg
    HAS_IMAGEIO_FFMPEG = True
except ImportError:
    HAS_IMAGEIO_FFMPEG = False

logger = logging.getLogger("AutoReviewLite.VideoEditorService")


@dataclass
class SubShot:
    """Đại diện cho một vết cắt hình ngắn (2.0s - 4.5s) tịnh tiến từ video gốc."""
    source_start_sec: float
    source_end_sec: float
    duration_sec: float


class VideoEditorService:
    """Engine Audio-Lead B-Roll Chopper (FFmpeg Safe Cut, -nostdin, timeout=20 & Clean Concat)."""

    def __init__(self, fps: float = 30.0):
        self.fps = fps

    def _tc_to_sec(self, tc_str: Any) -> float:
        """Quy đổi Timecode (chuỗi HH:MM:SS.mmm hoặc số float/int) sang Giây."""
        if isinstance(tc_str, (int, float)):
            return float(tc_str)
        if not tc_str or not isinstance(tc_str, str):
            return 0.0

        tc_str = tc_str.strip().replace(',', '.')
        if '->' in tc_str:
            tc_str = tc_str.split('->')[0].strip()

        parts = tc_str.split(':')
        try:
            if len(parts) == 3:
                return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
            elif len(parts) == 2:
                return float(parts[0]) * 60 + float(parts[1])
            else:
                return float(tc_str)
        except ValueError:
            return 0.0

    def generate_subshots(self, in_time_str: Any, out_time_str: Any, min_shot_len: float = 2.0, max_shot_len: float = 4.5) -> List[SubShot]:
        """Tự động chia nhỏ mốc timecode thành các Sub-Shots tịnh tiến liên tục."""
        start_orig = self._tc_to_sec(in_time_str)
        end_orig = self._tc_to_sec(out_time_str)

        if end_orig <= start_orig:
            end_orig = start_orig + 3.0

        subshots = []
        curr_pos = start_orig

        while curr_pos < end_orig:
            rem = end_orig - curr_pos
            if rem <= max_shot_len:
                shot_len = rem
            else:
                shot_len = random.uniform(min_shot_len, max_shot_len)

            subshots.append(SubShot(
                source_start_sec=round(curr_pos, 3),
                source_end_sec=round(curr_pos + shot_len, 3),
                duration_sec=round(shot_len, 3)
            ))
            curr_pos += shot_len

        return subshots

    def attach_subshots_to_scenes(self, scenes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Gán danh sách subshots tịnh tiến liên tục vào từng phân cảnh kịch bản."""
        for scene in scenes:
            in_tc = scene.get("in_time", scene.get("in", ""))
            out_tc = scene.get("out_time", scene.get("out", ""))
            scene["subshots"] = self.generate_subshots(in_tc, out_tc)
        return scenes

    def render_full_review_video(
        self,
        source_video_path: str,
        scenes: List[Dict[str, Any]],
        voiceover_path: str = "",
        output_path: str = "output.mp4",
        progress_callback=None,
        **kwargs
    ) -> str:
        """Ghép các B-Roll sub-shots ra file MP4 HOÀN TOÀN SẠCH SẼ (Chống đơ/treo UI)."""
        srt_file_path = kwargs.get("srt_file_path", voiceover_path)
        output_mp4_path = kwargs.get("output_mp4_path", output_path)
        target_out_path = output_mp4_path if output_mp4_path else output_path
        voice_path = voiceover_path if voiceover_path else srt_file_path

        if not source_video_path or not os.path.exists(source_video_path):
            raise FileNotFoundError("Chưa chọn file Video gốc để render!")

        ffmpeg_executable = "ffmpeg"
        if HAS_IMAGEIO_FFMPEG:
            try:
                ffmpeg_executable = imageio_ffmpeg.get_ffmpeg_exe()
            except Exception:
                ffmpeg_executable = "ffmpeg"

        temp_dir = os.path.join(os.path.dirname(os.path.abspath(target_out_path)), "temp_render_shots")
        os.makedirs(temp_dir, exist_ok=True)

        try:
            scenes = self.attach_subshots_to_scenes(scenes)
            all_subshots = []
            for sc in scenes:
                all_subshots.extend(sc.get("subshots", []))

            total_shots = len(all_subshots)
            logger.info(f"Tổng số Shot B-Roll cần băm: {total_shots}")

            concat_list_path = os.path.join(temp_dir, "concat_list.txt")
            global_shot_idx = 0

            with open(concat_list_path, "w", encoding="utf-8") as f_concat:
                for shot in all_subshots:
                    global_shot_idx += 1
                    clip_out_path = os.path.join(temp_dir, f"shot_{global_shot_idx:04d}.mp4")

                    cmd_cut = [
                        ffmpeg_executable, "-y",
                        "-nostdin",
                        "-threads", "2",
                        "-loglevel", "error",
                        "-ss", str(shot.source_start_sec),
                        "-i", str(source_video_path),
                        "-t", str(shot.duration_sec),
                        "-c:v", "libx264",
                        "-preset", "ultrafast",
                        "-crf", "23",
                        "-an", "-sn", "-dn",
                        str(clip_out_path)
                    ]

                    try:
                        res = subprocess.run(cmd_cut, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=20)
                        if res.returncode == 0 and os.path.exists(clip_out_path) and os.path.getsize(clip_out_path) > 0:
                            escaped_path = clip_out_path.replace("\\", "/")
                            f_concat.write(f"file '{escaped_path}'\n")
                        else:
                            logger.warning(f"Shot {global_shot_idx} cắt lỗi, bỏ qua.")
                    except subprocess.TimeoutExpired:
                        logger.warning(f"Shot {global_shot_idx} bị timeout (20s), bỏ qua.")

                    if progress_callback:
                        msg_str = f"🎬 Đang băm B-Roll Shot {global_shot_idx}/{total_shots}..."
                        try:
                            progress_callback(msg_str)
                        except TypeError:
                            try:
                                progress_callback(int((global_shot_idx / max(1, total_shots)) * 80), msg_str)
                            except Exception:
                                pass

            # Tiến hành ghép nối (Concat)
            temp_video_only = os.path.join(temp_dir, "temp_concat_video.mp4")
            cmd_concat = [
                ffmpeg_executable, "-y", "-nostdin",
                "-f", "concat", "-safe", "0",
                "-i", concat_list_path,
                "-c", "copy",
                temp_video_only
            ]
            subprocess.run(cmd_concat, check=True)

            # Ghép audio voiceover nếu có
            if voice_path and os.path.exists(voice_path) and voice_path.lower().endswith(('.mp3', '.wav', '.m4a', '.aac')):
                cmd_final = [
                    ffmpeg_executable, "-y", "-nostdin",
                    "-i", temp_video_only,
                    "-i", voice_path,
                    "-c:v", "copy",
                    "-c:a", "aac",
                    "-shortest",
                    target_out_path
                ]
                subprocess.run(cmd_final, check=True)
            else:
                shutil.copy(temp_video_only, target_out_path)

            return target_out_path

        finally:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
