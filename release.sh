#!/bin/bash
# 复利动能轮动资产策略 · 一键发布脚本
# 流程：回测 → 生成数据 → 打包 .app → 封装 .dmg
# 用法：bash release.sh
set -e
cd "$(dirname "$0")"

PY=/Users/linhaojie/.workbuddy/binaries/python/versions/3.13.12/bin/python3
APP_NAME="慢富十倍·复利策略"

echo "========== 1. 回测（波动率目标版，2014-2026 全周期，无前视偏差）=========="
$PY sim_full_v3.py

echo ""
echo "========== 2. 生成 App 数据 =========="
$PY gen_data.py
$PY inline_data.py

echo ""
echo "========== 3. 打包 .app =========="
cd app_1.0
bash build_mac.sh

echo ""
echo "========== 4. 封装 .dmg =========="
STAGE="/tmp/dmg_stage"
rm -rf "$STAGE"; mkdir -p "$STAGE"
ditto "dist/$APP_NAME.app" "$STAGE/$APP_NAME.app"
ln -s /Applications "$STAGE/Applications"
rm -f "dist/$APP_NAME-v2.0.dmg"
hdiutil create -volname "$APP_NAME" -srcfolder "$STAGE" -ov -format UDZO "dist/$APP_NAME-v2.0.dmg" 2>&1 | tail -2

echo ""
echo "========== 完成 =========="
echo "产出："
echo "  · App:  app_1.0/dist/$APP_NAME.app"
echo "  · 安装包: app_1.0/dist/$APP_NAME-v2.0.dmg"
ls -lh "dist/$APP_NAME-v2.0.dmg"
