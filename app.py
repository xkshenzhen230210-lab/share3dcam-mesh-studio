"""Windows desktop and command-line entry point."""
import argparse
import json
import os
import queue
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from converter import Control, Cancelled, convert, input_tree
from tiles import flatten, obj_nodes


def gui():
    import tkinter as tk
    from tkinter import ttk,filedialog,messagebox
    root=tk.Tk();root.title('SHARE Mesh 格式转换工具 1.0');root.geometry('900x700');root.minsize(780,620)
    root.configure(bg='#f2f5f9')
    style=ttk.Style();style.theme_use('clam')
    style.configure('.',font=('Microsoft YaHei UI',10),background='#f2f5f9')
    style.configure('TEntry',fieldbackground='white',padding=7)
    style.configure('TButton',padding=(14,9))
    style.configure('Accent.TButton',background='#146ce4',foreground='white',font=('Microsoft YaHei UI',11,'bold'))
    style.map('Accent.TButton',background=[('active','#0b55ba'),('disabled','#a2b5ce')])
    style.configure('TProgressbar',troughcolor='#dce4ef',background='#146ce4',thickness=10)
    main=ttk.Frame(root,padding=28);main.pack(fill='both',expand=True)
    ttk.Label(main,text='Mesh 格式转换',font=('Microsoft YaHei UI',23,'bold'),foreground='#14243b').pack(anchor='w')
    ttk.Label(main,text='GLB / 3D Tiles  →  OSGB / OBJ',foreground='#476581',font=('Segoe UI',12)).pack(anchor='w',pady=(5,20))
    source=tk.StringVar();target=tk.StringVar();fmt=tk.StringVar(value='OSGB + OBJ')
    status=tk.StringVar(value='选择模型文件或数据目录，开始转换。');progress=tk.DoubleVar(value=0)
    events=queue.Queue();event=threading.Event();running=False;last_output=None

    def suggest(path):
        source.set(path)
        p=Path(path);base=p if p.is_dir() else p.parent
        target.set(str(base.parent/(base.name+'_转换_'+datetime.now().strftime('%m%d_%H%M%S'))))
    row=ttk.Frame(main);row.pack(fill='x')
    ttk.Label(row,text='输入数据',font=('Microsoft YaHei UI',10,'bold')).pack(anchor='w')
    controls=ttk.Frame(row);controls.pack(fill='x',pady=(7,13))
    source_entry=ttk.Entry(controls,textvariable=source);source_entry.pack(side='left',fill='x',expand=True)
    def choose_file():
        path=filedialog.askopenfilename(title='选择 GLB 或 tileset.json',filetypes=[('三维模型 / Tileset','*.glb *.b3dm *.json'),('所有文件','*.*')])
        if path:suggest(path)
    def choose_folder():
        path=filedialog.askdirectory(title='选择 GLB 或 3D Tiles 数据目录')
        if path:suggest(path)
    file_button=ttk.Button(controls,text='选文件',command=choose_file);file_button.pack(side='left',padx=(8,4))
    folder_button=ttk.Button(controls,text='选目录',command=choose_folder);folder_button.pack(side='left')
    ttk.Label(main,text='输出目录',font=('Microsoft YaHei UI',10,'bold')).pack(anchor='w')
    controls=ttk.Frame(main);controls.pack(fill='x',pady=(7,5))
    target_entry=ttk.Entry(controls,textvariable=target);target_entry.pack(side='left',fill='x',expand=True)
    def choose_output():
        path=filedialog.askdirectory(title='选择新的空输出目录')
        if path:target.set(path)
    output_button=ttk.Button(controls,text='浏览…',command=choose_output);output_button.pack(side='left',padx=(8,0))
    ttk.Label(main,text='写入独立的新目录；大模型请预留足够空间。',foreground='#61738b').pack(anchor='w',pady=(0,17))
    options=ttk.Frame(main);options.pack(fill='x')
    ttk.Label(options,text='输出格式').pack(side='left',padx=(0,12))
    combo=ttk.Combobox(options,textvariable=fmt,values=['OSGB + OBJ','仅 OSGB','仅 OBJ'],state='readonly',width=17);combo.pack(side='left')
    ttk.Label(main,text='OSGB 保留 Tiles 层级和分页；OBJ 输出最终精度网格与贴图。\n单个 GLB 按源节点分块，输出静态分页 OSGB。',foreground='#61738b',justify='left').pack(anchor='w',pady=(12,16))
    bar=ttk.Frame(main);bar.pack(fill='x')
    def set_running(value):
        nonlocal running
        running=value
        for widget in [source_entry,target_entry,file_button,folder_button,output_button,start_button]:widget.configure(state='disabled' if value else 'normal')
        combo.configure(state='disabled' if value else 'readonly')
        cancel_button.configure(state='normal' if value else 'disabled')
        open_button.configure(state='normal' if last_output else 'disabled')
    def start():
        nonlocal last_output
        src=source.get().strip().strip('"');dst=target.get().strip().strip('"')
        if not src or not dst:messagebox.showerror('路径不完整','请选择输入数据和输出目录。');return
        event.clear();progress.set(0);log.configure(state='normal');log.delete('1.0','end');log.configure(state='disabled')
        last_output=dst;set_running(True);status.set('正在读取数据…')
        mode={'OSGB + OBJ':'both','仅 OSGB':'osgb','仅 OBJ':'obj'}[fmt.get()]
        def work():
            try:
                report=convert(src,dst,mode,Control(lambda text,pct:events.put(('progress',text,pct)),event))
                events.put(('done',f'转换完成 · 用时 {report["seconds"]:.1f} 秒',100))
            except Cancelled as e:events.put(('cancelled',str(e),0))
            except Exception as e:
                events.put(('error',str(e),0))
                if Path(dst).is_dir():
                    try:(Path(dst)/'error_details.txt').write_text(traceback.format_exc(),encoding='utf-8')
                    except OSError:pass
        threading.Thread(target=work,daemon=True).start()
    start_button=ttk.Button(bar,text='开始转换',style='Accent.TButton',command=start);start_button.pack(side='left')
    cancel_button=ttk.Button(bar,text='取消',state='disabled',command=lambda:(event.set(),status.set('正在停止，请稍候…')));cancel_button.pack(side='left',padx=8)
    open_button=ttk.Button(bar,text='打开输出目录',state='disabled',command=lambda:os.startfile(last_output) if Path(last_output).is_dir() else None);open_button.pack(side='right')
    ttk.Progressbar(main,variable=progress,maximum=100).pack(fill='x',pady=(18,8))
    ttk.Label(main,textvariable=status,foreground='#234363',wraplength=820).pack(anchor='w')
    logframe=ttk.Frame(main);logframe.pack(fill='both',expand=True,pady=(12,0))
    log=tk.Text(logframe,bg='#142235',fg='#d9e6f4',font=('Consolas',10),relief='flat',padx=12,pady=10,wrap='word',height=9,state='disabled')
    scroll=ttk.Scrollbar(logframe,command=log.yview);log.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');log.pack(fill='both',expand=True)
    def poll():
        try:
            while True:
                kind,text,pct=events.get_nowait();status.set(text)
                if kind in ('progress','done'):progress.set(pct)
                log.configure(state='normal');log.insert('end',datetime.now().strftime('%H:%M:%S')+'  '+text+'\n');log.see('end');log.configure(state='disabled')
                if kind in ('done','error','cancelled'):
                    set_running(False)
                    if kind=='error':messagebox.showerror('转换未完成',text)
        except queue.Empty:pass
        root.after(150,poll)
    def close():
        if running:
            event.set();status.set('正在停止转换，停止后可关闭窗口。')
        else:root.destroy()
    root.protocol('WM_DELETE_WINDOW',close);root.after(150,poll);root.mainloop()


def main():
    parser=argparse.ArgumentParser(description='SHARE mesh GLB/3D Tiles 转 OSGB/OBJ')
    parser.add_argument('--input');parser.add_argument('--output');parser.add_argument('--format',choices=['both','obj','osgb'],default='both')
    parser.add_argument('--inspect',action='store_true',help='只分析输入结构')
    args=parser.parse_args()
    if not args.input:gui();return
    try:
        if args.inspect:
            tree,source,kind=input_tree(args.input)
            result={'source':str(source),'kind':kind,'nodes':len(list(flatten(tree))),'obj_contents':len(obj_nodes(tree))}
            print(json.dumps(result,ensure_ascii=False,indent=2));return
        if not args.output:parser.error('--input 转换需要 --output')
        convert(args.input,args.output,args.format)
    except Exception as e:
        if sys.stderr:print(str(e),file=sys.stderr)
        raise SystemExit(1)

if __name__=='__main__':main()
