"""Metric report figures. Empty cells stay empty; cell colors retain extremes."""
from pathlib import Path
import sys
import numpy as np
import matplotlib
matplotlib.use('Agg')
from matplotlib import pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from matplotlib import font_manager
from matplotlib.patches import Rectangle

ASSETS=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))/'assets'
FONT=ASSETS/'NotoSansSC-Regular.ttf'
font_manager.fontManager.addfont(str(FONT))
plt.rcParams.update({'font.family':font_manager.FontProperties(fname=str(FONT)).get_name(),
                     'axes.unicode_minus':False,'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
COLORS=LinearSegmentedColormap.from_list('wall_deviation',['#1f59ff','#1fd159','#ff2e1f']).with_extremes(bad='#e7edf3')


def region_colors(count):
    import colorsys
    return np.array([colorsys.hsv_to_rgb((i*.61803398875)%1,.65,.82) for i in range(count)])


def overview(path,report,assets):
    fig,ax=plt.subplots(figsize=(10,7.3),layout='constrained')
    sample=assets['sample'];labels=assets['labels'];palette=region_colors(len(report['walls']))
    outside=labels<0
    ax.scatter(sample[outside,0],sample[outside,1],s=.7,c='#b8c2cf',alpha=.35,rasterized=True)
    inside=~outside
    if inside.any():ax.scatter(sample[inside,0],sample[inside,1],s=1.2,c=palette[labels[inside]],rasterized=True)
    low=sample[:,:2].min(axis=0);span=np.maximum(np.ptp(sample[:,:2],axis=0),.1)
    boxes=[]
    for i,wall in enumerate(report['walls']):
        xy=(np.asarray(wall['centroid'])-assets['origin'])*assets['metres_per_unit'];q=(xy[:2]-low)/span
        candidates=[q]
        for ring in range(1,9):
            for angle in np.arange(0,2*np.pi,np.pi/4):candidates.append(q+ring*.035*np.array([np.cos(angle),np.sin(angle)]))
        label=candidates[-1]
        for choice in candidates:
            if not np.all((choice>-.07)&(choice<1.07)):continue
            if all(abs(choice[0]-b[0])>.075 or abs(choice[1]-b[1])>.035 for b in boxes):label=choice;break
        boxes.append(label)
        ax.annotate(wall['id'],xy[:2],xytext=low+label*span,fontsize=8,ha='center',va='center',
                    bbox=dict(boxstyle='round,pad=.2',fc='white',ec=palette[i],lw=.8),
                    arrowprops=dict(arrowstyle='-',color=palette[i],lw=.6))
    ax.set(xlabel='局部 X / Local X (m)',ylabel='局部 Y / Local Y (m)',
           title='墙面定位总览 / Wall location overview')
    ax.set_aspect('equal');ax.grid(alpha=.15)
    ax.text(.01,-.13,'灰色：未归属 / Gray: unassigned · 位置以源坐标记录，图中坐标为局部米制',transform=ax.transAxes,fontsize=8,color='#53657b')
    fig.savefig(path,dpi=180,facecolor='white',bbox_inches='tight');plt.close(fig)


def wall_map(path,wall,raster,tolerance,factor):
    minimum,maximum=raster['minimum'],raster['maximum']
    extreme=np.where(np.abs(minimum)>np.abs(maximum),minimum,maximum)
    data=np.ma.masked_where(raster['count']==0,extreme).T
    resolution=raster['resolution'];shape=raster['shape']
    fig,ax=plt.subplots(figsize=(10,4.7),layout='constrained')
    im=ax.imshow(data,origin='lower',extent=[0,shape[0]*resolution,0,shape[1]*resolution],
                 interpolation='nearest',cmap=COLORS,vmin=-tolerance,vmax=tolerance,aspect='equal')
    for zone in wall['zones']:
        lo,hi=np.asarray(zone['uv_bounds']);size=hi-lo
        ax.add_patch(Rectangle(lo,*size,fill=False,edgecolor='#243449',linewidth=.7))
        if min(size)>.12:
            ax.text(*(lo+hi)/2,zone['id'].split('-')[-1],ha='center',va='center',fontsize=8,
                    bbox=dict(fc='white',ec='none',alpha=.78,pad=1.5))
    point=(np.asarray(wall['worst_point'])-wall['plane_origin'])*factor
    uv=point@np.column_stack((wall['u'],wall['v']))-np.asarray(wall['uv_bounds'])[0]
    ax.scatter(*uv,marker='x',color='#17263c',s=45,linewidths=1.4,zorder=5)
    ax.set(xlabel='墙面水平距离 / Wall U (m)',ylabel='墙面竖向距离 / Wall V (m)')
    fig.colorbar(im,ax=ax,shrink=.85,extend='both',label='有符号偏差 / Deviation (mm)')
    ax.set_title(f'{wall["id"]}  |  全量点网格极值 / All-point cell extremes',fontsize=11)
    fig.savefig(path,dpi=180,facecolor='white',bbox_inches='tight');plt.close(fig)


def wall_extraction(path,wall,index,assets):
    """Show only assigned wall RGB, with surrounding surfaces in a depth section.

    The section is diagnostic context, never added to the measured wall. Both
    panels use the same bounded source sample as the interactive wall preview.
    """
    factor=assets['metres_per_unit']
    center=(np.asarray(wall['plane_origin'])-assets['origin'])*factor
    rotation=np.column_stack((wall['u'],wall['v'],np.cross(wall['u'],wall['v'])))
    local=(assets['sample']-center)@rotation
    low,high=np.asarray(wall['uv_bounds'])
    selected=assets['labels']==index
    context=(~selected)&np.all((local[:,:2]>=low-.05)&(local[:,:2]<=high+.05),axis=1)&(np.abs(local[:,2])<=.35)
    fig,axes=plt.subplots(1,2,figsize=(10,3.1),layout='constrained')
    axes[0].scatter(local[selected,0]-low[0],local[selected,1]-low[1],c=assets['rgb'][selected],s=1.5,rasterized=True)
    axes[0].set_aspect('equal');axes[0].set(xlabel='U (m)',ylabel='V (m)',title='单独墙面原色 / Isolated wall RGB')
    for u,v in wall.get('overlap_cells',[]):
        axes[0].add_patch(Rectangle((u-.06,v-.06),.12,.12,fill=False,edgecolor='#e87508',linewidth=.9))
    axes[1].scatter(local[context,0]-low[0],local[context,2]*1000,c='#aeb9c6',s=1,rasterized=True,label='周边表面 / Context')
    axes[1].scatter(local[selected,0]-low[0],local[selected,2]*1000,c='#176399',s=1.5,rasterized=True,label='本墙面 / Wall')
    axes[1].set(xlabel='U (m)',ylabel='深度 / Depth (mm)',title='水平剖面 / Depth section',ylim=(-350,350))
    axes[1].legend(loc='upper right',fontsize=7,markerscale=3)
    for ax in axes:ax.grid(alpha=.15)
    fig.savefig(path,dpi=180,facecolor='white',bbox_inches='tight');plt.close(fig)
