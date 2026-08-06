import os
import re
import time
import random
import logging
import subprocess
import shutil
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Tuple

# Import an toàn imageio_ffmpeg
try:
    import imageio_ffmpeg

    HAS_IMAGEIO_FFMPEG = True
except ImportError:
    HAS_IMAGEIO_FFMPEG = False

logger = logging.getLogger("AutoReviewLite.VideoEditorService")


@dataclass
class SubShot:
    """Đại diện cho một vết cắt hình ngắn tịnh tiến từ video gốc."""

    shot_id: int
    source_start_sec: float
    source_end_sec: float
    duration_sec: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "shot_id": self.shot_id,
            "start": self.source_start_sec,
            "end": self.source_end_sec,
            "duration": self.duration_sec,
        }


class VideoEditorService:
    """Engine Audio-Lead B-Roll Chopper (FFmpeg High-Quality Cutting & Subtitle Engine)."""

    def __init__(self, fps: float = 30.0):
        self.fps = fps
        self.ffmpeg_bin = self.get_ffmpeg_exe_path()

    @classmethod
    def get_ffmpeg_exe_path(cls) -> str:
        """Lấy đường dẫn tệp thực thi FFmpeg an toàn."""
        # 1. Thử lấy từ imageio_ffmpeg
        if HAS_IMAGEIO_FFMPEG:
            try:
                exe_path = imageio_ffmpeg.get_ffmpeg_exe()
                if exe_path and os.path.exists(exe_path):
                    return os.path.abspath(exe_path)
            except Exception:
                pass

        # 2. Dự phòng: Tìm FFmpeg cài sẵn trong PATH của hệ thống
        system_ffmpeg = shutil.which("ffmpeg")
        if system_ffmpeg:
            return system_ffmpeg

        # 3. Tìm các vị trí thông dụng trên Windows
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

        # 4. Trả về tên lệnh mặc định
        return "ffmpeg"

    def create_srt_subtitle_file(
        self, subtitles: List[Dict[str, Any]], output_srt_path: str
    ) -> bool:
        """Tạo file phụ đề SRT an toàn mã hóa UTF-8 (Chống đứng/treo I/O file)."""
        try:
            os.makedirs(os.path.dirname(os.path.abspath(output_srt_path)), exist_ok=True)
            with open(output_srt_path, "w", encoding="utf-8") as f:
                for idx, sub in enumerate(subtitles, 1):
                    start_sec = self._tc_to_sec(sub.get("start", sub.get("in_time", 0.0)))
                    end_sec = self._tc_to_sec(sub.get("end", sub.get("out_time", 0.0)))
                    start_str = self._sec_to_srt_timecode(start_sec)
                    end_str = self._sec_to_srt_timecode(end_sec)
                    text = str(sub.get("text", sub.get("review_text", ""))).strip()

                    f.write(f"{idx}\n")
                    f.write(f"{start_str} --> {end_str}\n")
                    f.write(f"{text}\n\n")
            return True
        except Exception as e:
            logger.error(f"Lỗi khi tạo file phụ đề: {e}")
            return False

    def _sec_to_srt_timecode(self, seconds: float) -> str:
        """Quy đổi số giây sang định dạng SRT Timecode (HH:MM:SS,mmm)."""
        millisec = int((seconds % 1) * 1000)
        total_sec = int(seconds)
        sec = total_sec % 60
        min_val = (total_sec // 60) % 60
        hrs = total_sec // 3600
        return f"{hrs:02d}:{min_val:02d}:{sec:02d},{millisec:03d}"

    def _tc_to_sec(self, tc_str: Any) -> float:
        """Quy đổi Timecode (chuỗi HH:MM:SS.mmm/MM:SS hoặc float/int) sang Giây."""
        if isinstance(tc_str, (int, float)):
            return float(tc_str)
        if not tc_str or not isinstance(tc_str, str):
            return 0.0

        try:
            tc_clean = tc_str.strip().replace(",", ".")
            if '->' in tc_clean:
                tc_clean = tc_clean.split('->')[0].strip()
            if '➜' in tc_clean:
                tc_clean = tc_clean.split('➜')[0].strip()

            parts = tc_clean.split(":")
            if len(parts) == 3:
                return (
                    float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
                )
            elif len(parts) == 2:
                return float(parts[0]) * 60 + float(parts[1])
            return float(tc_clean)
        except ValueError:
            return 0.0

    def cut_subshot_high_quality(
        self,
        input_path: str,
        output_path: str,
        start_sec: float,
        duration_sec: float,
        timeout: int = 20,
    ) -> bool:
        """Cắt phân đoạn video đạt CHẤT LƯỢNG CAO NHẤT (Frame-Accurate & Visually Lossless)."""
        cmd = [
            self.ffmpeg_bin,
            "-y",  # Ghi đè file nếu đã tồn tại
            "-nostdin",  # Tránh treo tiến trình ngầm
            "-i",
            str(input_path),
            "-ss",
            f"{start_sec:.3f}",  # Đặt -ss sau -i để cắt chính xác frame
            "-t",
            f"{duration_sec:.3f}",
            "-c:v",
            "libx264",
            "-preset",
            "slow",  # Render kỹ để giữ tối đa chi tiết
            "-crf",
            "17",  # Mức 17 = Chất lượng gần như lossless
            "-pix_fmt",
            "yuv420p",  # Tương thích chuẩn màu sắc mọi thiết bị
            "-an",  # Tắt âm thanh video gốc cho B-Roll
            "-sn",
            "-dn",
            str(output_path),
        ]

        try:
            result = subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, Exception) as e:
            logger.error(f"Lỗi khi cắt video: {e}")
            return False

    def export_video_with_subtitles(
        self,
        input_video: str,
        srt_file: str,
        output_video: str,
        timeout: int = 60,
    ) -> bool:
        """Ghép phụ đề và xuất video - CÓ CƠ CHẾ CHỐNG TREO/ĐỨNG TÁC VỤ."""
        clean_srt_path = str(Path(srt_file).resolve()).replace("\\", "/")
        clean_srt_path = clean_srt_path.replace(":", "\\:")

        cmd = [
            self.ffmpeg_bin,
            "-y",  # Tự động ghi đè, không đợi hỏi keyboard
            "-nostdin",  # TẮT STDIN: Chống đứng tác vụ 100%
            "-i",
            str(input_video),
            "-vf",
            f"subtitles='{clean_srt_path}'",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "18",
            "-c:a",
            "copy",
            str(output_video),
        ]

        try:
            process = subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
            )
            return process.returncode == 0
        except subprocess.TimeoutExpired:
            logger.error(f"Lỗi: Quá thời gian xử lý ({timeout}s).")
            return False
        except Exception as e:
            logger.error(f"Lỗi xuất video phụ đề: {e}")
            return False

    def generate_subshots_for_scene(
        self,
        in_time_str: Any,
        out_time_str: Any,
        voice_duration_sec: float = 5.0,
        min_shot_len: float = 2.0,
        max_shot_len: float = 4.5
    ) -> List[SubShot]:
        """Tự động chia nhỏ mốc in_time -> out_time thành các Sub-Shots tịnh tiến liên tục (Strict Monotonic)."""
        start_orig = self._tc_to_sec(in_time_str)
        end_orig = self._tc_to_sec(out_time_str)

        if end_orig <= start_orig:
            end_orig = start_orig + max(3.0, voice_duration_sec)

        subshots: List[SubShot] = []
        shot_count = 0
        current_pos = start_orig

        while current_pos < end_orig:
            shot_count += 1
            remaining = end_orig - current_pos

            if remaining <= max_shot_len:
                cur_len = round(remaining, 3)
            else:
                cur_len = round(random.uniform(min_shot_len, max_shot_len), 3)

            shot_start = round(current_pos, 3)
            shot_end = round(shot_start + cur_len, 3)

            subshots.append(SubShot(
                shot_id=shot_count,
                source_start_sec=shot_start,
                source_end_sec=shot_end,
                duration_sec=cur_len
            ))
            current_pos += cur_len

        return subshots

    def attach_subshots_to_scenes(self, scenes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Gán trước danh sách subshots tịnh tiến liên tục vào từng phân cảnh kịch bản."""
        for scene in scenes:
            in_tc = scene.get("in_time", scene.get("in", ""))
            out_tc = scene.get("out_time", scene.get("out", ""))
            dur_sec = float(scene.get("estimated_duration_sec", 5.0))

            subshots = self.generate_subshots_for_scene(in_tc, out_tc, voice_duration_sec=dur_sec)
            scene["subshots"] = [s.to_dict() for s in subshots]
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
            logger.error(f"File Video gốc không tồn tại: {source_video_path}")
            raise FileNotFoundError("Chưa chọn file Video gốc để render!")

        logger.info(f"▶️ BẮT ĐẦU RENDER B-ROLL VIDEO. Executable: {self.ffmpeg_bin} | Source: {source_video_path}")

        temp_dir = os.path.join(os.path.dirname(os.path.abspath(target_out_path)), "temp_render_shots")
        os.makedirs(temp_dir, exist_ok=True)

        try:
            concat_list_path = os.path.join(temp_dir, "concat_list.txt")
            clip_paths = []
            global_shot_idx = 0

            scenes = self.attach_subshots_to_scenes(scenes)
            all_subshots = []
            for sc in scenes:
                sub_dicts = sc.get("subshots", [])
                for sdict in sub_dicts:
                    all_subshots.append(SubShot(
                        shot_id=sdict.get("shot_id", 1),
                        source_start_sec=sdict.get("start", 0.0),
                        source_end_sec=sdict.get("end", 5.0),
                        duration_sec=sdict.get("duration", 5.0)
                    ))

            total_shots = len(all_subshots)
            logger.info(f"Tổng số Shot B-Roll cần băm: {total_shots}")

            with open(concat_list_path, "w", encoding="utf-8") as f_concat:
                for shot in all_subshots:
                    global_shot_idx += 1
                    clip_out_path = os.path.join(temp_dir, f"shot_{global_shot_idx:04d}.mp4")

                    t_start = time.time()
                    success = self.cut_subshot_high_quality(
                        input_path=source_video_path,
                        output_path=clip_out_path,
                        start_sec=shot.source_start_sec,
                        duration_sec=shot.duration_sec,
                        timeout=20
                    )
                    t_elapsed = time.time() - t_start

                    if success and os.path.exists(clip_out_path) and os.path.getsize(clip_out_path) > 0:
                        escaped_path = clip_out_path.replace("\\", "/")
                        f_concat.write(f"file '{escaped_path}'\n")
                        clip_paths.append(clip_out_path)
                        logger.info(f"✅ [Shot #{global_shot_idx}/{total_shots}] Cut thành công trong {t_elapsed:.2f}s")
                    else:
                        logger.warning(f"⚠️ Shot #{global_shot_idx} cắt lỗi hoặc timeout, bỏ qua.")

                    if progress_callback:
                        msg_str = f"🎬 Đang băm B-Roll Shot {global_shot_idx}/{total_shots}..."
                        try:
                            progress_callback(msg_str)
                        except TypeError:
                            try:
                                progress_callback(int((global_shot_idx / max(1, total_shots)) * 80), msg_str)
                            except Exception:
                                pass

            if not clip_paths:
                raise RuntimeError("Không cắt được clip B-Roll hợp lệ nào từ video gốc!")

            # Tiến hành ghép nối (Concat)
            temp_video_only = os.path.join(temp_dir, "temp_concat_video.mp4")
            cmd_concat = [
                self.ffmpeg_bin, "-y", "-nostdin",
                "-f", "concat", "-safe", "0",
                "-i", concat_list_path,
                "-c:v", "libx264",
                "-preset", "slow",
                "-crf", "17",
                "-pix_fmt", "yuv420p",
                "-an", "-sn", "-dn",
                temp_video_only
            ]
            res_concat = subprocess.run(
                cmd_concat,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=300
            )
            if res_concat.returncode != 0:
                raise RuntimeError(f"FFmpeg Clean Concat Error: {res_concat.stderr}")

            # Ghép audio voiceover nếu có file audio phù hợp
            if voice_path and os.path.exists(voice_path) and voice_path.lower().endswith(('.mp3', '.wav', '.m4a', '.aac')):
                cmd_final = [
                    self.ffmpeg_bin, "-y", "-nostdin",
                    "-i", temp_video_only,
                    "-i", voice_path,
                    "-c:v", "copy",
                    "-c:a", "aac",
                    "-b:a", "320k",
                    "-shortest",
                    target_out_path
                ]
                subprocess.run(cmd_final, stdin=subprocess.DEVNULL, check=True)
            else:
                shutil.copy(temp_video_only, target_out_path)

            logger.info(f"🎉 RENDER HOÀN TẤT VÀ XUẤT FILE THÀNH CÔNG -> {target_out_path}")
            return target_out_path

        finally:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
