import os
import sys
import traceback


PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("MPLCONFIGDIR", os.path.join(PROJECT_DIR, ".mplconfig"))


DEPENDENCY_HINT = (
    "缺少运行桌面工具所需的 Python 依赖。\n\n"
    "请先在当前环境安装：\n"
    "  python -m pip install -r requirements.txt\n\n"
    "当前 GUI 需要的核心依赖：numpy、matplotlib、PySide6。"
)


def show_startup_error(message):
    print(message, file=sys.stderr)


def main():
    try:
        import numpy  # noqa: F401
        import matplotlib  # noqa: F401
    except ModuleNotFoundError as exc:
        show_startup_error(f"{DEPENDENCY_HINT}\n\n缺失模块：{exc.name}")
        return 1

    try:
        import PySide6  # noqa: F401
        from gui_qt import launch_app
    except ModuleNotFoundError as exc:
        if exc.name != "PySide6":
            show_startup_error(f"{DEPENDENCY_HINT}\n\n缺失模块：{exc.name}")
            return 1
        try:
            from gui import launch_app
            print(
                "未安装 PySide6，当前回退到 Tkinter 界面。安装 requirements.txt 后会自动使用新版 Qt 界面。",
                file=sys.stderr,
            )
        except ModuleNotFoundError as fallback_exc:
            show_startup_error(f"{DEPENDENCY_HINT}\n\n缺失模块：{fallback_exc.name}")
            return 1
    except Exception as exc:
        show_startup_error(f"程序启动失败：{exc}\n\n{traceback.format_exc()}")
        return 1

    result = launch_app()
    return result if isinstance(result, int) else 0


if __name__ == "__main__":
    raise SystemExit(main())
