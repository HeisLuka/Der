#!/usr/bin/env bash
set -euo pipefail

PKG="com.canyua.publisherexpert"
MAIN="com.canyua.publisherexpert/.MainActivity"
ROOT="${GITHUB_WORKSPACE:-$PWD}"
WORK="$ROOT/work"
OUT="$WORK/canyua-3127"
BUNDLE="$OUT/oracle-bundle"
REMOTE="/sdcard/Download/CanyuaOracleSample.pub"

mkdir -p "$OUT" "$BUNDLE"
cp "$WORK/Sample.pub" "$BUNDLE/source.pub"

capture() {
  local label="$1"
  adb shell dumpsys activity activities > "$OUT/$label-activity.txt" 2>&1 || true
  adb shell dumpsys activity top > "$OUT/$label-activity-top.txt" 2>&1 || true
  adb shell uiautomator dump /sdcard/window.xml >/dev/null 2>&1 || true
  adb pull /sdcard/window.xml "$OUT/$label-ui.xml" >/dev/null 2>&1 || true
  adb exec-out screencap -p > "$OUT/$label.png" 2>/dev/null || true
  adb logcat -d -v threadtime > "$OUT/$label-logcat.txt" 2>&1 || true
}

ui_has_purchase_surface() {
  local xml="$1"
  [ -f "$xml" ] || return 1
  grep -Eqi     'purchase|purchases|buy|unlock|subscription|subscribe|payment|upgrade|document converter|in-app'     "$xml"
}

