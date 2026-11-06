"""Windows desktop and command-line entry point."""
import argparse
import json
import sys
from converter import input_tree
from tiles import flatten, obj_nodes
from supervisor import convert_isolated,worker_main


def main():
    parser=argparse.ArgumentParser(description='SHARE3DCAM Mesh Studio 1.8.2: Mesh, LAS, automatic wall inspection and video')
    parser.add_argument('--input');parser.add_argument('--output');parser.add_argument('--format',choices=['both','obj','osgb','3dtiles','source'],default='both')
    parser.add_argument('--inspect',action='store_true',help='只分析输入结构')
    parser.add_argument('--worker-job',help=argparse.SUPPRESS)
    parser.add_argument('--inspection-job',help=argparse.SUPPRESS)
    parser.add_argument('--clip',type=float,nargs=6,metavar=('XMIN','YMIN','ZMIN','XMAX','YMAX','ZMAX'),help='保留剪切盒内模型 / Keep geometry inside box')
    args=parser.parse_args()
    if args.inspection_job:
        from inspection_job import worker_main as inspection_worker
        raise SystemExit(inspection_worker(args.inspection_job))
    if args.worker_job:raise SystemExit(worker_main(args.worker_job))
    if not args.input:
        from studio import gui as studio_gui
        studio_gui();return
    try:
        if args.inspect:
            from model_paths import resolve_model
            from point_data import is_point_source,point_info
            source=resolve_model(args.input)
            if is_point_source(source):
                print(json.dumps(point_info(source),ensure_ascii=False,indent=2));return
            tree,source,kind=input_tree(args.input)
            result={'source':str(source),'kind':kind,'nodes':len(list(flatten(tree))),'obj_contents':len(obj_nodes(tree))}
            print(json.dumps(result,ensure_ascii=False,indent=2));return
        if not args.output:parser.error('--input 转换需要 --output')
        convert_isolated(args.input,args.output,args.format,clip_box=args.clip)
    except Exception as e:
        if sys.stderr:print(str(e),file=sys.stderr)
        raise SystemExit(1)

if __name__=='__main__':main()
