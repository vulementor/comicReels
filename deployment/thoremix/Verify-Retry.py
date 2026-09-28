"""Installed retry-button acceptance at the reached daily quota; no generation."""
import argparse
import hashlib
import json
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

parser=argparse.ArgumentParser()
parser.add_argument('--root',type=Path,default=Path('D:/StableApp/ThoRemix'))
parser.add_argument('--job-id',required=True)
args=parser.parse_args();sys.path.insert(0,str(args.root/'source'))
from PIL import ImageGrab
from agent.thoremix.config import Settings
from agent.thoremix.desktop import DesktopWindow
s=Settings.load(args.root);day=datetime.now(ZoneInfo(s.timezone)).date().isoformat()
with sqlite3.connect((s.data/'campaign.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
    count=db.execute("SELECT count(*) FROM production_attempts WHERE status='complete' AND completed_day=?",(day,)).fetchone()[0]
assert s.enabled and count>=s.daily_production_limit,'This probe must not generate a clip.'
stage=s.data/'production'/args.job_id/'analysis.json';original=stage.read_bytes()
app=DesktopWindow(s);evidence=s.data/'verification';evidence.mkdir(exist_ok=True)

def pump(seconds):
    until=time.monotonic()+seconds
    while time.monotonic()<until:app.window.update();time.sleep(.01)

def capture(name):
    app.window.lift();app.window.focus_force();pump(.25)
    x,y=app.window.winfo_rootx(),app.window.winfo_rooty()
    ImageGrab.grab(bbox=(x,y,x+app.window.winfo_width(),y+app.window.winfo_height())).save(evidence/name)

try:
    row=next(r for r in app.snapshot['rows'] if r.get('job_id')==args.job_id)
    app.selected=row['key'];app.refresh();pump(.4);capture('retry-before.png')
    app.retry_button.invoke()
    assert str(app.retry_button.cget('state'))=='disabled'
    until=time.monotonic()+20
    while app.active is not None and time.monotonic()<until:pump(.1)
    assert app.active is None and 'hạn mức' in app.retry_feedback[args.job_id]
    assert stage.read_bytes()==original and str(app.retry_button.cget('state'))=='normal'
    capture('retry-after.png')
    result={'job_id':args.job_id,'button_invoked':True,'pressed_disabled':True,'result':app.retry_feedback[args.job_id],
        'original_receipt_unchanged':True,'daily_completed':count,'generation_started':False}
    (evidence/'retry.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
finally:app.quit()
