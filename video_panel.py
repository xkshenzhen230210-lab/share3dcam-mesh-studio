"""Camera keyframe controls for the model workspace."""
import json
import math
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from converter import write_json
from video import camera_at, validate_keyframes


class VideoPanel(ttk.Frame):
    def __init__(self, parent, get_camera, set_camera, get_source, export, footer=None):
        super().__init__(parent, padding=(10, 8))
        self.get_camera, self.set_camera = get_camera, set_camera
        self.get_source, self.export = get_source, export
        self.keys = []
        self.play_task = None
        self.scrubbing = False
        self.is_busy = False
        self.recording = False
        self.controls = []
        self.seconds = tk.StringVar(value='0')
        self.position = tk.DoubleVar(value=0)
        self.resolution = tk.StringVar(value='1080p')
        self.fps = tk.StringVar(value='30')
        self.hint = tk.StringVar(value='调整视角后添加关键帧。\nMove the camera, then add a keyframe.')
        ttk.Label(self, text='相机动画 / Camera animation', font=('Microsoft YaHei UI', 12, 'bold')).pack(anchor='w')
        ttk.Label(self, text='16:9 画幅 · 平滑运镜\n16:9 framing · Smooth camera motion', foreground='#536b85').pack(anchor='w', pady=(5, 10))
        row = ttk.Frame(self); row.pack(fill='x')
        ttk.Label(row, text='时间 / Time (s)').pack(side='left')
        self.time_entry = ttk.Spinbox(row, from_=0, to=1800, increment=.5, textvariable=self.seconds, width=9)
        self.time_entry.pack(side='right'); self.controls.append(self.time_entry)
        self.button(self, '添加当前视角 / Add keyframe', self.add, accent=True).pack(fill='x', pady=(8, 8))
        self.tree = ttk.Treeview(self, columns=('time',), show='tree headings', height=6, selectmode='browse')
        self.tree.heading('#0', text='关键帧 / Key'); self.tree.column('#0', width=110, stretch=True)
        self.tree.heading('time', text='秒 / sec'); self.tree.column('time', width=70, stretch=False)
        self.tree.pack(fill='x'); self.tree.bind('<<TreeviewSelect>>', self.select)
        row = ttk.Frame(self); row.pack(fill='x', pady=7)
        self.button(row, '更新 / Update', self.replace).pack(side='left', fill='x', expand=True)
        self.button(row, '删除 / Delete', self.delete).pack(side='left', fill='x', expand=True, padx=(5, 0))
        self.button(self, '查看选中帧 / Go to keyframe', self.go).pack(fill='x')
        self.scale = ttk.Scale(self, from_=0, to=1, variable=self.position, command=self.seek)
        self.scale.pack(fill='x', pady=(12, 3)); self.controls.append(self.scale)
        self.clock = ttk.Label(self, text='0.00 / 0.00 s'); self.clock.pack(anchor='w')
        row = ttk.Frame(self); row.pack(fill='x', pady=(7, 10))
        self.button(row, '播放 / Play', self.play).pack(side='left', fill='x', expand=True)
        self.button(row, '停止 / Stop', self.stop).pack(side='left', fill='x', expand=True, padx=(5, 0))
        row = ttk.Frame(self); row.pack(fill='x')
        self.button(row, '保存 / Save', self.save).pack(side='left', fill='x', expand=True)
        self.button(row, '载入 / Load', self.load).pack(side='left', fill='x', expand=True, padx=(5, 0))
        export_area = footer if footer is not None else self
        ttk.Separator(export_area).pack(fill='x', pady=(4, 8))
        row = ttk.Frame(export_area); row.pack(fill='x')
        self.size_combo = ttk.Combobox(row, textvariable=self.resolution, values=['1080p', '4K'], width=9, state='readonly')
        self.size_combo.pack(side='left')
        ttk.Label(row, text='FPS').pack(side='left', padx=(12, 5))
        self.fps_combo = ttk.Combobox(row, textvariable=self.fps, values=['24', '30', '60'], width=6, state='readonly')
        self.fps_combo.pack(side='right')
        self.button(export_area, '导出 MP4 / Render video', self.render, accent=True).pack(fill='x', pady=(8, 4))
        ttk.Label(self, textvariable=self.hint, foreground='#536b85', wraplength=280, justify='left').pack(anchor='w')
        ttk.Label(self, text='导出使用原始贴图；沿用当前剪切范围。\nOriginal textures; current clipping applies.\n取消导出请点击下方“取消任务”。\nUse Cancel below to stop rendering.', foreground='#536b85', wraplength=280, font=('Microsoft YaHei UI', 9)).pack(anchor='w', pady=(10, 0))

    def button(self, parent, text, action, accent=False):
        def invoke():
            if self.is_busy: return
            try: action()
            except Exception as error: messagebox.showerror('视频 / Video', str(error), parent=self.winfo_toplevel())
        button = ttk.Button(parent, text=text, command=invoke, style='Accent.TButton' if accent else 'TButton')
        self.controls.append(button)
        return button

    def set_busy(self, active):
        self.is_busy = active
        if active: self.stop()
        disabled = active or self.recording
        for widget in self.controls: widget.configure(state='disabled' if disabled else 'normal')
        for widget in (self.size_combo, self.fps_combo): widget.configure(state='disabled' if disabled else 'readonly')

    def reset(self):
        self.stop(); self.keys = []; self.seconds.set('0'); self.refresh()

    def selected(self):
        selection = self.tree.selection()
        if not selection: raise ValueError('请先选择关键帧 / Select a keyframe first')
        return int(selection[0])

    def time_value(self):
        value = float(self.seconds.get())
        if not math.isfinite(value) or not 0 <= value <= 1800:
            raise ValueError('时间须在 0–1800 秒之间 / Time must be 0–1800 seconds')
        return value

    def update_key(self, replace=None):
        self.stop()
        value = self.time_value()
        if any(abs(k['time'] - value) < 1e-6 for i, k in enumerate(self.keys) if i != replace):
            raise ValueError('关键帧时间不能重复 / Keyframe times must be unique')
        self.recording = True; self.set_busy(self.is_busy)
        def captured(camera, error=None):
            self.recording = False; self.set_busy(self.is_busy)
            if error:
                messagebox.showerror('视频 / Video', str(error), parent=self.winfo_toplevel()); return
            key = dict(camera, time=value)
            if replace is None: self.keys.append(key)
            else: self.keys[replace] = key
            self.keys.sort(key=lambda k: k['time']); self.refresh()
            if replace is None: self.seconds.set(f'{min(1800, self.keys[-1]["time"] + 3):g}')
        try: self.get_camera(captured)
        except Exception:
            self.recording = False; self.set_busy(self.is_busy); raise

    def add(self): self.update_key()
    def replace(self): self.update_key(self.selected())

    def delete(self):
        self.stop(); del self.keys[self.selected()]; self.refresh()

    def select(self, _=None):
        if self.tree.selection(): self.seconds.set(f'{self.keys[self.selected()]["time"]:g}')

    def go(self):
        self.stop(); key = self.keys[self.selected()]
        self.set_camera(key); self.position.set(key['time']); self.update_clock()

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        for i, key in enumerate(self.keys): self.tree.insert('', 'end', iid=str(i), text=f'{i + 1:02d}', values=(f'{key["time"]:g}',))
        duration = self.keys[-1]['time'] if self.keys else 0
        self.scale.configure(to=max(duration, .01)); self.position.set(0); self.update_clock()
        self.hint.set(f'{len(self.keys)} 个关键帧 / keyframes · {duration:g} s\n首帧设为 0 秒；至少添加 2 帧。\nStart at 0 s; add at least 2 keyframes.')

    def update_clock(self):
        duration = self.keys[-1]['time'] if self.keys else 0
        self.clock.configure(text=f'{self.position.get():.2f} / {duration:.2f} s')

    def seek(self, value):
        if self.is_busy or self.scrubbing: return
        self.stop(); self.update_clock()
        try: self.set_camera(camera_at(validate_keyframes(self.keys), float(value)))
        except ValueError: pass

    def stop(self):
        if self.play_task is not None: self.after_cancel(self.play_task); self.play_task = None

    def play(self):
        keys = validate_keyframes(self.keys); self.stop()
        duration = keys[-1]['time']; start = self.position.get()
        if start >= duration: start = 0
        started = time.monotonic() - start
        def tick():
            value = min(duration, time.monotonic() - started)
            self.set_camera(camera_at(keys, value))
            self.scrubbing = True; self.position.set(value); self.scrubbing = False; self.update_clock()
            self.play_task = self.after(33, tick) if value < duration else None
        tick()

    def save(self):
        keys = validate_keyframes(self.keys)
        filename = filedialog.asksaveasfilename(parent=self, title='保存相机动画 / Save camera animation', defaultextension='.json', filetypes=[('相机动画 / Camera animation', '*.json')])
        if filename: write_json(filename, dict(version=1, source=str(self.get_source()), keyframes=keys))

    def load(self):
        filename = filedialog.askopenfilename(parent=self, title='载入相机动画 / Load camera animation', filetypes=[('相机动画 / Camera animation', '*.json')])
        if not filename: return
        path = Path(filename)
        if path.stat().st_size > 4_000_000: raise ValueError('动画文件过大 / Animation file is too large')
        data = json.loads(path.read_text(encoding='utf-8'))
        if data.get('version') != 1: raise ValueError('不支持的动画文件版本 / Unsupported animation version')
        keys = validate_keyframes(data['keyframes'])
        self.stop(); self.keys = keys; self.refresh()

    def render(self):
        keys = validate_keyframes(self.keys); source = self.get_source(); self.stop()
        filename = filedialog.asksaveasfilename(parent=self, title='导出视频 / Render video', initialfile=source.stem + '_camera.mp4', defaultextension='.mp4', filetypes=[('MP4 视频 / MP4 video', '*.mp4')])
        if filename: self.export(filename, keys, self.resolution.get(), int(self.fps.get()))
