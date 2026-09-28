"""Local video review surface; one player, no browser and no implicit approval."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk

INK='#1c2940';MUTED='#647189';ACCENT='#6550bb';BG='#f4f6fa'


def review_note(value):
    if isinstance(value,str) and re.fullmatch(r'[A-Z][A-Z0-9_]+',value):
        return 'Chưa có kết quả kiểm tra tự động ở bước này. Anh xem lại clip trước khi duyệt; mã chi tiết được giữ trong hồ sơ.'
    return str(value)


class ReviewWindow:
    def __init__(self, app, row):
        from .quality import manifest_digest
        self.app=app;self.row=row;self.player=None;self.timer=None;self.alive=True
        self.reviewed_digest=manifest_digest(row['manifest']);self.invalidated=False
        self.first_frame=True;self.preview_target=0.;self.playing=False;self.ended=False;self.muted=False
        self.position=0.;self.duration=float(row['manifest'].get('media',{}).get('duration_s',10))
        self.dragging=False;self.photos=[];self.frame_count=0;self.approval_requested=False
        self.window=tk.Toplevel(app.window);self.window.title('Thỏ Remix · Xem & duyệt clip')
        self.window.configure(bg=BG);self.window.geometry('1080x800');self.window.minsize(920,680)
        self.window.protocol('WM_DELETE_WINDOW',self.close)
        header=tk.Frame(self.window,bg=BG,padx=24,pady=16);header.pack(fill='x')
        app.label(header,'THỎ REMIX',bold=True,size=12,color=ACCENT).pack(anchor='w')
        app.label(header,row['title'],bold=True,size=17,wraplength=970).pack(anchor='w',pady=(6,0))
        self.state=app.label(header,row['state'],color=MUTED,size=10);self.state.pack(anchor='w',pady=(5,0))
        footer=tk.Frame(self.window,bg='white',padx=24,pady=14);footer.pack(side='bottom',fill='x')
        self.feedback=app.label(footer,'Xem clip và nhận xét trước khi duyệt.',color=MUTED,wraplength=520)
        self.feedback.pack(side='left',fill='x',expand=True)
        self.approve=app.button(footer,'Duyệt clip để đăng',self.request_approval,primary=True)
        self.approve.pack(side='right',padx=(12,0))
        app.button(footer,'Đóng',self.close).pack(side='right')
        body=tk.Frame(self.window,bg=BG);body.pack(fill='both',expand=True,padx=24,pady=(0,18))
        body.columnconfigure(0,weight=3,uniform='review');body.columnconfigure(1,weight=2,uniform='review');body.rowconfigure(0,weight=1)
        media=tk.Frame(body,bg='#111820');media.grid(row=0,column=0,sticky='nsew',padx=(0,20))
        controls=tk.Frame(media,bg='#111820',padx=12,pady=10);controls.pack(side='bottom',fill='x')
        self.seek=tk.Scale(controls,from_=0,to=self.duration,resolution=.01,orient='horizontal',
            showvalue=False,bg='#111820',fg='white',highlightthickness=0,bd=0,troughcolor='#344052',
            activebackground=ACCENT,command=self._seek_change)
        self.seek.pack(fill='x');self.seek.bind('<ButtonPress-1>',lambda e:setattr(self,'dragging',True))
        self.seek.bind('<ButtonRelease-1>',self._seek_release)
        buttons=tk.Frame(controls,bg='#111820');buttons.pack(fill='x',pady=(4,0))
        self.play=app.button(buttons,'▶ Phát',self.toggle,primary=True);self.play.pack(side='left')
        self.sound=app.button(buttons,'Âm thanh: bật',self.toggle_mute);self.sound.pack(side='left',padx=8)
        self.clock=app.label(buttons,'0:00 / 0:10',color='#e3e8f1',size=10);self.clock.pack(side='right')
        self.canvas=tk.Canvas(media,bg='#111820',highlightthickness=0);self.canvas.pack(fill='both',expand=True)
        self.canvas.create_text(180,160,text='Đang mở video…',fill='#aeb9c9',tags='placeholder')
        self.canvas.bind('<Button-1>',lambda _:self.toggle())
        self.window.bind('<space>',self._space)
        context=tk.Frame(body,bg='white',padx=16,pady=16);context.grid(row=0,column=1,sticky='nsew')
        app.label(context,'Chi tiết clip',bold=True,size=14).pack(anchor='w')
        meta=row['manifest'].get('media',{})
        app.label(context,f"{meta.get('width','—')} × {meta.get('height','—')}  ·  {self.duration:g} giây",color=MUTED).pack(anchor='w',pady=(6,12))
        context_footer=tk.Frame(context,bg='white');context_footer.pack(side='bottom',fill='x')
        notebook=ttk.Notebook(context);notebook.pack(fill='both',expand=True)
        qa=tk.Frame(notebook,bg='white',padx=8,pady=12)
        caption=tk.Frame(notebook,bg='white',padx=8,pady=12)
        sources=tk.Frame(notebook,bg='white',padx=8,pady=12)
        warnings=row.get('qa_issues',[])
        notebook.add(qa,text=f'Nhận xét ({len(warnings)})');notebook.add(caption,text='Nội dung');notebook.add(sources,text='Ảnh nguồn')
        app.label(qa,'QA chỉ tham khảo',bold=True,size=12).pack(anchor='w',pady=(0,8))
        self._text(qa,'\n\n'.join(f'{i+1}. {review_note(text)}' for i,text in enumerate(warnings)) or 'Không có cảnh báo chất lượng.')
        self._text(caption,row['caption'])
        for image_path,bounds in [(row.get('original'),(300,230)),*[(p,(72,112)) for p in row.get('frames',[])]]:
            if not image_path:continue
            photo=app._thumbnail(image_path,bounds)
            if photo:
                self.photos.append(photo)
                tk.Label(sources,image=photo,bg='white').pack(side='top' if len(self.photos)==1 else 'left',padx=3,pady=6)
        app.button(context_footer,'Mở thư mục truyện',lambda:app.open_local(row['folder'])).pack(fill='x',pady=(12,0))
        finishing=row['manifest'].get('finishing',{}).get('options',{})
        pieces=[]
        if finishing.get('mask_enabled'):pieces.append('Dải che trên / dưới')
        if finishing.get('laugh_enabled'):pieces.append('Tiếng cười cuối clip')
        app.label(context_footer,' · '.join(pieces) or 'Video gốc',size=9,color=MUTED,wraplength=330).pack(anchor='w',pady=(10,0))
        self._approval_state(row)
        try:
            # The wheel prepends its shared FFmpeg executables to PATH at import.
            # Keep these DLLs inside the player, never change CLI tool resolution.
            original_path=os.environ.get('PATH','')
            try:
                from ffpyplayer.player import MediaPlayer
            finally:os.environ['PATH']=original_path
            self.player=MediaPlayer(str(row['video']),ff_opts={'paused':False,'out_fmt':'rgb24','x':360,'y':-1,
                'volume':0,'autoexit':False},loglevel='error')
            self.timer=self.window.after(20,self._tick)
        except Exception:
            self.canvas.itemconfigure('placeholder',text='Không mở được trình phát.\nDùng “Mở thư mục truyện” để xem file.')
            self.play.configure(state='disabled')

    def _text(self,parent,value):
        box=tk.Text(parent,wrap='word',bg='white',fg=INK,relief='flat',font=('Segoe UI',10),
                    padx=2,pady=2,highlightthickness=0,width=1,height=1)
        bar=ttk.Scrollbar(parent,command=box.yview);bar.pack(side='right',fill='y')
        box.configure(yscrollcommand=bar.set);box.pack(fill='both',expand=True)
        box.insert('1.0',value);box.configure(state='disabled')

    def _space(self,event):
        if not isinstance(event.widget,(tk.Text,tk.Entry)):
            self.toggle();return 'break'

    def _seek_change(self,value):
        if self.dragging:self.clock.configure(text=f'{float(value):04.1f}s / {self.duration:g}s')

    def _seek_release(self,event=None):
        self.dragging=False
        if self.player:
            self.position=min(float(self.seek.get()),max(0,self.duration-.05))
            self.preview_target=self.position;self.player.seek(self.position,relative=False,accurate=True)
            self.ended=False
            # Decode a frame at the chosen position, then return to pause.
            if not self.playing:
                self.first_frame=True;self.player.set_volume(0);self.player.set_pause(False)

    def toggle(self):
        if not self.player:return
        if self.ended:self.player.seek(0,relative=False);self.ended=False
        self.first_frame=False;self.playing=not self.playing
        self.player.set_volume(0 if self.muted else 1);self.player.set_pause(not self.playing)
        self.play.configure(text='Ⅱ Tạm dừng' if self.playing else '▶ Phát')

    def toggle_mute(self):
        self.muted=not self.muted
        if self.player:self.player.set_volume(0 if self.muted or self.first_frame else 1)
        self.sound.configure(text='Âm thanh: tắt' if self.muted else 'Âm thanh: bật')

    def _tick(self):
        if not self.alive or not self.player:return
        try:
            frame,value=self.player.get_frame()
            if frame:
                raw,pts=frame;self.position=pts;self.frame_count+=1
                image=Image.frombytes('RGB',raw.get_size(),bytes(raw.to_bytearray()[0]))
                image.thumbnail((max(10,self.canvas.winfo_width()-8),max(10,self.canvas.winfo_height()-8)))
                self.photo=ImageTk.PhotoImage(image,master=self.window)
                self.canvas.delete('all');self.canvas.create_image(self.canvas.winfo_width()/2,
                    self.canvas.winfo_height()/2,image=self.photo,anchor='center')
                if self.first_frame and pts>=self.preview_target-.08:
                    self.player.set_pause(True);self.first_frame=False
            if value=='eof':
                self.ended=True;self.playing=False;self.play.configure(text='↻ Phát lại')
            if not self.dragging:self.seek.set(self.position)
            self.clock.configure(text=f'{self.position:04.1f}s / {self.duration:g}s')
        except Exception:
            self.feedback.configure(text='Trình phát gặp lỗi; file video vẫn được giữ.')
            self._stop_player();return
        self.timer=self.window.after(25,self._tick)

    def request_approval(self):
        if self.invalidated:return
        self.approval_requested=True;self.approve.configure(text='Đang gửi…',state='disabled')
        self.feedback.configure(text='Đang lưu yêu cầu duyệt clip này…')
        queued=self.app.launch('approve',self.row['job_id'],'--manifest-sha256',self.reviewed_digest)
        if queued is False:
            self.approval_requested=False;self._approval_state(self.row)
            self.feedback.configure(text='Chưa lưu được yêu cầu duyệt. Anh có thể bấm thử lại.')
        self.window.after(250,self.sync)

    def _approval_state(self,row):
        status=row['manifest'].get('review',{}).get('status')
        if status=='pending':
            self.approve.configure(text='Đã gửi · chờ áp dụng' if self.approval_requested else 'Duyệt clip để đăng',
                                   state='disabled' if self.approval_requested else 'normal')
        else:
            self.approve.configure(text='Đã duyệt' if status=='approved' else 'Sẵn sàng đăng',state='disabled')
            if self.approval_requested:self.feedback.configure(text='Đã duyệt. Clip được đưa vào hàng chờ đăng.')

    def sync(self):
        if not self.alive:return
        from .quality import manifest_digest
        row=next((r for r in self.app.snapshot.get('rows',[]) if r['key']==self.row['key']),None)
        if row:
            review=row['manifest'].get('review',{})
            expected_approval=(review.get('status')=='approved'
                and review.get('approved_manifest_sha256')==self.reviewed_digest)
            if (manifest_digest(row['manifest'])!=self.reviewed_digest and not expected_approval) or self.invalidated:
                self.invalidated=True
                self._stop_player();self.approve.configure(state='disabled',text='Mở lại bản mới')
                self.feedback.configure(text='Hồ sơ đã thay đổi. Đóng và mở lại để xem đúng bản mới.');return
            self.row=row;self.state.configure(text=row['state']);self._approval_state(row)
        request=self.app.settings.data/'review-requests'/(str(self.row['job_id'])+'.json')
        if (self.approval_requested and not request.is_file() and self.app.active!='approve'
                and self.row['manifest'].get('review',{}).get('status')=='pending'):
            self.approval_requested=False;self._approval_state(self.row)
            self.feedback.configure(text='Chưa lưu được yêu cầu duyệt. Anh có thể bấm thử lại.')
        if self.approval_requested and request.is_file():
            try:saved=json.loads(request.read_text(encoding='utf-8'))
            except (OSError,ValueError):return
            if saved.get('state')=='rejected':
                self.approval_requested=False;self._approval_state(self.row)
                self.feedback.configure(text='Hồ sơ đã đổi; làm mới và xem lại trước khi duyệt.')

    def _stop_player(self):
        if self.timer:
            self.window.after_cancel(self.timer);self.timer=None
        if self.player:
            self.player.close_player();self.player=None

    def close(self):
        if not self.alive:return
        self.alive=False;self._stop_player();self.window.destroy()
        if self.app.review is self:self.app.review=None
