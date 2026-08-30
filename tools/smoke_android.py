"""兼容旧命令；正式入口为 tools/run_android.py。"""

from run_android import main


if __name__ == "__main__":
    raise SystemExit(main())
