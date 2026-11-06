import unittest

import numpy as np
from scipy.spatial.transform import Rotation

from video import camera_at, validate_keyframes, _basis
from video_timing import playback_keyframes


def orbit(stamp, angle, center=(0, 0, 0), distance=10, fovy=35):
    rotation=Rotation.from_euler('Z',angle,degrees=True).as_matrix()
    return dict(time=stamp,eye=(np.array(center)+rotation@np.array([0,-distance,0])).tolist(),
                center=list(center),up=[0,0,1],fovy=fovy)


def rotation(pose):
    return Rotation.from_matrix(_basis(pose)[0])


class CameraMotionTests(unittest.TestCase):
    def test_middle_keys_keep_translation_and_turning_velocity(self):
        keys=validate_keyframes([orbit(t,a,(x,y,0)) for t,a,x,y in
                                 [(0,0,0,0),(2,30,2,0),(5,80,5,2),(9,140,8,4)]])
        h=1e-4
        for stamp in (2,5):
            before,at,after=[camera_at(keys,stamp+d) for d in (-h,0,h)]
            left=(np.array(at['center'])-before['center'])/h
            right=(np.array(after['center'])-at['center'])/h
            self.assertGreater(np.linalg.norm(left),.2,'Camera stops at an intermediate key')
            np.testing.assert_allclose(left,right,atol=2e-3)
            angular_left=(rotation(at)*rotation(before).inv()).as_rotvec()/h
            angular_right=(rotation(after)*rotation(at).inv()).as_rotvec()/h
            self.assertGreater(np.linalg.norm(angular_left),.05,'Turning stops at an intermediate key')
            np.testing.assert_allclose(angular_left,angular_right,atol=2e-3)

    def test_position_and_rotation_acceleration_join_smoothly(self):
        keys=validate_keyframes([orbit(t,a,(x,y,z),d,f) for t,a,x,y,z,d,f in
            [(0,0,0,0,0,10,35),(1.5,30,2,1,0,12,45),(5,70,4,4,1,16,55),(8,100,5,7,3,18,65)]])
        # One-sided second differences measure acceleration one step away from
        # the join; use a small step to separate jerk from an actual jump.
        h=1e-4
        for t in (1.5,5):
            poses=[camera_at(keys,t+k*h) for k in (-2,-1,0,1,2)]
            for name in ('eye','center','fovy'):
                values=np.array([p[name] for p in poses])
                left=(values[2]-2*values[1]+values[0])/h**2
                right=(values[4]-2*values[3]+values[2])/h**2
                np.testing.assert_allclose(left,right,atol=.04)
            rotations=[rotation(p) for p in poses]
            rates=[(b*a.inv()).as_rotvec()/h for a,b in zip(rotations,rotations[1:])]
            np.testing.assert_allclose((rates[1]-rates[0])/h,(rates[3]-rates[2])/h,atol=.015)

    def test_combined_roll_pitch_and_yaw_have_continuous_angular_motion(self):
        keys=[]
        for t,angles in [(0,(10,20,0)),(1,(40,10,70)),(3,(-20,45,160)),(6,(30,-50,230))]:
            matrix=Rotation.from_euler('XYZ',angles,degrees=True).as_matrix()
            keys.append(dict(time=t,eye=(matrix[:,2]*10).tolist(),center=[0,0,0],up=matrix[:,1].tolist(),fovy=35))
        keys=validate_keyframes(keys);h=1e-4
        for t in (1,3):
            r=[rotation(camera_at(keys,t+k*h)) for k in (-2,-1,0,1,2)]
            v=[(b*a.inv()).as_rotvec()/h for a,b in zip(r,r[1:])]
            self.assertGreater(np.linalg.norm(v[1]),.05)
            np.testing.assert_allclose(v[1],v[2],atol=.002)
            np.testing.assert_allclose((v[1]-v[0])/h,(v[3]-v[2])/h,atol=.02)

    def test_translation_curve_is_stable_with_large_world_coordinates(self):
        keys=validate_keyframes([orbit(0,0),orbit(1,30,(1,0,0)),orbit(100,60,(1,2,0))])
        shift=np.array([1e7,-1e7,1e6])
        translated=[dict(k,eye=(np.array(k['eye'])+shift).tolist(),center=(np.array(k['center'])+shift).tolist()) for k in keys]
        for t in (.5,1,20,90):
            for name in ('eye','center'):
                np.testing.assert_allclose(np.array(camera_at(translated,t)[name])-shift,camera_at(keys,t)[name],atol=1e-8)
        # The short incoming segment cannot generate an unbounded outgoing handle.
        centers=np.array([camera_at(keys,t)['center'] for t in np.linspace(1,100,101)])
        self.assertLess(np.max(np.abs(centers[:,0]-1)),.5)
        tiny=validate_keyframes([orbit(0,0),orbit(.001,10,(.001,0,0)),orbit(100,90,(.001,2,0))])
        centers=np.array([camera_at(tiny,t)['center'] for t in np.linspace(.001,100,101)])
        self.assertLess(np.max(np.abs(centers[:,0]-.001)),.0005)

    def test_same_pose_hold_does_not_drift_or_wiggle(self):
        keys=validate_keyframes([orbit(0,0),orbit(2,50,(2,1,0),12,40),
                                 orbit(4,50,(2,1,0),12,40),orbit(7,90,(4,3,1))])
        for t in np.linspace(2,4,17):
            pose=camera_at(keys,t)
            for name in ('eye','center','up','fovy'):
                np.testing.assert_allclose(pose[name],keys[1][name],atol=1e-11)

    def test_beginning_and_end_have_gentle_speed_and_acceleration(self):
        keys=validate_keyframes([orbit(0,0),orbit(2,35,(2,1,0)),orbit(5,90,(5,4,0))])
        h=1e-4
        for t,sign in ((0,1),(5,-1)):
            a,b,c=[camera_at(keys,t+sign*i*h) for i in (0,1,2)]
            self.assertLess(np.linalg.norm((np.array(b['eye'])-a['eye'])/h),1e-4)
            self.assertLess(np.linalg.norm((np.array(c['eye'])-2*np.array(b['eye'])+a['eye'])/h**2),.1)

    def test_zoom_stays_between_key_values_and_all_poses_remain_valid(self):
        keys=validate_keyframes([orbit(0,0,distance=.1,fovy=5),orbit(.2,170,distance=100,fovy=120),
                                 orbit(7,340,distance=2,fovy=6),orbit(8,510,distance=20,fovy=80)])
        for a,b in zip(keys,keys[1:]):
            bounds=sorted([_basis(a)[1],_basis(b)[1]])
            for t in np.linspace(a['time'],b['time'],31):
                p=camera_at(keys,t);basis,distance=_basis(p)
                self.assertTrue(np.isfinite(basis).all())
                np.testing.assert_allclose(basis.T@basis,np.eye(3),atol=1e-12)
                self.assertGreaterEqual(distance,bounds[0]*(1-1e-10))
                self.assertLessEqual(distance,bounds[1]*(1+1e-10))
                self.assertGreaterEqual(p['fovy'],min(a['fovy'],b['fovy'])-1e-10)
                self.assertLessEqual(p['fovy'],max(a['fovy'],b['fovy'])+1e-10)

    def test_exact_keys_retiming_and_mutated_keys_do_not_use_stale_paths(self):
        keys=validate_keyframes([orbit(0,0),orbit(2,40,(2,1,0)),orbit(6,100,(5,4,0))])
        for key in keys:
            self.assertEqual(camera_at(keys,key['time']),{k:v for k,v in key.items() if k!='time'})
        for speed in (.25,.5,2,4):
            timed=playback_keyframes(keys,speed)
            for t in (0,.5,1.8,3,5.9,6):
                for name,value in camera_at(keys,t).items():
                    np.testing.assert_allclose(camera_at(timed,t/speed)[name],value,atol=1e-10)
        before=camera_at(keys,1);keys[1]['center'][0]+=1
        self.assertNotEqual(camera_at(keys,1),before)
