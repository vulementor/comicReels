"""Read-only installed UI acceptance: real saved clip; never approve or publish."""
import argparse
import json
import sys
import time
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument('--root',type=Path,default=Path('D:/StableApp/ThoRemix'))
parser.add_argument('--job-id')
args=parser.parse_args()
sys.path.insert(0,str(args.root/'source'))
from PIL import ImageGrab
from agent.thoremix.config import Settings
from agent.thoremix.desktop import DesktopWindow

app=DesktopWindow(Settings.load(args.root),poll=False)
evidence=args.root/'data/verification';evidence.mkdir(parents=True,exist_ok=True)

def pump(seconds):
    until=time.monotonic()+seconds
    while time.monotonic()<until:app.window.update();time.sleep(.01)

def capture(window,name):
    window.lift();window.focus_force();pump(.3)
    x,y=window.winfo_rootx(),window.winfo_rooty()
    ImageGrab.grab(bbox=(x,y,x+window.winfo_width(),y+window.winfo_height())).save(evidence/name)

try:
    pump(.5)
    capture(app.window,'finishing-desktop.png')
    row=next(r for r in app.snapshot['rows'] if r.get('video') and r['manifest'].get('finishing')
             and r['manifest'].get('review',{}).get('status')=='pending'
             and (not args.job_id or r.get('job_id')==args.job_id))
    app.open_review(row);review=app.review;pump(1)
    assert review.frame_count>0 and review.player.get_pause()
    review.toggle();pump(1)
    assert review.position>.5 and review.frame_count>10
    review.toggle();position=review.position;pump(.2)
    assert abs(review.position-position)<.08
    review.seek.set(8);review._seek_release();pump(.6)
    assert review.position>7.8 and review.player.get_pause()
    capture(review.window,'finishing-review.png')
    receipt={'job_id':row['job_id'],'video':str(row['video']),'frame_count':review.frame_count,
        'seek_position':review.position,'embedded_play_pause_seek':True,'approval_invoked':False,
        'finishing':row['manifest']['finishing']}
    review.close()
    app.show_page('settings');pump(.3);capture(app.window,'finishing-settings.png')
    (evidence/'finishing-review.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'verified':True,'job_id':row['job_id'],'frames':receipt['frame_count']}))
finally:app.quit()
