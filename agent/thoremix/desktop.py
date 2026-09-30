"""Desktop controller: subprocess commands, no AI agent or background campaign loop."""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, simpledialog, ttk
import webbrowser

from .dashboard import (build_snapshot, selected_key, state_text, safe_link,
                        date_text, mapping, visible_rows, PLATFORMS, NAMES)

from .config import Settings


def readable_result(command: str, result: dict) -> str:
    """Human copy stays separate from raw command diagnostics."""
    result = mapping(result)
    if command=='retry-failed':
        if result.get('state') == 'retry_batch_finished':
            return (f"Đã xử lý {result.get('processed',0)}/{result.get('requested',0)} lỗi/kẹt. "
                    "Danh sách đã được làm mới; video vẫn lỗi sẽ còn trong bộ lọc Đang lỗi.")
        return str(result.get('reason') or 'Chưa chạy được thử lại hàng loạt; xem Diagnostics.')
    if command=='retry-production':
        labels={'retry_complete':'Đã hoàn thành clip. Mở video để xem kết quả.',
            'retry_not_needed':'Clip đã hoàn thành hoặc đã bắt đầu đăng; không sản xuất lại.',
            'retry_paused':'Tự động đang tạm dừng. Bật lại trong Sản xuất & lịch rồi tiếp tục.',
            'retry_quota_reached':'Đã đủ hạn mức clip hôm nay. Tiếp tục vào ngày mai hoặc đổi hạn mức trong Sản xuất & lịch.',
            'retry_rejected':'Ảnh nguồn hoặc dữ liệu đã lưu không còn khớp. Chưa chạy lại truyện.',
            'retry_uncertain':'Chưa xác nhận được lượt trước; giữ nguyên để đối soát, chưa gửi tạo lại.',
            'retry_failed':'Đã kiểm tra lại nhưng chưa thể tiếp tục.',
            'retry_blocked':'Chưa thể tiếp tục lúc này.',
            'busy':'Đang có lượt sản xuất khác. Chờ lượt đó xong rồi bấm tiếp tục.',
            'retry_cooldown':f"Chờ thêm {result.get('seconds',60)} giây sau lượt lỗi rồi thử lại."}
        text=labels.get(result.get('state'),'Chưa chạy được yêu cầu; xem chi tiết trong Hoạt động.')
        return text+(' '+result['message'] if result.get('message') else '')
    if command=='approve-correction':
        if result.get('state')=='correction_approved':
            return 'Đã duyệt correction; clip sạch được đưa vào hàng chờ đăng Facebook và TikTok.'
        return str(result.get('reason') or 'Chưa duyệt được correction; làm mới và xem lại đúng bản hiện tại.')
    if command=='approve':
        if result.get('state')=='approval_rejected':
            return 'Chưa áp dụng duyệt vì hồ sơ đã thay đổi. Làm mới và xem lại video hiện tại.'
        if result.get('state') not in {'approval_queued','video_ready','awaiting_approval','published','publishing'}:
            return 'Chưa lưu được yêu cầu duyệt. Anh có thể bấm thử lại.'
        return ('Đã duyệt clip; clip được đưa vào hàng chờ đăng.' if result.get('state')=='video_ready'
                else 'Đã nhận yêu cầu duyệt. App sẽ áp dụng sau lượt sản xuất đang chạy.')
    if command=='finish-unpublished':
        if result.get('state')=='busy':
            return 'Đang có lượt sản xuất. Chờ lượt đó xong rồi áp dụng lại; chưa đổi video.'
        if result.get('state')!='processed':
            return 'Chưa xử lý xong các clip. Video gốc vẫn được giữ; xem chi tiết trong Hoạt động rồi thử lại.'
        return f"Đã xử lý {result.get('count',0)} clip chưa đăng. Video đã đăng được giữ nguyên."
    if command in {'produce-ahead', 'dispatch'}:
        labels = {'quota_reached': 'Đã đủ hạn mức.', 'source_exhausted': 'Không còn ảnh mới hợp lệ.',
                  'production_not_ready': 'Bộ sản xuất cả truyện thành một clip chưa sẵn sàng.',
                  'reconciliation_required': 'Có lượt chưa rõ kết quả, cần đối soát.',
                  'paused': 'Tự động đang tạm dừng.', 'scheduled_mode': 'Đang dùng chế độ theo lịch đăng.'}
        lines = [labels.get(result.get('state'), 'Đã lưu trạng thái sản xuất.'),
                 f"{result.get('completed', 0)}/{result.get('limit', '—')} clip hoàn thành · {result.get('failed', 0)} lỗi",
                 f"{result.get('ready_count', 0)} clip chờ đăng"]
        for error in result.get('errors', [])[:30]:
            lines.append(Path(str(error.get('source', ''))).name + ': ' + str(error.get('reason') or error.get('state')))
        if result.get('report_path'):
            lines += ['', 'Báo cáo: ' + result['report_path']]
        return '\n'.join(lines)
    if command in {'status', 'init', 'pause', 'resume'}:
        lines = ['Lịch đã bật' if result.get('enabled') else 'Lịch đang tạm dừng',
                 '11:00 và 18:30 — giờ Việt Nam', '',
                 'Ảnh nguồn: ' + str(result.get('input_dir') or 'Chưa ghi nhận'),
                 'Video: ' + str(result.get('output_dir') or 'Chưa ghi nhận')]
        flow = mapping(result.get('flowkit'))
        if flow:
            label = ('Tạo video: đã cấu hình, kiểm tra đăng nhập khi chạy' if flow.get('automatic_story_ready')
                     else 'FlowKit: ' + ('đã kết nối' if flow.get('connected') else 'chưa kết nối'))
            lines += ['', label,
                      'Credit: ' + str(flow.get('credits')) if flow.get('credit_verified') else 'Credit: chưa xác minh']
        auth = mapping(result.get('last_auth_check'))
        if auth:
            lines += ['', 'Lần kiểm tra đã lưu: ' + str(auth.get('observed_at') or 'chưa ghi thời gian'),
                      ' · '.join(f"{p}: {mapping(v).get('state', 'chưa rõ')}"
                                 for p, v in mapping(auth.get('platforms')).items()),
                      'Kênh đích được kiểm tra lại trước mỗi lần đăng.']
        jobs = result.get('jobs')
        if isinstance(jobs, list):
            lines += ['', 'CÔNG VIỆC']
            for job in jobs[:30]:
                job = mapping(job)
                lines.append(Path(str(job.get('source') or 'Hồ sơ chưa rõ')).name + ' — ' + state_text(job.get('state')))
        return '\n'.join(lines)
    if command == 'affiliate':
        if result.get('state') == 'verified':
            return 'Sản phẩm đã xác minh: ' + str(mapping(result.get('product')).get('title') or '') + '\n\n' + str(result.get('comment') or '')
        return 'Chưa có sản phẩm Affiliate đủ bằng chứng.\n' + str(result.get('reason') or 'Xem Diagnostics để biết bước cần xử lý.')
    if command == 'login':
        return 'Cửa sổ đăng nhập đã đóng. Chọn “Kiểm tra đăng nhập” để xác minh ba kênh.'
    if isinstance(result.get('platforms'), dict):
        lines = ['TRẠNG THÁI ĐÃ LƯU']
        for platform in PLATFORMS:
            if command != 'auth-status' and platform not in result['platforms']:
                continue
            item = mapping(result['platforms'].get(platform))
            if command == 'auth-status':
                lines.append(NAMES[platform] + ': ' + state_text(item.get('state')))
            else:
                lines += [NAMES[platform] + ': bài ' + state_text(mapping(item.get('publication')).get('state')) +
                          ' · bình luận ' + state_text(mapping(item.get('comment')).get('state'))]
        return '\n'.join(lines)
    return str(result.get('reason') or state_text(result.get('state')))


