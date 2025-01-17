from typing import *
import os,json
from scipy.optimize import least_squares
from FileUtils import save_json, read_json, getFileList, makeDir ,getFileList_aligned
import glob
import g2o
import struct,random
import numpy as np
import cv2
from ChessBoard import detect_chessboard
import argparse
import pandas as pd #install tabulate

##intri
# 寻找单应矩阵，计算重投影误差
def reProjection(pointData,is_charu,num_board):
    if is_charu:
        error=0
        for board_index in range(num_board) :
            if f'mask_{board_index}' not in pointData:
                continue
            pointDetect = np.array(pointData[f'keyPoints2d_{board_index}'], dtype=np.float32)
            pointBoard = np.array(pointData[f'keyPoints3d_{board_index}'], dtype=np.float32)[:, :2]
            transMat, __ = cv2.findHomography(pointDetect, pointBoard, cv2.RANSAC, 1.0)
            # 使用perspectiveTransform时，需要注意，二维变三维， 整形转float型
            pointAfter = cv2.perspectiveTransform(pointDetect.reshape(1, -1, 2), transMat)
            pointAfter=  np.squeeze(pointAfter, axis=0)
            error+=np.sum((pointBoard-pointAfter)*(pointBoard-pointAfter))
            #print(pointBoard)
            #print(pointAfter)
            #print(pointBoard-pointAfter)
        return error
    else:
        pointDetect = np.array(pointData['keyPoints2d'], dtype=np.float32)
        pointBoard = np.array(pointData['keyPoints3d'], dtype=np.float32)[:, :2]
        transMat, __ = cv2.findHomography(pointDetect, pointBoard, cv2.RANSAC, 1.0)
        # 使用perspectiveTransform时，需要注意，二维变三维， 整形转float型
        pointAfter = cv2.perspectiveTransform(pointDetect.reshape(1, -1, 2), transMat)
        return np.sum((pointBoard - pointAfter) * (pointBoard - pointAfter))

