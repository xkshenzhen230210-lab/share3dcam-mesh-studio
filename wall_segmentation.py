"""Deterministic geometric wall candidates. All coordinates here are local metres.

Detection uses a bounded sample; membership is independent of report tolerance.
Near-vertical planes are candidates, not a semantic classification of buildings.
"""
from collections import deque
import numpy as np
from scipy.spatial import cKDTree
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components

VOXEL = .18
FOOTPRINT = .20
ASSIGN_BAND = .15
AMBIGUITY = .005


def basis(normal):
    normal=np.asarray(normal,dtype=float)
    u=np.cross([0.,0.,1.],normal);u/=np.linalg.norm(u)
    return u,np.cross(normal,u)


def plane(xyz):
    center=xyz.mean(axis=0);local=xyz-center
    values,vectors=np.linalg.eigh(local.T@local/max(1,len(xyz)))
    normal=vectors[:,0]
    if normal[np.argmax(np.abs(normal))]<0:normal=-normal
    return center,normal,values


def _local_planes(xyz):
    # Covariance is accumulated in local voxel coordinates, avoiding large
    # coordinate cancellation even for georeferenced surveys.
    anchor=xyz.min(axis=0)
    key=np.floor((xyz-anchor)/VOXEL).astype(np.int64)
    cells,inverse,counts=np.unique(key,axis=0,return_inverse=True,return_counts=True)
    local=xyz-anchor-key*VOXEL
    sums=np.stack([np.bincount(inverse,weights=local[:,i],minlength=len(cells)) for i in range(3)],axis=1)
    means=sums/counts[:,None]
    moments=np.empty((len(cells),3,3))
    for i in range(3):
        for j in range(i,3):
            moments[:,i,j]=moments[:,j,i]=np.bincount(inverse,weights=local[:,i]*local[:,j],minlength=len(cells))/counts-means[:,i]*means[:,j]
    values,vectors=np.linalg.eigh(moments)
    normals=vectors[:,:,0]
    stable=(counts>=5)&(values[:,1]>1e-5)&(values[:,0]<values[:,1]*.08)
    keep=stable&(np.abs(normals[:,2])<.30)
    return (anchor+cells*VOXEL+means)[keep],normals[keep]


def _sample_geometry(xyz,control=None):
    """Estimate normals on actual nearby surfaces, not shared coordinate voxels.

    The graph only connects approximately tangential neighbours. This prevents
    a parallel fixture from joining a wall across an empty gap in depth.
    """
    tree=cKDTree(xyz)
    distances,neighbours=tree.query(xyz,k=min(16,len(xyz)))
    normals=np.zeros_like(xyz)
    for start in range(0,len(xyz),16384):
        if control:control.check()
        stop=min(start+16384,len(xyz))
        points=xyz[neighbours[start:stop,:12]]
        local=points-points.mean(axis=1,keepdims=True)
        moments=np.einsum('nki,nkj->nij',local,local)
        values,vectors=np.linalg.eigh(moments)
        stable=(values[:,1]>1e-10)&(values[:,0]<values[:,1]*.25)
        normals[start:stop][stable]=vectors[stable,:,0]
    rows=[];columns=[]
    for start in range(0,len(xyz),16384):
        if control:control.check()
        stop=min(start+16384,len(xyz))
        row=np.repeat(np.arange(start,stop,dtype=np.int32),neighbours.shape[1]-1)
        col=neighbours[start:stop,1:].ravel()
        delta=xyz[col]-xyz[row]
        lengths=distances[start:stop,1:].ravel()
        compatible=np.abs(np.einsum('ij,ij->i',normals[row],normals[col]))>.8
        tangent=np.maximum(np.abs(np.einsum('ij,ij->i',delta,normals[row])),
                           np.abs(np.einsum('ij,ij->i',delta,normals[col])))
        keep=compatible&(lengths<=.12)&(tangent<=lengths*.7+1e-8)
        rows.append(row[keep]);columns.append(col[keep].astype(np.int32))
    row=np.concatenate(rows);col=np.concatenate(columns)
    graph=csr_matrix((np.ones(len(row),dtype=bool),(row,col)),
                     shape=(len(xyz),len(xyz)))
    return dict(tree=tree,xyz=xyz,normals=normals,graph=graph,
                radius=np.minimum(.12,np.maximum(.025,distances[:,-1]*1.5)))


