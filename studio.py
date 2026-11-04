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
from converter import Control,Cancelled,convert,write_json,RUNTIME

MODEL_TYPES=[('三维模型 / 3D models','*.glb *.b3dm *.json *.osgb *.obj *.ply *.stl'),('所有文件 / All files','*.*')]


def resolve_source(value):
    p=Path(value.strip().strip('"')).resolve()
    if p.is_dir():
        for name in ('tileset.json','Model.osgb','Model.glb','Model.obj','Model.ply','Model.stl','osgb/Model.osgb','3dtiles/tileset.json','glb/Model.glb'):
            if (p/name).is_file():return p/name
        raise ValueError('目录中未找到模型入口 / No model entry found')
    if not p.is_file():raise ValueError('模型路径不存在 / Model not found')
    if p.suffix.lower() not in ('.glb','.b3dm','.json','.osgb','.obj','.ply','.stl'):raise ValueError('不支持此文件格式 / Unsupported file format')
    return p


def gui():
    root=tk.Tk();root.title('SHARE3DCAM Mesh Studio 1.1.2 | 模型工作台');root.geometry('1440x960');root.minsize(1180,820);root.configure(bg='#edf1f7')
    style=ttk.Style();style.theme_use('clam')
    style.configure('.',font=('Microsoft YaHei UI',10),background='#edf1f7',foreground='#17263c')
    style.configure('TButton',padding=(9,7));style.configure('TEntry',padding=6,fieldbackground='white')
    style.configure('Accent.TButton',background='#e5473b',foreground='white',font=('Microsoft YaHei UI',10,'bold'))
    style.map('Accent.TButton',background=[('active','#c6362c'),('disabled','#b9c1cd')])
    style.configure('TProgressbar',background='#e5473b',troughcolor='#d8e0eb',thickness=6)
    header=tk.Frame(root,bg='#101d30',height=106);header.pack(fill='x');header.pack_propagate(False)
    asset=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))/'assets/share3dcam.png'
    logo=tk.PhotoImage(file=str(asset)).subsample(2,2);tk.Label(header,image=logo,bg='#101d30').pack(side='left',padx=(24,28))
    brand=tk.Frame(header,bg='#101d30');brand.pack(side='left')
    tk.Label(brand,text='SHARE3DCAM 电商销售中心',fg='white',bg='#101d30',font=('Microsoft YaHei UI',18,'bold')).pack(anchor='w')
    tk.Label(brand,text='SHARE3DCAM E-commerce Sales Center',fg='#a8bbd2',bg='#101d30',font=('Segoe UI',11)).pack(anchor='w',pady=(5,0))
    tk.Label(header,text='MESH STUDIO  1.1.2\n模型查看 · 裁剪 · 转换',bg='#101d30',fg='#a8bbd2',font=('Microsoft YaHei UI',11),justify='right').pack(side='right',padx=24)
    main=ttk.Frame(root,padding=(18,12));main.pack(fill='both',expand=True)
    source=tk.StringVar();target=tk.StringVar();fmt=tk.StringVar(value='OSGB + OBJ');status=tk.StringVar(value='选择模型并点击打开 / Select a model and click Open')
    progress=tk.DoubleVar();enabled=tk.BooleanVar();show_box=tk.BooleanVar(value=True);wire=tk.BooleanVar()
    events=queue.Queue();cancel=threading.Event();worker=None;viewer=None;viewer_log=None;ipc=None;loaded_source=None;bounds=None;seq=0;state_read=False;closing=False;pending=None
    line=ttk.Frame(main);line.pack(fill='x');ttk.Label(line,text='模型 / Model',font=('Microsoft YaHei UI',10,'bold')).pack(side='left',padx=(0,12))
    entry=ttk.Entry(line,textvariable=source);entry.pack(side='left',fill='x',expand=True)
    def suggest(p):
        source.set(p);base=Path(p);base=base if base.is_dir() else base.parent
        target.set(str(base.parent/('SHARE3DCAM_export_'+datetime.now().strftime('%Y%m%d_%H%M%S'))))
    def choose_file():
        p=filedialog.askopenfilename(title='打开模型 / Open model',filetypes=MODEL_TYPES)
        if p:suggest(p)
    def choose_folder():
        p=filedialog.askdirectory(title='选择模型文件夹 / Select model folder')
        if p:suggest(p)
    file_btn=ttk.Button(line,text='文件 / File',command=choose_file);file_btn.pack(side='left',padx=5)
    folder_btn=ttk.Button(line,text='文件夹 / Folder',command=choose_folder);folder_btn.pack(side='left')
    open_btn=ttk.Button(line,text='打开 / Open',style='Accent.TButton');open_btn.pack(side='left',padx=(8,0))
    ttk.Label(main,text='GLB  ·  3D Tiles  ·  OSGB  ·  OBJ  ·  PLY  ·  STL     |     左键旋转 / Rotate  ·  中键平移 / Pan  ·  滚轮缩放 / Zoom',foreground='#536b85').pack(anchor='w',pady=(8,10))
    content=ttk.Frame(main);content.pack(fill='both',expand=True)
    left=ttk.Frame(content);left.pack(side='left',fill='both',expand=True)
    toolbar=ttk.Frame(left);toolbar.pack(fill='x',pady=(0,7))
    def command(view=''):
        nonlocal seq
        if not ipc or not bounds:return
        try:b=[float(v.get()) for v in values]
        except (ValueError,tk.TclError):return
        if not all(math.isfinite(x) for x in b) or any(b[i]>=b[i+3] for i in range(3)):return
        seq+=1;write_json(ipc/'command.json',dict(seq=seq,enabled=enabled.get(),showBox=show_box.get() and enabled.get(),wire=wire.get(),box=b,view=view))
    for label,view in [('适应 / Fit','fit'),('顶视 / Top','top'),('正视 / Front','front'),('右视 / Right','right')]:ttk.Button(toolbar,text=label,command=lambda v=view:command(v)).pack(side='left',padx=(0,5))
    def review_original_obj():
        try:
            path=resolve_source(source.get())
            if path.suffix.lower()!='.obj':raise ValueError('请先选择 OBJ 文件 / Select an OBJ file first')
            launcher=[sys.executable] if getattr(sys,'frozen',False) else [sys.executable,str(Path(__file__).parent/'app.py')]
            subprocess.Popen(launcher+['--review-obj',str(path)],creationflags=subprocess.CREATE_NO_WINDOW)
        except Exception as e:messagebox.showerror('原图复核 / Original-texture review',str(e))
    ttk.Button(toolbar,text='OBJ 原图复核 / Review OBJ',command=review_original_obj).pack(side='left',padx=5)
    ttk.Checkbutton(toolbar,text='线框 / Wireframe',variable=wire,command=command).pack(side='right')
    viewport=tk.Frame(left,bg='#0e141f',highlightbackground='#23344a',highlightthickness=1);viewport.pack(fill='both',expand=True)
    placeholder=tk.Label(viewport,text='3D MODEL WORKSPACE\n\n打开模型，开始查看与裁剪\nOpen a model to view and clip',bg='#0e141f',fg='#8195af',font=('Microsoft YaHei UI',16),justify='center');placeholder.place(relx=.5,rely=.5,anchor='center')
    side_outer=ttk.Frame(content,padding=(18,0,0,0),width=330);side_outer.pack(side='right',fill='y');side_outer.pack_propagate(False)
    scroll=ttk.Scrollbar(side_outer);scroll.pack(side='right',fill='y')
    canvas=tk.Canvas(side_outer,bg='#edf1f7',highlightthickness=0,yscrollcommand=scroll.set);canvas.pack(fill='both',expand=True);scroll.configure(command=canvas.yview)
    side=ttk.Frame(canvas);side_window=canvas.create_window((0,0),window=side,anchor='nw')
    side.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')));canvas.bind('<Configure>',lambda e:canvas.itemconfigure(side_window,width=e.width))
    ttk.Label(side,text='剪切盒 / Clipping box',font=('Microsoft YaHei UI',14,'bold')).pack(anchor='w',pady=(0,12))
    ttk.Checkbutton(side,text='启用六面剪切 / Enable clipping',variable=enabled,command=command).pack(anchor='w')
    ttk.Checkbutton(side,text='显示边框 / Show box edges',variable=show_box,command=command).pack(anchor='w',pady=(5,10))
    values=[tk.DoubleVar(value=0) for _ in range(6)];sliders=[];number_entries=[]
    def debounce(*_):
        nonlocal pending
        if pending:root.after_cancel(pending)
        def update():
            for value in values:
                try:value.set(round(value.get(),5))
                except tk.TclError:pass
            command()
        pending=root.after(100,update)
    for i,label in enumerate(['X 最小 / Min','Y 最小 / Min','Z 最小 / Min','X 最大 / Max','Y 最大 / Max','Z 最大 / Max']):
        row=ttk.Frame(side);row.pack(fill='x',pady=(6,0));ttk.Label(row,text=label).pack(side='left');number=ttk.Entry(row,textvariable=values[i],width=12);number.pack(side='right');number_entries.append(number)
        slider=ttk.Scale(side,variable=values[i],from_=-1,to=1,command=debounce);slider.pack(fill='x',pady=(3,7));sliders.append(slider);number.bind('<Return>',lambda _:command());number.bind('<FocusOut>',lambda _:command())
    def reset_box():
        if bounds:
            for v,b in zip(values,bounds):v.set(round(b,5))
            command()
    ttk.Button(side,text='重置范围 / Reset bounds',command=reset_box).pack(fill='x',pady=(6,10))
    ttk.Label(side,text='保留盒内部分；切面不自动封口。\nKeep inside; cut surfaces stay open.\n\n单位沿用源模型。缓存贴图 ≤ 512 px。\nSource units. Cached textures ≤ 512 px.\n导出保留原贴图精度。\nExports retain original texture resolution.',foreground='#5b6f87',wraplength=285,justify='left',font=('Microsoft YaHei UI',9)).pack(anchor='w')
    export=ttk.Frame(main);export.pack(fill='x',pady=(14,8));ttk.Label(export,text='输出 / Output').pack(side='left',padx=(0,10));target_entry=ttk.Entry(export,textvariable=target);target_entry.pack(side='left',fill='x',expand=True)
    def choose_output():
        p=filedialog.askdirectory(title='选择新的空输出目录 / Select empty output directory')
        if p:target.set(p)
    output_btn=ttk.Button(export,text='浏览 / Browse',command=choose_output);output_btn.pack(side='left',padx=6)
    combo=ttk.Combobox(export,textvariable=fmt,values=['OSGB + OBJ','OSGB','OBJ'],state='readonly',width=13);combo.pack(side='left')
    actions=ttk.Frame(main);actions.pack(fill='x');export_btn=ttk.Button(actions,text='转换完整模型 / Export full');export_btn.pack(side='left')
    crop_btn=ttk.Button(actions,text='导出盒内模型 / Export clipped',style='Accent.TButton');crop_btn.pack(side='left',padx=8)
    cancel_btn=ttk.Button(actions,text='取消任务 / Cancel',state='disabled',command=lambda:cancel.set());cancel_btn.pack(side='left')
    ttk.Button(actions,text='输出文件夹 / Open output',command=lambda:os.startfile(target.get()) if Path(target.get()).is_dir() else None).pack(side='right')
    ttk.Progressbar(main,variable=progress).pack(fill='x',pady=(12,6));ttk.Label(main,textvariable=status,wraplength=1330).pack(anchor='w')
    log=tk.Text(main,height=4,bg='#e1e7ef',fg='#324a65',font=('Consolas',9),relief='flat',padx=8,pady=5,state='disabled');log.pack(fill='x',pady=(6,0))
    def busy(active):
        for button in (file_btn,folder_btn,open_btn,export_btn,entry):button.configure(state='disabled' if active else 'normal')
        crop_btn.configure(state='normal' if not active and loaded_source and bounds else 'disabled');cancel_btn.configure(state='normal' if active else 'disabled')
    def stop_viewer():
        nonlocal viewer,viewer_log,ipc
        if viewer and viewer.poll() is None:viewer.terminate();viewer.wait(timeout=5)
        viewer=None
        if viewer_log:viewer_log.close();viewer_log=None
        if ipc:
            # Only this process's freshly created IPC directory is removed.
            import shutil
            shutil.rmtree(ipc,ignore_errors=True);ipc=None
    def start_viewer(path,original):
        nonlocal viewer,viewer_log,ipc,loaded_source,state_read,bounds
        stop_viewer();bounds=None;enabled.set(False);loaded_source=original;state_read=False
        ipc=Path(tempfile.mkdtemp(prefix='share_view_'));root.update_idletasks()
        write_json(ipc/'job.json',{'source':str(path),'parent':viewport.winfo_id()})
        env=os.environ.copy();env['PATH']=str(RUNTIME)+os.pathsep+env.get('PATH','');env['OSG_LIBRARY_PATH']=str(RUNTIME/'osgPlugins-3.6.5')
        viewer_log=(ipc/'viewer.log').open('wb');viewer=subprocess.Popen([str(RUNTIME/'mesh_viewer.exe'),'job.json'],cwd=ipc,env=env,stdout=viewer_log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        placeholder.configure(text='模型显示中 / Starting viewer…');status.set('正在创建模型视图 / Starting 3D view…')
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
    def open_model():
        try:src=resolve_source(source.get())
        except Exception as e:messagebox.showerror('打开失败 / Open failed',str(e));return
        def task(control):
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
                    convert(src,folder,'osgb',control,preview=True)
                path=folder/'osgb/Model.osgb'
            control.check();events.put(('viewer',(path,src),100))
        launch(task)
    def export_model(crop):
        try:
            src=resolve_source(source.get());dst=target.get().strip().strip('"')
            if not dst:raise ValueError('请选择输出目录 / Select output directory')
            box=None
            if crop:
                if src!=loaded_source or not bounds:raise ValueError('请先打开当前模型 / Open the current model first')
                if not enabled.get():raise ValueError('请先启用剪切盒 / Enable clipping first')
                box=[float(v.get()) for v in values]
                if not all(math.isfinite(x) for x in box) or any(box[i]>=box[i+3] for i in range(3)):raise ValueError('请输入有效范围，最小值须小于最大值 / Enter finite bounds with Min below Max')
        except Exception as e:messagebox.showerror('无法导出 / Cannot export',str(e));return
        mode={'OSGB + OBJ':'both','OSGB':'osgb','OBJ':'obj'}[fmt.get()]
        def task(control):
            report=convert(src,dst,mode,control,clip_box=box)
            events.put(('done',f'导出完成 / Export complete · {report["seconds"]:.1f} s · {dst}',100))
        launch(task)
    open_btn.configure(command=open_model);export_btn.configure(command=lambda:export_model(False));crop_btn.configure(command=lambda:export_model(True));busy(False)
    def poll():
        nonlocal bounds,state_read,closing
        try:
            while True:
                kind,text,pct=events.get_nowait()
                if kind=='viewer':start_viewer(*text);continue
                if kind=='idle':busy(False);continue
                if kind!='trace':status.set(text);progress.set(pct)
                log.configure(state='normal');log.insert('end',datetime.now().strftime('%H:%M:%S')+' '+text+'\n');log.see('end');log.configure(state='disabled')
        except queue.Empty:pass
        if ipc and not state_read and (ipc/'state.json').is_file():
            try:
                state=json.loads((ipc/'state.json').read_text(encoding='utf-8'))
                if state.get('ready'):
                    state_read=True;bounds=state['bounds']
                    for i in range(3):
                        if bounds[i]>=bounds[i+3]:bounds[i]-=.01;bounds[i+3]+=.01
                    for i,slider in enumerate(sliders):slider.configure(from_=bounds[i%3],to=bounds[i%3+3])
                    reset_box();placeholder.place_forget();status.set('模型已打开 / Model ready · '+loaded_source.name);progress.set(100);busy(False)
                elif 'error' in state:state_read=True;status.set('显示失败 / Viewer error: '+state['error'])
            except (OSError,ValueError):pass
        if viewer and viewer.poll() is not None and not state_read:
            state_read=True;status.set('查看器启动失败 / Viewer failed to start. '+str(ipc/'viewer.log'))
        if closing and not (worker and worker.is_alive()):stop_viewer();root.destroy();return
        root.after(150,poll)
    def close():
        nonlocal closing
        closing=True;cancel.set();status.set('正在结束任务 / Stopping…')
    root.protocol('WM_DELETE_WINDOW',close)
    sample=Path(r'V:\给泽强\2.7版本\mesh\2.7.5新\藏经阁\osgb\Model.osgb')
    if sample.is_file():suggest(str(sample))
    root.after(150,poll);root.mainloop()