#得到单个相机的内参K和畸变系数D后，对数据去畸变
def undistort(img_path,K,D,is_fisheye,k0,dim2,dim3,scale=0.6,imshow=False):#scale=1,图像越小
    # DIM=[1200,1200]
    # balance=0.6
    if k0 is None:
        k0=K
    img = cv2.imread(img_path)
    dim1 = img.shape[:2][::-1]  # dim1 is the dimension of input image to un-distort
    assert dim1[0] / dim1[1] == dim2[0] / dim2[
        1], "Image to undistort needs to have same aspect ratio as the ones used in calibration"
    if not dim2:
        dim2 = dim1
    if not dim3:
        dim3 = dim1
    scaled_K=K.copy()
    scaled_K[0][0] = K[0][0] * scale  # The values of K is to scale with image dimension.
    scaled_K[1][1] = K[1][1] * scale  # The values of K is to scale with image dimension.
    scaled_K[2][2] = 1.0  # Except that K[2][2] is always 1.0
    # This is how scaled_K, dim2 and balance are used to determine the final K used to un-distort image. OpenCV document failed to make this clear!
    # new_K = cv2.fisheye.estimateNewCameraMatrixForUndistortRectify(scaled_K, D, dim2, np.eye(3), balance=balance)
    if is_fisheye:
        map1, map2 = cv2.fisheye.initUndistortRectifyMap(K, D, np.eye(3), k0, dim3, cv2.CV_16SC2)##opencv中的balance难调，我们选择的是K,D到K的映射
        undistorted_img = cv2.remap(img, map1, map2, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    else:
        undistorted_img= cv2.undistort(img, K, D, None)


    if imshow:
        cv2.imshow("undistorted", undistorted_img)
    return undistorted_img,k0
def quarternion_to_rotation_matrix(q):
    """
    The formula for converting from a quarternion to a rotation
    matrix is taken from here:
    https://www.euclideanspace.com/maths/geometry/rotations/conversions/quaternionToMatrix/index.htm
    """
    qw = q.w()
    qx = q.x()
    qy = q.y()
    qz = q.z()
    R11 = 1 - 2 * qy ** 2 - 2 * qz ** 2
    R12 = 2 * qx * qy - 2 * qz * qw
    R13 = 2 * qx * qz + 2 * qy * qw
    R21 = 2 * qx * qy + 2 * qz * qw
    R22 = 1 - 2 * qx ** 2 - 2 * qz ** 2
    R23 = 2 * qy * qz - 2 * qx * qw
    R31 = 2 * qx * qz - 2 * qy * qw
    R32 = 2 * qy * qz + 2 * qx * qw
    R33 = 1 - 2 * qx ** 2 - 2 * qy ** 2
    R = np.array([[R11, R12, R13], [R21, R22, R23], [R31, R32, R33]])
    return R
def rotationMatrixToQuaternion(R: np.ndarray) -> np.ndarray:
    """Creates a quaternion from a rotation matrix defining a given orientation.

    Parameters
    ----------
    R : [3x3] np.ndarray
        Rotation matrix

    Returns
    -------
    q : [4x1] np.ndarray
        quaternion defining the orientation
    """
    u_q0 = np.sqrt((1 + R[0, 0] + R[1, 1] + R[2, 2]) / 4)  # the prefix u_ means unsigned
    u_q1 = np.sqrt((1 + R[0, 0] - R[1, 1] - R[2, 2]) / 4)
    u_q2 = np.sqrt((1 - R[0, 0] + R[1, 1] - R[2, 2]) / 4)
    u_q3 = np.sqrt((1 - R[0, 0] - R[1, 1] + R[2, 2]) / 4)

    q = np.array([u_q0, u_q1, u_q2, u_q3])

    if u_q0 == max(q):
        q0 = u_q0
        q1 = (R[2, 1] - R[1, 2]) / (4 * q0)
        q2 = (R[0, 2] - R[2, 0]) / (4 * q0)
        q3 = (R[1, 0] - R[0, 1]) / (4 * q0)

    if u_q1 == max(q):
        q1 = u_q1
        q0 = (R[2, 1] - R[1, 2]) / (4 * q1)
        q2 = (R[0, 1] + R[1, 0]) / (4 * q1)
        q3 = (R[0, 2] + R[2, 0]) / (4 * q1)

    if u_q2 == max(q):
        q2 = u_q2
        q0 = (R[0, 2] - R[2, 0]) / (4 * q2)
        q1 = (R[0, 1] + R[1, 0]) / (4 * q2)
        q3 = (R[1, 2] + R[2, 1]) / (4 * q2)

    if u_q3 == max(q):
        q3 = u_q3
        q0 = (R[1, 0] - R[0, 1]) / (4 * q3)
        q1 = (R[0, 2] + R[2, 0]) / (4 * q3)
        q2 = (R[1, 2] + R[2, 1]) / (4 * q3)

    q =[q0, q1, q2, q3]
    return q
# class Undistort:
#     distortMap = {}
#
#     @classmethod
#     def image(cls, frame, K, dist, sub=None, interp=cv2.INTER_NEAREST):
#         if sub is None:
#             return cv2.undistort(frame, K, dist, None)
#         else:
#             if sub not in cls.distortMap.keys():
#                 h, w = frame.shape[:2]
#                 mapx, mapy = cv2.initUndistortRectifyMap(K, dist, None, K, (w, h), 5)
#                 cls.distortMap[sub] = (mapx, mapy)
#             mapx, mapy = cls.distortMap[sub]
#             img = cv2.remap(frame, mapx, mapy, interp)
#             return img
#
#     @staticmethod
#     def points(keypoints, K, dist):
#         # keypoints: (N, 3)
#         assert len(keypoints.shape) == 2, keypoints.shape
#         kpts = keypoints[:, None, :2]
#         kpts = np.ascontiguousarray(kpts)
#         kpts = cv2.undistortPoints(kpts, K, dist, P=K)
#         keypoints = np.hstack([kpts[:, 0], keypoints[:, 2:]])
#         return keypoints
#
#     @staticmethod
#     def bbox(bbox, K, dist):
#         keypoints = np.array([[bbox[0], bbox[1], 1], [bbox[2], bbox[3], 1]])
#         kpts = Undistort.points(keypoints, K, dist)
#         bbox = np.array([kpts[0, 0], kpts[0, 1], kpts[1, 0], kpts[1, 1], bbox[4]])
#         return bbox
class Point:
    """
    data structure:  id: point_id from 0-2k+
                     point: 3d dimension
    """
    def __init__(self, point_id: int, point: np.array):
        self.id = point_id
        self.point = point

    @property
    def x(self) -> float:
        return self.point[0]

    @property
    def y(self) -> float:
        return self.point[1]

    @property
    def z(self) -> float:
        return self.point[2]
class Observation:
    """
    data structure:
                     point_id :point_id  0-2k+
                     camera_id:camera_id  0-5
                     point: 2d dimension
    """
    def __init__(self, point_id: int, camera_id: int, point: np.array):
        self.point_id = point_id
        self.camera_id = camera_id
        self.point = point

    @property
    def u(self) -> float:
        return self.point[0]

    @property
    def v(self) -> float:
        return self.point[1]
class Camera:
    """
    data structure:
                     id:camera_id  0-5
                     R :np.array(3,3)
                     t :np.array(3,1)
                     fixed : true for camera0
    """
    def __init__(self, camera_id: int, R: np.array = np.eye(3), t: np.array = np.zeros(3), fixed: bool = False):
        self.id = camera_id
        self.R = R
        self.t = t
        self.fixed = fixed

    @property
    def pose(self) -> np.array:
        pose = np.eye(4)
        pose[:3, :3] = self.R
        pose[:3, 3] = self.t.ravel()
        return pose

    @pose.setter
    def pose(self, pose: np.array):
        self.R = pose[:3, :3]
        self.t = pose[:3, 3]
class Map:
    """
        points: List[Point]
        observations: List[Observation]
        cameras: List[Camera]
        K : List[Camera] np.array(6,3,3)
        L:List of masks
        true_poses:np.array(6,4,4)
    """
    def __init__(self):
        self.points: List[Point] = []
        self.observations: List[Observation] = []
        self.cameras: List[Camera] = []
        self.K : List[Camera]=[]
        self.L:List=[]
        self.true_poses=[]
    def remove_camera(self, cam_id: int):
        before = len(self.observations)
        self.cameras = [cam for cam in self.cameras if cam.id != cam_id]
        self.observations = [obs for obs in self.observations if obs.camera_id != cam_id]
        return before - len(self.observations)

    def invert_depth(self,x):
        assert len(x) == 3 and x[2] != 0
        return np.array([x[0], x[1], 1]) / x[2]
    def reproj_err(self) -> float:
        id2p = {p.id: p for p in self.points}
        id2c = {c.id: c for c in self.cameras}

        sum = 0
        for obs in self.observations:
            cam = id2c[obs.camera_id]
            # if cam.id == 0:
            #     continue

            p = id2p[obs.point_id].point
            q = np.append(p, 1)
            p_cam = cam.pose @ q
            t = self.K[cam.id] @ p_cam[:3]
            t /= t[2]
            dx = t[0] - obs.u
            dy = t[1] - obs.v
            err = dx ** 2 + dy ** 2

            sum += err
        return sum,sum/len(self.observations)

    def bundle_adjustment(self):
        '''
            revised from https://github.com/uoip/g2opy/blob/master/python/examples/ba_demo.py
        '''
        optimizer = g2o.SparseOptimizer()
        solver = g2o.BlockSolverSE3(g2o.LinearSolverEigenSE3()) #LinearSolverPCGSE3 LinearSolverDenseSE3
        solver = g2o.OptimizationAlgorithmLevenberg(solver)
        optimizer.set_algorithm(solver)

        # inliers = dict()
        camera_vertices = {}
        #define cam parameters
        for idx, camera in enumerate(self.cameras):
            focal_length = self.K[idx][0, 0]  #Only one parameter can be passed.
            principal_point = (self.K[idx][0, 2], self.K[idx][1, 2])
            baseline = 0
            cam = g2o.CameraParameters(focal_length, principal_point, baseline)
            cam.set_id(idx)
            optimizer.add_parameter(cam)

            # Use the estimated pose of the second camera based on the
            # essential matrix.
            pose = g2o.SE3Quat(camera.R, camera.t)
            self.true_poses.append(pose)
            # Set the poses that should be optimized.
            # Define their initial value to be the true pose
            # keep in mind that there is added noise to the observations afterwards.
            v_se3 = g2o.VertexSE3Expmap()
            v_se3.set_id(camera.id)
            v_se3.set_estimate(pose)
            print("fixed?", camera.fixed)
            v_se3.set_fixed(camera.fixed)
            optimizer.add_vertex(v_se3)
            camera_vertices[camera.id] = v_se3
            # print("camera id: %d" % camera.camera_id)
        print("num cam_vertices:", len(camera_vertices))
        anchor = 0
        point_vertices = {}
        #define 3d points
        for point in self.points:
            # Add 3d location of point to the graph
            vp = g2o.VertexPointXYZ()
            vp.set_id(point.id)
            vp.set_marginalized(True)
            # Use positions of 3D points from the triangulation

            # point_temp = np.array(point.point, dtype=np.float64) #TODO: forventer 3x1, er 4x1 (scale)
            point_temp = np.array(point.point[0:3], dtype=np.float64)

            ##revised version
            # point2 =self.true_poses[anchor] * (point.point)
            # if point2[2] == 0:
            #     continue
            # vp.set_estimate(self.invert_depth(point2))

            vp.set_estimate(point_temp)
            optimizer.add_vertex(vp)
            point_vertices[point.id] = vp
        print("num point_vertices:", len(point_vertices))
        print("# observations:", len(self.observations))
        #define observation:image plane 2d
        for i,observation in enumerate(self.observations): # Ikke sikker på at det her er rette syntax
            # if i%2==1:
            #     continue
            # Add edge from first camera to the point
            edge = g2o.EdgeProjectXYZ2UV()

            # edge = g2o.EdgeProjectPSI2UV()
            # edge.resize(3)

            # 3D point
            edge.set_vertex(0, point_vertices[observation.point_id])
            # Pose of first camera
            edge.set_vertex(1, camera_vertices[observation.camera_id])
            # edge.set_vertex(2, camera_vertices[anchor])

            edge.set_measurement(observation.point)
            edge.set_information(np.identity(2))
            edge.set_robust_kernel(g2o.RobustKernelHuber())

            edge.set_parameter_id(0, observation.camera_id)
            optimizer.add_edge(edge)

        # for i,observation in enumerate(self.observations): # Ikke sikker på at det her er rette syntax
        #     if i%2==0:
        #         continue
        #     # Add edge from first camera to the point
        #     edge = g2o.EdgeProjectXYZ2UV()
        #
        #     # edge = g2o.EdgeProjectPSI2UV()
        #     # edge.resize(3)
        #
        #     # 3D point
        #     edge.set_vertex(0, point_vertices[observation.point_id])
        #     # Pose of first camera
        #     edge.set_vertex(1, camera_vertices[observation.camera_id])
        #     # edge.set_vertex(2, camera_vertices[anchor])
        #
        #     edge.set_measurement(observation.point)
        #     edge.set_information(np.identity(2))
        #     edge.set_robust_kernel(g2o.RobustKernelHuber())
        #
        #     edge.set_parameter_id(0, observation.camera_id)
        #     optimizer.add_edge(edge)


        print('num vertices:', len(optimizer.vertices()))
        print('num edges:', len(optimizer.edges()))
        print('Performing full BA:')
        optimizer.initialize_optimization()
        optimizer.set_verbose(True)
        optimizer.optimize(40)
        optimizer.save("test.g2o");

        for idx, camera in enumerate(self.cameras):
            print("Camera ID:", self.cameras[idx].id)
            t = camera_vertices[camera.id].estimate().translation()
            print("Camera Translation Before BA:\n", self.cameras[idx].t)
            self.cameras[idx].t = t
            print("Camera Translation After BA:\n", self.cameras[idx].t)
            q = camera_vertices[camera.id].estimate().rotation()
            print("Camera Rotation Before BA:\n", self.cameras[idx].R)
            self.cameras[idx].R = quarternion_to_rotation_matrix(q)
            print("Camera Rotation After BA:\n", self.cameras[idx].R)

        for idx, point in enumerate(self.points):
            p = point_vertices[point.id].estimate()
            # It is important to copy the point estimates.
            # Otherwise I end up with some memory issues.
            # self.points[idx].point = p
            # print("point before:", self.points[idx].point)
            self.points[idx].point = np.copy(p)
            # self.points[idx].point = np.hstack((self.points[idx].point, 1)) #fixes things

#初始化相机内参
def initIntriPara(outPath, camIds):
    intriPara = {}
    for camId in camIds:
        intriPara[camId] = read_json(os.path.join(outPath, camId + '.json'))
    return intriPara


def initIntriParam(paramPath,cams):##初始化所有相机的内参
    # paramList = os.listdir(paramPath)
    # paramList = [f for f in paramList if f.endswith('.json')]
    K = []
    dist = []
    for cam in cams:
        f = open(os.path.join(paramPath, cam+".json"),'r')
        dic = json.load(f)
        k = np.array(dic['K'], dtype=np.float32)
        d = np.array(dic['dist'], dtype=np.float32)
        new_k=np.array(dic['new_K'], dtype=np.float32)
        K.append(new_k)
        dist.append(d)
        f.close()
    return K,dist

#检测用于标定外参的某一帧是否有效
def isImageValid(imageName, outPath, camIds, ext):
    for camId in camIds:
        # print(os.path.join(outPath, "PointData", "Extri", camId, imageName.replace(ext, '.json')))
        if not os.path.exists(os.path.join(outPath, "PointData", "Extri", camId, imageName.replace(ext, '.json'))):
            return False
    return True

def estimate_pose(pts1, pts2,K1,K2,MASK_i):

    # # 基础矩阵
    # F, mask = cv2.findFundamentalMat(pts1, pts2, cv2.FM_RANSAC,0.1)
    # # 选择inlier points
    # pts1 = pts1[mask.ravel() == 1]
    # pts2 = pts2[mask.ravel() == 1]
    # mask_inner=np.array(MASK_i,dtype=int)
    # mask_inner=mask_inner[mask.ravel()==1].tolist()
    # E = np.matmul(np.matmul(np.transpose(K2), F), K1)
    # retval, R, t, mask = cv2.recoverPose(E, pts1, pts2)
    # # return pts1, pts2, mask_inner, R, t


    # # 使用基础矩阵和本质矩阵估计相机位姿
    E, mask = cv2.findEssentialMat(pts1, pts2, K1, cv2.RANSAC,threshold=0.01)
    # 选择 inlier points
    pts1_inner = pts1[mask.ravel() == 1]
    pts2_inner = pts2[mask.ravel()== 1]
    mask_inner=np.array(MASK_i,dtype=int)
    mask_inner=mask_inner[mask.ravel()==1].tolist()
    _, R, t, mask = cv2.recoverPose(E, pts1_inner, pts2_inner, K1)
    # _, R, t, _ = cv2.recoverPose(E, src_pts, dst_pts, K)

    #使用单应矩阵估计位姿
    # H = cv2.findHomography(pts1, pts2, method=cv2.RANSAC)
    # return pts1_inner,pts2_inner,mask_inner, R, t
    return R,t
# 三角化计算点云
def triangulate(pts1, pts2, R1, t1, R2, t2, K1, K2):
    # 将相机位姿转换为投影矩阵
    P1 = K1 @ np.hstack((R1, t1))
    P2 = K2 @ np.hstack((R2, t2))
    # 使用三角化计算匹配点的三维坐标
    points4D = cv2.triangulatePoints(P1, P2, pts1, pts2)
    points3D = cv2.convertPointsFromHomogeneous(points4D.T)# 将齐次坐标转化为欧式三维坐标
    return points3D.squeeze()

#光束平差
def bundle_adjustment(points3d, Ks, Rs, ts, point2dList,masklist,num_cam_pair):  #not used


    def get_start_end(masklist,index):
        start,end=0,0
        if index == 0:
            start = 0
            end = len(masklist[0])
        else:
            for k in range(index):
                start += len(masklist[k])
            end = start + len(masklist[index])
        return start,end
    """ 使用Bundle Adjustment优化三维点和相机位姿 """
    def reproj_error(params, camNum, Ks, point2dList,masklist):
        """ 重投影误差函数 """
        errors = []
        for i in range(camNum):
            R = params[i * 9:i * 9 + 9].reshape(3, 3)
            t = params[camNum * 9 + i * 3:camNum * 9 + i * 3 + 3].reshape(3, 1)
            if i==0:
                start1,end1=get_start_end(masklist,i)
                points3d1 = params[camNum * 12 + start1 * 3:camNum * 12 + end1 * 3]
                points3d2 = []
                points2d=point2dList[i]
            elif i==5:
                j=i-1
                start2,end2=get_start_end(masklist,j)
                points3d1 = []
                points3d2 = params[camNum * 12+start2*3:camNum * 12+end2*3]
                points2d=point2dList[2*i-1]
            else:
                j=i-1
                start1,end1=get_start_end(masklist,j)
                start2,end2=get_start_end(masklist,i)
                points3d1 = params[camNum * 12+start1*3:camNum * 12+end1*3]
                points3d2 = params[camNum * 12+start2*3:camNum * 12+end2*3]
                points2d = np.concatenate([point2dList[2*i-1], point2dList[2*i]])
            points3d= np.concatenate([points3d1,points3d2])
            points3d = points3d.reshape(-1,3)
            # 计算三维点在当前相机下的投影
            '''
            cv2.projectPoints(objectPoints, rvec, tvec, cameraMatrix, distCoeffs[, imagePoints[, jacobian[, aspectRatio]]]) → imagePoints, jacobian
            objectPoints：三维物体坐标的数组，其形状为(N,1,3)，其中N是点的数目，每个点有三个坐标。
            rvec：旋转向量，是相机坐标系到物体坐标系的旋转向量。
            tvec：平移向量，是相机坐标系到物体坐标系的平移向量。
            cameraMatrix：相机矩阵，是相机内参的矩阵。
            distCoeffs：畸变系数，包含k1、k2、p1、p2、k3等系数。
            imagePoints：输出的二维图像坐标的数组，其形状为(N,1,2)。
            jacobian：可选的输出的导数矩阵，其形状为(N,2,6)。
            aspectRatio：可选的纵横比参数，用于调整相机内参矩阵中的焦距。
            返回值有两个，第一个是imagePoints是一个(N,1,2)形状的数组
            '''
            pointProj = cv2.projectPoints(points3d, R, t, Ks[i], None)[0]
            # 计算重投影误差
            errors.append(np.linalg.norm(pointProj.squeeze() - points2d.squeeze())) #squeeze去掉维度为1的维度
        return np.array(errors)

    camNum = len(Rs)
    # 将相机姿态和三维点坐标向量拼接
    Rs = np.array(Rs, dtype=np.float32)
    ts = np.array(ts, dtype=np.float32)
    points3d = np.concatenate([np.array(point).reshape(-1) for point in points3d])
    params = np.hstack((Rs.reshape(-1), ts.reshape(-1), points3d.reshape(-1)))
    # 使用scipy.optimize.least_squares优化重投影误差,第一个参数为计算残差的函数，第二个参数为自变量
    result = least_squares(reproj_error, params, args=(camNum, Ks, point2dList,masklist))
    # 将优化后的向量分解为相机位姿和三维点坐标
    Rs = result.x[:camNum * 9].reshape(camNum, 3, 3)
    ts = result.x[camNum * 9: camNum * 12].reshape(camNum, 3, 1)
    points3D = result.x[camNum * 12:].reshape(-1, 3)
    return points3D, Rs, ts

# 保存标定结果
def saveResult(outPath, Rs, Ts,cams):
    paramList = os.listdir(outPath)
    paramList = [f for f in paramList if f.endswith('.json')]
    for i, cam in enumerate(cams):
        f = open(os.path.join(outPath, cam+".json"), 'r')
        dic = json.load(f)
        dic['R'] = Rs[i].tolist()
        dic['t'] = Ts[i].tolist()
        f.close()
        f = open(os.path.join(outPath, cam+".json"), 'w')
        json.dump(dic, f, indent=4)
        f.close()

def saveResult_txt(outPath,camera_params):
    with open(outPath, "w") as f:
        f.write("# fu u0 v0 ar s | k1 k2 p1 p2 k3 | quaternion(scalar part first) translation | width height |\n")
        for params in camera_params:
            fu, u0, v0, ar, s, k1, k2, k3,k4, q0, q1, q2, q3, tx, ty, tz, width, height = params
            f.write(f"{fu:.6f} {u0:.6f} {v0:.6f} {ar:.6f} {s:.6f} | {k1:.6f} {k2:.6f}  {k3:.6f} {k4:.6f}| {q0:.6f} {q1:.6f} {q2:.6f} {q3:.6f} | {tx:.6f} {ty:.6f} {tz:.6f} {width} {height}\n")

    print("Output saved to", outPath)
def batch_triangulate(keypoints_, Pall, keypoints_pre=None, lamb=1e3):
    # keypoints: (nViews, nJoints, 3)
    # Pall: (nViews, 3, 4)
    # A: (nJoints, nViewsx2, 4), x: (nJoints, 4, 1); b: (nJoints, nViewsx2, 1)
    v = (keypoints_[:, :, -1]>0).sum(axis=0)
    valid_joint = np.where(v > 1)[0]
    keypoints = keypoints_[:, valid_joint]
    conf3d = keypoints[:, :, -1].sum(axis=0)/v[valid_joint]
    # P2: P矩阵的最后一行：(1, nViews, 1, 4)
    P0 = Pall[None, :, 0, :]
    P1 = Pall[None, :, 1, :]
    P2 = Pall[None, :, 2, :]
    # uP2: x坐标乘上P2: (nJoints, nViews, 1, 4)
    uP2 = keypoints[:, :, 0].T[:, :, None] * P2
    vP2 = keypoints[:, :, 1].T[:, :, None] * P2
    conf = keypoints[:, :, 2].T[:, :, None]
    Au = conf * (uP2 - P0)
    Av = conf * (vP2 - P1)
    A = np.hstack([Au, Av])
    if keypoints_pre is not None:
        # keypoints_pre: (nJoints, 4)
        B = np.eye(4)[None, :, :].repeat(A.shape[0], axis=0)
        B[:, :3, 3] = -keypoints_pre[valid_joint, :3]
        confpre = lamb * keypoints_pre[valid_joint, 3]
        # 1, 0, 0, -x0
        # 0, 1, 0, -y0
        # 0, 0, 1, -z0
        # 0, 0, 0,   0
        B[:, 3, 3] = 0
        B = B * confpre[:, None, None]
        A = np.hstack((A, B))
    u, s, v = np.linalg.svd(A)
    X = v[:, -1, :]
    X = X / X[:, 3:]
    # out: (nJoints, 4)
    result = np.zeros((keypoints_.shape[1], 4))
    result[valid_joint, :3] = X[:, :3]
    result[valid_joint, 3] = conf3d
    return result

def solvePnP(k3d, k2d, K, dist, flag, tryextri=False):
    k2d = np.ascontiguousarray(k2d[:, :2])
    # try different initial values:
    if tryextri:
        def closure(rvec, tvec):
            ret, rvec, tvec = cv2.solvePnP(k3d, k2d, K, dist, rvec, tvec, True, flags=flag)
            points2d_repro, xxx = cv2.projectPoints(k3d, rvec, tvec, K, dist)
            kpts_repro = points2d_repro.squeeze()
            err = np.linalg.norm(points2d_repro.squeeze() - k2d, axis=1).mean()
            return err, rvec, tvec, kpts_repro
        # create a series of extrinsic parameters looking at the origin
        height_guess = 2.1
        radius_guess = 7.
        infos = []
        for theta in np.linspace(0, 2*np.pi, 180):
            st = np.sin(theta)
            ct = np.cos(theta)
            center = np.array([radius_guess*ct, radius_guess*st, height_guess]).reshape(3, 1)
            R = np.array([
                [-st, ct,  0],
                [0,    0, -1],
                [-ct, -st, 0]
            ])
            tvec = - R @ center
            rvec = cv2.Rodrigues(R)[0]
            err, rvec, tvec, kpts_repro = closure(rvec, tvec)
            infos.append({
                'err': err,
                'repro': kpts_repro,
                'rvec': rvec,
                'tvec': tvec
            })
        infos.sort(key=lambda x:x['err'])
        err, rvec, tvec, kpts_repro = infos[0]['err'], infos[0]['rvec'], infos[0]['tvec'], infos[0]['repro']
    else:
        ret, rvec, tvec = cv2.solvePnP(k3d, k2d, K, dist, flags=flag)
        points2d_repro, xxx = cv2.projectPoints(k3d, rvec, tvec, K, dist)
        kpts_repro = points2d_repro.squeeze()
        err = np.linalg.norm(points2d_repro.squeeze() - k2d, axis=1).mean()
    # print(err)
    return err, rvec, tvec, kpts_repro
def extraPoint(dic_data,frame,num_board,pattern):
    if dic_data[frame]['valid']==True:
        dic = dic_data[frame]
        points = np.zeros((0,2), dtype=np.float32)
        masks= []
        num_points_all=pattern[0]*pattern[1]
        for board_index in range(num_board):
            if f'mask_{board_index}' in dic:
                coord = np.array(dic[f'keyPoints2d_{board_index}'], dtype=np.float32)
                mask=np.array(dic[f'mask_{board_index}'],dtype=int)+num_points_all*board_index
                points = np.vstack((points,coord))
                masks = np.concatenate((masks, mask), axis=0) # 拼接
            else:
                pass
        masks = np.array(masks)
    else:
        return False,None,None
    return True,points,masks

def write_pointcloud(filename,xyz_points,rgb_points=None):

    """ creates a .pkl file of the point clouds generated
    """

    assert xyz_points.shape[1] == 3,'Input XYZ points should be Nx3 float array'
    if rgb_points is None:
        rgb_points = np.ones(xyz_points.shape).astype(np.uint8)*255
    assert xyz_points.shape == rgb_points.shape,'Input RGB colors should be Nx3 float array and have same size as input XYZ points'

    # Write header of .ply file
    fid = open(filename,'wb')
    fid.write(bytes('ply\n', 'utf-8'))
    fid.write(bytes('format binary_little_endian 1.0\n', 'utf-8'))
    fid.write(bytes('element vertex %d\n'%xyz_points.shape[0], 'utf-8'))
    fid.write(bytes('property float x\n', 'utf-8'))
    fid.write(bytes('property float y\n', 'utf-8'))
    fid.write(bytes('property float z\n', 'utf-8'))
    fid.write(bytes('property uchar red\n', 'utf-8'))
    fid.write(bytes('property uchar green\n', 'utf-8'))
    fid.write(bytes('property uchar blue\n', 'utf-8'))
    fid.write(bytes('end_header\n', 'utf-8'))

    # Write 3D points to .ply file
    for i in range(xyz_points.shape[0]):
        fid.write(bytearray(struct.pack("fffccc",xyz_points[i,0],xyz_points[i,1],xyz_points[i,2],
                                        rgb_points[i,0].tobytes() ,rgb_points[i,1].tobytes() ,
                                        rgb_points[i,2].tobytes() )))
    fid.close()
def get_points(point1, point2, mask1, mask2):
    # 取出 point1 和 point2 中对应的点
    common_indices = np.intersect1d(mask1, mask2)

    # 找到这些相同序号元素在 mask1 和 mask2 中的索引
    mask1_indices = [np.where(mask1 == idx)[0][0] for idx in common_indices]
    mask2_indices = [np.where(mask2 == idx)[0][0] for idx in common_indices]

    point1_selected = [point1[idx] for idx in mask1_indices]
    point2_selected = [point2[idx] for idx in mask2_indices]

    point1_selected = np.array(point1_selected,dtype=np.float32)
    point2_selected = np.array(point2_selected,dtype=np.float32)

    mask1_p=[mask1[idx] for idx in mask1_indices]
    mask2_p=[mask2[idx] for idx in mask2_indices]
    return point1_selected, point2_selected,mask1_indices,mask2_indices,mask1_p,mask2_p
def calibIntriandExtri(rootiPath,outPath, pattern, gridSize, ext, num_pic,is_charu,is_fisheye,num_board):
    """
    pattern:Number of squares horizontally & vertically ,[4,6]
    gridSize:Square side length (in m)
    ext:Data extension ,'.png'
    num_pic:Number of pics for calibraion
    is_charu:Charucoboard detection
    is_fisheye:Fisheye cam system or pinhole cam
    num_board:Number of boards

    calibrate intri parameters
    """
    iFolder = getFileList(rootiPath, ext)

    camIds = [cam['camId'] for cam in iFolder]
    makeDir(outPath, camIds)
    pointcorner_data={}
    pdshow_data = {
        'Cam':list(range(1, len(camIds)+1))
    }
    annots = {'cams': {
    }}
    before_point_list=[]
    after_point_list=[]
    Ks, Dists=[],[]
    width,height=0,0
    # Intri
    # detect chessboard corners and save the results
    for cam in iFolder:
        dataList = []
        intriPara = {}
        point_num=0
        valid_num=0
        for imgName in cam['imageList']:
            detect_flag,pointData=detect_chessboard(os.path.join(rootiPath, cam['camId'], imgName), outPath, "Intri", pattern, gridSize, ext,is_charu,is_fisheye,num_board,None,None)
            if detect_flag==True:
                # pointData = read_json(os.path.join(outPath, "PointData", "Intri", cam['camId'], imgName.replace(ext,'.json')))
                reProjErr = float(reProjection(pointData,is_charu,num_board))
                pointData['reProjErr'] = reProjErr
                valid_num+=1
                dataList.append(pointData)
            else:
                continue
        num = len(dataList)# - 5
        print("cam:",cam['camId'],"use:%02d images"%num)
        if len(dataList) < num :
            print("cam:",cam['camId'], "calibrate intri failed: doesn't have enough valid image")
            continue
        dataList = sorted(dataList, key = lambda x: x['reProjErr'])
        i = 0
        for data in dataList:
            if i < num :
                data['selected'] = True
                i = i + 1
        point2dList=[]
        point3dList=[]
        for data in dataList:
            if data['selected'] == True & is_charu   :
                for board_index in range(num_board):
                    if f'mask_{board_index}'  in data:
                        point_num+=len(data[f'mask_{board_index}'])
                        point2dList.append(np.expand_dims(np.array(data[f'keyPoints2d_{board_index}'],dtype=np.float32),0))
                        point3dList.append(np.expand_dims(np.array(data[f'keyPoints3d_{board_index}'],dtype=np.float32),0))
                    else:
                        pass
            elif not data['selected'] == True& (is_charu):
                point2dList.append(np.expand_dims(np.array(data['keyPoints2d'], dtype=np.float32), 0))
                point3dList.append(np.expand_dims(np.array(data['keyPoints3d'], dtype=np.float32), 0))
            else:
                pass
        before_point_list.append(point_num)
        width=dataList[0]['iWidth']
        height=dataList[0]['iHeight']
        #do intri calibration using opencv2  cv2.calibrateCamera or  cv2.fisheye.calibrate
        if not is_fisheye:
            # 采用np.stack 对矩阵进行叠加,类型必须为float32，float64不可以
            ret, K, dist, rvecs, tvecs = cv2.calibrateCamera(point3dList, point2dList, (dataList[0]['iWidth'],dataList[0]['iHeight']), None, None,flags=cv2.CALIB_FIX_K3)
        else:
            # point3dList=np.expand_dims(np.asarray(point3dList),1)
            # point2dList=np.expand_dims(np.asarray(point2dList),1)
            ret, K, dist, rvecs, tvecs = cv2.fisheye.calibrate(point3dList, point2dList,
                                                             (dataList[0]['iWidth'], dataList[0]['iHeight']), None,
                                                             None,flags = cv2.fisheye.CALIB_CHECK_COND+cv2.fisheye.CALIB_FIX_SKEW,
            criteria=(cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_COUNT, 30, 1e-6))



        #Undistort an image using the calibrated intrinsic parameters and distortion coefficients
        for imgName in cam['imageList']:
            img_path=os.path.join(os.path.join(rootiPath, cam['camId'], imgName))
            #save pics
            undistorted_img,new_k=undistort(img_path,K,dist,is_fisheye,k0=None,dim2=[width,height],dim3=[ width,height])#dim2=[2448,2048],dim3=[ 2448,2048]
            out_path=os.path.join(os.path.join(outPath,'undistorted',cam['camId'], imgName))
            cv2.imwrite(out_path,undistorted_img)

        #save results of calibation
        annots['cams'][cam['camId']] = {
            'K': K,
            'D': dist,#np.zeros((5,1))#
            'new_K':new_k
        }
        Ks.append(new_k)
        Dists.append(dist)
    np.save(os.path.join(outPath,'annots.npy'), annots)
    #去畸变后的图片识别角点
    #detect undistorted pics again and save pointdata
    for cam in iFolder:
        dataList = []
        point_num=0
        for imgName in cam['imageList']:
            detect_flag,pointData=detect_chessboard(os.path.join(outPath,'undistorted', cam['camId'], imgName), outPath, "Intri_undistorted", pattern, gridSize, ext,is_charu,is_fisheye,num_board,None,None)
            if detect_flag==True:
                pointData['valid']=True
                reProjErr = float(reProjection(pointData,is_charu,num_board))
                pointData['reProjErr'] = reProjErr
                dataList.append(pointData)
            else:
                pointData['valid']=False
                dataList.append(pointData)
                continue
        num = len(dataList)  # - 5
        print("cam:", cam['camId'], "use:%02d images" % num)
        if len(dataList) < num:
            print("cam:", cam['camId'], "calibrate intri failed: doesn't have enough valid image")
            continue
        # dataList = sorted(dataList, key=lambda x: x['reProjErr'])
        i = 0
        for data in dataList:
            if i < num and data['valid']:
                data['selected'] = True
                i = i + 1
            else:
                continue
            for board_index in range(num_board):
                if f'mask_{board_index}' in data:
                    point_num += len(data[f'mask_{board_index}'])
            # save_json(os.path.join(outPath, "PointData", "Intri_undistorted", cam["camId"], data['imageName'].replace(ext, ".json")), data)
        pointcorner_data[cam['camId']]=dataList
        # for data in dataList:
        #     for board_index in range(num_board):
        #         if f'mask_{board_index}' in data:
        #             point_num += len(data[f'mask_{board_index}'])
        after_point_list.append(point_num)
    pdshow_data['去畸变前角点数目']=before_point_list
    pdshow_data['去畸变后角点数目']=after_point_list
    df = pd.DataFrame(pdshow_data)
    print(df.to_markdown(index=False))



##Extri
    # annots = np.load(os.path.join(outPath, "annots.npy"), allow_pickle=True).item()
    # cams = annots['cams'].keys()
    # save total pointdata KEYPOINTS2D & MASK & KEYPOINTS3D
    KEYPOINTS2D = []
    MASK = []
    KEYPOINTS3D = []



    for cam in annots['cams'].keys():
        masks = []
        points = np.zeros((0, 2), dtype=np.float32)
        for frame in range(num_pic):
            ret, keypoint2d, mask = extraPoint(pointcorner_data[cam],frame, num_board,pattern)
            if not ret:
                continue
            points = np.vstack((points, keypoint2d))
            masks = np.concatenate((masks, mask + frame * num_board * pattern[0] * pattern[1]), axis=0)  # 拼接
            masks = np.array(masks, dtype=int)
        KEYPOINTS2D.append(points)
        MASK.append(masks)


    # Initialize map for BA
    map = Map()
    # Rs Ts SAVE Relative pose
    # R_abs T_abs SAVE Absolute pose
    Rs = []  # 各个相机旋转矩阵,0号相机的旋转矩阵为I，平均向量为0
    Rs.append(np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=np.float32))
    Ts = []  # 各个相机平移
    Ts.append(np.array([[0], [0], [0]], dtype=np.float32))
    R_abs = [Rs[0]]
    T_abs = [Ts[0]]
    # read intri

    '''
        KEYPOINTS2D_NEWLIST Store the common visible points between adjacent cameras 
        MASK_NEWLIST  Store the mask of common visible points between adjacent cameras 
    '''

    KEYPOINTS2D_NEWLIST = []
    MASK_NEWLIST = []
    for index in range(len(camIds)):
        i = index % len(camIds)  # first cam index
        j = (index + 1) % len(camIds)  # adjacent cam index
        # Retreive 2d pointdata & mask
        KEYPOINTS2D_i = KEYPOINTS2D[i]
        KEYPOINTS2D_j = KEYPOINTS2D[j]
        mask_i = MASK[i]
        mask_j = MASK[j]
        KEYPOINTS2D_i, KEYPOINTS2D_j, MASK_i, MASK_j, mask1_p, mask2_p = get_points(KEYPOINTS2D_i, KEYPOINTS2D_j,
                                                                                    mask_i, mask_j)
        Ki=Ks[i]
        Kj=Ks[j]
        # KEYPOINTS2D_i,KEYPOINTS2D_j,MASK_i,R, t = estimate_pose(KEYPOINTS2D_i, KEYPOINTS2D_j, Ks[i],Ks[j],MASK_i)#解出位姿
        R, t = estimate_pose(KEYPOINTS2D_i, KEYPOINTS2D_j, Ki, Kj, MASK_i)  # 解出位姿
        Rs.append(R)
        Ts.append(t)
        KEYPOINTS2D_NEWLIST.append(KEYPOINTS2D_i)
        KEYPOINTS2D_NEWLIST.append(KEYPOINTS2D_j)
        MASK_NEWLIST.append(MASK_i)
        # 存绝对位姿
        R_abs.append(np.matmul(R, R_abs[i]))
        T_abs.append(T_abs[i] + np.matmul(R_abs[i], t))

        # Do triangulation
        keyPoints3d = triangulate(KEYPOINTS2D_i.T, KEYPOINTS2D_j.T, R_abs[i], T_abs[i], R_abs[j], T_abs[j], Ki,
                                  Kj)
        # save 3d points
        points = np.array(keyPoints3d)
        os.makedirs(os.path.join(outPath, 'pointcloud'), exist_ok=True)
        filename = f'pointCloud_{index:02d}.ply'
        output_filename = os.path.join(outPath, 'pointcloud', filename)
        write_pointcloud(output_filename, points)

        # add data to map
        for n, m in enumerate(MASK_i):
            idx3d = mask_i[m]
            map.points.append(Point(idx3d, keyPoints3d.T[:, n]))  # 第一个摄像头的内点用point存
            map.observations.append(Observation(idx3d, i, KEYPOINTS2D_i.T[:, n]))
            map.observations.append(Observation(idx3d, j, KEYPOINTS2D_j.T[:, n]))

        # save length of masklist
        map.L.append(len(MASK_i))
        if index < 1:
            cam = Camera(index, R_abs[0], T_abs[0], True)  # 存下该相机的参数：R,T->POSE
        else:
            cam = Camera(index, R_abs[index], T_abs[index], False)  # 存下该相机的参数：R,T->POSE
        map.cameras.append(cam)  # 写入map
        map.K.append(Ks[index])

    print(
        f"Before BA reprojection error: {map.reproj_err()[0]:.2f}, reprojection error per observation :{map.reproj_err()[1]:.2f}")
    # Do bundle_adjustment
    map.bundle_adjustment()

    # save 3d points after BA
    points = []
    for i in range(len(map.points)):
        if map.points[i].id < 10000:
            points.append(np.array(map.points[i].point, dtype=np.float32))
        else:
            continue
    points = np.array(points)
    os.makedirs(os.path.join(outPath, 'pointcloud'), exist_ok=True)
    filename = 'pointCloud.ply'
    output_filename = os.path.join(outPath, 'pointcloud', filename)
    write_pointcloud(output_filename, points)
    # calibrate scale factor
    mask_i = MASK[0]
    MASK_i = MASK_NEWLIST[0]
    scale_idx = mask_i[MASK_i[0]]
    scale_calibrate_frame = scale_idx // (num_board * pattern[0] * pattern[1])
    scale_calibrate_board = (scale_idx - (num_board * pattern[0] * pattern[1]) * scale_calibrate_frame) // (
            pattern[0] * pattern[1])
    k3d = points
    print(scale_calibrate_frame, scale_calibrate_board)
    pointData1 = pointcorner_data['00'][scale_calibrate_frame]
    pointData2 = pointcorner_data['01'][scale_calibrate_frame]
    point3d1 = np.array(pointData1[f'keyPoints3d_{scale_calibrate_board}'], dtype=np.float32)
    point3d2 = np.array(pointData2[f'keyPoints3d_{scale_calibrate_board}'], dtype=np.float32)
    point_gt = []
    for p1 in point3d1:
        if p1 in point3d2:
            point_gt.append(p1)
    # 将相同的元素组成新的数据
    point_gt = np.array(point_gt)
    point_pre = np.array(k3d[:len(point_gt), :])
    ref_point_id = np.linalg.norm(point_gt - point_gt[:1], axis=-1).argmax()
    length = np.linalg.norm(point_pre[0, :3] - point_pre[ref_point_id, :3])
    length_gt = np.linalg.norm(point_gt[0, :3] - point_gt[ref_point_id, :3])
    scale = length_gt / length
    print('gt diag={:.3f}, est diag={:.3f}, scale={:.3f}'.format(length_gt, length, length_gt / length))
    # points3D, Rs, Ts=bundle_adjustment(KEYPOINTS3D, Ks, R_abs, T_abs, KEYPOINTS2D_NEWLIST,MASK_NEWLIST,len(cams))
    print(
        f"After BA reprojection error: {map.reproj_err()[0]:.2f}, reprojection error per observation :{map.reproj_err()[1]:.2f}")

    camera_params = []
    # save results
    for i, cam in enumerate(camIds):
        if i == 0:
            R = R_abs[0]
            T = T_abs[0]
        else:
            R = R_abs[i]
            T = T_abs[i]
        k = Ks[i]
        d = Dists[i]
        c2w = np.eye(4)
        c2w[:3, :3] = R
        c2w[:3, 3] = T.squeeze()* scale
        # c2w[:3, :] = c2w[:3, :] * scale
        # scale normalization
        c2w_ba= np.eye(4)
        c2w_ba[:3, :] = map.cameras[i].pose[:3, :]
        c2w_ba[:3,3]=c2w_ba[:3,3]*scale
        # R_ref=np.array([[0, 0, -1], [-1, 0, 0], [0, 1, 0]], dtype=np.float32)
        # c2w_ba1=np.matmul(R_ref,c2w_ba)

        ##annots format
        annots['cams'][cam]['c2w_old'] = c2w
        annots['cams'][cam]['c2w_new'] = c2w_ba

        ##txt format
        # fu, u0, v0, ar, s, k1, k2, p1, p2, k3, q0, q1, q2, q3, tx, ty, tz
        fu = k[0][0]
        u0 = k[0][2]
        v0 = k[1][2]
        ar = 1
        s = k[0][1]
        k1 = float(d[0])
        k2 = float(d[1])
        k3 = float(d[2])
        k4 = float(d[3])
        q0, q1, q2, q3 = rotationMatrixToQuaternion(c2w[:3, :3])
        t1, t2, t3 = c2w[:3, 3].T
        camera_params.append([fu, u0, v0, ar, s, k1, k2, k3, k4, q0, q1, q2, q3, t1, t2, t3, width, height])
    np.save(os.path.join(outPath, 'extri_annots.npy'), annots)

    ##align format
    output_file = os.path.join(outPath, "camera_params.txt")
    saveResult_txt(output_file, camera_params)




if __name__ == '__main__':
    # torch.set_default_tensor_type('torch.cuda.FloatTensor')

    parser = argparse.ArgumentParser()
    parser.add_argument('--root_path', type=str, default='../sfm1/archive/bimage_fisheye_multicharuco_360')
    parser.add_argument('--out_path', type=str, default='../sfm1/archive/output_bimage_fisheye_multicharuco_360')
    parser.add_argument('--pattern', type=int, nargs='+', default=[4, 6])
    parser.add_argument('--gridsize', type=float,default=0.197)
    parser.add_argument('--ext', type=str,default='.png')
    parser.add_argument('--num_pic',type=int, default=18)
    parser.add_argument('--is_charu', default=False, action="store_true")
    parser.add_argument('--is_fisheye', default=False, action="store_true")
    parser.add_argument('--num_board', type=int, default=6)
    parser.add_argument('--num_cam', type=int, default=6)
    args = parser.parse_args()
    calibIntriandExtri(args.root_path, args.out_path, args.pattern,args.gridsize,args.ext,args.num_pic,args.is_charu,args.is_fisheye,args.num_board,args.num_cam)

