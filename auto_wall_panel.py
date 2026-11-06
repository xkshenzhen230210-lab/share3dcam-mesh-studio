"""One-click whole LAS inspection and wall/zone navigation."""
import math
import os
from pathlib import Path
import tkinter as tk
from tkinter import ttk
import numpy as np

from wall_flatness import UNIT_MM,wall_camera


def zone_camera(wall,zone,unit,aspect):
    factor=UNIT_MM[unit]/1000
    low,high=np.asarray(zone['uv_bounds'])+np.asarray(wall['uv_bounds'])[0]
    normal=np.asarray(wall['normal']);origin=np.asarray(wall['plane_origin']);center=np.asarray(wall['centroid'])
    corners=np.array([origin+(np.asarray(wall['u'])*x+np.asarray(wall['v'])*y)/factor
                      for x in (low[0],high[0]) for y in (low[1],high[1])])
    corners-=((corners-center)@normal)[:,None]*normal
    pad=.02/factor
    return wall_camera(dict(centroid=corners.mean(axis=0),normal=normal,
                           bounds=[corners.min(axis=0)-pad,corners.max(axis=0)+pad]),aspect)


class AutoWallPanel(ttk.Frame):
    def __init__(self,master,analyze,change_view,view_aspect=lambda:1.):
        super().__init__(master,padding=(9,8))
        self.analyze=analyze;self.change_view=change_view;self.view_aspect=view_aspect
        self.result=None;self.current=None;self.context=(False,False);self.objects={}
        self.project=tk.StringVar();self.site=tk.StringVar();self.operator=tk.StringVar()
        self.unit=tk.StringVar(value='m');self.tolerance=tk.StringVar(value='5');self.zone=tk.StringVar(value='2')
        self.visible=tk.BooleanVar(value=True);self.message=tk.StringVar(value='自动分析整份 LAS，不使用剪切盒。\nWhole scan; independent of clipping.')
        self.editors=[]
        footer=ttk.Frame(self);footer.pack(side='bottom',fill='x',pady=(5,0))
        self.pdf=ttk.Button(footer,text='完整报告 / Report',command=lambda:self.open_file('report.html'));self.pdf.pack(side='left')
        self.csv=ttk.Button(footer,text='表格 / CSV',command=lambda:self.open_file('分区统计.csv'));self.csv.pack(side='right')
        self.toggle=ttk.Checkbutton(self,text='分析着色 / Analysis colors',variable=self.visible,command=self.toggle_colors);self.toggle.pack(side='bottom',anchor='w',pady=(3,0))
        row=ttk.Frame(self);row.pack(fill='x',pady=(5,3))
        ttk.Label(row,text='单位 Units').pack(side='left')
        self.units=ttk.Combobox(row,textvariable=self.unit,values=list(UNIT_MM),width=3,state='readonly');self.units.pack(side='left',padx=4)
        ttk.Label(row,text='容差 ±mm').pack(side='left')
        entry=ttk.Entry(row,textvariable=self.tolerance,width=5);entry.pack(side='right');self.editors.append(entry)
        row=ttk.Frame(self);row.pack(fill='x',pady=3)
        ttk.Label(row,text='分区 Zone(m)').pack(side='left')
        entry=ttk.Entry(row,textvariable=self.zone,width=5);entry.pack(side='left',padx=4);self.editors.append(entry)
        self.metadata_button=ttk.Button(row,text='信息 / Info',command=self.edit_metadata);self.metadata_button.pack(side='right')
        self.run_button=ttk.Button(self,text='自动分析并生成报告 / Analyse',style='Accent.TButton',command=self.run)
        self.run_button.pack(fill='x',pady=(7,4))
        ttk.Label(self,textvariable=self.message,wraplength=275,justify='left',font=('Microsoft YaHei UI',9)).pack(anchor='w',pady=6)
        self.legend=tk.StringVar(value='编号分色；灰色未归属 / Wall IDs')
        ttk.Label(self,textvariable=self.legend,font=('Microsoft YaHei UI',9)).pack(anchor='w',pady=(0,4))
        tree_row=ttk.Frame(self);tree_row.pack(fill='both',expand=True)
        self.tree=ttk.Treeview(tree_row,columns=('max','status'),height=5,selectmode='browse')
        self.tree.heading('#0',text='墙面 / 分区');self.tree.column('#0',width=98,minwidth=80,stretch=True)
        self.tree.heading('max',text='偏差 mm');self.tree.column('max',width=64,minwidth=55,stretch=False,anchor='e')
        self.tree.heading('status',text='状态');self.tree.column('status',width=48,minwidth=40,stretch=False)
        self.tree.pack(side='left',fill='both',expand=True)
        scroll=ttk.Scrollbar(tree_row,orient='vertical',command=self.tree.yview);scroll.pack(side='right',fill='y');self.tree.configure(yscrollcommand=scroll.set)
        self.tree.tag_configure('outside',foreground='#b33128');self.tree.tag_configure('review',foreground='#946300');self.tree.tag_configure('within',foreground='#26734a')
        self.tree.bind('<<TreeviewSelect>>',self.select)
        for variable in (self.project,self.site,self.operator,self.unit,self.tolerance,self.zone):variable.trace_add('write',lambda *_:self.invalidate())
        self.set_context(False,False)

    def settings(self):
        tolerance=float(self.tolerance.get());size=float(self.zone.get());unit=self.unit.get()
        if not math.isfinite(tolerance) or tolerance<=0:raise ValueError('容差必须为正数 / Enter a positive tolerance')
        if not math.isfinite(size) or not .25<=size<=20:raise ValueError('分区边长：0.25～20 米 / Zone size: 0.25–20 m')
        if unit not in UNIT_MM:raise ValueError('请选择坐标单位 / Select units')
        return dict(unit=unit,tolerance_mm=tolerance,zone_size_m=size,
                    metadata=dict(project=self.project.get().strip(),site=self.site.get().strip(),operator=self.operator.get().strip()))

    def run(self):
        try:self.analyze(self.settings())
        except (ValueError,OSError) as error:self.message.set(str(error))

    def set_context(self,supported,busy):
        self.context=(supported,busy);ready=supported and not busy
        for widget in self.editors+[self.run_button,self.metadata_button]:widget.configure(state='normal' if ready else 'disabled')
        self.units.configure(state='readonly' if ready else 'disabled')
        for widget in (self.pdf,self.csv,self.toggle):widget.configure(state='normal' if self.result and not busy else 'disabled')

    def invalidate(self):
        had=self.result is not None;self.result=None;self.current=None;self.objects={}
        self.legend.set('编号分色；灰色未归属 / Wall IDs')
        for item in self.tree.get_children():self.tree.delete(item)
        if had:self.message.set('设置已更改，重新分析后生成新报告。\nSettings changed; analyse again.')
        self.set_context(*self.context)
        if had:self.change_view()

    def reset(self,source=None):
        self.invalidate()
        self.project.set(Path(source).stem if source else '')
        self.message.set('自动分析整份 LAS，不使用剪切盒。\nWhole scan; independent of clipping.' if source else '先导入 LAS / Import LAS first')

    def show_result(self,report):
        self.result=report;self.current=None;self.objects={};self.visible.set(True)
        self.legend.set('编号分色；灰色未归属 / Wall IDs')
        for item in self.tree.get_children():self.tree.delete(item)
        self.tree.insert('','end',iid='overview',text='全部 / All',values=('',''))
        status={'within':'容差内','outside':'超差','review':'复核'}
        for wall in report['walls']:
            self.objects[wall['id']]=(wall,None)
            self.tree.insert('','end',iid=wall['id'],text=wall['id'],values=(f'{wall["max_abs_mm"]:.2f}',status[wall['status']]),tags=(wall['status'],))
            for zone in wall['zones']:
                self.objects[zone['id']]=(wall,zone)
                self.tree.insert(wall['id'],'end',iid=zone['id'],text=zone['id'].split('-')[-1],values=(f'{zone["max_abs_mm"]:.2f}',status[zone['status']]),tags=(zone['status'],))
        self.message.set(f'{len(report["walls"])} 面墙候选 · {report["zone_count"]} 分区\n未归属 {report["unassigned_count"]:,} 点（不判定）')
        self.tree.selection_set('overview');self.set_context(*self.context)

    def select(self,_=None):
        if not self.result or self.context[1]:return
        selected=self.tree.selection()
        if not selected:return
        self.current=self.objects.get(selected[0]);self.visible.set(True)
        if self.current:
            self.legend.set(f'蓝 -{self.result["tolerance_mm"]:g} | 绿 0 | 红 +{self.result["tolerance_mm"]:g} mm')
            wall,zone=self.current
            camera=zone_camera(wall,zone,self.result['unit'],self.view_aspect()) if zone else wall_camera(wall,self.view_aspect())
            obj=zone or wall
            self.message.set(f'{obj["id"]} · {obj["count"]:,} 点\n最大 {obj["max_abs_mm"]:.3f} mm · 超差 {obj["outside_percent"]:.2f}%')
            self.change_view(camera=camera)
        else:
            self.legend.set('编号分色；灰色未归属 / Wall IDs')
            self.message.set(f'{len(self.result["walls"])} 面墙候选 · {self.result["zone_count"]} 分区\n未归属 {self.result["unassigned_count"]:,} 点（不判定）')
            self.change_view(view='fit')

    def overlay_path(self):
        if not self.result:return ''
        folder=Path(self.result['output'])/(self.current[0]['id'] if self.current else 'overview')
        if self.current and not self.visible.get():folder/='original'
        return str(folder/'model.spoints')

    def toggle_colors(self):
        if not self.visible.get():self.legend.set('原始颜色 / Original colors')
        elif self.current:self.legend.set(f'蓝 -{self.result["tolerance_mm"]:g} | 绿 0 | 红 +{self.result["tolerance_mm"]:g} mm')
        else:self.legend.set('编号分色；灰色未归属 / Wall IDs')
        self.change_view()

    def open_file(self,name):
        if self.result:
            try:os.startfile(Path(self.result['output'])/name)
            except OSError as error:self.message.set(f'无法打开 / Cannot open: {error}')

    def edit_metadata(self):
        dialog=tk.Toplevel(self);dialog.title('报告信息 / Report information');dialog.transient(self.winfo_toplevel());dialog.grab_set()
        panel=ttk.Frame(dialog,padding=16);panel.pack(fill='both',expand=True)
        for row,(label,variable) in enumerate([('项目 / Project',self.project),('位置 / Site',self.site),('编制人 / Author',self.operator)]):
            ttk.Label(panel,text=label).grid(row=row,column=0,sticky='w',pady=6,padx=(0,12))
            editor=ttk.Entry(panel,textvariable=variable,width=36);editor.grid(row=row,column=1,pady=6)
            if row==0:first=editor
        ttk.Button(panel,text='完成 / Done',command=dialog.destroy).grid(row=3,column=1,sticky='e',pady=(12,0))
        dialog.bind('<Escape>',lambda _:dialog.destroy())
        dialog.update_idletasks();parent=self.winfo_toplevel()
        x=max(0,parent.winfo_rootx()+(parent.winfo_width()-dialog.winfo_reqwidth())//2)
        y=max(0,parent.winfo_rooty()+(parent.winfo_height()-dialog.winfo_reqheight())//2)
        dialog.geometry(f'+{x}+{y}');first.focus_force();first.selection_range(0,'end')