BG, INK, MUTED, SIDE, ACCENT = '#f4f6fa', '#1c2940', '#647189', '#17243a', '#6550bb'
PAGES = {'videos': ('Video', 'Hồ sơ đã lưu · bài đăng và bình luận được xác nhận riêng'),
         'channels': ('Kênh đăng', 'ThoRemixOfficial · Facebook, TikTok và YouTube'),
         'affiliate': ('Affiliate', 'Sản phẩm và nội dung bình luận đã lưu'),
         'schedule': ('Sản xuất & lịch', 'Một ảnh nguồn = một truyện ngắn = một clip riêng'),
         'settings': ('Xử lý video', 'Dải che và âm thanh cuối clip · giữ nguyên khung hình và thời lượng'),
         'activity': ('Nhật ký & Trạng thái', 'Sản xuất · sửa video · đăng từng kênh · lỗi và bước cần xử lý')}

VIDEO_FILTERS = {'Tất cả': 'all', 'Đã sản xuất': 'produced', 'Đang lỗi': 'failed',
                 'Đã đăng': 'posted', 'Chờ đăng': 'ready'}
VIDEO_ORDERS = {'Mới sản xuất trước': 'newest', 'Cũ sản xuất trước': 'oldest'}
ACTIVITY_FILTERS = {'Tất cả': 'all', 'Lỗi & cần xử lý': 'attention',
                    'Sản xuất': 'production', 'Sửa video': 'repair', 'Đăng kênh': 'publishing'}

ACTION_GROUPS = {
    'status': 'inspect',
    'login': 'browser', 'auth-status': 'browser', 'affiliate': 'browser',
    'publish': 'browser', 'publish-platform': 'browser', 'cleanup-tiktok-stale-editor': 'browser',
    'retry-failed': 'production', 'retry-production': 'production',
    'produce-ahead': 'production', 'dispatch': 'production', 'tick': 'production',
    'produce-one': 'production', 'reconcile-production': 'production',
    'finish-unpublished': 'production', 'repair-audio': 'production',
    'repair-audio-all': 'production', 'repair-source-text': 'production',
    'prepare-media-correction': 'production', 'finalize': 'production',
    'prepare-package': 'production', 'reconcile-package': 'production',
    'import-source': 'production',
}
ACTION_CONFLICTS = {
    'inspect': {'inspect'},
    'browser': {'browser', 'production'},
    'production': {'browser', 'production'},
    'control': {'control'},
}


