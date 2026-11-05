"""Wall analysis controls; computation and viewport ownership stay in studio."""
import math
import os
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from wall_flatness import UNIT_MM, wall_camera


class FlatnessPanel(ttk.Frame):
    def __init__(self, master, select_wall, analyze, change_view, view_aspect=lambda:1.):
        super().__init__(master, padding=(10, 8))
        self.analyze = analyze
        self.change_view = change_view
        self.view_aspect = view_aspect
        self.result = None
        self.context = (False, False, False)
        self.unit = tk.StringVar(value='m')
        self.tolerance = tk.StringVar(value='5')
        self.show_colors = tk.BooleanVar(value=True)
        self.info = tk.StringVar(value='先导入 LAS 点云 / Import LAS first')
        self.summary = tk.StringVar(value='选取一面墙，排除家具和地面。\nSelect one wall; exclude objects and floors.')
        ttk.Label(self, text='墙面平整度 / Wall flatness', font=('Microsoft YaHei UI',12,'bold')).pack(anchor='w')
        ttk.Label(self, textvariable=self.info, wraplength=270, foreground='#536b85').pack(anchor='w', pady=(5,8))
        self.select_button = ttk.Button(self, text='① 选取墙面 / Select wall', command=select_wall)
        self.select_button.pack(fill='x')
        ttk.Label(self, text='用剪切盒只保留一面墙，再返回此页。\nIsolate a wall with the clipping box.', wraplength=270).pack(anchor='w', pady=(5,8))
        row = ttk.Frame(self); row.pack(fill='x')
        ttk.Label(row, text='源坐标单位 / Units').pack(side='left')
        self.unit_box = ttk.Combobox(row, textvariable=self.unit, values=list(UNIT_MM), width=5, state='readonly')
        self.unit_box.pack(side='right')
        row = ttk.Frame(self); row.pack(fill='x', pady=6)
        ttk.Label(row, text='容差 ± / Tolerance (mm)').pack(side='left')
        self.tolerance_entry = ttk.Entry(row, textvariable=self.tolerance, width=7)
        self.tolerance_entry.pack(side='right')
        self.run_button = ttk.Button(self, text='② 分析全量点 / Analyze', style='Accent.TButton', command=self.run)
        self.run_button.pack(fill='x', pady=(2,8))
        self.legend = tk.Canvas(self, width=265, height=16, highlightthickness=0)
        self.legend.pack(fill='x')
        self.legend.bind('<Configure>', self.draw_legend)
        self.legend_text = tk.StringVar(value='负 / −     0 mm     正 / +')
        ttk.Label(self, textvariable=self.legend_text, wraplength=275).pack(anchor='center')
        ttk.Label(self, textvariable=self.summary, wraplength=275, justify='left', font=('Microsoft YaHei UI',10)).pack(anchor='w', pady=8)
        self.color_button = ttk.Checkbutton(self, text='偏差色谱 / Deviation colors', variable=self.show_colors, command=change_view)
        self.color_button.pack(anchor='w')
        row = ttk.Frame(self); row.pack(fill='x', pady=6)
        self.face_button = ttk.Button(row, text='正对墙面 / Face wall', command=self.face_wall)
        self.face_button.pack(side='left')
        self.report_button = ttk.Button(row, text='报告 / Report', command=self.open_report)
        self.report_button.pack(side='right')
        ttk.Label(self, text='相对拟合平面的偏差；不是 2 米靠尺值。\nBest-fit plane deviation, not a 2 m straightedge.\n请核对单位；容差由你设置。\nVerify units; tolerance is user-defined.', wraplength=275,
                  foreground='#536b85', justify='left', font=('Microsoft YaHei UI',9)).pack(anchor='w', pady=5)
        self.unit.trace_add('write', lambda *_: self.invalidate())
        self.tolerance.trace_add('write', lambda *_: self.invalidate())
        self.set_context(False, False, False)

    def draw_legend(self, event=None):
        from wall_flatness import deviation_colors
        import numpy as np
        self.legend.delete('all')
        width = self.legend.winfo_width()
        colors = deviation_colors(np.linspace(-1,1,64),1)
        for i, color in enumerate(colors):
            value = '#'+''.join(f'{round(channel*255):02x}' for channel in color)
            self.legend.create_rectangle(i*width/64,0,(i+1)*width/64+1,16,fill=value,outline='')

    def settings(self):
        tolerance = float(self.tolerance.get())
        unit = self.unit.get()
        if unit not in UNIT_MM or not math.isfinite(tolerance) or tolerance <= 0:
            raise ValueError('请选择单位，容差必须为正数 / Select units and a positive tolerance')
        return unit, tolerance

    def run(self):
        try:
            unit, tolerance = self.settings()
            self.analyze(unit, tolerance)
        except ValueError as error:
            self.summary.set(str(error))

    def invalidate(self, message='设置或选区已更改，请重新分析。\nSettings/selection changed; analyze again.'):
        had_result = self.result is not None
        self.result = None
        self.legend_text.set('负 / −     0 mm     正 / +')
        if had_result:
            self.summary.set(message)
        self.set_context(*self.context)
        if had_result:
            self.change_view()

    def reset(self, info='先导入 LAS 点云 / Import LAS first'):
        self.result = None
        self.info.set(info)
        self.legend_text.set('负 / −     0 mm     正 / +')
        self.summary.set('选取一面墙，排除家具和地面。\nSelect one wall; exclude objects and floors.')
        self.set_context(*self.context)

    def set_context(self, supported, selected, busy):
        self.context = (supported, selected, busy)
        ready = supported and not busy
        for widget, available in ((self.select_button, ready), (self.run_button, ready and selected),
                                  (self.tolerance_entry, ready), (self.color_button, ready and self.result is not None),
                                  (self.face_button, ready and self.result is not None), (self.report_button, self.result is not None)):
            widget.configure(state='normal' if available else 'disabled')
        self.unit_box.configure(state='readonly' if ready else 'disabled')

    def show_result(self, result):
        self.result = result
        self.show_colors.set(True)
        self.legend_text.set(f'≤ −{result["tolerance_mm"]:g}    0 mm    ≥ +{result["tolerance_mm"]:g}')
        self.summary.set(
            f'统计 / Measured: {result["count"]:,} 点\n'
            f'最大绝对偏差 / Max: {result["max_abs_mm"]:.3f} mm\n'
            f'均方根 / RMS: {result["rms_mm"]:.3f} mm\n'
            f'峰谷差 / Range: {result["range_mm"]:.3f} mm\n'
            f'超差 / Outside: {result["outside_percent"]:.2f}%\n'
            f'显示 / Display: {result["preview_count"]:,} 点')
        if max(result['coordinate_steps_mm']) > result['tolerance_mm']:
            self.summary.set(self.summary.get()+'\n坐标步长大于容差 / Coarse coordinate steps')
        if result['planarity_ratio'] > .01:
            self.summary.set(self.summary.get()+'\n请检查是否混入其他物体 / Check selection')
        self.set_context(*self.context)

    def face_wall(self):
        if self.result:
            self.change_view(camera=wall_camera(self.result,self.view_aspect()))

    def open_report(self):
        if self.result:
            try:
                os.startfile(Path(self.result['output'])/'report.html')
            except OSError as error:
                self.summary.set(f'无法打开报告 / Cannot open report: {error}')
