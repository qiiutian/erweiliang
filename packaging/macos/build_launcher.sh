#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h:h}"
APP_NAME="iFEM 重构软件.app"
APP_PATH="${PROJECT_DIR}/dist/${APP_NAME}"
CONTENTS_DIR="${APP_PATH}/Contents"
MACOS_DIR="${CONTENTS_DIR}/MacOS"
RESOURCES_DIR="${CONTENTS_DIR}/Resources"
PYTHON_BIN="/Users/qiutian/miniconda3/envs/venv/bin/python"

/bin/mkdir -p "${MACOS_DIR}" "${RESOURCES_DIR}"
/usr/bin/install -m 644 "${SCRIPT_DIR}/Info.plist" "${CONTENTS_DIR}/Info.plist"
/usr/bin/install -m 755 "${SCRIPT_DIR}/ifem-launcher" "${MACOS_DIR}/ifem-launcher"

TMP_DIR="$(/usr/bin/mktemp -d)"
cleanup() {
    if [[ "${IFEM_KEEP_BUILD_TEMP:-0}" == "1" ]]; then
        print "构建临时目录：${TMP_DIR}"
    else
        /bin/rm -rf "${TMP_DIR}"
    fi
}
trap cleanup EXIT
ICON_PATH="${RESOURCES_DIR}/AppIcon.icns"

"${PYTHON_BIN}" - "${SCRIPT_DIR}/AppIcon.svg" "${ICON_PATH}" "${TMP_DIR}" <<'PY'
import sys
from pathlib import Path

from PIL import Image
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

source, destination, temporary_directory = sys.argv[1:]
app = QGuiApplication([])
image = QImage(1024, 1024, QImage.Format.Format_ARGB32)
image.fill(0)
painter = QPainter(image)
renderer = QSvgRenderer(source)
if not renderer.isValid():
    raise SystemExit(f"无法读取图标：{source}")
renderer.render(painter)
painter.end()
png_path = Path(temporary_directory) / "AppIcon.png"
if not image.save(str(png_path)):
    raise SystemExit(f"无法生成图标：{png_path}")
with Image.open(png_path) as icon:
    icon.save(destination, format="ICNS")
PY
/usr/bin/touch "${APP_PATH}"
/usr/bin/codesign --force --deep --sign - "${APP_PATH}"

if [[ "${1:-}" == "--desktop" ]]; then
    DESKTOP_LINK="${HOME}/Desktop/${APP_NAME}"
    if [[ -L "${DESKTOP_LINK}" ]]; then
        /bin/rm "${DESKTOP_LINK}"
    elif [[ -e "${DESKTOP_LINK}" ]]; then
        print -u2 "桌面已存在同名文件，未覆盖：${DESKTOP_LINK}"
        exit 1
    fi
    /bin/ln -s "${APP_PATH}" "${DESKTOP_LINK}"
fi

print "启动器已生成：${APP_PATH}"
if [[ "${1:-}" == "--desktop" ]]; then
    print "桌面快捷入口已生成：${HOME}/Desktop/${APP_NAME}"
fi
