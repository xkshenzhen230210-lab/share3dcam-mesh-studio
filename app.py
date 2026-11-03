"""Windows desktop and command-line entry point."""
import argparse
import json
import sys
from converter import convert, input_tree
from tiles import flatten, obj_nodes


def main():
    parser=argparse.ArgumentParser(description='SHARE3DCAM Mesh Studio 1.1.1: GLB/Tiles/OSGB/OBJ/PLY/STL to OSGB/OBJ')
    parser.add_argument('--input');parser.add_argument('--output');parser.add_argument('--format',choices=['both','obj','osgb'],default='both')
    parser.add_argument('--inspect',action='store_true',help='只分析输入结构')
    parser.add_argument('--review-obj',help='直接读取 OBJ 原图复核 / Review OBJ with original-resolution textures')
    parser.add_argument('--clip',type=float,nargs=6,metavar=('XMIN','YMIN','ZMIN','XMAX','YMAX','ZMAX'),help='保留剪切盒内模型 / Keep geometry inside box')
    args=parser.parse_args()
    if args.review_obj:
        from review_obj import gui as review_gui
        review_gui(args.review_obj);return
    if not args.input:
        from studio import gui as studio_gui
        studio_gui();return
    try:
        if args.inspect:
            tree,source,kind=input_tree(args.input)
            result={'source':str(source),'kind':kind,'nodes':len(list(flatten(tree))),'obj_contents':len(obj_nodes(tree))}
            print(json.dumps(result,ensure_ascii=False,indent=2));return
        if not args.output:parser.error('--input 转换需要 --output')
        convert(args.input,args.output,args.format,clip_box=args.clip)
    except Exception as e:
        if sys.stderr:print(str(e),file=sys.stderr)
        raise SystemExit(1)

if __name__=='__main__':main()
