"""Open the actual exported OBJ through OSG's independent OBJ reader, at original texture resolution."""
import json
import os
import subprocess
import tempfile
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from converter import RUNTIME,write_json


def gui(source):
    source=Path(source).resolve()
    if not source.is_file() or source.suffix.lower()!='.obj':raise ValueError('请选择 OBJ / Select an OBJ file')
    root=tk.Tk();root.title('SHARE3DCAM · OBJ 原图复核 / Original-texture OBJ review');root.geometry('1320x900');root.minsize(900,600)
    root.configure(bg='#111f32');style=ttk.Style();style.theme_use('clam');style.configure('TButton',padding=8,font=('Microsoft YaHei UI',10))
    tk.Label(root,text='SHARE3DCAM 电商销售中心  /  E-commerce Sales Center',bg='#111f32',fg='white',font=('Microsoft YaHei UI',17,'bold'),anchor='w').pack(fill='x',padx=20,pady=(16,5))
    tk.Label(root,text='OBJ 原图复核  ·  Original texture resolution  ·  直接读取 OBJ / MTL，贴图不缩放',bg='#111f32',fg='#becde0',font=('Microsoft YaHei UI',11),anchor='w').pack(fill='x',padx=20,pady=(0,10))
    toolbar=tk.Frame(root,bg='#111f32');toolbar.pack(fill='x',padx=18,pady=5)
    work=Path(tempfile.mkdtemp(prefix='share_obj_review_'));seq=0;wire=tk.BooleanVar();bounds=None;ready=False
    def command(view=''):
        nonlocal seq
        seq+=1;write_json(work/'command.json',{'seq':seq,'enabled':False,'showBox':False,'box':bounds or [-1,-1,-1,1,1,1],'view':view,'wire':wire.get()})
    for label,view in [('适应 / Fit','fit'),('顶视 / Top','top'),('正视 / Front','front'),('右视 / Right','right')]:ttk.Button(toolbar,text=label,command=lambda v=view:command(v)).pack(side='left',padx=3)
    ttk.Checkbutton(toolbar,text='线框 / Wireframe',variable=wire,command=command).pack(side='left',padx=15)
    pane=tk.Frame(root,bg='#0e141f');pane.pack(fill='both',expand=True,padx=18,pady=8)
    status=tk.StringVar(value='读取实际 OBJ 与原图贴图中 / Reading OBJ and original textures…')
    tk.Label(root,textvariable=status,bg='#111f32',fg='white',anchor='w').pack(fill='x',padx=20,pady=4)
    tk.Label(root,text=str(source),bg='#111f32',fg='#9cb2cf',anchor='w').pack(fill='x',padx=20,pady=(0,12))
    root.update_idletasks();write_json(work/'job.json',{'source':str(source),'parent':pane.winfo_id()})
    env=os.environ.copy();env['PATH']=str(RUNTIME)+os.pathsep+env.get('PATH','');env['OSG_LIBRARY_PATH']=str(RUNTIME/'osgPlugins-3.6.5')
    log=(work/'viewer.log').open('wb');process=subprocess.Popen([str(RUNTIME/'mesh_viewer.exe'),'job.json'],cwd=work,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
    def poll():
        nonlocal bounds,ready
        if not ready and (work/'state.json').exists():
            try:
                state=json.loads((work/'state.json').read_text(encoding='utf-8'))
                if state.get('ready'):bounds=state['bounds'];ready=True;status.set('已直接打开 OBJ · 原图分辨率 / OBJ loaded · Original texture resolution');command()
                elif state.get('error'):status.set(state['error'])
            except (OSError,ValueError):pass
        if process.poll() is not None and not ready:status.set('读取失败 / Load failed: '+str(work/'viewer.log'))
        root.after(200,poll)
    def close():
        if process.poll() is None:process.terminate();process.wait(timeout=5)
        log.close();root.destroy()
    root.protocol('WM_DELETE_WINDOW',close);root.after(200,poll);root.mainloop()

if __name__=='__main__':
    import sys
    gui(sys.argv[1])