class DesktopWindow:
    """A passive viewer until the user explicitly invokes a command."""

    def __init__(self, settings: Settings, *, window=None, poll=True, snapshot_loader=build_snapshot):
        self.settings, self.load_snapshot = settings, snapshot_loader
        self.window = window or tk.Tk()
        self.window.title('Thỏ Remix — Toolkit')
        self.window.geometry('1240x820')
        self.window.minsize(1080, 740)
        self.window.configure(bg=BG)
        self.window.option_add('*Font', ('Segoe UI', 10))
        self.events = queue.Queue()
        self.ui_commands = queue.Queue()
        self.tray = None
        self.instance = None
        self.production_mode = tk.StringVar(self.window, value=settings.production_mode)
        self.production_limit = tk.StringVar(self.window, value=str(settings.daily_production_limit))
        self.video_filter = tk.StringVar(self.window, value='Tất cả')
        self.video_order = tk.StringVar(self.window, value='Mới sản xuất trước')
        self.activity_filter = tk.StringVar(self.window, value='Tất cả')
        self.active = None
        self.active_groups = {}
        self.review = None
        self.retry_job_id = None
        self.retry_feedback = {}
        self.finish_vars={
            'mask_enabled':tk.BooleanVar(self.window,value=settings.mask_enabled),
            'mask_top_percent':tk.StringVar(self.window,value=str(settings.mask_top_percent)),
            'mask_bottom_percent':tk.StringVar(self.window,value=str(settings.mask_bottom_percent)),
            'laugh_enabled':tk.BooleanVar(self.window,value=settings.laugh_enabled),
            'laugh_path':tk.StringVar(self.window,value=settings.laugh_path),
            'laugh_volume':tk.StringVar(self.window,value=str(round(settings.laugh_volume*100)))}
        self.selected = None
        self.page = 'videos'
        self.snapshot = {}
        self.nav = {}
        self.photo = None
        self.activity = 'Chưa có lệnh nào được chạy trong cửa sổ này.'
        self.diagnostics = ''
        self.alive = True
        self._style()
        self._shell()
        self.refresh()
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        if poll:
            self.window.after(200, self._pump)
            self.window.after(10000, self._refresh_timer)

    def _style(self):
        style = ttk.Style(self.window)
        style.theme_use('clam')
        style.configure('Treeview', font=('Segoe UI', 10), rowheight=78, background='white',
                        fieldbackground='white', foreground=INK, borderwidth=0)
        style.configure('Treeview.Heading', font=('Segoe UI', 10, 'bold'), background='#edf0f6',
                        foreground=MUTED, padding=(10, 10), relief='flat', borderwidth=0)
        style.map('Treeview', background=[('selected', '#ece7fb')], foreground=[('selected', INK)])
        style.configure('Horizontal.TProgressbar', background=ACCENT, troughcolor=BG, borderwidth=0)
        style.configure('Activity.Treeview', font=('Segoe UI', 9), rowheight=34, background='white',
                        fieldbackground='white', foreground=INK, borderwidth=0)
        style.configure('Activity.Treeview.Heading', font=('Segoe UI', 9, 'bold'),
                        background='#edf0f6', foreground=MUTED, padding=(8, 8), relief='flat')

    def label(self, parent, text='', *, size=10, bold=False, color=INK, **kw):
        return tk.Label(parent, text=text, font=('Segoe UI', size, 'bold' if bold else 'normal'),
                        bg=parent.cget('bg'), fg=color, anchor='w', justify='left', **kw)

    def button(self, parent, text, command, *, primary=False):
        bg, hover = (ACCENT, '#5541a7') if primary else ('#e9edf5', '#dee4ef')
        widget = tk.Button(parent, text=text, command=command, bg=bg, fg='white' if primary else INK,
                           activebackground=hover, activeforeground='white' if primary else INK,
                           relief='flat', bd=0, padx=14, pady=9, cursor='hand2', takefocus=True)
        widget.configure(disabledforeground='#929aab')
        widget.bind('<Enter>', lambda _: widget.configure(bg=hover) if str(widget.cget('state'))!='disabled' else None)
        widget.bind('<Leave>', lambda _: widget.configure(bg=bg) if str(widget.cget('state'))!='disabled' else None)
        return widget

    @staticmethod
    def _action_group(command):
        return ACTION_GROUPS.get(command, 'production')

    def _ensure_action_state(self):
        if not hasattr(self, 'active_groups') or not isinstance(self.active_groups, dict):
            self.active_groups = {}

    def _sync_active(self):
        self._ensure_action_state()
        for group in ('production', 'browser', 'inspect', 'control'):
            if group in self.active_groups:
                self.active = self.active_groups[group]
                return
        self.active = None

    def _action_busy(self, command):
        self._ensure_action_state()
        group = self._action_group(command)
        conflicts = ACTION_CONFLICTS.get(group, {group})
        return any(active_group in conflicts for active_group in self.active_groups)

    def _action_active(self, command):
        self._ensure_action_state()
        group = self._action_group(command)
        return self.active_groups.get(group) == command

    def _reserve_action(self, command):
        if self._action_busy(command):
            return False
        self.active_groups[self._action_group(command)] = command
        self._sync_active()
        return True

    def _release_action(self, command):
        self._ensure_action_state()
        group = self._action_group(command)
        if self.active_groups.get(group) == command:
            self.active_groups.pop(group, None)
        self._sync_active()

    def _shell(self):
        side = tk.Frame(self.window, bg=SIDE, width=196)
        side.pack(side='left', fill='y')
        side.pack_propagate(False)
        self.label(side, 'THỎ\nREMIX', size=25, bold=True, color='white').pack(anchor='w', padx=24, pady=(30, 5))
        self.label(side, 'CONTENT TOOLKIT', size=9, color='#a4b3ca').pack(anchor='w', padx=24, pady=(0, 40))
        for i, (key, (title, _)) in enumerate(PAGES.items(), 1):
            button = tk.Button(side, text=f'{i:02}   {title}', command=lambda k=key: self.show_page(k),
                               bg=SIDE, fg='#cad4e5', relief='flat', bd=0, anchor='w', padx=17,
                               pady=15, cursor='hand2', activebackground='#2b3a55', activeforeground='white')
            button.pack(fill='x', padx=10, pady=2)
            self.nav[key] = button
        self.label(side, 'ThoRemixOfficial\n3 kênh · 1 hồ sơ video', size=9, color='#a4b3ca').pack(side='bottom', anchor='w', padx=24, pady=26)
        body = tk.Frame(self.window, bg=BG)
        body.pack(side='left', fill='both', expand=True, padx=24, pady=(23, 14))
        header = tk.Frame(body, bg=BG)
        header.pack(fill='x')
        self.heading = self.label(header, size=24, bold=True)
        self.heading.pack(side='left')
        self.button(header, 'Làm mới', self.refresh).pack(side='right')
        self.subtitle = self.label(body, color=MUTED)
        self.subtitle.pack(fill='x', pady=(6, 16))
        self.summary = self.label(body, color=ACCENT, bold=True)
        self.summary.pack(fill='x', pady=(0, 16))
        self.content = tk.Frame(body, bg='white')
        self.content.pack(fill='both', expand=True)
        self.status = self.label(body, 'Chỉ đọc dữ liệu đã lưu. Đóng cửa sổ không hủy lượt đang chạy.', size=9, color=MUTED)
        self.status.pack(fill='x', pady=(12, 0))
        self.progress = ttk.Progressbar(body, mode='indeterminate')

    def enable_tray(self, instance):
        from .tray import DesktopTray

        self.instance = instance
        try:
            self.tray = DesktopTray(self.ui_commands)
            self.tray.start()
        except Exception:
            self.tray = None
            self.status.configure(text='Không mở được system tray. Cửa sổ vẫn hoạt động bình thường.')

    def show_window(self):
        if self.alive:
            self.window.deiconify()
            self.window.lift()
            self.window.focus_force()

    def _tray_command(self, command):
        if command == 'quit':
            self.quit()
        elif command in {'show', 'schedule', 'pause'}:
            self.show_window()
            if command == 'schedule':
                self.show_page('schedule')
            elif command == 'pause':
                self.toggle_automation(False)
        elif command == 'tray_ready':
            self.status.configure(text='Bấm X để ẩn xuống system tray. Chuột phải biểu tượng thỏ để mở lại hoặc thoát.')
        elif command == 'tray_unavailable':
            self.show_window()
            self.status.configure(text='System tray không khả dụng. Cửa sổ đã được mở lại.')

    def _video_rows(self):
        return visible_rows(self.snapshot.get('rows', []),
                            VIDEO_FILTERS.get(self.video_filter.get(), 'all'),
                            VIDEO_ORDERS.get(self.video_order.get(), 'newest'))

    def _video_view_changed(self, _event=None):
        self.selected = selected_key(self._video_rows(), self.selected)
        self.show_page('videos')

    def refresh(self):
        self.snapshot = self.load_snapshot(self.settings)
        rows = self._video_rows() if self.page == 'videos' else self.snapshot['rows']
        self.selected = selected_key(rows, self.selected)
        self.show_page(self.page)
        if self.review:self.review.sync()

    def show_page(self, key):
        self.page = key
        for child in self.content.winfo_children():
            child.destroy()
        for name, button in self.nav.items():
            button.configure(bg='#344263' if name == key else SIDE, fg='white' if name == key else '#cad4e5')
        title, subtitle = PAGES[key]
        self.heading.configure(text=title)
        self.subtitle.configure(text=subtitle)
        rows = self.snapshot.get('rows', [])
        count = sum(r['complete'] for r in rows)
        self.summary.configure(text=f'{len(rows)} hồ sơ video   /   {count} hoàn tất phạm vi đăng   /   ' +
                               ('Lịch đã bật' if self.snapshot.get('enabled') else 'Lịch đang tạm dừng'))
        getattr(self, '_page_' + key)()

    def text_panel(self, parent, text, *, height=8, diagnostic=False):
        frame = tk.Frame(parent, bg=parent.cget('bg'))
        frame.pack(fill='both', expand=True)
        box = tk.Text(frame, height=height, wrap='word', bg=parent.cget('bg'), fg=INK,
                      font=('Consolas' if diagnostic else 'Segoe UI', 10), relief='flat', bd=0,
                      padx=2, pady=8, highlightthickness=0)
        scrollbar = ttk.Scrollbar(frame, command=box.yview)
        scrollbar.pack(side='right', fill='y')
        box.configure(yscrollcommand=scrollbar.set)
        box.pack(fill='both', expand=True)
        box.insert('1.0', text)
        box.configure(state='disabled')
        return box

    def _thumbnail(self, path, size):
        if not path:
            return None
        try:
            from PIL import Image, ImageTk, ImageOps
            with Image.open(path) as source:
                thumb = ImageOps.contain(ImageOps.exif_transpose(source).convert('RGB'), size)
                return ImageTk.PhotoImage(thumb, master=self.window)
        except (ImportError, OSError, ValueError, tk.TclError):
            return None

    def _page_videos(self):
        self.content.rowconfigure(1, weight=1)
        self.content.columnconfigure(0, weight=1)
        toolbar = tk.Frame(self.content, bg='white', padx=12, pady=10)
        toolbar.grid(row=0, column=0, sticky='ew')
        self.label(toolbar, 'Lọc', size=9, color=MUTED).pack(side='left', padx=(0, 6))
        filter_box = ttk.Combobox(toolbar, textvariable=self.video_filter,
                                  values=tuple(VIDEO_FILTERS), state='readonly', width=15)
        filter_box.pack(side='left', padx=(0, 14))
        filter_box.bind('<<ComboboxSelected>>', self._video_view_changed)
        self.label(toolbar, 'Sắp xếp', size=9, color=MUTED).pack(side='left', padx=(0, 6))
        order_box = ttk.Combobox(toolbar, textvariable=self.video_order,
                                 values=tuple(VIDEO_ORDERS), state='readonly', width=20)
        order_box.pack(side='left')
        order_box.bind('<<ComboboxSelected>>', self._video_view_changed)
        self.retry_all_button = self.button(toolbar, 'Reset & thử lại tất cả lỗi/kẹt',
                                            self.retry_failed_production)
        self.retry_all_button.pack(side='right')
        if self._action_busy('retry-failed'):
            self.retry_all_button.configure(state='disabled')
        self.video_panes = tk.PanedWindow(self.content, orient='horizontal', bg='#e0e5ef',
                                        sashwidth=6, bd=0, sashrelief='flat')
        self.video_panes.grid(row=1, column=0, sticky='nsew')
        table_box = tk.Frame(self.video_panes, bg='white')
        self.video_panes.add(table_box, minsize=440, stretch='always')
        self.table = ttk.Treeview(table_box, columns=('title', *PLATFORMS),
                                 show='tree headings', height=8, selectmode='browse')
        self.table.heading('#0', text='ẢNH')
        self.table.column('#0', width=64, minwidth=58, stretch=False)
        self.table.heading('title', text='TRUYỆN / TIẾN ĐỘ')
        self.table.column('title', width=230, minwidth=150, stretch=True)
        for platform in PLATFORMS:
            self.table.heading(platform, text=NAMES[platform])
            self.table.column(platform, width=94, minwidth=82, stretch=False)
        scroll = ttk.Scrollbar(table_box, command=self.table.yview)
        scroll.pack(side='right', fill='y')
        horizontal = ttk.Scrollbar(table_box, orient='horizontal', command=self.table.xview)
        horizontal.pack(side='bottom', fill='x')
        self.table.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        self.table.pack(fill='both', expand=True)
        self.row_photos = []
        for row in self._video_rows():
            title = row['title']
            values = [title + '\n' + row['state']]
            for p in PLATFORMS:
                channel = row['channels'][p]
                post = {'Chưa thực hiện':'Chưa đăng', 'Đã xác nhận':'Đã đăng',
                        'Không yêu cầu':'—'}.get(channel['publication'],channel['publication'])
                comment = {'Chưa thực hiện':'Chưa có', 'Đã xác nhận':'Đã có',
                           'Không yêu cầu':'—'}.get(channel['comment'],channel['comment'])
                values.append(f'{post}\nBL: {comment}')
            photo = self._thumbnail(row['preview'], (52, 66))
            if photo:
                self.row_photos.append(photo)
            self.table.insert('', 'end', iid=row['key'], values=values, image=photo or '')
        self.table.bind('<<TreeviewSelect>>', self._select)
        self.table.bind('<Double-1>',lambda _:self.open_review())
        inspector_box = tk.Frame(self.video_panes, bg='white', width=330)
        self.video_panes.add(inspector_box, minsize=280, width=330, stretch='never')
        self.detail_canvas = tk.Canvas(inspector_box, bg='white', highlightthickness=0)
        details_scroll = ttk.Scrollbar(inspector_box, command=self.detail_canvas.yview)
        details_scroll.pack(side='right', fill='y')
        self.detail_canvas.configure(yscrollcommand=details_scroll.set)
        self.detail_canvas.pack(fill='both', expand=True)
        self.inspector = tk.Frame(self.detail_canvas, bg='white', padx=14, pady=14)
        self.detail_window = self.detail_canvas.create_window((0, 0), window=self.inspector, anchor='nw')
        self.inspector.bind('<Configure>', lambda _: self.detail_canvas.configure(
            scrollregion=self.detail_canvas.bbox('all')))
        self.detail_canvas.bind('<Configure>', lambda event: self.detail_canvas.itemconfigure(
            self.detail_window, width=event.width))
        if self.selected:
            self.table.selection_set(self.selected)
            self.table.see(self.selected)
        self._inspect()

    def _select(self, _event=None):
        selection = self.table.selection()
        if selection and selection[0] != self.selected:
            self.selected = selection[0]
            self._inspect()

    def _inspect(self):
        for child in self.inspector.winfo_children():
            child.destroy()
        self.detail_canvas.yview_moveto(0)
        self.detail_photos = []
        row = next((r for r in self.snapshot['rows'] if r['key'] == self.selected), None)
        detail = self.inspector
        if not row:
            self.label(detail, 'Chưa có truyện', size=18, bold=True).pack(anchor='w', pady=(20, 12))
            self.label(detail, 'Ảnh và tiến độ sẽ hiện ngay khi bắt đầu sản xuất.', color=MUTED,
                       wraplength=260).pack(anchor='w')
            self.button(detail, 'Mở thư mục video', lambda: self.open_local(self.snapshot['output'])).pack(fill='x', pady=18)
            self.button(detail, 'Chọn hồ sơ video…', self.choose_package).pack(fill='x')
            return
        self.label(detail, row['title'], size=13, bold=True, wraplength=280).pack(fill='x')
        self.label(detail, row['state'], color=ACCENT, size=9, wraplength=270).pack(fill='x', pady=(6, 10))
        if row.get('retry_label'):
            busy=self._action_active('retry-production') and self.retry_job_id==row['job_id']
            self.retry_button=self.button(detail,'Đang tiếp tục…' if busy else row['retry_label'],
                lambda:self.retry_production(row),primary=True)
            self.retry_button.pack(fill='x',pady=(0,10))
            if busy:self.retry_button.configure(state='disabled')
            message=self.retry_feedback.get(row['job_id']) or row.get('failure_message')
            if message:self.label(detail,message,color=MUTED,size=9,wraplength=270).pack(fill='x',pady=(0,14))
        if row['video']:
            self.button(detail,'▶  Xem & duyệt clip',lambda:self.open_review(row),primary=True).pack(fill='x',pady=(0,16))
            self.label(detail,f"{len(row.get('qa_issues',[]))} nhận xét · xem ngay trong app",color=MUTED,size=9).pack(fill='x',pady=(0,12))
        self.photo = self._thumbnail(row.get('original') or row['preview'], (270, 175))
        if self.photo:
            tk.Label(detail, image=self.photo, bg='#edf0f6').pack(fill='x')
        self.label(detail, 'Ảnh nguồn · một câu chuyện', size=9, color=MUTED).pack(fill='x', pady=(4, 12))
        frames = row.get('frames', [])
        self.label(detail, f'{len(frames)} ảnh con đã lưu' if frames else 'Chưa có ảnh con', bold=True).pack(fill='x')
        strip = tk.Frame(detail, bg='white')
        strip.pack(fill='x', pady=8)
        for i, frame in enumerate(frames):
            cell = tk.Frame(strip, bg='white')
            cell.grid(row=i // 4, column=i % 4, padx=(0, 6), pady=3)
            photo = self._thumbnail(frame, (58, 94))
            if photo:
                self.detail_photos.append(photo)
                tk.Button(cell, image=photo, bg='#edf0f6', relief='flat', bd=0,
                          command=lambda p=frame: self.open_local(p)).pack()
            self.label(cell, f'Cảnh {i + 1}', size=8, color=MUTED).pack()
        if row.get('qa_issues'):
            self.label(detail, 'QA tham khảo · mở clip để xem nhận xét',color=MUTED,size=9,wraplength=270).pack(fill='x',pady=8)
        correction=isinstance(row.get('manifest',{}).get('correction'),dict)
        correction_approved=True
        if correction:
            from .media_correction import correction_approval_valid
            correction_approved=correction_approval_valid(self.settings,row['job_id'],row['manifest'])
            self.label(detail,
                'Correction đã duyệt · chỉ Facebook + TikTok' if correction_approved else
                'Correction sạch đang chờ duyệt riêng trước khi đăng',
                color=ACCENT if correction_approved else MUTED,size=9,wraplength=270).pack(fill='x',pady=(2,8))
        review_ready=(row['manifest'] and row['manifest'].get('review',{}).get('status')!='pending')
        if review_ready and correction_approved:
            self.button(detail, 'Đăng / đối soát hồ sơ', lambda: self.launch('publish', str(row['folder']))).pack(fill='x', pady=4)
        for link in row['links']:
            self.button(detail, link['label'] + ' ↗', lambda u=link['url']: webbrowser.open(u)).pack(fill='x', pady=3)
        self.label(detail, str(row['folder']), size=9, color=MUTED, wraplength=270).pack(fill='x', pady=(10, 4))
        if row['folder'].is_dir():
            self.button(detail, 'Mở thư mục truyện', lambda: self.open_local(row['folder'])).pack(fill='x', pady=4)
        elif row.get('original'):
            self.button(detail, 'Mở ảnh nguồn', lambda: self.open_local(row['original'])).pack(fill='x', pady=4)

    def retry_failed_production(self):
        if self._action_busy('retry-failed'):
            self.status.configure(text='Nhóm sản xuất/đăng đang chạy; chờ hoàn tất rồi reset các lỗi/kẹt.')
            return
        if self.launch('retry-failed'):
            self.status.configure(text='Đang reset và thử lại từng lỗi/kẹt từ receipt đã lưu; trạng thái chưa rõ sẽ đối soát trước.')
            if hasattr(self, 'retry_all_button'):
                self.retry_all_button.configure(state='disabled')

    def retry_production(self,row):
        if self._action_busy('retry-production'):
            self.status.configure(text='Nhóm sản xuất/đăng đang chạy; chờ hoàn tất rồi tiếp tục truyện này.')
            return
        queued=self.launch('retry-production',row['job_id'])
        if queued:
            self.retry_job_id=row['job_id']
            self.retry_feedback[row['job_id']]='Đang tiếp tục đúng truyện này từ dữ liệu đã lưu…'
            self.retry_button.configure(text='Đang tiếp tục…',state='disabled')

    def open_review(self,row=None):
        row=row or next((r for r in self.snapshot['rows'] if r['key']==self.selected),None)
        if not row or not row.get('video'):return
        if getattr(self,'review',None):self.review.close()
        from .review_window import ReviewWindow
        self.review=ReviewWindow(self,row)

    def _page_settings(self):
        frame=self._padded()
        self.label(frame,'Dải che trên / dưới',size=18,bold=True).pack(anchor='w')
        tk.Checkbutton(frame,text='Bật dải đen · giữ nguyên độ phân giải',variable=self.finish_vars['mask_enabled'],
            bg='white',activebackground='white',fg=INK).pack(anchor='w',pady=(12,8))
        masks=tk.Frame(frame,bg='white');masks.pack(anchor='w')
        for key,title in [('mask_top_percent','Phía trên'),('mask_bottom_percent','Phía dưới')]:
            self.label(masks,title,color=MUTED).pack(side='left',padx=(0,8))
            tk.Spinbox(masks,from_=0,to=35,increment=.5,textvariable=self.finish_vars[key],width=5,
                       font=('Segoe UI',12)).pack(side='left',padx=(0,6))
            self.label(masks,'% chiều cao',color=MUTED).pack(side='left',padx=(0,24))
        self.label(frame,'Mặc định: trên 11%, dưới 12%. Hình nằm dưới dải đen; không cắt hay phóng to video.',
            size=10,color=MUTED,wraplength=780).pack(anchor='w',pady=(12,25))
        ttk.Separator(frame).pack(fill='x')
        self.label(frame,'Tiếng cười cuối clip',size=18,bold=True).pack(anchor='w',pady=(22,0))
        tk.Checkbutton(frame,text='Thêm tiếng cười vào cuối clip',variable=self.finish_vars['laugh_enabled'],
            bg='white',activebackground='white',fg=INK).pack(anchor='w',pady=(12,8))
        audio=tk.Frame(frame,bg='white');audio.pack(fill='x')
        tk.Entry(audio,textvariable=self.finish_vars['laugh_path'],font=('Segoe UI',10),relief='solid',bd=1).pack(side='left',fill='x',expand=True,ipady=8)
        self.button(audio,'Chọn file…',self.choose_laugh).pack(side='left',padx=(10,0))
        gain=tk.Frame(frame,bg='white');gain.pack(anchor='w',pady=14)
        self.label(gain,'Âm lượng',color=MUTED).pack(side='left',padx=(0,12))
        tk.Spinbox(gain,from_=0,to=200,increment=10,textvariable=self.finish_vars['laugh_volume'],width=5,
                   font=('Segoe UI',12)).pack(side='left')
        self.label(gain,' %  ·  trộn cùng âm thanh gốc',color=MUTED).pack(side='left',padx=8)
        self.label(frame,'Tiếng cười kết thúc cùng video. Thời lượng clip không thay đổi; file âm thanh được lưu riêng trong app.',
            size=10,color=MUTED,wraplength=780).pack(anchor='w',pady=(0,24))
        actions=tk.Frame(frame,bg='white');actions.pack(fill='x')
        self.save_finish_button=self.button(actions,'Lưu cài đặt',self.save_finishing,primary=True);self.save_finish_button.pack(side='left')
        self.finish_apply_button=self.button(actions,'Đang xử lý…' if self._action_active('finish-unpublished')
            else 'Áp dụng cho clip chưa đăng',self.apply_finishing)
        self.finish_apply_button.pack(side='left',padx=10)
        if self._action_active('finish-unpublished'):self.finish_apply_button.configure(state='disabled')
        self.finish_feedback=self.label(frame,'Cài đặt áp dụng cho clip sản xuất tiếp theo. Clip đã đăng được giữ nguyên.',color=MUTED,wraplength=780)
        self.finish_feedback.pack(anchor='w',pady=16)

    def choose_laugh(self):
        path=filedialog.askopenfilename(parent=self.window,title='Chọn tiếng cười',
            filetypes=[('Âm thanh','*.mp3 *.wav *.aac *.m4a *.ogg'),('Tất cả','*.*')])
        if path:self.finish_vars['laugh_path'].set(path)

    def save_finishing(self):
        from .sdk import ThoRemixClient
        try:
            values={k:v.get() for k,v in self.finish_vars.items()}
            for key in ('mask_top_percent','mask_bottom_percent','laugh_volume'):values[key]=float(values[key])
            values['laugh_volume']/=100
            self.settings=ThoRemixClient(self.settings.directory).configure_finishing(**values)
            self.finish_vars['laugh_path'].set(self.settings.laugh_path)
            self.save_finish_button.configure(text='Đã lưu ✓')
            self.finish_feedback.configure(text='Đã lưu. Clip mới sẽ dùng cài đặt này.')
            return True
        except (ValueError,OSError):
            self.finish_feedback.configure(text='Chưa lưu: kiểm tra tỷ lệ 0–35%, âm lượng 0–200% và file âm thanh.')
            return False

    def apply_finishing(self):
        if self._action_busy('finish-unpublished'):
            self.finish_feedback.configure(text='Nhóm sản xuất/đăng đang chạy. Chờ hoàn tất để xử lý các clip đã lưu.');return
        if not self.save_finishing():return
        if self.review:self.review.close()
        self.finish_feedback.configure(text='Đang xử lý các clip chưa đăng…')
        self.finish_apply_button.configure(text='Đang xử lý…',state='disabled')
        self.launch('finish-unpublished')

    def _padded(self):
        frame = tk.Frame(self.content, bg='white', padx=25, pady=23)
        frame.pack(fill='both', expand=True)
        return frame

    def _page_channels(self):
        frame = self._padded()
        auth = mapping(self.snapshot.get('auth'))
        self.label(frame, 'Kết nối tài khoản', size=18, bold=True).pack(anchor='w')
        self.label(frame, 'Kiểm tra đã lưu: ' + date_text(auth.get('observed_at')), color=MUTED).pack(anchor='w', pady=(6, 15))
        for platform in PLATFORMS:
            item = mapping(mapping(auth.get('platforms')).get(platform))
            line = tk.Frame(frame, bg='white', pady=13)
            line.pack(fill='x')
            self.label(line, NAMES[platform], bold=True, size=13, width=13).pack(side='left')
            self.label(line, state_text(item.get('state')) if item else 'Chưa kiểm tra', color=ACCENT).pack(side='left')
            self.label(line, 'ThoRemixOfficial', color=MUTED).pack(side='right')
            if platform == 'facebook' and auth.get('facebook_rechecked_at'):
                self.label(frame, 'Facebook kiểm tra lại: ' + date_text(auth['facebook_rechecked_at']), size=9, color=MUTED).pack(anchor='w')
        self.label(frame, 'Phiên đăng nhập và đúng kênh đích được kiểm tra lại trước khi đăng.', color=MUTED).pack(anchor='w', pady=16)
        actions = tk.Frame(frame, bg='white')
        actions.pack(fill='x')
        self.button(actions, 'Đăng nhập 3 kênh', lambda: self.launch('login'), primary=True).pack(side='left', padx=(0, 9))
        self.button(actions, 'Kiểm tra đăng nhập', lambda: self.launch('auth-status')).pack(side='left')
        self.button(frame, 'Cấu hình tên Page Facebook', self.facebook_name).pack(anchor='w', pady=12)
        self.label(frame, 'Đóng cửa sổ trình duyệt đăng nhập trước khi chạy kiểm tra hoặc đăng bài.', color=MUTED, wraplength=720).pack(anchor='w', pady=5)

    def _page_affiliate(self):
        frame = self._padded()
        affiliate = mapping(self.snapshot.get('affiliate'))
        product = mapping(affiliate.get('product'))
        verified = affiliate.get('state') == 'verified'
        self.label(frame, 'Sản phẩm đã chọn' if verified else 'Chưa có lựa chọn đã xác minh', size=18, bold=True).pack(anchor='w')
        self.label(frame, str(product.get('title') or 'Chọn sản phẩm từ phiên Shopee Affiliate đã đăng nhập.'), wraplength=740).pack(anchor='w', pady=14)
        price, commission = mapping(product.get('price')), mapping(product.get('commission'))
        if verified:
            self.label(frame, f"Giá đã ghi nhận: {price.get('current', '—')} VND   ·   Đã bán: {product.get('sold', '—')}", color=MUTED).pack(anchor='w')
            rate = commission.get('effective_rate')
            rate_text = f'{rate * 100:g}%' if isinstance(rate, (int, float)) else 'chưa rõ'
            self.label(frame, f'Hoa hồng đã xác minh: {rate_text}   ·   ' + date_text(commission.get('observed_at')), color=ACCENT).pack(anchor='w', pady=8)
        self.label(frame, 'BÌNH LUẬN ĐI KÈM', size=9, bold=True, color=MUTED).pack(anchor='w', pady=(20, 3))
        self.text_panel(frame, str(affiliate.get('comment') or affiliate.get('reason') or 'Chưa có nội dung bình luận đã xác minh.'), height=8)
        if verified and (url := safe_link(affiliate.get('url'), 'shopee')):
            self.button(frame, 'Mở liên kết Affiliate đã xác minh ↗', lambda: webbrowser.open(url)).pack(anchor='w', pady=12)
        self.button(frame, 'Chọn Affiliate', lambda: self.launch('affiliate'), primary=True).pack(anchor='w', pady=(8, 0))

    def _page_schedule(self):
        frame = self._padded()
        columns = tk.Frame(frame, bg='white')
        columns.pack(fill='x')
        production = tk.Frame(columns, bg='white')
        production.pack(side='left', fill='both', expand=True, padx=(0, 25))
        schedule = tk.Frame(columns, bg='white')
        schedule.pack(side='left', fill='both', expand=True)
        self.label(production, 'Cách sản xuất', size=18, bold=True).pack(anchor='w', pady=(0, 12))
        for value, title in [('scheduled', 'Theo lịch đăng'), ('ahead', 'Sản xuất sớm')]:
            tk.Radiobutton(production, text=title, value=value, variable=self.production_mode,
                bg='white', fg=INK, selectcolor='white', activebackground='white',
                font=('Segoe UI', 11), anchor='w').pack(anchor='w', pady=3)
        self.label(production, 'Hạn mức sản xuất sớm mỗi ngày', color=MUTED).pack(anchor='w', pady=(15, 6))
        quota = tk.Frame(production, bg='white')
        quota.pack(anchor='w')
        tk.Spinbox(quota, from_=1, to=1000, textvariable=self.production_limit, width=6,
                   font=('Segoe UI', 13), relief='solid', bd=1).pack(side='left', padx=(0, 10))
        self.label(quota, 'clip hoàn thành  ·  1–1000', color=MUTED).pack(side='left')
        self.label(production, 'Lỗi không tính vào hạn mức; lấy ảnh khác.\nMỗi ảnh là một truyện, không nối các clip với nhau.',
                   color=MUTED, size=9, wraplength=355).pack(anchor='w', pady=12)
        self.button(production, 'Lưu cấu hình', self.save_production, primary=True).pack(anchor='w')
        mode = self.snapshot.get('production_mode', 'scheduled')
        saved = 'Theo lịch đăng' if mode == 'scheduled' else f"Sản xuất sớm · {self.snapshot.get('daily_production_limit', 5)} clip/ngày"
        self.label(production, 'Đang lưu: ' + saved, color=MUTED, size=9).pack(anchor='w', pady=9)

        self.label(schedule, 'Giờ đăng', size=18, bold=True).pack(anchor='w')
        self.label(schedule, '  /  '.join(self.snapshot['slots']), size=25, color=ACCENT).pack(anchor='w', pady=(14, 8))
        self.label(schedule, 'Giờ Việt Nam · Mỗi lượt đăng một clip.', color=MUTED).pack(anchor='w')
        self.label(schedule, 'Đến giờ mới sản xuất và đăng.' if mode == 'scheduled' else
                   'Lấy clip đã làm sẵn trong hàng chờ để đăng.', color=MUTED, wraplength=335).pack(anchor='w', pady=(5, 16))
        self.label(schedule, 'Tự động đã bật' if self.snapshot['enabled'] else 'Tự động đang tạm dừng',
                   bold=True, color=ACCENT).pack(anchor='w', pady=(0, 9))
        actions = tk.Frame(schedule, bg='white')
        actions.pack(fill='x')
        self.button(actions, 'Tạm dừng' if self.snapshot['enabled'] else 'Bật tự động',
                    lambda: self.toggle_automation(not self.snapshot['enabled']), primary=True).pack(side='left', padx=(0, 8))
        self.button(schedule, 'Sản xuất sớm hôm nay' if mode == 'ahead' else 'Chạy một lượt đăng',
                    lambda: self.launch('produce-ahead' if mode == 'ahead' else 'tick')).pack(anchor='w', pady=10)
        self.label(schedule, 'Tạm dừng sẽ dừng trước clip tiếp theo.', color=MUTED, size=9).pack(anchor='w')

        report = mapping(self.snapshot.get('production'))
        self.label(frame, 'Tiến độ sản xuất', size=16, bold=True).pack(anchor='w', pady=(20, 7))
        ready = sum(r.get('publication', {}) == {} and r.get('video') is not None for r in self.snapshot.get('rows', []))
        self.label(frame, f"{report.get('completed', 0)}/{report.get('limit', self.snapshot.get('daily_production_limit', 5))} hoàn thành"
                   f"   ·   {report.get('awaiting_approval',0)} chờ anh duyệt"
                   f"   ·   {report.get('ready_count', ready)} chờ đăng   ·   {report.get('failed', 0)} lỗi"
                   f"   ·   {report.get('uncertain', 0)} chờ đối soát", bold=True, color=ACCENT).pack(anchor='w')
        messages = {'quota_reached': 'Đã đủ hạn mức hôm nay.', 'source_exhausted': 'Không còn ảnh mới hợp lệ.',
                    'failure_cooldown': f"Lượt trước lỗi · nghỉ {int(report.get('retry_after_s',60))} giây trước ảnh tiếp theo.",
                    'reconciliation_required': 'Có lượt chưa rõ kết quả; cần đối soát trước khi sản xuất tiếp.',
                    'production_not_ready': 'Bộ sản xuất cả truyện thành một clip chưa sẵn sàng.',
                    'waiting_schedule': 'Hàng chờ đã cập nhật; clip sẵn sàng sẽ đợi giờ đăng.',
                    'publication_pending': 'Bài đăng chưa xác nhận; hồ sơ được giữ để đối soát.',
                    'producing': 'Đang sản xuất lần lượt từng truyện.', 'paused': 'Đang tạm dừng.'}
        message = messages.get(report.get('state'), 'Chưa có lượt sản xuất tự động đã ghi nhận.')
        if report.get('day'):
            message = f"Ngày {report['day']} · " + message
        self.label(frame, message, color=MUTED, wraplength=760).pack(anchor='w', pady=(6, 9))
        pacing = mapping(self.snapshot.get('chatgpt_pacing'))
        if pacing.get('next_request_at'):
            from datetime import datetime
            ready = datetime.fromtimestamp(pacing['next_request_at']).strftime('%H:%M:%S')
            text = ('ChatGPT đang giới hạn lượt gửi · chờ ít nhất đến ' if pacing.get('state') == 'rate_limit_wait'
                    else 'Nghỉ giữa các lượt ChatGPT · lượt tiếp theo sớm nhất ') + ready
            self.label(frame, text, color=MUTED, size=9).pack(anchor='w', pady=(0, 9))
        controls = tk.Frame(frame, bg='white')
        controls.pack(fill='x')
        self.button(controls, 'Xem log sản xuất', lambda: self.open_production_report()).pack(side='left', padx=(0, 8))
        self.button(controls, 'Kiểm tra FlowKit', lambda: self.launch('status', '--probe')).pack(side='left')
        for text, path in [('Ảnh nguồn', self.snapshot['input']), ('Video', self.snapshot['output'])]:
            self.button(controls, text, lambda p=path: self.open_local(p)).pack(side='left', padx=(8, 0))

    def save_production(self):
        from .sdk import ThoRemixClient
        try:
            raw = self.production_limit.get().strip()
            if not raw.isdecimal():
                raise ValueError('Hạn mức phải là số nguyên từ 1 đến 1000 clip hoàn thành mỗi ngày.')
            limit = int(raw)
            self.settings = ThoRemixClient(self.settings.directory).configure_production(
                mode=self.production_mode.get(), daily_limit=limit)
            self.refresh()
            self.status.configure(text='Đã lưu cấu hình. Hạn mức tính theo clip hoàn thành; không tự bật lại lịch.')
        except (ValueError, OSError) as exc:
            self.status.configure(text=str(exc) if isinstance(exc, ValueError) else 'Không lưu được cấu hình.')

    def toggle_automation(self, enabled):
        from .sdk import ThoRemixClient
        try:
            self.settings = ThoRemixClient(self.settings.directory).set_enabled(enabled)
            self.refresh()
            self.status.configure(text='Đã bật tự động; bộ lập lịch sẽ kiểm tra trong vòng 5 phút.' if enabled else
                                  'Đã tạm dừng; clip đang xử lý giữ nguyên và không bắt đầu clip tiếp theo.')
        except (ValueError, OSError):
            self.status.configure(text='Không cập nhật được trạng thái tự động.')

    def open_production_report(self):
        path = self.settings.data / 'reports' / 'production'
        if path.exists():
            self.open_local(path)
        else:
            self.status.configure(text='Chưa có báo cáo sản xuất. Báo cáo được tạo khi chạy lượt đầu tiên.')

    def _activity_rows(self):
        rows = list(self.snapshot.get('activity') or [])
        selected = ACTIVITY_FILTERS.get(self.activity_filter.get(), 'all')
        if selected == 'attention':
            rows = [row for row in rows if row.get('level') in {'error', 'attention'}]
        elif selected != 'all':
            rows = [row for row in rows if row.get('category') == selected]
        return rows

    def _activity_filter_changed(self, _event=None):
        self.show_page('activity')

    def _page_activity(self):
        frame = self._padded()
        notebook = ttk.Notebook(frame)
        notebook.pack(fill='both', expand=True)
        timeline = tk.Frame(notebook, bg='white', padx=12, pady=12)
        human = tk.Frame(notebook, bg='white', padx=12, pady=12)
        diagnostics = tk.Frame(notebook, bg='white', padx=12, pady=12)
        notebook.add(timeline, text='Nhật ký & trạng thái')
        notebook.add(human, text='Kết quả lệnh gần nhất')
        notebook.add(diagnostics, text='Diagnostics')

        toolbar = tk.Frame(timeline, bg='white')
        toolbar.pack(fill='x', pady=(0, 10))
        self.label(toolbar, 'Hiển thị', size=9, color=MUTED).pack(side='left', padx=(0, 6))
        box = ttk.Combobox(toolbar, textvariable=self.activity_filter,
                           values=tuple(ACTIVITY_FILTERS), state='readonly', width=19)
        box.pack(side='left')
        box.bind('<<ComboboxSelected>>', self._activity_filter_changed)

        all_events = list(self.snapshot.get('activity') or [])
        errors = sum(row.get('level') == 'error' for row in all_events)
        attention = sum(row.get('level') == 'attention' for row in all_events)
        waiting = sum(row.get('level') == 'waiting' for row in all_events)
        ok = sum(row.get('level') == 'ok' for row in all_events)
        self.label(toolbar, f'Lỗi {errors}   ·   Cần xử lý {attention}   ·   Đang/chờ {waiting}   ·   OK {ok}',
                   size=9, bold=True, color=ACCENT).pack(side='right')

        table_frame = tk.Frame(timeline, bg='white')
        table_frame.pack(fill='both', expand=True)
        columns = ('time', 'clip', 'action', 'channel', 'status')
        tree = ttk.Treeview(table_frame, columns=columns, show='headings',
                            style='Activity.Treeview', selectmode='browse', height=11)
        headings = {'time': 'Thời gian', 'clip': 'Clip / nguồn', 'action': 'Hành động',
                    'channel': 'Kênh', 'status': 'Trạng thái'}
        widths = {'time': 150, 'clip': 245, 'action': 180, 'channel': 90, 'status': 140}
        for column in columns:
            tree.heading(column, text=headings[column])
            tree.column(column, width=widths[column], anchor='w', stretch=column in {'clip', 'action'})
        scrollbar = ttk.Scrollbar(table_frame, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        tree.pack(fill='both', expand=True)
        tree.tag_configure('error', background='#fff0f0')
        tree.tag_configure('attention', background='#fff8e8')
        tree.tag_configure('ok', background='#eef9f1')
        tree.tag_configure('waiting', background='white')

        events = self._activity_rows()
        by_iid = {}
        for index, event in enumerate(events):
            iid = f'event-{index}'
            by_iid[iid] = event
            tree.insert('', 'end', iid=iid, tags=(event.get('level') or 'waiting',), values=(
                date_text(event.get('timestamp')),
                str(event.get('clip') or ''),
                str(event.get('action') or ''),
                str(event.get('channel') or '—'),
                str(event.get('status') or ''),
            ))

        detail = tk.Text(timeline, height=7, wrap='word', bg='#f7f8fb', fg=INK,
                         font=('Segoe UI', 9), relief='flat', bd=0, padx=10, pady=8,
                         highlightthickness=0)
        detail.pack(fill='x', pady=(10, 0))

        def show_detail(_event=None):
            selected = tree.selection()
            event = by_iid.get(selected[0]) if selected else None
            if not event:
                text = 'Chọn một dòng để xem chi tiết hành động và nguồn biên nhận.'
            else:
                parts = [
                    'Clip: ' + str(event.get('clip') or '—'),
                    'Thời gian: ' + date_text(event.get('timestamp')),
                    'Nhóm: ' + {'production':'Sản xuất','repair':'Sửa video','publishing':'Đăng kênh'}.get(
                        event.get('category'), str(event.get('category') or '—')),
                    'Hành động: ' + str(event.get('action') or '—'),
                    'Kênh: ' + str(event.get('channel') or '—'),
                    'Trạng thái: ' + str(event.get('status') or '—'),
                ]
                if event.get('detail'):
                    parts += ['', 'Chi tiết: ' + str(event['detail'])]
                if event.get('source'):
                    parts += ['', 'Nguồn biên nhận: ' + str(event['source'])]
                text = '\n'.join(parts)
            detail.configure(state='normal')
            detail.delete('1.0', 'end')
            detail.insert('1.0', text)
            detail.configure(state='disabled')

        tree.bind('<<TreeviewSelect>>', show_detail)
        if events:
            tree.selection_set('event-0')
            tree.focus('event-0')
        show_detail()
        self.activity_tree = tree

        issues = '\n'.join(self.snapshot.get('issues', []))
        last = mapping(self.snapshot.get('last'))
        saved = readable_result(str(last.get('command')), mapping(last.get('result'))) if last else 'Chưa có kết quả lệnh đã lưu.'
        self.text_panel(human, (issues + '\n\n' if issues else '') + self.activity +
                        '\n\nKẾT QUẢ ĐÃ LƯU\n' + saved)
        self.text_panel(diagnostics, self.diagnostics or json.dumps(last, ensure_ascii=False, indent=2),
                        diagnostic=True)

    def open_local(self, path):
        if Path(path).exists():
            try:
                os.startfile(str(Path(path).resolve()))
            except OSError:
                self.status.configure(text='Không mở được đường dẫn này. Kiểm tra ứng dụng mặc định của Windows.')
        else:
            self.status.configure(text='Đường dẫn chưa tồn tại: ' + str(path))

    def choose_package(self):
        chosen = filedialog.askdirectory(title='Chọn hồ sơ video đã kiểm tra', initialdir=self.settings.output, parent=self.window)
        if chosen:
            self.launch('publish', chosen)

    def facebook_name(self):
        value = simpledialog.askstring('Tên Page Facebook', 'Tên hiển thị chính xác của Page ThoRemixOfficial:', parent=self.window)
        if value and value.strip():
            self.launch('configure-facebook', '--name', value.strip())

    def launch(self, command, *arguments):
        if command=='approve':
            from .sdk import ThoRemixClient
            from .core import RunnerBusyError
            try:
                result=ThoRemixClient(self.settings.directory).request_approval(arguments[0],arguments[2])
                self.status.configure(text=readable_result(command,result))
                return True
            except (ValueError,OSError,RunnerBusyError):
                self.status.configure(text='Chưa lưu được yêu cầu duyệt; làm mới và xem lại hồ sơ.')
                return False
        if not self._reserve_action(command):
            self.status.configure(text='Hành động cùng nhóm đang chạy; các nút đọc/cấu hình an toàn vẫn dùng được.')
            return False
        self.status.configure(text='Đang mở trình duyệt đăng nhập; đóng trình duyệt khi xong.' if command == 'login' else f'Đang chạy {command}… Có thể tiếp tục xem dữ liệu đã lưu.')
        self.progress.pack(fill='x', pady=(8, 0))
        self.progress.start(14)
        def worker():
            try:
                logs = self.settings.directory / 'logs'
                logs.mkdir(parents=True, exist_ok=True)
                python = Path(sys.executable).with_name('python.exe') if os.name == 'nt' else Path(sys.executable)
                # Use this module's source tree, matching the UI revision in either install or checkout.
                source = Path(__file__).resolve().parents[2]
                with (logs / f'{command}.log').open('w', encoding='utf-8') as log:
                    process = subprocess.Popen([str(python), '-m', 'agent.thoremix.cli', '--root', str(self.settings.directory), command, *arguments],
                        cwd=source, env=dict(os.environ, PYTHONUTF8='1', THOREMIX_ROOT=str(self.settings.directory)),
                        stdout=log, stderr=log, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                    code = process.wait()
                data = (logs / f'{command}.log').read_text(encoding='utf-8')[-32000:]
                self.events.put((command, code, data))
            except Exception as exc:
                self.events.put((command, 2, json.dumps({'state': 'needs_input', 'reason': f'Không chạy được lệnh ({type(exc).__name__}). Kiểm tra nhật ký.'})))
        threading.Thread(target=worker, daemon=True).start()
        return True

    def _pump(self):
        if self.instance and self.instance.activation_pending():
            self.show_window()
        try:
            while self.alive:
                self._tray_command(self.ui_commands.get_nowait())
        except queue.Empty:
            pass
        if not self.alive:
            return
        if self.tray:
            try:
                self.tray.update(enabled=self.snapshot.get('enabled'), active=self.active)
            except Exception:
                self.tray.stop()
                self.tray = None
                self._tray_command('tray_unavailable')
        try:
            while True:
                command, code, data = self.events.get_nowait()
                self._release_action(command)
                if not self.active_groups:
                    self.progress.stop()
                    self.progress.pack_forget()
                self.diagnostics = data
                try:
                    self.activity = readable_result(command, mapping(json.loads(data)))
                except (ValueError, TypeError, KeyError, AttributeError):
                    self.activity = 'Lệnh đã dừng nhưng kết quả không đọc được. Xem Diagnostics và nhật ký.'
                self.status.configure(text=f'{command}: ' + ('đã kết thúc; xem kết quả trong Hoạt động.' if code == 0 else 'cần kiểm tra trong Hoạt động.'))
                if command=='retry-production':
                    self.retry_feedback[self.retry_job_id]=self.activity
                    self.status.configure(text='Đã cập nhật kết quả tiếp tục trong chi tiết truyện.')
                self.refresh()
                if command=='finish-unpublished' and self.page=='settings':
                    self.finish_feedback.configure(text=self.activity)
        except queue.Empty:
            pass
        if self.alive:
            self.window.after(200, self._pump)

    def _refresh_timer(self):
        if self.alive:
            # Keep a number being edited intact across the passive refresh.
            if not isinstance(self.window.focus_get(), (tk.Entry, tk.Spinbox)):
                self.refresh()
            self.window.after(10000, self._refresh_timer)

    def close(self):
        if self.tray and self.tray.available:
            self.window.withdraw()
        else:
            self.quit()

    def quit(self):
        self.alive = False
        if getattr(self,'review',None):self.review.close()
        # No terminate/kill: a child already launched retains its runner ownership.
        if self.tray:
            self.tray.stop()
        self.window.destroy()


def run_desktop(settings: Settings) -> None:
    from .tray import DesktopInstance

    instance = DesktopInstance()
    app = None
    try:
        if not instance.primary:
            return
        app = DesktopWindow(settings)
        if os.name == 'nt':
            app.enable_tray(instance)
        app.window.mainloop()
    finally:
        if app and app.tray:
            app.tray.stop()
        instance.close()
