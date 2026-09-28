#!/usr/bin/env bash
set -euo pipefail

PKG="com.canyua.publisherexpert"
MAIN="com.canyua.publisherexpert/.MainActivity"
ROOT="${GITHUB_WORKSPACE:-$PWD}"
WORK="$ROOT/work"
RESULTS="$WORK/dynamic"
mkdir -p "$RESULTS" "$RESULTS/outputs"

capture_state() {
  local label="$1"
  adb shell dumpsys activity activities > "$RESULTS/$label-activity.txt" 2>&1 || true
  adb shell dumpsys activity top > "$RESULTS/$label-activity-top.txt" 2>&1 || true
  adb shell uiautomator dump /sdcard/window.xml >/dev/null 2>&1 || true
  adb pull /sdcard/window.xml "$RESULTS/$label-ui.xml" >/dev/null 2>&1 || true
  adb exec-out screencap -p > "$RESULTS/$label.png" 2>/dev/null || true
  adb logcat -d -v threadtime > "$RESULTS/$label-logcat.txt" 2>&1 || true
}

click_common_bootstrap_dialogs() {
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

    clicked = False
    for node in root.iter("node"):
        label = ((node.attrib.get("text") or "") or (node.attrib.get("content-desc") or "")).strip()
        if not safe.match(label):
            continue
        m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', node.attrib.get("bounds", ""))
        if not m:
            continue
        x1, y1, x2, y2 = map(int, m.groups())
        subprocess.run(
            ["adb", "shell", "input", "tap", str((x1 + x2) // 2), str((y1 + y2) // 2)],
            check=False,
        )
        time.sleep(1)
        clicked = True
        break
    if not clicked:
        break
PY
}

snapshot_pubs() {
  local output="$1"
  python3 - "$output" <<'PY'
from __future__ import annotations
import hashlib
import json
import subprocess
import sys
from pathlib import Path

out = Path(sys.argv[1])
roots = [
    "/sdcard/Download",
    "/sdcard/Documents",
    "/sdcard/Android/data/com.canyua.publisherexpert/files",
]

paths = []
for root in roots:
    proc = subprocess.run(
        ["adb", "shell", "find", root, "-type", "f"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    for line in proc.stdout.splitlines():
        p = line.strip()
        if p.lower().endswith(".pub") and p not in paths:
            paths.append(p)

rows = []
for path in sorted(paths):
    h = subprocess.run(
        ["adb", "shell", "sha256sum", path],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    ).stdout.strip()
    sha = h.split()[0] if h else None
    s = subprocess.run(
        ["adb", "shell", "stat", "-c", "%s", path],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    ).stdout.strip()
    try:
        size = int(s)
    except Exception:
        size = None
    rows.append({"path": path, "sha256": sha, "bytes": size})

out.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n")
print(json.dumps(rows, indent=2, ensure_ascii=False))
PY
}

inspect_ui() {
  local mode="$1"
  python3 - "$mode" <<'PY'
from __future__ import annotations
import json
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

mode = sys.argv[1]
dump = Path("/tmp/canyua-save-ui.xml")

DANGER = re.compile(
    r"(buy|purchase|unlock|subscribe|subscription|upgrade|document converter|billing|trial)",
    re.I,
)
SAVE = re.compile(r"^save$", re.I)
FILE_MENU = re.compile(r"^(file|more options|menu)$", re.I)

def refresh():
    subprocess.run(
        ["adb", "shell", "uiautomator", "dump", "/sdcard/window.xml"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        ["adb", "pull", "/sdcard/window.xml", str(dump)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        return ET.parse(dump).getroot()
    except Exception:
        return None

def label(node):
    return ((node.attrib.get("text") or "") or (node.attrib.get("content-desc") or "")).strip()

def tap(node):
    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.attrib.get("bounds", ""))
    if not m:
        return False
    x1, y1, x2, y2 = map(int, m.groups())
    subprocess.run(
        ["adb", "shell", "input", "tap", str((x1 + x2) // 2), str((y1 + y2) // 2)],
        check=False,
    )
    return True

def summarize(root):
    rows = []
    if root is None:
        return rows
    for node in root.iter("node"):
        lab = label(node)
        rid = node.attrib.get("resource-id", "")
        if lab or rid:
            rows.append({
                "label": lab,
                "resource_id": rid,
                "class": node.attrib.get("class", ""),
                "clickable": node.attrib.get("clickable", ""),
                "bounds": node.attrib.get("bounds", ""),
            })
    return rows

root = refresh()
rows = summarize(root)
print(json.dumps(rows, indent=2, ensure_ascii=False))

if any(DANGER.search(row["label"]) for row in rows if row["label"]):
    print("dangerous_surface")
    raise SystemExit(20)

if mode == "danger-only":
    raise SystemExit(0)

if root is not None:
    for node in root.iter("node"):
        if SAVE.match(label(node)) and node.attrib.get("clickable") == "true":
            if tap(node):
                print("clicked_save")
                raise SystemExit(0)

# Ask Android for the app's menu surface; this is a normal UI key event.
subprocess.run(["adb", "shell", "input", "keyevent", "82"], check=False)
time.sleep(1)
root = refresh()
rows = summarize(root)
if any(DANGER.search(row["label"]) for row in rows if row["label"]):
    print("dangerous_surface_after_menu")
    raise SystemExit(20)
if root is not None:
    for node in root.iter("node"):
        if SAVE.match(label(node)) and node.attrib.get("clickable") == "true":
            if tap(node):
                print("clicked_save_after_keymenu")
                raise SystemExit(0)

# Conservative fallback: open only an explicitly labelled File/Menu/More Options control,
# then look again for exact Save. Never select Export/Convert/Save As here.
root = refresh()
if root is not None:
    for node in root.iter("node"):
        lab = label(node)
        if FILE_MENU.match(lab) and node.attrib.get("clickable") == "true":
            if tap(node):
                time.sleep(1)
                break

root = refresh()
rows = summarize(root)
if any(DANGER.search(row["label"]) for row in rows if row["label"]):
    print("dangerous_surface_after_file_menu")
    raise SystemExit(20)
if root is not None:
    for node in root.iter("node"):
        if SAVE.match(label(node)) and node.attrib.get("clickable") == "true":
            if tap(node):
                print("clicked_save_after_file_menu")
                raise SystemExit(0)

print("save_control_not_found")
raise SystemExit(21)
PY
}

compare_and_pull_changed() {
  python3 - <<'PY'
from __future__ import annotations
import json
import shutil
import subprocess
from pathlib import Path

root = Path("work/dynamic")
before = {row["path"]: row for row in json.loads((root / "pubs-before.json").read_text())}
after_rows = json.loads((root / "pubs-after.json").read_text())
changes = []

for row in after_rows:
    old = before.get(row["path"])
    if old is None:
        changes.append({"kind": "added", "before": None, "after": row})
    elif old.get("sha256") != row.get("sha256"):
        changes.append({"kind": "changed", "before": old, "after": row})

(root / "pub-changes.json").write_text(
    json.dumps(changes, indent=2, ensure_ascii=False) + "\n"
)
print(json.dumps(changes, indent=2, ensure_ascii=False))

if not changes:
    raise SystemExit(0)

# Prefer the overwritten input if it changed; otherwise take the first new/changed PUB.
preferred = None
for change in changes:
    if change["after"]["path"] == "/sdcard/Download/CanyuaOracleSample.pub":
        preferred = change
        break
if preferred is None:
    preferred = changes[0]

remote = preferred["after"]["path"]
local = root / "saved-output.pub"
subprocess.run(["adb", "pull", remote, str(local)], check=True)
(root / "selected-output.json").write_text(
    json.dumps({"remote": remote, "local": str(local), "change": preferred}, indent=2) + "\n"
)
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

def dump(tag):
    remote = "/sdcard/window.xml"
    local = out / f"{tag}.xml"
    subprocess.run(["adb","shell","uiautomator","dump",remote],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["adb","pull",remote,str(local)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        return ET.parse(local).getroot()
    except Exception:
        return None

def rows(root):
    if root is None:
        return []
    result=[]
    for n in root.iter("node"):
        result.append({
            "text":(n.attrib.get("text") or "").strip(),
            "desc":(n.attrib.get("content-desc") or "").strip(),
            "resource_id":(n.attrib.get("resource-id") or "").strip(),
            "bounds":n.attrib.get("bounds",""),
            "clickable":n.attrib.get("clickable",""),
            "class":n.attrib.get("class",""),
        })
    return result

def tap(row):
    m=re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',row["bounds"])
    if not m:
        return False
    x1,y1,x2,y2=map(int,m.groups())
    subprocess.run(["adb","shell","input","tap",str((x1+x2)//2),str((y1+y2)//2)],check=True)
    time.sleep(1.5)
    return True

rs=rows(dump("picker-main"))
(out/"picker-main.json").write_text(json.dumps(rs,indent=2,ensure_ascii=False)+"\n")
cloud=[r for r in rs if r["resource_id"]=="com.canyua.publisherexpert:id/menu_cloud"]
if len(cloud)!=1 or not tap(cloud[0]):
    print(f"menu_cloud control not uniquely available: {len(cloud)}",file=sys.stderr)
    sys.exit(45)

opened_roots=False
clicked_downloads=False
for step in range(30):
    rs=rows(dump(f"picker-step-{step:02d}"))
    if step < 8:
        (out/f"picker-step-{step:02d}.json").write_text(
            json.dumps(rs,indent=2,ensure_ascii=False)+"\n"
        )
    target=[r for r in rs if r["text"]==target_name or r["desc"]==target_name]
    if target and tap(target[0]):
        print("selected",target_name)
        sys.exit(0)

    if not opened_roots:
        roots=[
            r for r in rs
            if r["desc"].lower() in {"show roots","open navigation drawer","show navigation drawer"}
            or r["resource_id"].endswith("/toolbar_navigation_button")
        ]
        if roots and tap(roots[0]):
            opened_roots=True
            continue

    downloads=[
        r for r in rs
        if (r["text"].lower() in {"downloads","download"} or
            r["desc"].lower() in {"downloads","download"})
        and r["clickable"]=="true"
    ]
    if downloads and (not clicked_downloads or step > 8):
        if tap(downloads[0]):
            clicked_downloads=True
            continue

    if not opened_roots:
        fallback=[
            r for r in rs
            if r["clickable"]=="true"
            and r["class"].endswith("ImageButton")
            and "documentsui" in r["resource_id"].lower()
        ]
        if fallback and tap(fallback[0]):
            opened_roots=True
            continue
    time.sleep(0.75)

print("system picker never exposed the pinned PUB",file=sys.stderr)
sys.exit(46)
PY
}

echo "=== device ==="
adb shell getprop ro.product.model | tee "$RESULTS/device-model.txt" || true
adb shell getprop ro.product.cpu.abilist | tee "$RESULTS/device-abis.txt" || true
adb shell getprop ro.build.version.release | tee "$RESULTS/android-release.txt" || true

echo "=== normal install ==="
adb install -r "$WORK/runtime/canyua-3.1.27.apk" | tee "$RESULTS/install.txt"
adb shell dumpsys package "$PKG" > "$RESULTS/package-dumpsys.txt" 2>&1 || true

# These are normal runtime permissions, not entitlement/protection changes.
adb shell pm grant "$PKG" android.permission.READ_EXTERNAL_STORAGE >/dev/null 2>&1 || true
adb shell pm grant "$PKG" android.permission.WRITE_EXTERNAL_STORAGE >/dev/null 2>&1 || true

echo "=== launch normally ==="
adb logcat -c || true
adb shell am force-stop "$PKG" || true
adb shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 > "$RESULTS/launch.txt" 2>&1 || true
sleep 6
click_common_bootstrap_dialogs || true
sleep 3
capture_state "bootstrap"

if grep -Eqi 'pairip|LicenseActivity|license check'     "$RESULTS/bootstrap-activity.txt" "$RESULTS/bootstrap-activity-top.txt" "$RESULTS/bootstrap-ui.xml" 2>/dev/null; then
  echo "blocked_by_protection_surface" | tee "$RESULTS/status.txt"
  exit 0
fi

echo "=== pinned offline PUB open ==="
adb push "$WORK/Sample.pub" /sdcard/Download/CanyuaOracleSample.pub >/dev/null
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
click_common_bootstrap_dialogs || true
sleep 4
capture_state "open-pub"

if ! grep -Eqi 'EditActivity|PageFragment' "$RESULTS/open-pub-activity.txt" "$RESULTS/open-pub-activity-top.txt" 2>/dev/null; then
  echo "=== retry through shipped in-app ACTION_OPEN_DOCUMENT path ==="
  adb shell am force-stop "$PKG" || true
  adb shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1     > "$RESULTS/picker-bootstrap-launch.txt" 2>&1 || true
  sleep 4
  click_common_bootstrap_dialogs || true

  set +e
  open_via_system_picker > "$RESULTS/picker-open.txt" 2> "$RESULTS/picker-open.stderr"
  picker_rc=$?
  set -e
  if [ "$picker_rc" -ne 0 ]; then
    printf 'system_picker_ingress_failed_%s\n' "$picker_rc" | tee "$RESULTS/status.txt"
    capture_state "picker-failed"
    exit 0
  fi

  sleep 12
  click_common_bootstrap_dialogs || true
  capture_state "open-picker"

  if ! grep -Eqi 'EditActivity|PageFragment'       "$RESULTS/open-picker-activity.txt" "$RESULTS/open-picker-activity-top.txt" 2>/dev/null; then
    echo "editor_surface_not_proven_after_picker" | tee "$RESULTS/status.txt"
    exit 0
  fi
fi

if inspect_ui danger-only > "$RESULTS/pre-save-ui-inventory.txt" 2>&1; then
  :
else
  rc=$?
  if [ "$rc" -eq 20 ]; then
    echo "purchase_or_protection_surface_before_save" | tee "$RESULTS/status.txt"
    exit 0
  fi
fi

snapshot_pubs "$RESULTS/pubs-before.json"

echo "=== invoke only ordinary Save ==="
set +e
inspect_ui save > "$RESULTS/save-control-attempt.txt" 2>&1
save_rc=$?
set -e
capture_state "post-save-click"

if [ "$save_rc" -eq 20 ]; then
  echo "save_routed_to_purchase" | tee "$RESULTS/status.txt"
  exit 0
elif [ "$save_rc" -eq 21 ]; then
  echo "save_control_not_found" | tee "$RESULTS/status.txt"
  exit 0
elif [ "$save_rc" -ne 0 ]; then
  echo "save_ui_automation_error" | tee "$RESULTS/status.txt"
  exit 0
fi

sleep 12
capture_state "post-save"

set +e
inspect_ui danger-only > "$RESULTS/post-save-ui-inventory.txt" 2>&1
danger_rc=$?
set -e
if [ "$danger_rc" -eq 20 ]; then
  echo "save_routed_to_purchase" | tee "$RESULTS/status.txt"
  exit 0
fi

snapshot_pubs "$RESULTS/pubs-after.json"
compare_and_pull_changed

if [ -f "$RESULTS/saved-output.pub" ]; then
  python3 experiments/diff-pub-cfb.py     "$WORK/Sample.pub" "$RESULTS/saved-output.pub"     --json "$RESULTS/cfb-diff.json"     --include-unchanged     | tee "$RESULTS/cfb-diff.txt"
  echo "natural_save_output_captured" | tee "$RESULTS/status.txt"
else
  echo "save_invoked_but_no_changed_pub_found" | tee "$RESULTS/status.txt"
fi

adb shell settings put global airplane_mode_on 0 || true
adb shell am broadcast -a android.intent.action.AIRPLANE_MODE --ez state false >/dev/null 2>&1 || true
adb shell svc wifi enable || true
