#!/usr/bin/env bash
set -euo pipefail

PKG="com.canyua.publisherexpert"
OUT="${GITHUB_WORKSPACE:-$PWD}/work/canyua-new-save"
APK="${GITHUB_WORKSPACE:-$PWD}/work/canyua-3.1.27.apk"
mkdir -p "$OUT" "$OUT/output"

capture() {
  local label="$1"
  adb shell dumpsys activity activities > "$OUT/$label-activity.txt" 2>&1 || true
  adb shell dumpsys activity top > "$OUT/$label-activity-top.txt" 2>&1 || true
  adb shell uiautomator dump /sdcard/window.xml >/dev/null 2>&1 || true
  adb pull /sdcard/window.xml "$OUT/$label-ui.xml" >/dev/null 2>&1 || true
  adb exec-out screencap -p > "$OUT/$label.png" 2>/dev/null || true
  adb logcat -d -v threadtime > "$OUT/$label-logcat.txt" 2>&1 || true
}

ui_has_purchase() {
  local xml="$1"
  [ -f "$xml" ] || return 1
  grep -Eqi 'purchase|purchases|buy|unlock|subscription|subscribe|payment|upgrade|document converter|in-app' "$xml"
}

wait_editor() {
  for _ in $(seq 1 30); do
    if adb shell dumpsys activity activities 2>/dev/null | grep -Eq 'mResumedActivity:.*com\.canyua\.publisherexpert/.+EditActivity'; then
      return 0
    fi
    sleep 1
  done
  return 1
}

