#!/usr/bin/env bash
set -euxo pipefail
mkdir -p work/results

{
  echo "=== ABI ==="
  adb shell getprop ro.product.cpu.abilist
  adb shell getprop ro.product.cpu.abilist64
  echo "=== native bridge ==="
  adb shell getprop ro.dalvik.vm.native.bridge
  adb shell getprop ro.enable.native.bridge.exec
  adb shell getprop ro.ndk_translation.version
  echo "=== bridge files ==="
  adb shell 'find /system /vendor /product \( -iname "*ndk_translation*" -o -iname "libnb.so" \) 2>/dev/null | head -100' || true
} | tee work/results/device.txt

set +e
adb install-multiple -r work/apks/*.apk > work/results/install.txt 2>&1
rc=$?
set -e
echo "install_rc=$rc" | tee -a work/results/install.txt
cat work/results/install.txt

if [ "$rc" -eq 0 ]; then
  adb shell am force-stop com.canyua.publisherexpert || true
  adb logcat -c || true
  adb shell monkey -p com.canyua.publisherexpert -c android.intent.category.LAUNCHER 1 > work/results/launch.txt 2>&1 || true
  sleep 8
  adb shell dumpsys activity activities > work/results/activity.txt || true
  adb logcat -d -v threadtime > work/results/logcat.txt || true
  adb exec-out screencap -p > work/results/screen.png || true
fi
