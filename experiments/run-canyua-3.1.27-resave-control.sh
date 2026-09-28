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


open_via_system_picker() {
  python3 - <<'PY'
import json
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

out = Path("work/canyua-3127")
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

        # Touching this AOSP DocumentsUI row can leave focus on the
        # RecyclerView rather than dispatching the item click. Move keyboard
        # focus into the list and activate the focused file with DPAD_CENTER.
        for attempt in range(4):
            subprocess.run(["adb","shell","input","keyevent","20"], check=False)  # DPAD_DOWN
            time.sleep(0.35)
            focus_root = dump(f"picker-focus-{attempt:02d}")
            focus_rows = rows(focus_root)
            (out/f"picker-focus-{attempt:02d}.json").write_text(
                json.dumps(focus_rows,indent=2,ensure_ascii=False)+"\\n"
            )
            subprocess.run(["adb","shell","input","keyevent","23"], check=False)  # DPAD_CENTER
            if wait_picker_return(f"picker-dpad-{attempt:02d}"):
                print("selected-and-returned-via-dpad", target_name, attempt)
                sys.exit(0)

        # Some Google DocumentsUI builds expose an explicit preview affordance
        # even when the list item itself is not accessibility-clickable.
        # Use that normal UI path, then accept only an explicit Open/Select
        # control and still require the picker Activity to return to Canyua.
        current = dump("picker-before-preview")
        preview = [
            r for r in rows(current)
            if r["resource_id"].endswith("/preview_icon")
            and target_name.lower() in r["desc"].lower()
            and r["clickable"] == "true"
        ]
        if preview and tap_row(preview[0]):
            time.sleep(1.5)
            preview_root = dump("picker-preview")
            preview_rows = rows(preview_root)
            (out/"picker-preview.json").write_text(
                json.dumps(preview_rows,indent=2,ensure_ascii=False)+"\\n"
            )
            labels = {"open","select","choose","use this file","done"}
            actions = [
                r for r in preview_rows
                if r["clickable"] == "true"
                and (
                    r["text"].strip().lower() in labels
                    or r["desc"].strip().lower() in labels
                )
            ]
            for idx, action in enumerate(actions[:4]):
                if tap_row(action) and wait_picker_return(f"picker-preview-action-{idx:02d}"):
                    print("selected-and-returned-via-preview", target_name)
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
proc = subprocess.run(
    ["adb","shell","find","/sdcard","-type","f","-iname","*.pub"],
    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
)
rows=[]
seen=set()
for line in proc.stdout.splitlines():
    path=line.strip()
    if not path or path in seen:
        continue
    seen.add(path)
    pulled=subprocess.run(
        ["adb","exec-out","cat",path],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    if pulled.returncode != 0:
        rows.append({"path":path,"sha256":None,"bytes":None,"readable":False})
        continue
    data=pulled.stdout
    rows.append({
        "path":path,
        "sha256":hashlib.sha256(data).hexdigest(),
        "bytes":len(data),
        "readable":True,
    })
out.write_text(json.dumps(rows,indent=2,ensure_ascii=False)+"\n")
PY
}

capture_changed_pub() {
  python3 - <<'PY'
from __future__ import annotations
import json
import subprocess
from pathlib import Path

out=Path("work/canyua-3127")
bundle=out/"oracle-bundle"
before={r["path"]:r for r in json.loads((out/"pubs-before.json").read_text())}
after=json.loads((out/"pubs-after.json").read_text())
changes=[]
for row in after:
    old=before.get(row["path"])
    if old is None:
        changes.append({"kind":"added","before":None,"after":row})
    elif old.get("sha256") != row.get("sha256"):
        changes.append({"kind":"changed","before":old,"after":row})
(out/"pub-changes.json").write_text(json.dumps(changes,indent=2,ensure_ascii=False)+"\n")
if not changes:
    raise SystemExit(0)

# Prefer a changed/added PUB other than the immutable ingress fixture.
candidates=[c for c in changes if c["after"]["path"] != "/sdcard/Download/CanyuaOracleSample.pub"]
pick=candidates[0] if candidates else changes[0]
remote=pick["after"]["path"]
subprocess.run(["adb","pull",remote,str(bundle/"resave-control.pub")],check=True)
(out/"selected-output.json").write_text(
    json.dumps({"remote":remote,"change":pick},indent=2,ensure_ascii=False)+"\n"
)
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
adb shell am broadcast \
  -a android.intent.action.MEDIA_SCANNER_SCAN_FILE \
  -d file:///sdcard/Download/CanyuaOracleSample.pub \
  >/dev/null 2>&1 || true
sleep 2
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

URI='file:///sdcard/Download/CanyuaOracleSample.pub'
adb logcat -c || true
adb shell am force-stop "$PKG" || true
adb shell am start -W   -n "$MAIN"   -a android.intent.action.VIEW   -d "$URI"   -t application/x-mspublisher   > "$OUT/open-pub.txt" 2>&1 || true
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
  echo "=== retry through shipped in-app ACTION_OPEN_DOCUMENT path ==="
  adb shell am force-stop "$PKG" || true
  adb shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1     > "$OUT/picker-bootstrap-launch.txt" 2>&1 || true
  sleep 4

  set +e
  click_common_dialogs
  picker_common_rc=$?
  set -e
  if [ "$picker_common_rc" -eq 42 ]; then
    printf 'purchase_surface_observed_before_picker\n' | tee "$OUT/status.txt"
    capture "picker-purchase"
    exit 0
  fi

  set +e
  open_via_system_picker > "$OUT/picker-open.txt" 2> "$OUT/picker-open.stderr"
  picker_rc=$?
  set -e
  if [ "$picker_rc" -ne 0 ]; then
    printf 'system_picker_ingress_failed_%s\n' "$picker_rc" | tee "$OUT/status.txt"
    capture "picker-failed"
    exit 0
  fi

  sleep 12
  set +e
  click_common_dialogs
  picker_common_rc=$?
  set -e
  if [ "$picker_common_rc" -eq 42 ]; then
    printf 'purchase_surface_observed_after_picker_open\n' | tee "$OUT/status.txt"
    capture "picker-open-purchase"
    exit 0
  fi

  capture "open-picker"
  if ui_has_purchase_surface "$OUT/open-picker-ui.xml"; then
    printf 'purchase_surface_observed_after_picker_open\n' | tee "$OUT/status.txt"
    exit 0
  fi

  if ! grep -Eqi 'EditActivity|PageFragment'       "$OUT/open-picker-activity.txt" "$OUT/open-picker-activity-top.txt" 2>/dev/null; then
    printf 'editor_surface_not_proven_after_picker\n' | tee "$OUT/status.txt"
    exit 0
  fi
fi

snapshot_pubs "$OUT/pubs-before.json"

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
snapshot_pubs "$OUT/pubs-after.json"
capture_changed_pub || true

if [ -f "$BUNDLE/resave-control.pub" ]; then
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
    printf 'save_completed_output_byte_identical\n' | tee "$OUT/status.txt"
  else
    printf 'resave_control_captured\n' | tee "$OUT/status.txt"
  fi
else
  printf 'save_clicked_but_no_changed_pub_found\n' | tee "$OUT/status.txt"
fi

adb shell settings put global airplane_mode_on 0 || true
adb shell am broadcast -a android.intent.action.AIRPLANE_MODE --ez state false >/dev/null 2>&1 || true
adb shell svc wifi enable || true
