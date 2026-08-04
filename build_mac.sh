#!/bin/bash
# Script tự động chạy đóng gói ứng dụng cho macOS trên Terminal

echo "🍎 Bắt đầu khởi chạy đóng gói AutoReview Lite cho macOS..."
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt pyinstaller imageio-ffmpeg
python3 build_mac.py
