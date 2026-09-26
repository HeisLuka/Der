#!/usr/bin/env bash
set -euo pipefail

PKG="com.canyua.publisherexpert"
MAIN="com.canyua.publisherexpert/.MainActivity"
ROOT="${GITHUB_WORKSPACE:-$PWD}"
WORK="$ROOT/work"
CORPUS="$WORK/corpus"
RESULTS="$WORK/results"
mkdir -p "$RESULTS"

echo "=== device ==="
adb shell getprop ro.product.model || true
adb shell getprop ro.product.cpu.abilist || true
adb shell getprop ro.build.version.release || true

echo "=== install Canyua splits ==="
mapfile -t APKS < <(find "$WORK/apks" -maxdepth 1 -type f -name '*.apk' | sort)
printf '%s\n' "${APKS[@]}"
adb install-multiple -r "${APKS[@]}"

echo "=== package metadata ==="
adb shell dumpsys package "$PKG" > "$RESULTS/package-dumpsys.txt" || true
adb shell cmd package query-activities -a android.intent.action.VIEW -t application/x-mspublisher > "$RESULTS/query-view-x-mspublisher.txt" || true
adb shell cmd package query-activities -a android.intent.action.VIEW -t application/vnd.ms-publisher > "$RESULTS/query-view-vnd-ms-publisher.txt" || true

for perm in   android.permission.READ_EXTERNAL_STORAGE   android.permission.WRITE_EXTERNAL_STORAGE   android.permission.READ_MEDIA_IMAGES
do
  adb shell pm grant "$PKG" "$perm" 2>/dev/null || true
done