def spatial_normals(xyz,field):
    distance,nearest=field['tree'].query(xyz)
    normals=field['normals'][nearest].copy()
    normals[distance>field['radius'][nearest]]=0
    return normals


def _connect_membership(wall,field):
    xyz=field['xyz']
    distance=np.abs((xyz-wall['centroid'])@wall['normal'])
    aligned=np.abs(field['normals']@wall['normal'])>.85
    selected=np.flatnonzero((distance<=ASSIGN_BAND)&aligned&_inside(xyz,wall))
    members=np.zeros(len(xyz),dtype=bool)
    if len(selected):
        _,components=connected_components(field['graph'][selected][:,selected],directed=False)
        # The footprint already distinguishes disconnected wall candidates.
        # Vote using the detected plane's seed locations. A larger neighbouring
        # surface must not steal a smaller wall merely because both fit the band.
        seed_nearest=field['tree'].query(wall['_seed_points'])[1]
        lookup=np.full(len(xyz),-1,dtype=np.int32);lookup[selected]=components
        seed_components=lookup[seed_nearest]
        votes=np.bincount(seed_components[seed_components>=0],minlength=components.max()+1)
        if not np.any(votes):votes=np.bincount(components[distance[selected]<.035],minlength=len(votes))
        if not np.any(votes):return
        winner=int(votes.argmax())
        members[selected[components==winner]]=True
    wall['_sample_members']=members
    wall['_normal_field']=field


def _components(cells):
    remaining=set(map(tuple,cells.tolist()))
    while remaining:
        first=min(remaining);remaining.remove(first);found=[first];queue=deque([first])
        while queue:
            x,y=queue.popleft()
            for dx in (-1,0,1):
                for dy in (-1,0,1):
                    neighbour=(x+dx,y+dy)
                    if neighbour in remaining:
                        remaining.remove(neighbour);found.append(neighbour);queue.append(neighbour)
        yield np.array(sorted(found),dtype=np.int64)


def detect_walls(xyz,control=None,max_walls=128):
    xyz=np.asarray(xyz,dtype=float)
    if len(xyz)<30:return [],False
    if xyz.ndim!=2 or xyz.shape[1]!=3 or not np.isfinite(xyz).all():raise ValueError('Invalid segmentation coordinates')
    centers,normals=_local_planes(xyz)
    walls=[];rng=np.random.default_rng(3107);iterations=0
    while len(centers)>=12 and len(walls)<max_walls:
        if control:control.check()
        # Voxel-weighted hypotheses prevent dense scan patches dominating area.
        best=np.zeros(len(centers),dtype=bool)
        for index in rng.choice(len(centers),min(96,len(centers)),replace=False):
            normal=normals[index]
            mask=(np.abs((centers-centers[index])@normal)<.035)&(np.abs(normals@normal)>.96)
            if np.count_nonzero(mask)>np.count_nonzero(best):best=mask
        if np.count_nonzero(best)<12:break
        centroid,normal,_=plane(centers[best])
        for _ in range(2):
            best=(np.abs((centers-centroid)@normal)<.04)&(np.abs(normals@normal)>.94)
            if np.count_nonzero(best)<12:break
            centroid,normal,_=plane(centers[best])
        if np.count_nonzero(best)<12:break
        u,v=basis(normal)
        candidate=centers[best]
        uv=(candidate-centroid)@np.column_stack((u,v))
        keys=np.floor(uv/FOOTPRINT).astype(np.int64)
        for component in _components(np.unique(keys,axis=0)):
            if len(component)*FOOTPRINT**2<.5:continue
            component_set=set(map(tuple,component.tolist()))
            selection=np.array([tuple(k) in component_set for k in keys])
            points=candidate[selection]
            projected=(points-centroid)@np.column_stack((u,v))
            if np.ptp(projected[:,1])<.8 or np.ptp(projected[:,0])<.45:continue
            if abs(normal[2])>.30:continue
            wall=dict(centroid=centroid.copy(),normal=normal.copy(),u=u,v=v,
                      cells=component,footprint=FOOTPRINT,
                      bounds=np.array([points.min(axis=0),points.max(axis=0)]),
                      seed_count=len(points),seed_area=len(component)*FOOTPRINT**2,
                      _seed_points=points)
            _prepare_membership(wall)
            walls.append(wall)
            if len(walls)>=max_walls:break
        centers,normals=centers[~best],normals[~best]
        iterations+=1
        if control:control.log(f'自动识别墙面 / Detecting walls: {len(walls)}',15+min(15,iterations/3))
    walls.sort(key=lambda w:tuple(np.round(w['bounds'].mean(axis=0),3)))
    limited=len(walls)>=max_walls
    if walls:
        field=_sample_geometry(xyz,control)
        for wall in walls:
            if control:control.check()
            _connect_membership(wall,field)
        walls=[wall for wall in walls if np.count_nonzero(wall.get('_sample_members',[]))>=30]
        del field['graph']
    for i,wall in enumerate(walls):wall['id']=f'W{i+1:03d}'
    return walls,limited


