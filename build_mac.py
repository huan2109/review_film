#!/usr/bin/env python3
"""
Script tự động đóng gói ứng dụng AutoReview Lite trên macOS (Intel & Apple Silicon M1/M2/M3/M4) thành file app / Unix Executable.
"""

import os
import sys
import subprocess
import shutil

def build_mac_app():
    print("=" * 60)
    print("🍎 BẮT ĐẦU ĐÓNG GÓI ỨNG DỤNG AUTOREVIEW LITE CHO MACOS")
    print("=" * 60)

    # 1. Kiểm tra PyInstaller & PyQt6
    try:
        import PyInstaller
        print(f"✅ Đã tìm thấy PyInstaller phiên bản: {PyInstaller.__version__}")
    except ImportError:
        print("⏳ Chưa cài PyInstaller. Đang tự động cài đặt...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # Cài đặt requirements nếu thiếu
    project_root = os.path.dirname(os.path.abspath(__file__))
    req_file = os.path.join(project_root, "requirements.txt")
    if os.path.exists(req_file):
        print("⏳ Cài đặt các thư viện phụ thuộc từ requirements.txt...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", req_file])

    main_script = os.path.join(project_root, "main.py")

    # 2. Đóng gói bằng PyInstaller với tùy chọn windowed (.app)
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=AutoReviewLite",
        "--windowed",       # Tạo ứng dụng dạng .app trên macOS
        "--onedir",
        "--clean",
        "-y",
        f"--add-data={os.path.join(project_root, 'src')}:src",
        main_script
    ]

    print("\n⏳ Đang thực thi lệnh đóng gói PyInstaller cho macOS...")
    print(" ".join(cmd))
    print("-" * 60)

    try:
        subprocess.check_call(cmd)
        dist_dir = os.path.join(project_root, "dist")
        app_path = os.path.join(dist_dir, "AutoReviewLite.app")
        print("\n" + "=" * 60)
        print("🎉 ĐÓNG GÓI CHO MACOS THÀNH CÔNG!")
        if os.path.exists(app_path):
            print(f"🍎 Ứng dụng macOS .app nằm tại: {app_path}")
        else:
            print(f"📁 Thư mục xuất file nằm tại: {os.path.join(dist_dir, 'AutoReviewLite')}")
        print("=" * 60)

        # Tạo file Zip để dễ chia sẻ
        zip_output = os.path.join(dist_dir, "AutoReviewLite_macOS.zip")
        if os.path.exists(app_path):
            print(f"📦 Đang nén file .app thành: {zip_output}")
            shutil.make_archive(zip_output.replace(".zip", ""), "zip", dist_dir, "AutoReviewLite.app")
            print(f"✅ Đã tạo file Zip chia sẻ thành công: {zip_output}")

    except subprocess.CalledProcessError as e:
        print(f"\n❌ Lỗi trong quá trình đóng gói macOS: {e}")

if __name__ == "__main__":
    build_mac_app()
