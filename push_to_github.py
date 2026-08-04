import os
import sys

try:
    from dulwich import porcelain
    from dulwich.repo import Repo
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "dulwich"])
    from dulwich import porcelain
    from dulwich.repo import Repo


def push_code(github_token: str = ""):
    target_dir = os.path.dirname(os.path.abspath(__file__))

    if not github_token:
        print("=" * 60)
        print("🔑 ĐỒNG BỘ MÃ NGUỒN LÊN GITHUB REPOSITORY (`huan2109/review_film`)")
        print("=" * 60)
        print("Hướng dẫn tạo Token nhanh:")
        print("1. Truy cập https://github.com/settings/tokens")
        print("2. Chọn 'Generate new token (classic)', tích chọn quyền 'repo'.")
        print("3. Dán Token vào bên dưới:")
        print("-" * 60)
        github_token = input("Nhập GitHub Token (ghp_...): ").strip()

    if not github_token:
        print("❌ Chưa nhập Token, không thể đẩy code!")
        return

    # Clean URL with token
    remote_url = f"https://{github_token}@github.com/huan2109/review_film.git"
    print("\n⏳ Đang tiến hành commit & push toàn bộ mã nguồn lên GitHub...")

    try:
        git_dir = os.path.join(target_dir, ".git")
        if not os.path.exists(git_dir):
            Repo.init(target_dir)

        # Stage files
        porcelain.add(
            target_dir,
            paths=[
                "main.py",
                "build.py",
                "build_mac.py",
                "build_mac.sh",
                "requirements.txt",
                "src",
                ".github",
            ],
        )

        # Commit
        try:
            porcelain.commit(
                target_dir,
                message=b"Initial commit - AutoReview Lite Master Version & macOS Cloud Build",
                author=b"AutoReview Lite <admin@autoreview.local>",
            )
        except Exception:
            pass

        # Push to main
        porcelain.push(target_dir, remote_url, refspecs=b"refs/heads/main")
        print("\n" + "=" * 60)
        print("🎉 ĐỒNG BỘ 100% MÃ NGUỒN LÊN GITHUB THÀNH CÔNG!")
        print("🔗 Repository Link: https://github.com/huan2109/review_film")
        print("🍎 GitHub Actions đang khởi tạo build file .app cho macOS!")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ Lỗi khi push code: {e}")


if __name__ == "__main__":
    token = sys.argv[1] if len(sys.argv) > 1 else ""
    push_code(token)
