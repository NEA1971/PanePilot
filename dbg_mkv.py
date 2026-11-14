import os, shutil, subprocess, sys, tempfile
sys.path.insert(0, "src")
os.environ["TZ"] = "Europe/Berlin"
from panepilot import tags as tg, videotags as vt
orig_run = vt._run
def run(args, timeout=60, binary=False):
    p = orig_run(args, timeout, binary)
    if "mkvpropedit" in args[0]:
        print("RUN", args[2:], "->", p.returncode, (p.stdout or "")[-300:], (p.stderr or "")[-300:])
    return p
vt._run = run
d = tempfile.mkdtemp(); path = os.path.join(d, "clip.mkv"); shutil.copy("tests/data/video/clip.mkv", path)
def info(label):
    print("==", label); print(subprocess.run(["mkvinfo", path], capture_output=True, text=True).stdout)
info("start")
rec = tg.read_file(path); snap = tg.snapshot(path, True); print(snap[2][1])
pic = tg.Picture(open("docs/screenshots/ftp.png", "rb").read(), "image/png")
rec = tg.write_file(rec, {"title": "Abend", "author": "Bob", "genre": "Urlaub", "x:ORT": "Cebu", "datetaken": "2026-07-01 10:00:00"}, [pic])
info("after write1"); print(rec.fields, [p.desc for p in rec.pictures])
rec = tg.write_file(rec, {"genre": None}, [])
info("after write2")
try:
    tg.restore(path, snap)
except Exception as e:
    print("RESTORE FAILED", e)
    p = orig_run(["mkvpropedit", path, "--edit", "info", "--set", "title=Strand"]); print("title only", p.returncode, p.stdout[-300:])
    p = orig_run(["mkvpropedit", path, "--tags", "all:"]); print("tags clear", p.returncode, p.stdout[-300:])
info("end")
