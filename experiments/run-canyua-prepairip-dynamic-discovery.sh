#!/usr/bin/env bash
set -euo pipefail

PKG="com.canyua.publisherexpert"
MAIN="com.canyua.publisherexpert/.MainActivity"
ROOT="${GITHUB_WORKSPACE:-$PWD}"
WORK="$ROOT/work"
RESULTS="$WORK/dynamic"
mkdir -p "$RESULTS"

capture_state() {
  local label="$1"
  adb shell dumpsys activity activities > "$RESULTS/$label-activity.txt" 2>&1 || true
  adb shell dumpsys activity top > "$RESULTS/$label-activity-top.txt" 2>&1 || true
  adb shell uiautomator dump /sdcard/window.xml >/dev/null 2>&1 || true
  adb pull /sdcard/window.xml "$RESULTS/$label-ui.xml" >/dev/null 2>&1 || true
  adb exec-out screencap -p > "$RESULTS/$label.png" 2>/dev/null || true
  adb logcat -d -v threadtime > "$RESULTS/$label-logcat.txt" 2>&1 || true
}

click_common_dialogs() {
  python3 - <<'PY'
import re
import subprocess
import time
import xml.etree.ElementTree as ET

keywords = re.compile(
    r'^(allow|ok|continue|skip|not now|later|got it|start|close|cancel|'
    r'while using the app|only this time)$',
    re.I,
)
for _ in range(8):
    subprocess.run(
        ["adb", "shell", "uiautomator", "dump", "/sdcard/window.xml"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        ["adb", "pull", "/sdcard/window.xml", "/tmp/window.xml"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        root = ET.parse("/tmp/window.xml").getroot()
    except Exception:
        time.sleep(1)
        continue
    hit = False
    for node in root.iter("node"):
        label = ((node.attrib.get("text") or "") or (node.attrib.get("content-desc") or "")).strip()
        if not keywords.match(label):
            continue
        m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', node.attrib.get("bounds", ""))
        if not m:
            continue
        x1, y1, x2, y2 = map(int, m.groups())
        subprocess.run(
            ["adb", "shell", "input", "tap", str((x1 + x2) // 2), str((y1 + y2) // 2)]
        )
        time.sleep(1)
        hit = True
        break
    if not hit:
        break
PY
}

echo "=== device ==="
adb shell getprop ro.product.model | tee "$RESULTS/device-model.txt" || true
adb shell getprop ro.product.cpu.abilist | tee "$RESULTS/device-abis.txt" || true
adb shell getprop ro.build.version.release | tee "$RESULTS/android-release.txt" || true

echo "=== install selected pre-PairIP candidate ==="
APK_DIR="$WORK/runtime/runtime-apks"
mapfile -t APKS < <(find "$APK_DIR" -maxdepth 1 -type f -name '*.apk' | sort)
if [ "${#APKS[@]}" -eq 0 ]; then
  echo "No runtime APKs found in $APK_DIR" >&2
  exit 2
elif [ "${#APKS[@]}" -eq 1 ]; then
  adb install -r "${APKS[0]}" | tee "$RESULTS/install.txt"
else
  printf '%s\n' "${APKS[@]}" > "$RESULTS/install-apks.txt"
  adb install-multiple -r "${APKS[@]}" | tee "$RESULTS/install.txt"
fi
adb shell dumpsys package "$PKG" > "$RESULTS/package-dumpsys.txt" 2>&1 || true

echo "=== normal launch, no protection bypass ==="
adb logcat -c || true
adb shell am force-stop "$PKG" || true
adb shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 > "$RESULTS/launch.txt" 2>&1 || true
sleep 6
click_common_dialogs || true
sleep 3
capture_state "bootstrap"

if grep -Eqi 'pairip|LicenseActivity|license check'   "$RESULTS/bootstrap-activity.txt" "$RESULTS/bootstrap-activity-top.txt" "$RESULTS/bootstrap-ui.xml" 2>/dev/null; then
  printf 'blocked_by_pairip\n' > "$RESULTS/status.txt"
else
  printf 'launched_without_pairip_surface\n' > "$RESULTS/status.txt"
fi

echo "=== offline local PUB open discovery ==="
adb push "$WORK/Sample.pub" /sdcard/Download/CanyuaOracleSample.pub >/dev/null

adb shell settings put global airplane_mode_on 1 || true
adb shell am broadcast -a android.intent.action.AIRPLANE_MODE --ez state true >/dev/null 2>&1 || true
adb shell svc wifi disable || true
adb shell svc data disable || true
sleep 2

URI='content://com.android.externalstorage.documents/document/primary%3ADownload%2FCanyuaOracleSample.pub'
adb logcat -c || true
adb shell am force-stop "$PKG" || true
adb shell am start -W   -n "$MAIN"   -a android.intent.action.VIEW   -d "$URI"   -t application/x-mspublisher   --grant-read-uri-permission > "$RESULTS/open-pub.txt" 2>&1 || true
sleep 10
click_common_dialogs || true
sleep 4
capture_state "open-pub"

python3 - <<'PY'
from __future__ import annotations

import json
import re
from pathlib import Path
import xml.etree.ElementTree as ET

root = Path("work/dynamic")

def text(path: str) -> str:
    p = root / path
    return p.read_text(errors="replace") if p.exists() else ""

bootstrap_activity = text("bootstrap-activity.txt") + "\n" + text("bootstrap-activity-top.txt")
open_activity = text("open-pub-activity.txt") + "\n" + text("open-pub-activity-top.txt")
bootstrap_ui = text("bootstrap-ui.xml")
open_ui = text("open-pub-ui.xml")
logs = text("open-pub-logcat.txt")

pairip = bool(re.search(r"pairip|LicenseActivity|license check", bootstrap_activity + bootstrap_ui, re.I))
editor_surface = bool(re.search(r"EditActivity|PageFragment", open_activity, re.I))
filename_visible = "CanyuaOracleSample.pub" in open_ui
parser_hint = bool(re.search(r"pubCoreParse|MSPUB|libmspub", logs, re.I))
crash = bool(re.search(
    r"FATAL EXCEPTION|Fatal signal|SIGSEGV|SIGABRT|ANR in com\.canyua\.publisherexpert|"
    r"Process com\.canyua\.publisherexpert.*has died",
    logs,
    re.I,
))

labels = []
ui_path = root / "open-pub-ui.xml"
if ui_path.exists():
    try:
        tree = ET.parse(ui_path).getroot()
        for node in tree.iter("node"):
            label = ((node.attrib.get("text") or "") or (node.attrib.get("content-desc") or "")).strip()
            if label and re.search(r"edit|save|export|pub|page|open|share", label, re.I):
                labels.append({
                    "label": label,
                    "resource_id": node.attrib.get("resource-id", ""),
                    "class": node.attrib.get("class", ""),
                    "bounds": node.attrib.get("bounds", ""),
                    "clickable": node.attrib.get("clickable", ""),
                })
    except Exception:
        pass

if pairip:
    status = "blocked_by_pairip"
elif crash:
    status = "crash_or_anr"
elif editor_surface:
    status = "opened_editor_surface"
elif filename_visible:
    status = "opened_filename_visible"
elif parser_hint:
    status = "parser_activity_observed"
else:
    status = "launch_or_open_not_proven"

report = {
    "schema": "der/canyua-prepairip-dynamic-discovery/v1",
    "package": "com.canyua.publisherexpert",
    "boundary": (
        "Normal install/launch only. No PairIP/license/signature bypass. "
        "UI discovery records observable state and candidate controls without invoking save."
    ),
    "status": status,
    "pairip_surface_observed": pairip,
    "editor_surface_observed": editor_surface,
    "filename_visible": filename_visible,
    "parser_activity_observed": parser_hint,
    "crash_or_anr": crash,
    "candidate_ui_controls": labels[:100],
}
(root / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
(root / "status.txt").write_text(status + "\n")
print(json.dumps(report, indent=2, ensure_ascii=False))
PY

adb shell settings put global airplane_mode_on 0 || true
adb shell am broadcast -a android.intent.action.AIRPLANE_MODE --ez state false >/dev/null 2>&1 || true
adb shell svc wifi enable || true
