import os
import sys
import subprocess

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def build_executable():
    """Script tự động đóng gói AutoReview Lite thành file .exe chạy trên Windows."""
    print("=" * 60)
    print("BAT DAU DONG GOI UNG DUNG AUTOREVIEW LITE (.EXE)")
    print("=" * 60)

    # 1. Kiểm tra PyInstaller
    try:
        import PyInstaller
        print(f"Da tim thay PyInstaller phien ban: {PyInstaller.__version__}")
    except ImportError:
        print("Chua tim thay PyInstaller. Dang tien hanh cai dat...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # 2. Xây dựng tham số PyInstaller
    project_root = os.path.dirname(os.path.abspath(__file__))
    main_script = os.path.join(project_root, "main.py")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=AutoReviewLite",
        "--noconsole",
        "--onedir",
        "--clean",
        "-y",
        f"--add-data={os.path.join(project_root, 'src')}{os.pathsep}src",
        main_script
    ]

    print("\nDang thuc thi lenh dong goi:")
    print(" ".join(cmd))
    print("-" * 60)

    try:
        subprocess.check_call(cmd)
        print("\n" + "=" * 60)
        print("DONG GOI THANH CONG!")
        print(f"Thu muc file thuc thi nam tai: {os.path.join(project_root, 'dist', 'AutoReviewLite')}")
        print("=" * 60)
    except subprocess.CalledProcessError as e:
        print(f"\nLoi trong qua trinh dong goi: {e}")


if __name__ == "__main__":
    build_executable()