click_common_dialogs() {
  python3 - <<'PY'
import re
import subprocess
import time
import xml.etree.ElementTree as ET

safe = re.compile(
    r'^(allow|ok|continue|skip|not now|later|got it|start|close|cancel|'
    r'while using the app|only this time)$',
    re.I,
)
blocked = re.compile(
    r'purchase|buy|unlock|subscription|subscribe|payment|upgrade|document converter|in-app',
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

    labels = []
    for node in root.iter("node"):
        label = ((node.attrib.get("text") or "") or
                 (node.attrib.get("content-desc") or "")).strip()
        if label:
            labels.append(label)
    if any(blocked.search(label) for label in labels):
        raise SystemExit(42)

    hit = False
    for node in root.iter("node"):
        label = ((node.attrib.get("text") or "") or
                 (node.attrib.get("content-desc") or "")).strip()
        if not safe.match(label):
            continue
        m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',
                     node.attrib.get("bounds", ""))
        if not m:
            continue
        x1, y1, x2, y2 = map(int, m.groups())
        subprocess.run(
            ["adb", "shell", "input", "tap",
             str((x1+x2)//2), str((y1+y2)//2)]
        )
        time.sleep(1)
        hit = True
        break
    if not hit:
        break
PY
}

click_exact_save() {
  python3 - <<'PY'
import json
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

out = Path("work/canyua-3127")
blocked = re.compile(
    r'purchase|buy|unlock|subscription|subscribe|payment|upgrade|document converter|in-app',
    re.I,
)

def dump(tag):
    subprocess.run(
        ["adb","shell","uiautomator","dump","/sdcard/window.xml"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        ["adb","pull","/sdcard/window.xml",str(out / f"{tag}.xml")],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return ET.parse(out / f"{tag}.xml").getroot()

def nodes(root):
    rows=[]
    for n in root.iter("node"):
        text=(n.attrib.get("text") or "").strip()
        desc=(n.attrib.get("content-desc") or "").strip()
        rid=(n.attrib.get("resource-id") or "").strip()
        label=text or desc
        rows.append({
            "text":text, "desc":desc, "resource_id":rid,
            "bounds":n.attrib.get("bounds",""),
            "clickable":n.attrib.get("clickable",""),
            "label":label,
        })
    return rows

def purchase_present(rows):
    return any(blocked.search(r["label"]) for r in rows if r["label"])

def exact_save(rows):
    hits=[]
    for r in rows:
        label=r["label"].strip().lower()
        rid=r["resource_id"].lower()
        if label == "save":
            hits.append(r)
        elif not label and re.search(r'(^|[/_:])save$', rid):
            hits.append(r)
    return hits

root=dump("save-search-initial")
rows=nodes(root)
(out/"save-search-initial.json").write_text(json.dumps(rows,indent=2,ensure_ascii=False)+"\n")
if purchase_present(rows):
    print("purchase surface already present before Save", file=sys.stderr)
    sys.exit(42)

hits=exact_save(rows)
if len(hits) != 1:
    subprocess.run(["adb","shell","input","keyevent","82"])
    time.sleep(1)
    root=dump("save-search-menu")
    rows=nodes(root)
    (out/"save-search-menu.json").write_text(json.dumps(rows,indent=2,ensure_ascii=False)+"\n")
    if purchase_present(rows):
        print("purchase surface appeared while opening menu", file=sys.stderr)
        sys.exit(42)
    hits=exact_save(rows)

if len(hits) != 1:
    print(f"need exactly one unambiguous Save control, found {len(hits)}", file=sys.stderr)
    for h in hits:
        print(h, file=sys.stderr)
    sys.exit(43)

hit=hits[0]
m=re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',hit["bounds"])
if not m:
    print("Save control has no usable bounds", file=sys.stderr)
    sys.exit(44)
x1,y1,x2,y2=map(int,m.groups())
(out/"save-control.json").write_text(json.dumps(hit,indent=2,ensure_ascii=False)+"\n")
subprocess.run(["adb","shell","input","tap",str((x1+x2)//2),str((y1+y2)//2)],check=True)
print(json.dumps(hit,ensure_ascii=False))
PY
}

echo "=== device/native bridge ==="
{
  adb shell getprop ro.product.model || true
  adb shell getprop ro.product.cpu.abilist || true
  adb shell getprop ro.build.version.release || true
  echo "native_bridge=$(adb shell getprop ro.dalvik.vm.native.bridge || true)"
  echo "bridge_exec=$(adb shell getprop ro.enable.native.bridge.exec || true)"
  echo "ndk_translation=$(adb shell getprop ro.ndk_translation.version || true)"
} | tee "$OUT/device.txt"

echo "=== install pinned 3.1.27 ==="
adb install -r "$WORK/canyua-3.1.27.apk" | tee "$OUT/install.txt"

for perm in   android.permission.READ_EXTERNAL_STORAGE   android.permission.WRITE_EXTERNAL_STORAGE
do
  adb shell pm grant "$PKG" "$perm" 2>/dev/null || true
done

adb push "$WORK/Sample.pub" "$REMOTE" >/dev/null
adb pull "$REMOTE" "$OUT/pre-save-source.pub" >/dev/null
sha256sum "$OUT/pre-save-source.pub" | tee "$OUT/pre-save-source.sha256"
adb shell ls -l "$REMOTE" > "$OUT/pre-save-stat.txt" 2>&1 || true
adb shell 'find /sdcard -type f -iname "*.pub" -print 2>/dev/null | sort'   > "$OUT/pre-save-pub-files.txt" || true

echo "=== normal bootstrap ==="
adb logcat -c || true
adb shell am force-stop "$PKG" || true
adb shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1   > "$OUT/bootstrap-launch.txt" 2>&1 || true
sleep 5
set +e
click_common_dialogs
common_rc=$?
set -e
if [ "$common_rc" -eq 42 ]; then
  printf 'purchase_surface_observed_during_bootstrap\n' | tee "$OUT/status.txt"
  capture "bootstrap-purchase"
  exit 0
fi
capture "bootstrap"

if ui_has_purchase_surface "$OUT/bootstrap-ui.xml"; then
  printf 'purchase_surface_observed_during_bootstrap\n' | tee "$OUT/status.txt"
  exit 0
fi

echo "=== open pinned PUB offline ==="
adb shell settings put global airplane_mode_on 1 || true
adb shell am broadcast -a android.intent.action.AIRPLANE_MODE --ez state true >/dev/null 2>&1 || true
adb shell svc wifi disable || true
adb shell svc data disable || true
sleep 2

URI='content://com.android.externalstorage.documents/document/primary%3ADownload%2FCanyuaOracleSample.pub'
adb logcat -c || true
adb shell am force-stop "$PKG" || true
adb shell am start -W   -n "$MAIN"   -a android.intent.action.VIEW   -d "$URI"   -t application/x-mspublisher   --grant-read-uri-permission   --grant-write-uri-permission   > "$OUT/open-pub.txt" 2>&1 || true
sleep 10

set +e
click_common_dialogs
common_rc=$?
set -e
if [ "$common_rc" -eq 42 ]; then
  printf 'purchase_surface_observed_after_open\n' | tee "$OUT/status.txt"
  capture "open-purchase"
  exit 0
fi

capture "open"
if ui_has_purchase_surface "$OUT/open-ui.xml"; then
  printf 'purchase_surface_observed_after_open\n' | tee "$OUT/status.txt"
  exit 0
fi

if ! grep -Eqi 'EditActivity|PageFragment'     "$OUT/open-activity.txt" "$OUT/open-activity-top.txt" 2>/dev/null; then
  printf 'editor_surface_not_proven\n' | tee "$OUT/status.txt"
  exit 0
fi

echo "=== one ordinary no-op Save ==="
adb logcat -c || true
set +e
click_exact_save > "$OUT/save-click.txt" 2> "$OUT/save-click.stderr"
save_rc=$?
set -e
if [ "$save_rc" -eq 42 ]; then
  printf 'purchase_surface_observed_before_save\n' | tee "$OUT/status.txt"
  capture "save-blocked-before-click"
  exit 0
elif [ "$save_rc" -ne 0 ]; then
  printf 'save_control_not_unambiguous\n' | tee "$OUT/status.txt"
  capture "save-control-failed"
  exit 0
fi

sleep 12
capture "post-save"

if ui_has_purchase_surface "$OUT/post-save-ui.xml"; then
  printf 'purchase_surface_observed_after_save_click\n' | tee "$OUT/status.txt"
  exit 0
fi

adb shell ls -l "$REMOTE" > "$OUT/post-save-stat.txt" 2>&1 || true
adb shell 'find /sdcard -type f -iname "*.pub" -print 2>/dev/null | sort'   > "$OUT/post-save-pub-files.txt" || true

if adb pull "$REMOTE" "$BUNDLE/resave-control.pub" >/dev/null 2>&1; then
  sha256sum "$BUNDLE/resave-control.pub" | tee "$OUT/resave-control.sha256"
  python3 - <<'PY'
from pathlib import Path
p=Path("work/canyua-3127/oracle-bundle/resave-control.pub")
magic=p.read_bytes()[:8]
if magic != bytes.fromhex("d0cf11e0a1b11ae1"):
    raise SystemExit("saved file is not CFB/OLE")
PY
  before="$(sha256sum "$BUNDLE/source.pub" | awk '{print $1}')"
  after="$(sha256sum "$BUNDLE/resave-control.pub" | awk '{print $1}')"
  if [ "$before" = "$after" ]; then
    printf 'save_completed_output_byte_identical_or_not_rewritten\n' | tee "$OUT/status.txt"
  else
    printf 'resave_control_captured\n' | tee "$OUT/status.txt"
  fi
else
  printf 'save_clicked_but_output_not_retrievable\n' | tee "$OUT/status.txt"
fi

adb shell settings put global airplane_mode_on 0 || true
adb shell am broadcast -a android.intent.action.AIRPLANE_MODE --ez state false >/dev/null 2>&1 || true
adb shell svc wifi enable || true
