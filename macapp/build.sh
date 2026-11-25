#!/bin/zsh
# 构建 AI盯盘.app：bash build.sh [install]
#   install：同时复制到 /Applications
set -e
cd "$(dirname "$0")"
APP="build/AI盯盘.app"
rm -rf build && mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" build/icon.iconset

echo "› 编译 SwiftUI"
swiftc -O -parse-as-library -swift-version 5 -target arm64-apple-macos14.0 \
  Sources/*.swift -o "$APP/Contents/MacOS/AIDingPan"

echo "› 生成图标"
swiftc -O tools/make_icon.swift -o build/make_icon
for s in 16 32 64 128 256 512 1024; do ./build/make_icon $s build/icon_$s.png; done
cp build/icon_16.png build/icon.iconset/icon_16x16.png
cp build/icon_32.png build/icon.iconset/icon_16x16@2x.png
cp build/icon_32.png build/icon.iconset/icon_32x32.png
cp build/icon_64.png build/icon.iconset/icon_32x32@2x.png
cp build/icon_128.png build/icon.iconset/icon_128x128.png
cp build/icon_256.png build/icon.iconset/icon_128x128@2x.png
cp build/icon_256.png build/icon.iconset/icon_256x256.png
cp build/icon_512.png build/icon.iconset/icon_256x256@2x.png
cp build/icon_512.png build/icon.iconset/icon_512x512.png
cp build/icon_1024.png build/icon.iconset/icon_512x512@2x.png
iconutil -c icns build/icon.iconset -o "$APP/Contents/Resources/AppIcon.icns"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>AI盯盘</string>
  <key>CFBundleDisplayName</key><string>AI 盯盘</string>
  <key>CFBundleIdentifier</key><string>local.stockplatform.aidingpan</string>
  <key>CFBundleExecutable</key><string>AIDingPan</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>LSApplicationCategoryType</key><string>public.app-category.finance</string>
  <key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict>
</dict></plist>
PLIST

# 记下仓库位置：App 从这里启动后台（server.py）
(cd .. && pwd) > "$APP/Contents/Resources/source_root.txt"

codesign --force --deep -s - "$APP" >/dev/null 2>&1 || true
echo "› 完成：$PWD/$APP"

if [[ "$1" == "install" ]]; then
  rm -rf "/Applications/AI盯盘.app"
  cp -R "$APP" /Applications/
  echo "› 已安装到 /Applications/AI盯盘.app"
fi
