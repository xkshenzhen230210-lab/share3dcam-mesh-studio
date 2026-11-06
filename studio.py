"""Bilingual desktop model viewer, clipping controls and conversion workspace."""
import hashlib
import json
import math
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from converter import Control,Cancelled,write_json,RUNTIME
from model_paths import resolve_model
from supervisor import convert_isolated
from video import render_video
from video_panel import VideoPanel
from workspace_tools import ClipHistory, available_output, read_recent, remember_model, save_view_snapshot
from flatness_panel import FlatnessPanel
from wall_flatness import analyze_wall
from auto_wall_panel import AutoWallPanel
from inspection_job import inspect_isolated

MODEL_TYPES=[('三维模型 / 3D models','*.glb *.b3dm *.json *.osgb *.obj *.ply *.stl *.las'),('所有文件 / All files','*.*')]


def resolve_source(value):
    return resolve_model(value)


def gui():
    root=tk.Tk();root.title('SHARE3DCAM Mesh Studio 1.8.1 | 模型工作台');root.geometry('1360x900+20+20');root.minsize(1180,820);root.configure(bg='#edf1f7')
    style=ttk.Style();style.theme_use('clam')
    style.configure('.',font=('Microsoft YaHei UI',10),background='#edf1f7',foreground='#17263c')
    style.configure('TButton',padding=(9,7));style.configure('TEntry',padding=6,fieldbackground='white')
    style.configure('Accent.TButton',background='#e5473b',foreground='white',font=('Microsoft YaHei UI',10,'bold'))
    style.map('Accent.TButton',background=[('active','#c6362c'),('disabled','#b9c1cd')])
    style.configure('TProgressbar',background='#e5473b',troughcolor='#d8e0eb',thickness=6)
    style.configure('TNotebook.Tab',font=('Microsoft YaHei UI',9),padding=(4,4))
    header=tk.Frame(root,bg='#101d30',height=106);header.pack(fill='x');header.pack_propagate(False)
    asset=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))/'assets/share3dcam.png'
    logo=tk.PhotoImage(file=str(asset)).subsample(2,2);tk.Label(header,image=logo,bg='#101d30').pack(side='left',padx=(24,28))
    brand=tk.Frame(header,bg='#101d30');brand.pack(side='left')
    tk.Label(brand,text='SHARE3DCAM 电商销售中心',fg='white',bg='#101d30',font=('Microsoft YaHei UI',18,'bold')).pack(anchor='w')
    tk.Label(brand,text='SHARE3DCAM E-commerce Sales Center',fg='#a8bbd2',bg='#101d30',font=('Segoe UI',11)).pack(anchor='w',pady=(5,0))
    tk.Label(header,text='MESH STUDIO  1.8.1\n网格 · 点云 · 墙面 · 视频',bg='#101d30',fg='#a8bbd2',font=('Microsoft YaHei UI',11),justify='right').pack(side='right',padx=24)
    main=ttk.Frame(root,padding=(18,12));main.pack(fill='both',expand=True)
    source=tk.StringVar();target=tk.StringVar();fmt=tk.StringVar(value='OSGB + OBJ');status=tk.StringVar(value='选择模型并点击打开 / Select a model and click Open')
    progress=tk.DoubleVar();enabled=tk.BooleanVar();show_box=tk.BooleanVar(value=True);wire=tk.BooleanVar();navigation_speed=tk.StringVar(value='1.5');mouse_sensitivity=tk.StringVar(value='1.0')
    events=queue.Queue();cancel=threading.Event();worker=None;viewer=None;viewer_log=None;ipc=None;loaded_source=None;bounds=None;seq=0;state_read=False;closing=False;pending=None
    clip_history=None;clip_valid=True;slider_drag=False;slider_changed=False;measure_reset=0;task_active=False
    last_result=None
    point_size=tk.StringVar(value='2')
    point_kind=None
    recent_path=Path(os.environ.get('LOCALAPPDATA',tempfile.gettempdir()))/'SHARE3DCAM/MeshStudio/recent.json'
    line=ttk.Frame(main);line.pack(fill='x');ttk.Label(line,text='模型 / Model',font=('Microsoft YaHei UI',10,'bold')).pack(side='left',padx=(0,12))
    entry=ttk.Entry(line,textvariable=source);entry.pack(side='left',fill='x',expand=True)
    def choose_file():
        p=filedialog.askopenfilename(parent=root,title='打开模型 / Open model',filetypes=MODEL_TYPES)
        if p:load_path(p)
    def choose_folder():
        p=filedialog.askdirectory(parent=root,title='打开模型文件夹 / Open model folder')
        if p:load_path(p)
    def choose_las():
        p=filedialog.askopenfilename(parent=root,title='导入 LAS 点云 / Import LAS point cloud',filetypes=[('LAS 点云 / LAS point cloud','*.las')])
        if p:load_path(p)
    def fill_recent():
        recent_menu.delete(0,'end')
        entries=read_recent(recent_path)
        if not entries:recent_menu.add_command(label='暂无记录 / No recent models',state='disabled')
        for p in entries:
            path=Path(p)
            label=f'{path.name}  ·  {path.parent}'
            if len(label)>100:label=f'{path.name}  ·  …{str(path.parent)[-70:]}'
            recent_menu.add_command(label=label,command=lambda value=p:load_path(value))
    file_btn=ttk.Button(line,text='文件 / File',command=choose_file);file_btn.pack(side='left',padx=5)
    folder_btn=ttk.Button(line,text='文件夹 / Folder',command=choose_folder);folder_btn.pack(side='left')
    recent_btn=ttk.Menubutton(line,text='最近 / Recent');recent_btn.pack(side='left',padx=(5,0))
    recent_menu=tk.Menu(recent_btn,tearoff=False,postcommand=fill_recent);recent_btn.configure(menu=recent_menu)
    open_btn=ttk.Button(line,text='打开 / Open',style='Accent.TButton');open_btn.pack(side='left',padx=(8,0))
    las_btn=ttk.Button(line,text='导入 LAS / Import LAS',command=choose_las);las_btn.pack(side='left',padx=(8,0))
    ttk.Label(main,text='GLB · 3D Tiles · OSGB · OBJ · PLY/3DGS · LAS · STL',foreground='#536b85').pack(anchor='w',pady=(8,5))
    mouse_row=ttk.Frame(main);mouse_row.pack(fill='x',pady=(0,5))
    ttk.Label(mouse_row,text='左键绕点 / L-drag orbit · 右键平移 / R-drag pan · 滚轮指向缩放 / Zoom at cursor · 双击居中 / Double-click center',foreground='#536b85').pack(side='left')
    ttk.Label(mouse_row,text='灵敏度 / Sensitivity').pack(side='left',padx=(18,4))
    mouse_entry=ttk.Spinbox(mouse_row,from_=.1,to=3.,increment=.1,textvariable=mouse_sensitivity,width=5);mouse_entry.pack(side='left')
    help_row=ttk.Frame(main);help_row.pack(fill='x',pady=(0,7))
    ttk.Label(help_row,text='点击视图后 WASD 移动 · Q 上升 / Up · E 下降 / Down · Shift 加速 / Fast · Ctrl 慢速 / Slow',foreground='#536b85').pack(side='left')
    ttk.Label(help_row,text='移动速度 / Speed (单位/s)').pack(side='left',padx=(18,4))
    move_entry=ttk.Spinbox(help_row,from_=.01,to=100000,increment=.5,textvariable=navigation_speed,width=7);move_entry.pack(side='left')
    content=ttk.Frame(main);content.pack(fill='both',expand=True)
    left=ttk.Frame(content);left.pack(side='left',fill='both',expand=True)
    toolbar=ttk.Frame(left);toolbar.pack(fill='x',pady=(0,7))
    def command(view='',camera=None,move=None):
        nonlocal seq
        if not ipc or not clip_history:return
        video_mode=notebook.select()==str(video_tab)
        try:speed=float(navigation_speed.get())
        except ValueError:speed=1.5
        try:sensitivity=float(mouse_sensitivity.get())
        except ValueError:sensitivity=1.
        if not math.isfinite(sensitivity) or not .1<=sensitivity<=3.:sensitivity=1.
        mouse_sensitivity.set(f'{sensitivity:g}')
        payload=dict(enabled=enabled.get(),showBox=show_box.get() and enabled.get() and not video_mode,wire=wire.get() and not video_mode,box=clip_history.box,view=view,aspect=16/9 if video_mode else 0,navigation_speed=speed if math.isfinite(speed) and speed>0 else 1.5,mouse_sensitivity=sensitivity,measure=notebook.select()==str(measure_tab),measure_reset=measure_reset)
        try:size=float(point_size.get())
        except ValueError:size=2.
        if not math.isfinite(size) or not 1<=size<=12:size=2.
        point_size.set(f'{size:g}')
        payload['point_size']=size
        automatic=flat_modes.select()==str(auto_tab)
        result=auto_panel.result if automatic else flat_panel.result
        if automatic:payload['analysis_source']=auto_panel.overlay_path()
        else:payload['analysis_source']=str(Path(result['output'])/'model.spoints') if result else ''
        payload['analysis_visible']=bool(result and notebook.select()==str(flat_tab) and ((auto_panel.visible.get() or auto_panel.current) if automatic else flat_panel.show_colors.get()))
        if automatic and result and notebook.select()==str(flat_tab):
            payload.update(enabled=False,showBox=False)
        if camera is not None:payload['camera']=camera
        if move is not None:payload['move']=move
        seq+=1;write_json(ipc/'command.json',dict(payload,seq=seq))
    move_entry.configure(command=command);move_entry.bind('<Return>',lambda _:command());move_entry.bind('<FocusOut>',lambda _:command())
    mouse_entry.configure(command=command);mouse_entry.bind('<Return>',lambda _:command());mouse_entry.bind('<FocusOut>',lambda _:command())
    def navigation_key(event):
        if not viewer or viewer.poll() is not None:return
        focused=root.focus_get()
        if focused is not None and focused.winfo_class() in ('Entry','TEntry','Spinbox','TSpinbox','Text','TCombobox','Treeview'):return
        direction={'w':[0,1,0],'s':[0,-1,0],'a':[-1,0,0],'d':[1,0,0],'q':[0,0,1],'e':[0,0,-1]}.get(event.keysym.lower())
        if direction:
            multiplier=(3 if event.state&1 else 1)*(.2 if event.state&4 else 1)
            command(move=[v*multiplier for v in direction]);return 'break'
    root.bind('<KeyPress>',navigation_key)
    def focus_editor(event):
        # The renderer owns a child HWND in another process. Explicitly reclaim
        # Windows focus when clicking an editor after navigating in that child.
        if event.widget.winfo_class() in ('Entry','TEntry','Spinbox','TSpinbox','Text','TCombobox'):
            event.widget.focus_force()
    root.bind('<ButtonPress-1>',focus_editor)
    view_buttons=[]
    for label,view in [('全景 / Fit','fit'),('顶视 / Top','top'),('正视 / Front','front'),('右视 / Right','right')]:
        button=ttk.Button(toolbar,text=label,command=lambda v=view:command(v))
        button.pack(side='left',padx=(0,5));view_buttons.append(button)
    snapshot_btn=ttk.Button(toolbar,text='截图 / PNG',command=lambda:take_snapshot());snapshot_btn.pack(side='left',padx=(4,0))
    ttk.Label(toolbar,text='点大小 / px').pack(side='left',padx=(10,3))
    point_entry=ttk.Spinbox(toolbar,from_=1,to=12,increment=1,textvariable=point_size,width=3,command=command)
    point_entry.pack(side='left');point_entry.bind('<Return>',lambda _:command());point_entry.bind('<FocusOut>',lambda _:command())
    wire_btn=ttk.Checkbutton(toolbar,text='线框 / Wireframe',variable=wire,command=command)
    wire_btn.pack(side='right')
    viewport=tk.Frame(left,bg='#0e141f',highlightbackground='#23344a',highlightthickness=1);viewport.pack(fill='both',expand=True)
    placeholder=tk.Label(viewport,text='3D MODEL WORKSPACE\n\n打开模型，开始查看与裁剪\nOpen a model to view and clip',bg='#0e141f',fg='#8195af',font=('Microsoft YaHei UI',16),justify='center');placeholder.place(relx=.5,rely=.5,anchor='center')
    side_outer=ttk.Frame(content,padding=(18,0,0,0),width=330);side_outer.pack(side='right',fill='y');side_outer.pack_propagate(False)
    notebook=ttk.Notebook(side_outer);notebook.pack(fill='both',expand=True)
    clip_tab=ttk.Frame(notebook);measure_tab=ttk.Frame(notebook,padding=(12,10));video_tab=ttk.Frame(notebook);flat_tab=ttk.Frame(notebook)
    notebook.add(clip_tab,text='剪切 Clip');notebook.add(measure_tab,text='测量 Measure');notebook.add(flat_tab,text='墙面 Wall');notebook.add(video_tab,text='视频 Video')
    ttk.Label(measure_tab,text='两点距离 / Two-point distance',font=('Microsoft YaHei UI',13,'bold')).pack(anchor='w',pady=(0,10))
    ttk.Label(measure_tab,text='左键依次点两处。拖动仍可转视角。\nClick two points. Drag to orbit.',wraplength=270,justify='left').pack(anchor='w')
    measure_text=tk.StringVar(value='请先打开模型 / Open a model first')
    ttk.Label(measure_tab,textvariable=measure_text,wraplength=275,justify='left',font=('Microsoft YaHei UI',11,'bold')).pack(anchor='w',pady=14)
    measure_clear=ttk.Button(measure_tab,text='清除 / Clear',command=lambda:clear_measure());measure_clear.pack(anchor='w')
    ttk.Label(measure_tab,text='按源坐标单位显示，基于当前预览拾取。\nUses source units and the visible preview.',foreground='#536b85',wraplength=275,justify='left').pack(anchor='w',pady=10)
    scroll=ttk.Scrollbar(clip_tab);scroll.pack(side='right',fill='y')
    canvas=tk.Canvas(clip_tab,bg='#edf1f7',highlightthickness=0,yscrollcommand=scroll.set);canvas.pack(fill='both',expand=True);scroll.configure(command=canvas.yview)
    side=ttk.Frame(canvas);side_window=canvas.create_window((0,0),window=side,anchor='nw')
    side.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')));canvas.bind('<Configure>',lambda e:canvas.itemconfigure(side_window,width=e.width))
    ttk.Label(side,text='剪切盒 / Clipping box',font=('Microsoft YaHei UI',14,'bold')).pack(anchor='w',pady=(0,12))
    def clip_toggle():
        if enabled.get() and not commit_clip():enabled.set(False)
        flat_panel.invalidate()
        sync_controls()
        command()
    clip_toggle_btn=ttk.Checkbutton(side,text='启用剪切预览 / Enable clipping',variable=enabled,command=clip_toggle)
    clip_toggle_btn.pack(anchor='w')
    box_edges_btn=ttk.Checkbutton(side,text='显示边框 / Show box edges',variable=show_box,command=command)
    box_edges_btn.pack(anchor='w',pady=(5,8))
    clip_actions=ttk.Frame(side);clip_actions.pack(fill='x',pady=(0,5))
    def focus_clip_box():
        if commit_clip():command('clip')
    fit_clip_btn=ttk.Button(clip_actions,text='聚焦盒内 / Fit box',command=focus_clip_box)
    fit_clip_btn.pack(side='left')
    undo_clip_btn=ttk.Button(clip_actions,text='撤回 / Undo',command=lambda:restore_clip(undo=True))
    undo_clip_btn.pack(side='left',padx=5)
    clip_note=tk.StringVar()
    ttk.Label(side,textvariable=clip_note,foreground='#9c3f28',wraplength=280,justify='left').pack(anchor='w')
    values=[tk.StringVar(value='0') for _ in range(6)];sliders=[];number_entries=[]
    def show_clip_box():
        for variable,value in zip(values,clip_history.box):
            variable.set(str(value))
    def commit_clip(restore=False):
        nonlocal slider_changed,clip_valid
        if not clip_history:return False
        try:
            changed=clip_history.edit((value.get() for value in values),record=not slider_drag or not slider_changed)
        except ValueError as error:
            clip_valid=restore
            clip_note.set(str(error)+'\n已保留上次预览 / Previous preview kept')
            if restore:show_clip_box()
            if not restore:flat_panel.invalidate()
            sync_controls()
            return False
        if slider_drag and changed:slider_changed=True
        clip_valid=True
        if changed:flat_panel.invalidate()
        clip_note.set('')
        sync_controls()
        if changed:command()
        return True
    def debounce(*_):
        nonlocal pending
        if pending is not None:root.after_cancel(pending)
        def update():
            nonlocal pending
            pending=None
            commit_clip(restore=not slider_drag)
        pending=root.after(85,update)
    def slider_begin(_):
        nonlocal slider_drag,slider_changed
        slider_drag=True;slider_changed=False
    def slider_end(_):
        # The native scale class processes the release after the widget binding.
        root.after_idle(finish_slider)
    def finish_slider():
        nonlocal slider_drag,pending
        if pending is not None:root.after_cancel(pending);pending=None
        commit_clip(restore=True)
        slider_drag=False
    for i in (0,3,1,4,2,5):
        label=f'{"XYZ"[i%3]} '+('最小 / Min' if i<3 else '最大 / Max')
        row=ttk.Frame(side);row.pack(fill='x',pady=(6,0));ttk.Label(row,text=label).pack(side='left');number=ttk.Entry(row,textvariable=values[i],width=20,justify='right');number.pack(side='right');number_entries.append(number)
        slider=ttk.Scale(side,variable=values[i],from_=-1,to=1,command=debounce);slider.pack(fill='x',pady=(3,7));sliders.append((i,slider))
        slider.bind('<ButtonPress-1>',slider_begin);slider.bind('<ButtonRelease-1>',slider_end)
        number.bind('<Return>',lambda _:commit_clip());number.bind('<FocusOut>',lambda _:commit_clip())
    def restore_clip(undo=False):
        nonlocal clip_valid
        if not clip_history:return
        if undo:
            if clip_valid:clip_history.undo()
        else:clip_history.edit(clip_history.original)
        flat_panel.invalidate()
        clip_valid=True
        show_clip_box();clip_note.set('');sync_controls();command()
    reset_clip_btn=ttk.Button(side,text='重置范围 / Reset bounds',command=restore_clip)
    reset_clip_btn.pack(fill='x',pady=(6,10))
    clip_description=tk.StringVar(value='保留盒内部分；切面不自动封口。\nKeep inside; cut surfaces stay open.\n\n缓存贴图 ≤ 512 px；导出保留原图。\nCached textures ≤ 512 px; exports use originals.')
    ttk.Label(side,textvariable=clip_description,foreground='#5b6f87',wraplength=285,justify='left',font=('Microsoft YaHei UI',9)).pack(anchor='w')
    export=ttk.Frame(main);export.pack(fill='x',pady=(14,8));ttk.Label(export,text='输出 / Output').pack(side='left',padx=(0,10));target_entry=ttk.Entry(export,textvariable=target);target_entry.pack(side='left',fill='x',expand=True)
    def choose_output():
        p=filedialog.askdirectory(parent=root,title='选择输出目录 / Choose output folder')
        if p:
            folder=Path(p)
            try:
                if any(folder.iterdir()):
                    folder/=f'{Path(source.get()).stem or "Model"}_export'
            except OSError as error:
                status.set(f'无法读取输出目录 / Cannot read output folder · {error}');return
            target.set(str(folder))
    output_btn=ttk.Button(export,text='浏览 / Browse',command=choose_output);output_btn.pack(side='left',padx=6)
    combo=ttk.Combobox(export,textvariable=fmt,values=['OSGB + OBJ','OSGB','OBJ','3D Tiles','原格式 / Source'],state='readonly',width=16);combo.pack(side='left')
    actions=ttk.Frame(main);actions.pack(fill='x');export_btn=ttk.Button(actions,text='转换完整模型 / Export full');export_btn.pack(side='left')
    crop_btn=ttk.Button(actions,text='导出盒内模型 / Export clipped',style='Accent.TButton');crop_btn.pack(side='left',padx=8)
    cancel_btn=ttk.Button(actions,text='取消任务 / Cancel',state='disabled',command=lambda:cancel_task());cancel_btn.pack(side='left')
    result_btn=ttk.Button(actions,text='打开成果目录 / Open result',command=lambda:open_result());result_btn.pack(side='right')
    ttk.Progressbar(main,variable=progress).pack(fill='x',pady=(12,6));ttk.Label(main,textvariable=status,wraplength=1330).pack(anchor='w')
    def sync_controls():
        blocked=task_active or (ipc is not None and not state_read) or closing
        ready=clip_history is not None and viewer is not None and viewer.poll() is None
        current=ready and source.get()==str(loaded_source)
        def switch(widget, available):
            widget.configure(state='normal' if available else 'disabled')
        for widget in (file_btn,folder_btn,las_btn,recent_btn,entry,target_entry,output_btn):
            switch(widget,not blocked)
        switch(open_btn,not blocked and bool(source.get().strip()))
        switch(export_btn,not blocked and bool(source.get().strip()) and (not ready or current))
        switch(crop_btn,not blocked and current and enabled.get() and clip_valid)
        switch(snapshot_btn,not blocked and ready)
        switch(point_entry,ready and point_kind=='points')
        for widget in (*view_buttons,wire_btn):
            switch(widget,ready)
        switch(cancel_btn,blocked and not closing)
        switch(result_btn,last_result is not None)
        for widget in (clip_toggle_btn,box_edges_btn,reset_clip_btn,measure_clear,*number_entries,*(slider for _,slider in sliders)):
            switch(widget,ready and not blocked)
        switch(fit_clip_btn,ready and not blocked and enabled.get() and clip_valid)
        switch(undo_clip_btn,ready and not blocked and (not clip_valid or bool(clip_history.history)))
        combo.configure(state='disabled' if blocked else 'readonly')
        video_panel.set_busy(blocked or not current)
        flat_panel.set_context(bool(current and loaded_source.suffix.lower()=='.las'),
                               enabled.get() and clip_valid,blocked)
        auto_panel.set_context(bool(current and loaded_source.suffix.lower()=='.las'),blocked)
    def busy(active):
        nonlocal task_active
        task_active=active
        sync_controls()
    def open_result():
        try:
            os.startfile(last_result)
        except OSError as error:
            status.set(f'无法打开成果目录 / Cannot open result · {error}')
    def stop_viewer():
        nonlocal viewer,viewer_log,ipc
        if viewer and viewer.poll() is None:viewer.terminate();viewer.wait(timeout=5)
        viewer=None
        if viewer_log:viewer_log.close();viewer_log=None
        if ipc:
            # Only this process's freshly created IPC directory is removed.
            import shutil
            shutil.rmtree(ipc,ignore_errors=True);ipc=None
    def start_viewer(path,original,default_target):
        nonlocal viewer,viewer_log,ipc,loaded_source,state_read,bounds,clip_history,clip_valid,pending,point_kind
        if original!=loaded_source:video_panel.reset()
        if pending is not None:root.after_cancel(pending);pending=None
        stop_viewer();bounds=None;clip_history=None;clip_valid=True;enabled.set(False);clip_note.set('')
        loaded_source=original;state_read=False
        if default_target is not None:target.set(str(default_target))
        measure_text.set('正在打开模型 / Opening model')
        point_kind=None
        flat_panel.reset('墙面分析支持 LAS / Wall analysis supports LAS')
        auto_panel.reset(original if original.suffix.lower()=='.las' else None)
        ipc=Path(tempfile.mkdtemp(prefix='share_view_'));root.update_idletasks()
        write_json(ipc/'job.json',{'source':str(path),'parent':viewport.winfo_id()})
        if path.suffix=='.spoints':
            info=json.loads(path.read_text(encoding='utf-8'))
            point_kind=info['kind']
            if original.suffix.lower()=='.las':flat_panel.info.set(f'LAS · {info["source_count"]:,} 点 / points\n预览 / Preview: {info["count"]:,}')
            clip_description.set(f'按点／高斯中心保留，边界高斯保持完整。\nKeep centers inside; Gaussians stay intact.\n\n预览 {info["count"]:,} / {info["source_count"]:,} 点\nPreview points; exports use all records.\n原格式裁剪保留全部字段。\nSource-format crop preserves all fields.')
        else:clip_description.set('保留盒内部分；切面不自动封口。\nKeep inside; cut surfaces stay open.\n\n缓存贴图 ≤ 512 px；导出保留原图。\nCached textures ≤ 512 px; exports use originals.')
        env=os.environ.copy();env['PATH']=str(RUNTIME)+os.pathsep+env.get('PATH','');env['OSG_LIBRARY_PATH']=str(RUNTIME/'osgPlugins-3.6.5')
        viewer_log=(ipc/'viewer.log').open('wb');viewer=subprocess.Popen([str(RUNTIME/'mesh_viewer.exe'),'job.json'],cwd=ipc,env=env,stdout=viewer_log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        placeholder.configure(text='模型显示中 / Starting viewer…')
        placeholder.place(relx=.5,rely=.5,anchor='center')
        status.set('正在创建模型视图 / Starting 3D view…')
        sync_controls()
    def launch(task):
        nonlocal worker
        if worker and worker.is_alive():return
        cancel.clear();busy(True);progress.set(0)
        def work():
            try:task(Control(lambda text,pct:events.put(('progress',text,pct)),cancel))
            except Cancelled:events.put(('error','任务已取消 / Task cancelled',0))
            except Exception as e:events.put(('error',str(e),0));events.put(('trace',traceback.format_exc(),0))
            finally:events.put(('idle','',0))
        worker=threading.Thread(target=work,daemon=True);worker.start()
    def load_path(path):
        source.set(path)
        open_model(auto_target=True)
    def open_model(auto_target=False):
        if task_active or (ipc is not None and not state_read) or closing:return
        requested=source.get().strip()
        if not requested:return
        default_target_needed=auto_target or not target.get().strip()
        def task(control):
            from point_data import is_point_source
            control.log('正在查找模型 / Finding model…',0)
            try:src=resolve_source(requested)
            except Exception as error:
                raise ValueError('打开失败 / Open failed · '+str(error)) from error
            default_target=None
            if default_target_needed:
                base=Path(requested.strip('"')).expanduser()
                base=base if base.is_dir() else base.parent
                default_target=base.parent/('SHARE3DCAM_export_'+datetime.now().strftime('%Y%m%d_%H%M%S'))
            point_source=is_point_source(src)
            if src.suffix.lower()=='.osgb':path=src
            else:
                cache=Path(os.environ.get('LOCALAPPDATA',tempfile.gettempdir()))/'SHARE3DCAM/MeshStudio/preview';cache.mkdir(parents=True,exist_ok=True)
                token=hashlib.sha256((str(src)+str(src.stat().st_mtime_ns)+str(src.stat().st_size)).encode()).hexdigest()[:20]
                # Tiles and external texture formats may change without their entry file changing.
                if src.suffix.lower() not in ('.glb','.stl'):token+='_'+datetime.now().strftime('%Y%m%d%H%M%S%f')
                folder=cache/token
                if not (folder/'mesh_result.json').is_file() or json.loads((folder/'mesh_result.json').read_text(encoding='utf-8')).get('state')!='succeeded':
                    if folder.exists():folder=cache/(token+'_'+str(time.time_ns()))
                    control.log('准备分页预览缓存 / Preparing paged preview cache…')
                    if point_source:
                        convert_isolated(src,folder,'pointcache',control,preview=True)
                    else:convert_isolated(src,folder,'osgb',control,preview=True)
                path=folder/'model.spoints' if point_source else folder/'osgb/Model.osgb'
            control.check();events.put(('viewer',(path,src,default_target),100))
        launch(task)
    def cancel_task():
        nonlocal loaded_source,state_read,bounds,clip_history
        cancel.set()
        if ipc is not None and not state_read:
            stop_viewer();loaded_source=None;bounds=None;clip_history=None;state_read=False
            placeholder.configure(text='打开已取消 / Open canceled')
            measure_text.set('请先打开模型 / Open a model first')
            status.set('已取消 / Canceled');progress.set(0)
            sync_controls()
        elif task_active:
            status.set('正在取消 / Canceling…')
    def current_source():
        if not loaded_source or not bounds or not viewer or viewer.poll() is not None:
            raise ValueError('请先打开模型 / Open a model first')
        return loaded_source
    def current_camera(done):
        current_source()
        requested=seq;folder=ipc;deadline=time.monotonic()+2
        baseline=(folder/'state.json').stat().st_mtime_ns
        def capture():
            if closing:return
            if ipc!=folder or not viewer or viewer.poll() is not None:
                done(None,ValueError('模型已切换或关闭 / Model changed or closed'));return
            try:
                state=json.loads((folder/'state.json').read_text(encoding='utf-8'))
                if (folder/'state.json').stat().st_mtime_ns!=baseline and state.get('applied_seq',-1)>=requested and 'camera' in state:
                    done(state['camera']);return
            except (OSError,ValueError):pass
            if time.monotonic()>deadline:
                done(None,ValueError('相机未响应，请稍后重试 / Camera did not respond; please retry'));return
            root.after(30,capture)
        root.after(30,capture)
    def export_video(filename,keys,resolution,fps):
        src=current_source()
        if enabled.get() and not clip_valid:raise ValueError('先修正剪切范围 / Fix the clipping bounds first')
        box=clip_history.box if enabled.get() else None
        def task(control):
            render_video(src,filename,keys,resolution,fps,control,clip_box=box)
            events.put(('result',(Path(filename).parent,f'视频已导出 / Video exported · {resolution} · {filename}'),100))
        launch(task)
    def take_snapshot():
        try:
            src=current_source()
        except ValueError as error:
            status.set(str(error));return
        pictures=Path.home()/'Pictures'
        filename=filedialog.asksaveasfilename(parent=root,title='保存视图截图 / Save view snapshot',
            initialdir=str(last_result or (pictures if pictures.is_dir() else Path.home())),
            initialfile=f'{src.stem}_{datetime.now():%Y%m%d_%H%M%S}.png',
            defaultextension='.png',filetypes=[('PNG image','*.png')])
        if not filename:return
        folder,process,requested=ipc,viewer,seq
        destination=Path(filename)
        def task(control):
            control.log('正在保存截图 / Saving snapshot…',5)
            save_view_snapshot(folder,destination,control,process,requested)
            events.put(('result',(destination.parent,f'截图已保存 / Snapshot saved · {destination}'),100))
        launch(task)
    def clear_measure():
        nonlocal measure_reset
        measure_reset+=1
        measure_text.set('请选择第一点 / Click the first point')
        command()
    def select_wall():
        if not clip_history:return
        enabled.set(True)
        clip_toggle()
        notebook.select(clip_tab)
        status.set('调整剪切盒，只保留一面墙，然后进入「墙面」分析 / Isolate one wall, then return to Wall')
    def analyze_current_wall(unit,tolerance):
        src=current_source()
        if not enabled.get():raise ValueError('先选取墙面范围 / Select a wall area first')
        if not commit_clip():raise ValueError('请修正选区范围 / Fix selection bounds')
        box=list(clip_history.box)
        destination=target.get().strip().strip('"')
        if not destination:raise ValueError('请选择输出目录 / Select output directory')
        folder=available_output(Path(destination)/'wall_analysis')
        flat_panel.invalidate()
        flat_panel.summary.set('正在读取选区全部原始点…\nReading all source points in selection…')
        def task(control):
            try:
                report=analyze_wall(src,folder,box,unit,tolerance,control)
                control.check();events.put(('flatness',report,100))
            except Exception as error:
                events.put(('flatness_error',str(error) or '已取消 / Canceled',0))
                raise
        launch(task)
    def analyze_whole_scan(settings):
        src=current_source()
        destination=target.get().strip().strip('"')
        if not destination:raise ValueError('请选择输出目录 / Select output directory')
        folder=available_output(Path(destination)/'wall_inspection')
        auto_panel.invalidate()
        auto_panel.message.set('正在自动分墙、计算全部归属点…\nDetecting walls and measuring source points…')
        def task(control):
            try:
                report=inspect_isolated(src,folder,settings,control)
                control.check();events.put(('inspection',report,100))
            except Cancelled:
                events.put(('inspection_error','已取消，没有生成新报告。\nCanceled; no new report.',0))
                raise
            except Exception as error:
                events.put(('inspection_error',str(error) or '已取消 / Canceled',0))
                raise
        launch(task)
    flat_modes=ttk.Notebook(flat_tab);flat_modes.pack(fill='both',expand=True)
    auto_tab=ttk.Frame(flat_modes);manual_tab=ttk.Frame(flat_modes)
    flat_modes.add(auto_tab,text='自动巡检 Auto');flat_modes.add(manual_tab,text='选区分析 Selection')
    auto_panel=AutoWallPanel(auto_tab,analyze_whole_scan,command,
                             lambda:viewport.winfo_width()/max(1,viewport.winfo_height()))
    auto_panel.pack(fill='both',expand=True)
    flat_scroll=ttk.Scrollbar(manual_tab);flat_scroll.pack(side='right',fill='y')
    flat_canvas=tk.Canvas(manual_tab,bg='#edf1f7',highlightthickness=0,yscrollcommand=flat_scroll.set)
    flat_canvas.pack(fill='both',expand=True);flat_scroll.configure(command=flat_canvas.yview)
    flat_panel=FlatnessPanel(flat_canvas,select_wall,analyze_current_wall,command,
                             lambda:viewport.winfo_width()/max(1,viewport.winfo_height()))
    flat_window=flat_canvas.create_window((0,0),window=flat_panel,anchor='nw')
    flat_panel.bind('<Configure>',lambda e:flat_canvas.configure(scrollregion=flat_canvas.bbox('all')))
    flat_canvas.bind('<Configure>',lambda e:flat_canvas.itemconfigure(flat_window,width=e.width))
    video_footer=ttk.Frame(video_tab,padding=(10,0,10,6));video_footer.pack(side='bottom',fill='x')
    video_body=ttk.Frame(video_tab);video_body.pack(fill='both',expand=True)
    video_scroll=ttk.Scrollbar(video_body);video_scroll.pack(side='right',fill='y')
    video_canvas=tk.Canvas(video_body,bg='#edf1f7',highlightthickness=0,yscrollcommand=video_scroll.set);video_canvas.pack(fill='both',expand=True);video_scroll.configure(command=video_canvas.yview)
    video_panel=VideoPanel(video_canvas,current_camera,lambda camera:command(camera=camera),current_source,export_video,footer=video_footer)
    video_window=video_canvas.create_window((0,0),window=video_panel,anchor='nw')
    video_panel.bind('<Configure>',lambda e:video_canvas.configure(scrollregion=video_canvas.bbox('all')))
    video_canvas.bind('<Configure>',lambda e:video_canvas.itemconfigure(video_window,width=e.width))
    def scroll_sidebar(event):
        widget=event.widget
        if widget.winfo_class() in ('TCombobox','TSpinbox'):return
        while widget is not None:
            if widget in (canvas,video_canvas,flat_canvas):
                if widget.yview()!=(0.,1.):
                    widget.yview_scroll(-max(1,abs(event.delta)//120) if event.delta>0 else max(1,abs(event.delta)//120),'units')
                    return 'break'
                return
            widget=widget.master
    root.bind('<MouseWheel>',scroll_sidebar)
    def switch_tools(_=None):
        video_panel.stop();command()
    notebook.bind('<<NotebookTabChanged>>',switch_tools)
    flat_modes.bind('<<NotebookTabChanged>>',lambda _:command())
    def export_model(crop):
        try:
            src=resolve_source(source.get());dst=target.get().strip().strip('"')
            if not dst:raise ValueError('请选择输出目录 / Select output directory')
            if bounds and src!=loaded_source:raise ValueError('先打开新路径中的模型 / Open the new model first')
            box=None
            if crop:
                if src!=loaded_source or not bounds:raise ValueError('请先打开当前模型 / Open the current model first')
                if not enabled.get():raise ValueError('请先启用剪切盒 / Enable clipping first')
                if not commit_clip():return
                box=clip_history.box
        except Exception as e:status.set('无法导出 / Cannot export · '+str(e));return
        selected_format=fmt.get()
        def task(control):
            from point_data import is_point_source
            requested=Path(dst).expanduser().resolve()
            output=available_output(requested)
            if output!=requested:control.log(f'使用新的输出目录 / Using a new folder · {output}',0)
            mode='source' if is_point_source(src) else {'OSGB + OBJ':'both','OSGB':'osgb','OBJ':'obj','3D Tiles':'3dtiles'}.get(selected_format,'both')
            report=convert_isolated(src,output,mode,control,clip_box=box)
            events.put(('result',(output,f'导出完成 / Export complete · {report["seconds"]:.1f} s · {output}'),100))
        launch(task)
    open_btn.configure(command=open_model);export_btn.configure(command=lambda:export_model(False));crop_btn.configure(command=lambda:export_model(True));busy(False)
    def source_edited(*_):
        if source.get()!=str(loaded_source):
            flat_panel.invalidate();auto_panel.invalidate()
        sync_controls()
    source.trace_add('write',source_edited)
    entry.bind('<Return>',lambda _:open_model())
    def poll():
        nonlocal bounds,state_read,closing,clip_history,last_result
        try:
            while True:
                kind,text,pct=events.get_nowait()
                if kind=='viewer':
                    if not cancel.is_set() and not closing:start_viewer(*text)
                    continue
                if kind=='idle':busy(False);continue
                if kind=='flatness_error':flat_panel.summary.set(text);continue
                if kind=='inspection_error':auto_panel.message.set(text[:350]);continue
                if kind=='inspection':
                    if not cancel.is_set() and not closing:
                        auto_panel.show_result(text)
                        notebook.select(flat_tab);flat_modes.select(auto_tab)
                        last_result=Path(text['output'])
                        status.set(f'自动巡检完成 / Inspection complete · {len(text["walls"])} 墙面候选 · {text["zone_count"]} 分区 · '+str(last_result))
                        progress.set(100);command(view='fit');sync_controls()
                    continue
                if kind=='flatness':
                    if not cancel.is_set() and not closing:
                        flat_panel.show_result(text);flat_panel.face_wall()
                        last_result=Path(text['output'])
                        status.set('墙面分析完成，色谱和报告已生成 / Wall analysis complete · '+str(last_result));progress.set(100);sync_controls()
                    continue
                if kind=='result':last_result,text=text;sync_controls()
                if kind!='trace':status.set(text);progress.set(pct)
        except queue.Empty:pass
        if ipc and (not state_read or notebook.select() in (str(measure_tab),str(flat_tab))):
            try:
                state=json.loads((ipc/'state.json').read_text(encoding='utf-8'))
                if state.get('ready') and not state_read:
                    state_read=True;bounds=state['bounds']
                    from point_data import is_point_source
                    is_points=is_point_source(loaded_source)
                    combo.configure(values=['原格式 / Source'] if is_points else ['OSGB + OBJ','OSGB','OBJ','3D Tiles'])
                    if is_points:fmt.set('原格式 / Source')
                    elif fmt.get()=='原格式 / Source':fmt.set('OSGB + OBJ')
                    for i in range(3):
                        if bounds[i]>=bounds[i+3]:
                            pad=max(.01,math.ulp(bounds[i])*2)
                            bounds[i]-=pad;bounds[i+3]+=pad
                    clip_history=ClipHistory(bounds)
                    for i,slider in sliders:slider.configure(from_=bounds[i%3],to=bounds[i%3+3])
                    source.set(str(loaded_source))
                    try:remember_model(recent_path,loaded_source)
                    except OSError:pass
                    show_clip_box();command();placeholder.place_forget()
                    status.set('模型已打开 / Model ready · '+loaded_source.name);progress.set(100);busy(False)
                elif 'error' in state and not state_read:
                    state_read=True;status.set('显示失败 / Viewer error: '+state['error']);sync_controls()
                if notebook.select()==str(flat_tab) and state.get('analysis_error'):
                    status.set('色谱显示失败 / Color preview failed · '+state['analysis_error'])
                if state.get('ready') and notebook.select()==str(measure_tab):
                    measurement=state.get('measurement',{})
                    count=measurement.get('count',0)
                    if measurement.get('miss'):
                        text='此处没有拾取到模型点 / No surface here'
                        if count==1:text+='\n请重选第二点 / Try the second point again'
                    elif count==2:
                        dx,dy,dz=measurement['delta']
                        text=f'{measurement["distance"]:.6g} 源单位 / units\nΔX {dx:.5g}   ΔY {dy:.5g}   ΔZ {dz:.5g}'
                    elif count==1:text='已选第一点，请选第二点 / Click the second point'
                    else:text='请选择第一点 / Click the first point'
                    measure_text.set(text)
            except (OSError,ValueError):pass
        if viewer and viewer.poll() is not None and (not state_read or clip_history is not None):
            state_read=True;bounds=None;clip_history=None;enabled.set(False)
            status.set('查看器已停止 / Viewer stopped · '+str(ipc/'viewer.log'))
            placeholder.configure(text='请重新打开模型 / Reopen the model')
            placeholder.place(relx=.5,rely=.5,anchor='center')
            measure_text.set('请先打开模型 / Open a model first');sync_controls()
        if closing and not (worker and worker.is_alive()):stop_viewer();root.destroy();return
        root.after(150,poll)
    def close():
        nonlocal closing
        closing=True;video_panel.stop();cancel.set();status.set('正在结束任务 / Stopping…')
    root.protocol('WM_DELETE_WINDOW',close)
    root.after(150,poll);root.mainloop()