def _prepare_membership(wall):
    # A one-cell halo includes boundaries without connecting distant surfaces.
    cells=wall['cells'];halo=np.unique(np.concatenate([cells+[x,y] for x in (-1,0,1) for y in (-1,0,1)]),axis=0)
    minimum=halo.min(axis=0);shape=halo.max(axis=0)-minimum+1
    codes=(halo[:,0]-minimum[0])*shape[1]+halo[:,1]-minimum[1]
    wall['_membership']=(minimum,shape,np.sort(codes))


def _inside(xyz,wall):
    uv=(xyz-wall['centroid'])@np.column_stack((wall['u'],wall['v']))
    cells=np.floor(uv/wall['footprint']).astype(np.int64)
    minimum,shape,codes=wall['_membership']
    offset=cells-minimum
    valid=np.all((offset>=0)&(offset<shape),axis=1)
    encoded=offset[:,0]*shape[1]+offset[:,1]
    positions=np.searchsorted(codes,encoded)
    valid&=codes[np.minimum(positions,len(codes)-1)]==encoded
    return valid


def assign_points(xyz,walls,control=None,normals=None):
    xyz=np.asarray(xyz,dtype=float)
    labels=np.full(len(xyz),-1,dtype=np.int32)
    best=np.full(len(xyz),np.inf);second=best.copy()
    member_best=best.copy()
    if walls:
        field=walls[0]['_normal_field']
        support_distance,nearest=field['tree'].query(xyz)
        estimated=field['normals'][nearest].copy()
        supported=support_distance<=field['radius'][nearest]
        # Connect full-source points to the sampled surface locally. The small
        # depth allowance preserves narrow defects missing from the sample;
        # it is independent of distance to the fitted plane or report tolerance.
        delta=xyz-field['xyz'][nearest]
        depth=np.abs(np.einsum('ij,ij->i',delta,estimated))
        tangent=np.sqrt(np.maximum(0.,support_distance**2-depth**2))
        supported&=depth<=.025+.7*tangent+1e-8
        if normals is not None:
            length=np.linalg.norm(normals,axis=1);valid=np.isfinite(normals).all(axis=1)&(length>.5)&(length<1.5)
            estimated[valid]=normals[valid]/length[valid,None]
        normals=estimated
    for index,wall in enumerate(walls):
        if control:control.check()
        distances=np.abs((xyz-wall['centroid'])@wall['normal'])
        candidate=np.flatnonzero((distances<=ASSIGN_BAND)&(np.abs(normals@wall['normal'])>.85))
        if not len(candidate):continue
        candidate=candidate[_inside(xyz[candidate],wall)]
        d=distances[candidate];improved=d<best[candidate]
        previous=best[candidate].copy()
        second[candidate]=np.minimum(second[candidate],np.where(improved,previous,d))
        best[candidate[improved]]=d[improved]
        member=supported[candidate]&wall['_sample_members'][nearest[candidate]]
        chosen=candidate[member&(d<member_best[candidate])]
        member_best[chosen]=distances[chosen];labels[chosen]=index
    ambiguous=np.isfinite(second)&((second-np.where(np.isfinite(best),best,0))<=AMBIGUITY)
    labels[ambiguous]=-1
    return labels,ambiguous
