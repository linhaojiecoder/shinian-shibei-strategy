#!/bin/bash
# 复利动能轮动资产策略 · macOS .app 打包脚本
# 用法：bash build_mac.sh
# 产出：dist/复利动能轮动资产策略.app（双击运行）
set -e

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"

ELECTRON_APP="$APP_DIR/node_modules/electron/dist/Electron.app"
APP_NAME="十二年十倍复利策略"
OUT_DIR="$APP_DIR/dist"
TARGET="$OUT_DIR/$APP_NAME.app"

echo "=== 1. 清理旧产物 ==="
mkdir -p "$OUT_DIR"
rm -f "$OUT_DIR/$APP_NAME-v3.0.dmg" "$OUT_DIR/$APP_NAME-v2.0.dmg" "$OUT_DIR/$APP_NAME-v3.3.3.dmg"
# 旧 .app 移到废纸篓（避免 rm -rf 触发大批量删除确认）
if [ -d "$TARGET" ]; then
  osascript -e "tell application \"Finder\" to delete POSIX file \"$TARGET\"" >/dev/null 2>&1 || rm -rf "$TARGET"
fi
mkdir -p "$OUT_DIR"

echo "=== 2. 复制 Electron.app 骨架（ditto 保留特殊权限）==="
ditto "$ELECTRON_APP" "$TARGET"

echo "=== 3. 放入应用代码（Resources/app 目录，Electron 优先加载）==="
RES="$TARGET/Contents/Resources"
mkdir -p "$RES/app"
cp "$APP_DIR/main.js" "$RES/app/main.js"
cp "$APP_DIR/engine.js" "$RES/app/engine.js"
cp "$APP_DIR/preload.js" "$RES/app/preload.js"
cp -r "$APP_DIR/modules" "$RES/app/modules"
cp -r "$APP_DIR/src" "$RES/app/src"
cp "$APP_DIR/package.json" "$RES/app/package.json"

echo "=== 4. 替换图标 ==="
if [ -f "$APP_DIR/icon.icns" ]; then
  cp "$APP_DIR/icon.icns" "$RES/icon.icns"
else
  cp /tmp/icon.icns "$RES/icon.icns" 2>/dev/null || echo "（无自定义图标，用默认）"
fi

echo "=== 5. 修改 Info.plist ==="
PLIST="$TARGET/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleDisplayName $APP_NAME" "$PLIST"
/usr/libexec/PlistBuddy -c "Set :CFBundleName $APP_NAME" "$PLIST"
/usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier com.linhaojie.momentum" "$PLIST"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString 3.5.0" "$PLIST"
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion 3.5.0" "$PLIST"
/usr/libexec/PlistBuddy -c "Set :CFBundleIconFile icon.icns" "$PLIST"

echo ""
echo "✅ 打包完成: $TARGET"
echo "   双击即可运行。首次打开若提示「未验证开发者」，请右键 → 打开。"
