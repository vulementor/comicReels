import time
import tkinter as tk
from pathlib import Path
import subprocess

from agent.thoremix.config import Settings
from agent.thoremix.core import media_tool
from agent.thoremix.desktop import DesktopWindow


def test_embedded_review_plays_pauses_seeks_and_closes_without_an_approval(tmp_path):
    settings=Settings(root=str(tmp_path/'app'),input_dir=str(tmp_path/'input'))
    video=tmp_path/'preview.mp4'
    subprocess.run([media_tool('ffmpeg',settings.directory),'-nostdin','-v','error','-y',
        '-f','lavfi','-i','testsrc2=s=120x240:r=24:d=3','-f','lavfi','-i','anullsrc=r=44100:cl=mono',
        '-t','3','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(video)],check=True,capture_output=True)
    root=tk.Tk();root.withdraw();app=DesktopWindow(settings,window=root,poll=False)
    row={'key':'one','title':'Thỏ Remix · kiểm tra review','state':'Chờ duyệt','video':video,
         'manifest':{'video_sha256':'a'*64,'media':{'width':120,'height':240,'duration_s':3},'review':{'status':'pending'}},
         'folder':tmp_path,'job_id':'b'*32,'original':None,'frames':[],'qa_issues':['Nhận xét thử.'],'caption':'Nội dung thử.'}
    def pump(seconds):
        end=time.monotonic()+seconds
        while time.monotonic()<end:root.update();time.sleep(.01)
    try:
        app.open_review(row);review=app.review;pump(.7)
        assert review.frame_count>=1 and review.player.get_pause() is True
        review.toggle();pump(.7)
        assert review.position>.35 and review.frame_count>8
        review.toggle();before=review.position;pump(.2)
        assert abs(review.position-before)<.08
        review.seek.set(1.6);review._seek_release();pump(.5)
        assert review.position>1.4 and review.player.get_pause() is True
        review.toggle_mute();assert review.muted
        assert review.approve.winfo_y()>=0 and str(review.approve.cget('state'))=='normal'
        app.launch=lambda *args:False
        review.request_approval()
        assert review.approval_requested is False and str(review.approve.cget('state'))=='normal'
        assert 'thử lại' in review.feedback.cget('text')
        assert not settings.data.exists()
        app.snapshot['rows']=[dict(row,manifest=dict(row['manifest'],caption='Caption mới'))]
        review.sync()
        assert review.invalidated and str(review.approve.cget('state'))=='disabled'
        review.close();assert app.review is None and review.player is None
    finally:app.quit()