tap_resource() {
  local wanted="$1"
  python3 - "$wanted" <<'PY'
import re, subprocess, sys, time, xml.etree.ElementTree as ET
wanted=sys.argv[1]
subprocess.run(["adb","shell","uiautomator","dump","/sdcard/window.xml"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
subprocess.run(["adb","pull","/sdcard/window.xml","/tmp/window.xml"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
root=ET.parse("/tmp/window.xml").getroot()
hits=[]
for n in root.iter("node"):
    if (n.attrib.get("resource-id") or "") != wanted:
        continue
    m=re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',n.attrib.get("bounds",""))
    if m:
        hits.append((n,m))
if len(hits)!=1:
    print(f"expected one {wanted}, got {len(hits)}",file=sys.stderr)
    raise SystemExit(2)
n,m=hits[0]
x1,y1,x2,y2=map(int,m.groups())
subprocess.run(["adb","shell","input","tap",str((x1+x2)//2),str((y1+y2)//2)],check=True)
time.sleep(1.5)
PY
}

accept_new_document_dialog() {
  python3 <<'PY'
import json,re,subprocess,sys,time,xml.etree.ElementTree as ET
from pathlib import Path
out=Path("work/canyua-new-save")
subprocess.run(["adb","shell","uiautomator","dump","/sdcard/window.xml"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
subprocess.run(["adb","pull","/sdcard/window.xml",str(out/"new-dialog.xml")],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
xml_path=out/"new-dialog.xml"
if (not xml_path.exists()) or xml_path.stat().st_size == 0:
    # On the API-30 Google image this legacy modal sometimes produces an empty
    # uiautomator dump even though the visible dialog is stable. Use the
    # positive-button location in the same fixed emulator viewport, then rely
    # on the independent EditActivity proof below before treating New as open.
    wm=subprocess.run(["adb","shell","wm","size"],stdout=subprocess.PIPE,text=True).stdout
    m=re.search(r'(\d+)x(\d+)',wm)
    if not m:
        print("cannot resolve emulator viewport",file=sys.stderr)
        raise SystemExit(43)
    w,h=map(int,m.groups())
    x=int(w*0.82)
    y=int(h*0.66)
    (out/"new-positive-fallback.json").write_text(
        json.dumps({"mode":"viewport_fraction","x":x,"y":y,"width":w,"height":h},indent=2)+"\\n"
    )
    subprocess.run(["adb","shell","input","tap",str(x),str(y)],check=True)
    time.sleep(2)
    raise SystemExit(0)
root=ET.parse(xml_path).getroot()
rows=[]
blocked=re.compile(r'purchase|buy|unlock|subscription|subscribe|payment|upgrade|in-app',re.I)
for n in root.iter("node"):
    row={k:n.attrib.get(k,"") for k in ["text","content-desc","resource-id","bounds","clickable","class"]}
    rows.append(row)
(out/"new-dialog.json").write_text(json.dumps(rows,indent=2,ensure_ascii=False)+"\n")
labels=[(r["text"] or r["content-desc"]).strip() for r in rows]
if any(blocked.search(x) for x in labels if x):
    print("purchase surface in new-document dialog",file=sys.stderr)
    raise SystemExit(42)

# The shipped paper-size dialog uses the standard positive AlertDialog button.
# Do not modify any paper settings: accept the app's default selected size.
hits=[]
for r in rows:
    rid=r["resource-id"]
    label=(r["text"] or r["content-desc"]).strip().lower()
    if rid=="android:id/button1" or (r["clickable"]=="true" and label in {"ok","create","new","done"}):
        m=re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',r["bounds"])
        if m:
            hits.append((r,m))
# Prefer the canonical positive button if present.
canonical=[x for x in hits if x[0]["resource-id"]=="android:id/button1"]
if canonical:
    hits=canonical
if len(hits)!=1:
    print("positive new-document control not unique",len(hits),file=sys.stderr)
    raise SystemExit(43)
r,m=hits[0]
(out/"new-positive-control.json").write_text(json.dumps(r,indent=2,ensure_ascii=False)+"\n")
x1,y1,x2,y2=map(int,m.groups())
subprocess.run(["adb","shell","input","tap",str((x1+x2)//2),str((y1+y2)//2)],check=True)
time.sleep(2)
PY
}

click_exact_save() {
  python3 <<'PY'
import json,re,subprocess,sys,time,xml.etree.ElementTree as ET
from pathlib import Path
out=Path("work/canyua-new-save")
blocked=re.compile(r'purchase|buy|unlock|subscription|subscribe|payment|upgrade|document converter|in-app',re.I)

def dump(tag):
    subprocess.run(["adb","shell","uiautomator","dump","/sdcard/window.xml"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    p=out/f"{tag}.xml"
    subprocess.run(["adb","pull","/sdcard/window.xml",str(p)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    return ET.parse(p).getroot()

def rows(root):
    rr=[]
    for n in root.iter("node"):
        rr.append({
            "text":(n.attrib.get("text") or "").strip(),
            "desc":(n.attrib.get("content-desc") or "").strip(),
            "resource_id":(n.attrib.get("resource-id") or "").strip(),
            "bounds":n.attrib.get("bounds",""),
            "clickable":n.attrib.get("clickable",""),
        })
    return rr

def hits(rr):
    if any(blocked.search((r["text"] or r["desc"])) for r in rr if (r["text"] or r["desc"])):
        raise SystemExit(42)
    out_hits=[]
    for r in rr:
        label=(r["text"] or r["desc"]).strip().lower()
        rid=r["resource_id"].lower()
        if label=="save" or (not label and re.search(r'(^|[/_:])save$',rid)):
            if re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',r["bounds"]):
                out_hits.append(r)
    return out_hits

rr=rows(dump("save-search-initial"))
hs=hits(rr)
if len(hs)!=1:
    file_controls=[
        r for r in rr
        if r["resource_id"]=="com.canyua.publisherexpert:id/title_file_imageButton"
    ]
    if len(file_controls)==1:
        m=re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',file_controls[0]["bounds"])
        if m:
            x1,y1,x2,y2=map(int,m.groups())
            subprocess.run(["adb","shell","input","tap",str((x1+x2)//2),str((y1+y2)//2)],check=True)
            time.sleep(1)
            rr=rows(dump("save-search-file-popup"))
            hs=hits(rr)
if len(hs)!=1:
    subprocess.run(["adb","shell","input","keyevent","82"],check=False)
    time.sleep(1)
    rr=rows(dump("save-search-menu"))
    hs=hits(rr)
if len(hs)!=1:
    print("need one unambiguous Save, found",len(hs),file=sys.stderr)
    raise SystemExit(44)
h=hs[0]
(out/"save-control.json").write_text(json.dumps(h,indent=2,ensure_ascii=False)+"\n")
m=re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',h["bounds"])
x1,y1,x2,y2=map(int,m.groups())
subprocess.run(["adb","shell","input","tap",str((x1+x2)//2),str((y1+y2)//2)],check=True)
PY
}

snapshot_pubs() {
  local dst="$1"
  python3 - "$dst" <<'PY'
import hashlib,json,subprocess,sys
from pathlib import Path
dst=Path(sys.argv[1])
proc=subprocess.run(["adb","shell","find","/sdcard","-type","f","-iname","*.pub"],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)
rows=[]
for p in sorted(set(x.strip() for x in proc.stdout.splitlines() if x.strip())):
    cat=subprocess.run(["adb","exec-out","cat",p],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    rows.append({
        "path":p,
        "readable":cat.returncode==0,
        "bytes":len(cat.stdout) if cat.returncode==0 else None,
        "sha256":hashlib.sha256(cat.stdout).hexdigest() if cat.returncode==0 else None,
    })
dst.write_text(json.dumps(rows,indent=2,ensure_ascii=False)+"\n")
PY
}

capture_new_pub() {
  python3 <<'PY'
import json,subprocess
from pathlib import Path
root=Path("work/canyua-new-save")
before={r["path"]:r for r in json.loads((root/"pubs-before-save.json").read_text())}
after=json.loads((root/"pubs-after-save.json").read_text())
changes=[]
for r in after:
    old=before.get(r["path"])
    if old is None:
        changes.append({"kind":"added","before":None,"after":r})
    elif old.get("sha256")!=r.get("sha256"):
        changes.append({"kind":"changed","before":old,"after":r})
(root/"pub-changes.json").write_text(json.dumps(changes,indent=2,ensure_ascii=False)+"\n")
if not changes:
    raise SystemExit(0)
# Prefer Untitled and then any newly added PUB.
cands=sorted(changes,key=lambda c:(0 if "untitled" in c["after"]["path"].lower() else 1,0 if c["kind"]=="added" else 1))
pick=cands[0]
remote=pick["after"]["path"]
subprocess.run(["adb","pull",remote,str(root/"output"/"new-save.pub")],check=True)
(root/"selected-output.json").write_text(json.dumps({"remote":remote,"change":pick},indent=2,ensure_ascii=False)+"\n")
PY
}


export_saved_via_app_share() {
  python3 <<'PY'
import json,re,subprocess,time,xml.etree.ElementTree as ET
from pathlib import Path

out=Path("work/canyua-new-save")
pkg="com.canyua.publisherexpert"

def dump(tag):
    subprocess.run(["adb","shell","uiautomator","dump","/sdcard/window.xml"],
                   stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    p=out/f"{tag}.xml"
    subprocess.run(["adb","pull","/sdcard/window.xml",str(p)],
                   stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    if not p.exists() or p.stat().st_size == 0:
        return []
    try:
        root=ET.parse(p).getroot()
    except Exception:
        return []
    rows=[]
    for n in root.iter("node"):
        rows.append({
            "text":(n.attrib.get("text") or "").strip(),
            "desc":(n.attrib.get("content-desc") or "").strip(),
            "rid":(n.attrib.get("resource-id") or "").strip(),
            "bounds":n.attrib.get("bounds",""),
            "clickable":n.attrib.get("clickable",""),
        })
    (out/f"{tag}.json").write_text(json.dumps(rows,indent=2,ensure_ascii=False)+"\n")
    return rows

def tap_row(r):
    m=re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',r.get("bounds",""))
    if not m:
        return False
    x1,y1,x2,y2=map(int,m.groups())
    subprocess.run(["adb","shell","input","tap",str((x1+x2)//2),str((y1+y2)//2)],check=True)
    time.sleep(1.5)
    return True

def resumed(fragment):
    p=subprocess.run(["adb","shell","dumpsys","activity","activities"],
                     stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)
    # A matching activity anywhere in the task/back stack is not enough.
    # Accept only the activity Android reports as currently resumed.
    for line in p.stdout.splitlines():
        if ("mResumedActivity:" in line or "topResumedActivity=" in line) and fragment in line:
            return True
    return False

# Leave the already-saved editor through the shipped Back control.
rows=dump("share-editor")
backs=[r for r in rows if r["rid"]==f"{pkg}:id/title_back_imageButton"]
if len(backs)!=1 or not tap_row(backs[0]):
    raise SystemExit(51)

# A new document can still present the app's normal "Save / Don't Save / Cancel"
# close dialog even after the explicit Save menu action. We must not invoke a
# second serializer here: choose the explicit DON'T SAVE action only as an exit
# policy, then copy out whatever the first Save actually persisted.
time.sleep(1)
if not resumed(f"{pkg}/.MainActivity"):
    rows=dump("share-back-result")
    labels=[(r["text"] or r["desc"]).strip() for r in rows]
    is_save_prompt=any(
        "do you want to save changes" in label.lower()
        for label in labels if label
    )
    if is_save_prompt:
        dont=[
            r for r in rows
            if (r["text"] or r["desc"]).strip().lower().replace("’","'")=="don't save"
            and r["clickable"]=="true"
        ]
        if len(dont)!=1 or not tap_row(dont[0]):
            raise SystemExit(58)
        (out/"share-exit-policy.json").write_text(json.dumps({
            "reason":"close dialog remained after explicit Save",
            "action":"DON'T SAVE",
            "writer_invocations_added":0,
        },indent=2,ensure_ascii=False)+"\n")

for _ in range(20):
    if resumed(f"{pkg}/.MainActivity"):
        break
    time.sleep(1)
else:
    dump("share-return-main-failed")
    raise SystemExit(52)

# Select the just-created document in MainActivity.
rows=dump("share-main")
titles=[r for r in rows if r["text"].lower() in {"untitled","untitled.pub"}]
if not titles:
    # Be tolerant of UI decoration around the document name, but never choose
    # an unrelated document.
    titles=[r for r in rows if "untitled" in r["text"].lower()]
if len(titles)!=1 or not tap_row(titles[0]):
    raise SystemExit(53)

rows=dump("share-main-selected")
share=[r for r in rows if r["rid"]==f"{pkg}:id/doc_share"]
if len(share)!=1 or not tap_row(share[0]):
    raise SystemExit(54)

# MainActivity.shareDocument() uses normal ACTION_CREATE_DOCUMENT requestCode=2.
for _ in range(20):
    if resumed("com.google.android.documentsui"):
        break
    time.sleep(1)
else:
    dump("share-create-document-not-open")
    raise SystemExit(55)

rows=dump("share-create-document")
roots=[r for r in rows if (r["desc"].lower()=="show roots" or r["text"].lower()=="show roots")]
if len(roots)==1:
    tap_row(roots[0])
    rows=dump("share-roots")
    downloads=[r for r in rows if r["text"].strip().lower()=="downloads"]
    if downloads:
        tap_row(downloads[0])
        rows=dump("share-downloads")

# Accept the app-provided Untitled.pub name in Downloads.
save_labels={"save","create","done","use this folder","select"}
save=[]
for r in rows:
    label=(r["text"] or r["desc"]).strip().lower()
    rid=r["rid"].lower()
    if label in save_labels or rid.endswith("action_menu_save"):
        if re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',r["bounds"]):
            save.append(r)
if not save:
    # Some DocumentsUI builds only expose the action after a short settle.
    time.sleep(1)
    rows=dump("share-downloads-settled")
    for r in rows:
        label=(r["text"] or r["desc"]).strip().lower()
        rid=r["rid"].lower()
        if label in save_labels or rid.endswith("action_menu_save"):
            if re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',r["bounds"]):
                save.append(r)
if len(save)!=1 or not tap_row(save[0]):
    raise SystemExit(56)

# If an existing filename collision appears, use the explicit normal replace action.
time.sleep(1)
rows=dump("share-after-save-action")
replace=[r for r in rows if (r["text"] or r["desc"]).strip().lower() in {"replace","overwrite"}]
if len(replace)==1:
    tap_row(replace[0])

for _ in range(20):
    if resumed(f"{pkg}/.MainActivity"):
        break
    time.sleep(1)

# The CREATE_DOCUMENT copy is now externally readable; pull the exact result.
proc=subprocess.run(
    ["adb","shell","find","/sdcard/Download","-maxdepth","1","-type","f","-iname","Untitled*.pub"],
    stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True
)
cands=[x.strip() for x in proc.stdout.splitlines() if x.strip()]
if not cands:
    dump("share-output-not-found")
    raise SystemExit(57)
remote=sorted(cands)[-1]
subprocess.run(["adb","pull",remote,str(out/"output"/"new-save.pub")],check=True)
(out/"selected-output.json").write_text(json.dumps({
    "remote":remote,
    "capture_method":"normal MainActivity Share -> ACTION_CREATE_DOCUMENT after ordinary Save",
},indent=2,ensure_ascii=False)+"\n")
PY
}

echo "=== device ==="
adb shell getprop ro.product.cpu.abilist | tee "$OUT/abilist.txt"
echo "native_bridge=$(adb shell getprop ro.dalvik.vm.native.bridge || true)" | tee "$OUT/native-bridge.txt"

echo "=== install pinned 3.1.27 ==="
adb install -r "$APK" | tee "$OUT/install.txt"
for perm in android.permission.READ_EXTERNAL_STORAGE android.permission.WRITE_EXTERNAL_STORAGE; do
  adb shell pm grant "$PKG" "$perm" 2>/dev/null || true
done

echo "=== offline normal launch ==="
adb shell settings put global airplane_mode_on 1 || true
adb shell svc wifi disable || true
adb shell svc data disable || true
adb logcat -c || true
adb shell am force-stop "$PKG" || true
adb shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 > "$OUT/launch.txt" 2>&1 || true
sleep 5
capture bootstrap
if ui_has_purchase "$OUT/bootstrap-ui.xml"; then
  echo purchase_surface_before_new > "$OUT/status.txt"
  exit 0
fi

echo "=== normal New document ==="
set +e
tap_resource "com.canyua.publisherexpert:id/menu_new"
new_rc=$?
set -e
if [ "$new_rc" -ne 0 ]; then
  echo new_control_not_found > "$OUT/status.txt"
  capture new-control-failed
  exit 0
fi
capture new-dialog
set +e
accept_new_document_dialog
new_rc=$?
set -e
if [ "$new_rc" -eq 42 ]; then
  echo purchase_surface_during_new > "$OUT/status.txt"
  capture new-purchase
  exit 0
elif [ "$new_rc" -ne 0 ]; then
  echo new_dialog_not_unambiguous > "$OUT/status.txt"
  capture new-dialog-failed
  exit 0
fi

if ! wait_editor; then
  echo editor_surface_not_proven_after_new > "$OUT/status.txt"
  capture after-new-no-editor
  exit 0
fi
sleep 4
capture editor
if ui_has_purchase "$OUT/editor-ui.xml"; then
  echo purchase_surface_after_new > "$OUT/status.txt"
  exit 0
fi

snapshot_pubs "$OUT/pubs-before-save.json"

echo "=== one ordinary Save ==="
set +e
click_exact_save > "$OUT/save-click.txt" 2> "$OUT/save-click.stderr"
save_rc=$?
set -e
if [ "$save_rc" -eq 42 ]; then
  echo purchase_surface_before_save > "$OUT/status.txt"
  capture save-purchase-before
  exit 0
elif [ "$save_rc" -ne 0 ]; then
  echo save_control_not_unambiguous > "$OUT/status.txt"
  capture save-control-failed
  exit 0
fi
sleep 12
capture post-save
if ui_has_purchase "$OUT/post-save-ui.xml"; then
  echo purchase_surface_after_save > "$OUT/status.txt"
  exit 0
fi

snapshot_pubs "$OUT/pubs-after-save.json"
capture_new_pub || true

# Canyua's My Documents path can be app-owned on modern Android, so a valid
# ordinary Save may not appear under /sdcard. If direct external inventory did
# not see it, use the app's own normal Share -> ACTION_CREATE_DOCUMENT flow to
# copy the already-saved Untitled.pub into Downloads. This does not invoke a
# second writer path and does not modify entitlement/protection state.
if [ ! -f "$OUT/output/new-save.pub" ]; then
  set +e
  export_saved_via_app_share > "$OUT/share-capture.stdout" 2> "$OUT/share-capture.stderr"
  share_rc=$?
  set -e
  printf '%s\n' "$share_rc" > "$OUT/share-capture.rc"
  capture share-capture-final
fi

if [ -f "$OUT/output/new-save.pub" ]; then
  python3 - <<'PY'
from pathlib import Path
p=Path("work/canyua-new-save/output/new-save.pub")
if p.read_bytes()[:8] != bytes.fromhex("d0cf11e0a1b11ae1"):
    raise SystemExit("new-save output is not CFB/OLE")
PY
  sha256sum "$OUT/output/new-save.pub" > "$OUT/output/new-save.sha256"
  echo new_pub_captured > "$OUT/status.txt"
else
  echo save_clicked_but_no_changed_pub_found > "$OUT/status.txt"
fi