click_common_dialogs() {
  python3 - <<'PY'
import re, subprocess, time, xml.etree.ElementTree as ET
keywords = re.compile(r'^(allow|ok|accept|agree|continue|skip|not now|later|got it|start|close|cancel|while using the app|only this time)$', re.I)
for _ in range(8):
    subprocess.run(["adb","shell","uiautomator","dump","/sdcard/window.xml"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["adb","pull","/sdcard/window.xml","/tmp/window.xml"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        root = ET.parse("/tmp/window.xml").getroot()
    except Exception:
        time.sleep(1)
        continue
    hit = False
    for node in root.iter("node"):
        text = (node.attrib.get("text") or "").strip()
        desc = (node.attrib.get("content-desc") or "").strip()
        label = text or desc
        if not keywords.match(label):
            continue
        m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', node.attrib.get("bounds",""))
        if not m:
            continue
        x1,y1,x2,y2 = map(int,m.groups())
        subprocess.run(["adb","shell","input","tap",str((x1+x2)//2),str((y1+y2)//2)])
        time.sleep(1)
        hit = True
        break
    if not hit:
        break
PY
}

echo "=== bootstrap once with network available ==="
adb shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true
sleep 5
click_common_dialogs || true
adb exec-out screencap -p > "$RESULTS/bootstrap.png" || true
adb shell uiautomator dump /sdcard/window.xml >/dev/null 2>&1 || true
adb pull /sdcard/window.xml "$RESULTS/bootstrap-ui.xml" >/dev/null 2>&1 || true

echo "=== force offline test path ==="
adb shell settings put global airplane_mode_on 1 || true
adb shell am broadcast -a android.intent.action.AIRPLANE_MODE --ez state true >/dev/null 2>&1 || true
adb shell svc wifi disable || true
adb shell svc data disable || true
sleep 2

printf 'slug,class,filename,sha256,size,status,resumed_activity,ui_hint,crash_hint\n' > "$RESULTS/summary.csv"

run_one() {
  local slug="$1"
  local class="$2"
  local file="$3"
  local base
  base="$(basename "$file")"
  local out="$RESULTS/$slug"
  mkdir -p "$out"

  local remote="/sdcard/Download/$base"
  adb push "$file" "$remote" >/dev/null
  local encoded
  encoded="$(python3 - "$base" <<'PY'
import sys, urllib.parse
print(urllib.parse.quote(sys.argv[1], safe=''))
PY
)"
  local uri="content://com.android.externalstorage.documents/document/primary%3ADownload%2F$encoded"

  adb logcat -c || true
  adb shell am force-stop "$PKG" || true
  sleep 1

  {
    echo "file=$base"
    echo "uri=$uri"
    echo "--- explicit MainActivity ACTION_VIEW ---"
    adb shell am start -W       -n "$MAIN"       -a android.intent.action.VIEW       -d "$uri"       -t application/x-mspublisher       --grant-read-uri-permission || true
  } > "$out/launch.txt" 2>&1

  sleep 10
  click_common_dialogs || true
  sleep 4

  adb shell dumpsys activity activities > "$out/activity.txt" 2>&1 || true
  adb shell dumpsys activity top > "$out/activity-top.txt" 2>&1 || true
  adb shell uiautomator dump /sdcard/window.xml >/dev/null 2>&1 || true
  adb pull /sdcard/window.xml "$out/ui.xml" >/dev/null 2>&1 || true
  adb exec-out screencap -p > "$out/screen.png" 2>/dev/null || true
  adb logcat -d -v threadtime > "$out/logcat.txt" 2>&1 || true

  local resumed
  resumed="$(grep -m1 -E 'mResumedActivity|topResumedActivity' "$out/activity.txt" | tr ',' ';' | tr '\n' ' ' || true)"
  local crash=""
  if grep -Eqi 'FATAL EXCEPTION|Fatal signal|SIGSEGV|SIGABRT|ANR in com\.canyua\.publisherexpert|Process com\.canyua\.publisherexpert.*has died' "$out/logcat.txt"; then
    crash="yes"
  fi

  local ui_hint=""
  local status="unknown"
  if [ -f "$out/ui.xml" ]; then
    ui_hint="$(tr '\n' ' ' < "$out/ui.xml" | sed -E 's/[[:space:]]+/ /g' | cut -c1-1200)"
  fi

  if [ "$crash" = "yes" ]; then
    status="crash_or_anr"
  elif grep -Eqi 'EditActivity|PageFragment' "$out/activity.txt"; then
    status="opened_editor_surface"
  elif [ -f "$out/ui.xml" ] && grep -Fqi "$base" "$out/ui.xml"; then
    status="opened_filename_visible"
  elif [ -f "$out/ui.xml" ] && grep -Eqi 'unsupported|not supported|cannot open|can.t open|failed|error|invalid|corrupt|damaged' "$out/ui.xml"; then
    status="rejected_or_error_ui"
  elif grep -Eqi 'pubCoreParse|MSPUB|libmspub' "$out/logcat.txt"; then
    status="parser_activity_observed"
  fi

  local sha size
  sha="$(shasum -a 256 "$file" | awk '{print $1}')"
  size="$(stat -f%z "$file")"
  local safe_resumed safe_ui
  safe_resumed="$(printf '%s' "$resumed" | tr '"' "'" | tr '\n' ' ')"
  safe_ui="$(printf '%s' "$ui_hint" | tr '"' "'" | tr '\n' ' ')"
  printf '"%s","%s","%s","%s","%s","%s","%s","%s","%s"\n'     "$slug" "$class" "$base" "$sha" "$size" "$status" "$safe_resumed" "$safe_ui" "$crash"     >> "$RESULTS/summary.csv"

  adb shell rm -f "$remote" || true
}

while IFS=',' read -r slug class filename path; do
  [ "$slug" = "slug" ] && continue
  [ -n "$slug" ] || continue
  run_one "$slug" "$class" "$path"
done < "$WORK/runtime-manifest.csv"

echo "=== summary ==="
cat "$RESULTS/summary.csv"

echo "=== restore network ==="
adb shell settings put global airplane_mode_on 0 || true
adb shell am broadcast -a android.intent.action.AIRPLANE_MODE --ez state false >/dev/null 2>&1 || true
adb shell svc wifi enable || true
