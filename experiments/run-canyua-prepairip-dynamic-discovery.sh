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

open_via_system_picker() {
  python3 - <<'PY'
import json
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

out = Path("work/dynamic")
target_name = "CanyuaOracleSample.pub"

def sh(*args):
    return subprocess.run(
        ["adb", "shell", *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )

def activity_state():
    p = sh("dumpsys", "activity", "activities")
    txt = p.stdout
    picker = bool(re.search(
        r"mResumedActivity:.*com\.google\.android\.documentsui/.+PickActivity",
        txt,
        re.I,
    ))
    canyua = bool(re.search(
        r"mResumedActivity:.*com\.canyua\.publisherexpert",
        txt,
        re.I,
    ))
    return picker, canyua, txt

def dump(tag):
    remote = "/sdcard/window.xml"
    local = out / f"{tag}.xml"
    subprocess.run(
        ["adb","shell","uiautomator","dump",remote],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        ["adb","pull",remote,str(local)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        return ET.parse(local).getroot()
    except Exception:
        return None

def row(n):
    return {
        "text": (n.attrib.get("text") or "").strip(),
        "desc": (n.attrib.get("content-desc") or "").strip(),
        "resource_id": (n.attrib.get("resource-id") or "").strip(),
        "bounds": n.attrib.get("bounds",""),
        "clickable": n.attrib.get("clickable",""),
        "focusable": n.attrib.get("focusable",""),
        "class": n.attrib.get("class",""),
    }

def rows(root):
    return [] if root is None else [row(n) for n in root.iter("node")]

def center(bounds):
    m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds or "")
    if not m:
        return None
    x1,y1,x2,y2 = map(int,m.groups())
    return ((x1+x2)//2, (y1+y2)//2)

def tap_bounds(bounds):
    p = center(bounds)
    if p is None:
        return False
    subprocess.run(
        ["adb","shell","input","tap",str(p[0]),str(p[1])],
        check=True,
    )
    time.sleep(1.25)
    return True

def tap_row(r):
    return tap_bounds(r["bounds"])

def target_item(root):
    if root is None:
        return None
    parent = {child: par for par in root.iter() for child in par}
    for n in root.iter("node"):
        text = (n.attrib.get("text") or "").strip()
        desc = (n.attrib.get("content-desc") or "").strip()
        if text != target_name and desc != target_name:
            continue
        cur = n
        best = n
        for _ in range(8):
            if cur is None:
                break
            rid = (cur.attrib.get("resource-id") or "").strip()
            if rid.endswith("/item_root"):
                best = cur
                break
            if cur.attrib.get("focusable") == "true":
                best = cur
            cur = parent.get(cur)
        return row(best)
    return None

def wait_picker_return(tag):
    trace = []
    for i in range(16):
        picker, canyua, txt = activity_state()
        trace.append({"poll": i, "picker": picker, "canyua": canyua})
        if not picker and canyua:
            (out / f"{tag}-return.json").write_text(
                json.dumps(trace, indent=2) + "\n"
            )
            return True
        time.sleep(0.5)
    (out / f"{tag}-return.json").write_text(
        json.dumps(trace, indent=2) + "\n"
    )
    return False

main = dump("picker-main")
main_rows = rows(main)
(out/"picker-main.json").write_text(
    json.dumps(main_rows,indent=2,ensure_ascii=False)+"\n"
)
cloud = [
    r for r in main_rows
    if r["resource_id"] == "com.canyua.publisherexpert:id/menu_cloud"
]
if len(cloud) != 1 or not tap_row(cloud[0]):
    print(f"menu_cloud control not uniquely available: {len(cloud)}", file=sys.stderr)
    sys.exit(45)

opened_roots = False
clicked_downloads = False
for step in range(30):
    root = dump(f"picker-step-{step:02d}")
    rs = rows(root)
    if step < 8:
        (out/f"picker-step-{step:02d}.json").write_text(
            json.dumps(rs,indent=2,ensure_ascii=False)+"\n"
        )

    item = target_item(root)
    if item is not None:
        (out/"picker-target.json").write_text(
            json.dumps(item,indent=2,ensure_ascii=False)+"\n"
        )
        # DocumentsUI file-title TextView is not clickable. Tap the enclosing
        # item_root/focusable row, then require PickActivity to actually return
        # its result to Canyua before claiming success.
        tap_row(item)
        if wait_picker_return("picker-tap"):
            print("selected-and-returned", target_name)
            sys.exit(0)

        # Some DocumentsUI builds focus the row on the first touch. ENTER is
        # the accessibility/keyboard equivalent of activating the focused item.
        subprocess.run(["adb","shell","input","keyevent","66"], check=False)
        if wait_picker_return("picker-enter"):
            print("selected-and-returned-via-enter", target_name)
            sys.exit(0)

        # Last normal UI attempt: second tap on the same visible row.
        tap_row(item)
        if wait_picker_return("picker-second-tap"):
            print("selected-and-returned-via-second-tap", target_name)
            sys.exit(0)

        print("target visible but DocumentsUI did not return selection", file=sys.stderr)
        sys.exit(47)

    if not opened_roots:
        roots = [
            r for r in rs
            if r["desc"].lower() in {
                "show roots", "open navigation drawer", "show navigation drawer"
            }
            or r["resource_id"].endswith("/toolbar_navigation_button")
        ]
        if roots and tap_row(roots[0]):
            opened_roots = True
            continue

    downloads = [
        r for r in rs
        if (r["text"].lower() in {"downloads","download"}
            or r["desc"].lower() in {"downloads","download"})
        and r["clickable"] == "true"
    ]
    if downloads and (not clicked_downloads or step > 8):
        if tap_row(downloads[0]):
            clicked_downloads = True
            continue

    if not opened_roots:
        fallback = [
            r for r in rs
            if r["clickable"] == "true"
            and r["class"].endswith("ImageButton")
            and "documentsui" in r["resource_id"].lower()
        ]
        if fallback and tap_row(fallback[0]):
            opened_roots = True
            continue

    time.sleep(0.75)

print("system picker never exposed the pinned PUB", file=sys.stderr)
sys.exit(46)
PY
}

echo "=== device ==="
adb shell getprop ro.product.model | tee "$RESULTS/device-model.txt" || true
adb shell getprop ro.product.cpu.abilist | tee "$RESULTS/device-abis.txt" || true
adb shell getprop ro.build.version.release | tee "$RESULTS/android-release.txt" || true
{
  echo "ro.dalvik.vm.native.bridge=$(adb shell getprop ro.dalvik.vm.native.bridge || true)"
  echo "ro.enable.native.bridge.exec=$(adb shell getprop ro.enable.native.bridge.exec || true)"
  echo "ro.ndk_translation.version=$(adb shell getprop ro.ndk_translation.version || true)"
  adb shell 'find /system /vendor /product \( -iname "*ndk_translation*" -o -iname "libnb.so" \) 2>/dev/null | head -100' || true
} | tee "$RESULTS/native-bridge.txt"

echo "=== install selected pre-PairIP candidate ==="
APK_DIR="$WORK/runtime/runtime-apks"
APKS=()
while IFS= read -r apk; do
  APKS+=("$apk")
done < <(find "$APK_DIR" -maxdepth 1 -type f -name '*.apk' | sort)
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

# Normal storage permissions declared by the historical app; no entitlement state is changed.
adb shell pm grant "$PKG" android.permission.READ_EXTERNAL_STORAGE >/dev/null 2>&1 || true
adb shell pm grant "$PKG" android.permission.WRITE_EXTERNAL_STORAGE >/dev/null 2>&1 || true

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
adb shell am broadcast \
  -a android.intent.action.MEDIA_SCANNER_SCAN_FILE \
  -d file:///sdcard/Download/CanyuaOracleSample.pub \
  >/dev/null 2>&1 || true
sleep 2

adb shell settings put global airplane_mode_on 1 || true
adb shell am broadcast -a android.intent.action.AIRPLANE_MODE --ez state true >/dev/null 2>&1 || true
adb shell svc wifi disable || true
adb shell svc data disable || true
sleep 2

URI='file:///sdcard/Download/CanyuaOracleSample.pub'
adb logcat -c || true
adb shell am force-stop "$PKG" || true
adb shell am start -W   -n "$MAIN"   -a android.intent.action.VIEW   -d "$URI"   -t application/x-mspublisher   > "$RESULTS/open-pub.txt" 2>&1 || true
sleep 10
click_common_dialogs || true
sleep 4
capture_state "open-pub"

# Android 11 scoped storage can reject this historical app's direct file://
# copy even though MainActivity itself launches normally. In that case use
# Canyua's own shipped menu_cloud -> ACTION_OPEN_DOCUMENT flow, which grants
# the content URI through DocumentsUI exactly as a user would.
if ! grep -Eqi 'EditActivity|PageFragment' "$RESULTS/open-pub-activity.txt" "$RESULTS/open-pub-activity-top.txt" 2>/dev/null; then
  if grep -Eqi 'CanyuaOracleSample\.pub.*EACCES|open failed: EACCES|Permission denied' "$RESULTS/open-pub-logcat.txt" 2>/dev/null; then
    printf 'direct_file_ingress_eacces\n' > "$RESULTS/direct-file-status.txt"
  fi

  adb shell am force-stop "$PKG" || true
  adb shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 > "$RESULTS/picker-bootstrap-launch.txt" 2>&1 || true
  sleep 4
  click_common_dialogs || true

  set +e
  open_via_system_picker > "$RESULTS/picker-open.txt" 2> "$RESULTS/picker-open.stderr"
  picker_rc=$?
  set -e
  if [ "$picker_rc" -eq 0 ]; then
    sleep 12
    click_common_dialogs || true
    capture_state "open-picker"
  else
    printf 'system_picker_ingress_failed_%s\n' "$picker_rc" > "$RESULTS/picker-status.txt"
    capture_state "picker-failed"
  fi
fi

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
direct_activity = text("open-pub-activity.txt") + "\n" + text("open-pub-activity-top.txt")
picker_activity = text("open-picker-activity.txt") + "\n" + text("open-picker-activity-top.txt")
open_activity = picker_activity if picker_activity.strip() else direct_activity
bootstrap_ui = text("bootstrap-ui.xml")
picker_ui = text("open-picker-ui.xml")
open_ui = picker_ui if picker_ui.strip() else text("open-pub-ui.xml")
direct_logs = text("open-pub-logcat.txt")
picker_logs = text("open-picker-logcat.txt")
logs = picker_logs if picker_logs.strip() else direct_logs

pairip = bool(re.search(r"pairip|LicenseActivity|license check", bootstrap_activity + bootstrap_ui, re.I))
editor_surface = bool(re.search(r"EditActivity|PageFragment", open_activity, re.I))
filename_visible = "CanyuaOracleSample.pub" in open_ui
direct_file_eacces = bool(re.search(
    r"CanyuaOracleSample\.pub.*EACCES|open failed: EACCES|Permission denied",
    direct_logs,
    re.I,
))
# Do not infer parser execution from symbol/method names printed in stack traces.
# A positive parse proof requires the editor/page surface or an independently
# observable document result.
parser_hint = editor_surface
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
elif direct_file_eacces and text("picker-status.txt"):
    status = "direct_file_eacces_and_picker_failed"
elif direct_file_eacces:
    status = "direct_file_ingress_eacces"
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
    "direct_file_ingress_eacces": direct_file_eacces,
    "picker_attempted": bool(text("picker-open.txt") or text("picker-status.txt")),
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

status="$(cat "$RESULTS/status.txt" 2>/dev/null || true)"
case "$status" in
  opened_editor_surface|opened_filename_visible)
    ;;
  *)
    echo "Dynamic PUB open was not proven: $status" >&2
    exit 3
    ;;
esac
