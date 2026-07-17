#!/bin/bash
set -euo pipefail

# ══════════════════════════════════════════════════════════════════
# DemoUpgrade 一键构建脚本
# 用法: ./build_app.sh [--ios] [--macos] [--install] [--clean]
# ══════════════════════════════════════════════════════════════════

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"
XCODEPROJ="$PROJECT_DIR/DemoUpgrade.xcodeproj"
DERIVED_DATA="/tmp/demoupgrade-build"
DEVICE_NAME="陈泓州的iPad"
SCHEME_MAC="DemoUpgrade-macOS"
SCHEME_IOS="DemoUpgrade-iOS"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

PLATFORM=""   # ios, macos, both
INSTALL=false
CLEAN=false

usage() {
    cat <<EOF
用法: ./build_app.sh [选项]

选项:
  --ios        构建 iOS (iPad) 版本
  --macos      构建 macOS 版本
  --all        构建双平台 (默认)
  --install    构建后安装到 iPad (仅 --ios)
  --clean      清理构建缓存后重新构建

示例:
  ./build_app.sh --macos                    # 本地 macOS 测试
  ./build_app.sh --ios --install            # 编译 + 安装到 iPad
  ./build_app.sh --ios --clean --install    # 清理重编译 + 安装
  ./build_app.sh --all                      # 双平台编译

注意:
  - derivedData 路径用 /tmp/demoupgrade-build (纯 ASCII，避免中文路径 codesign 报错)
  - 安装到 iPad 需要设备已连接且信任此 Mac
EOF
    exit 0
}

# ── Parse args ──
if [[ $# -eq 0 ]]; then
    usage
fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        --ios)     PLATFORM="ios" ;;
        --macos)   PLATFORM="macos" ;;
        --all)     PLATFORM="both" ;;
        --install) INSTALL=true ;;
        --clean)   CLEAN=true ;;
        -h|--help) usage ;;
        *) echo -e "${RED}未知参数: $1${NC}"; usage ;;
    esac
    shift
done

if [[ -z "$PLATFORM" ]]; then
    echo -e "${RED}请指定平台: --ios, --macos, 或 --all${NC}"
    exit 1
fi

if $INSTALL && [[ "$PLATFORM" != "ios" && "$PLATFORM" != "both" ]]; then
    echo -e "${RED}--install 只能与 --ios 或 --all 一起使用${NC}"
    exit 1
fi

# ── Check prerequisites ──
echo -e "${GREEN}[检查] 环境...${NC}"
for cmd in python3 xcodebuild xcrun; do
    if ! command -v $cmd &>/dev/null; then
        echo -e "${RED}错误: 未找到 $cmd${NC}"
        exit 1
    fi
done
echo "  ✅ python3: $(python3 --version)"
echo "  ✅ xcodebuild: $(xcodebuild -version | head -1)"

# ── Generate Xcode project ──
echo ""
echo -e "${GREEN}[1/3] 生成 Xcode 项目...${NC}"
cd "$PROJECT_DIR"
python3 gen_xcode_project.py

if [[ ! -d "$XCODEPROJ" ]]; then
    echo -e "${RED}错误: Xcode 项目生成失败${NC}"
    exit 1
fi

# ── Build ──
BUILD_FLAGS=(-derivedDataPath "$DERIVED_DATA" -allowProvisioningUpdates)
if $CLEAN; then
    BUILD_FLAGS+=(clean build)
else
    BUILD_FLAGS+=(build)
fi

build_target() {
    local scheme="$1"
    local sdk="$2"
    local dest="$3"
    local label="$4"

    echo ""
    echo -e "${GREEN}[2/3] 编译 $label...${NC}"
    xcodebuild -project "$XCODEPROJ" \
        -scheme "$scheme" \
        -destination "$dest" \
        -configuration Debug \
        "${BUILD_FLAGS[@]}" 2>&1 | tail -20

    if [[ ${PIPESTATUS[0]} -ne 0 ]]; then
        echo -e "${RED}错误: $label 编译失败${NC}"
        return 1
    fi
    echo -e "${GREEN}  ✅ $label 编译成功${NC}"
}

# macOS
if [[ "$PLATFORM" == "macos" || "$PLATFORM" == "both" ]]; then
    build_target "$SCHEME_MAC" "macosx" 'generic/platform=macOS' "macOS"

    MACOS_APP="$DERIVED_DATA/Build/Products/Debug/DemoUpgrade.app"
    if [[ -d "$MACOS_APP" ]]; then
        echo ""
        echo -e "${GREEN}  macOS App: $MACOS_APP${NC}"
        echo "  运行: open '$MACOS_APP'"
    fi
fi

# iOS
if [[ "$PLATFORM" == "ios" || "$PLATFORM" == "both" ]]; then
    build_target "$SCHEME_IOS" "iphoneos" 'generic/platform=iOS' "iOS"

    IOS_APP="$DERIVED_DATA/Build/Products/Debug-iphoneos/DemoUpgrade.app"
    if [[ ! -d "$IOS_APP" ]]; then
        echo -e "${RED}错误: iOS .app 未找到于 $IOS_APP${NC}"
        exit 1
    fi
    echo "  iOS App: $IOS_APP"

    # ── Install to iPad ──
    if $INSTALL; then
        echo ""
        echo -e "${GREEN}[3/3] 安装到 iPad...${NC}"
        echo "  设备: $DEVICE_NAME"

        # 检查设备是否连接
        if ! xcrun devicectl list devices 2>/dev/null | grep -q "$DEVICE_NAME"; then
            echo -e "${YELLOW}  ⚠ 未找到设备 '$DEVICE_NAME'，尝试列出可用设备...${NC}"
            xcrun devicectl list devices 2>/dev/null || true
            echo ""
            echo -e "${YELLOW}  请确认 iPad 已连接并信任此 Mac，然后手动运行:${NC}"
            echo "  xcrun devicectl device install app --device '$DEVICE_NAME' '$IOS_APP'"
            exit 1
        fi

        xcrun devicectl device install app \
            --device "$DEVICE_NAME" \
            "$IOS_APP"

        echo -e "${GREEN}  ✅ 已安装到 iPad${NC}"
    fi
fi

echo ""
echo -e "${GREEN}═══════════════════════════════════════${NC}"
echo -e "${GREEN}  构建完成！${NC}"
echo -e "${GREEN}═══════════════════════════════════════${NC}"
