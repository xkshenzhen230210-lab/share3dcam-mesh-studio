"""Horizontal working frames; stored/output geometry always uses source coordinates."""
import math
import numpy as np


class ClipBox:
    def __init__(self, value):
        if isinstance(value, ClipBox):
            self.__dict__.update(value.__dict__)
            return
        self.oriented = isinstance(value, dict)
        try:
            self.bounds = np.asarray(value['bounds'] if self.oriented else value, dtype=float)
            self.origin = np.asarray(value.get('origin', [0, 0, 0]) if self.oriented else [0, 0, 0], dtype=float)
            self.yaw = float(value.get('yaw_degrees', 0) if self.oriented else 0)
            if self.bounds.shape != (6,) or self.origin.shape != (3,) or not np.isfinite(self.bounds).all() or not np.isfinite(self.origin).all() or not math.isfinite(self.yaw) or np.any(self.bounds[:3] >= self.bounds[3:]):
                raise ValueError()
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            raise ValueError('剪切盒范围无效 / Invalid clipping box') from error
        angle = math.radians(self.yaw)
        c, s = math.cos(angle), math.sin(angle)
        self.rotation = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])

    def local(self, xyz):
        return (np.asarray(xyz) - self.origin) @ self.rotation

    def world(self, xyz):
        return np.asarray(xyz) @ self.rotation.T + self.origin

    def contains(self, xyz):
        local = self.local(xyz)
        return np.all((local >= self.bounds[:3]) & (local <= self.bounds[3:]), axis=-1)

    def world_bounds(self):
        corners = self.world([[self.bounds[i], self.bounds[1+j], self.bounds[2+k]]
                              for i in (0, 3) for j in (0, 3) for k in (0, 3)])
        # Native extraction is only a broad phase; pad numerical roundoff outwards.
        lo, hi = corners.min(axis=0), corners.max(axis=0)
        pad = np.maximum(np.spacing(np.maximum(abs(lo), abs(hi)))*8, 1e-9)
        return np.r_[lo-pad, hi+pad].tolist()

    def tolist(self):
        if not self.oriented:
            return self.bounds.tolist()
        return dict(bounds=self.bounds.tolist(), origin=self.origin.tolist(), yaw_degrees=self.yaw)


def footprint_hull(xy):
    """Small exact convex footprint, including collinear/point-only data."""
    from scipy.spatial import ConvexHull, QhullError
    xy = np.asarray(xy, dtype=float)
    xy = xy[np.isfinite(xy).all(axis=1)]
    if len(xy) < 3:
        return np.unique(xy, axis=0)
    anchor = xy[0]
    try:
        return xy[ConvexHull(xy-anchor).vertices]
    except QhullError:
        # Collinear points are fully represented by extrema on both axes.
        return np.unique(xy[np.r_[xy.argmin(axis=0), xy.argmax(axis=0)]], axis=0)
