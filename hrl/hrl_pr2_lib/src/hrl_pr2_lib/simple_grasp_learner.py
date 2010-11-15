#! /usr/bin/python
import numpy as np, math
import sys
from threading import RLock

import roslib; roslib.load_manifest('hrl_pr2_lib')
import rospy

import actionlib

from geometry_msgs.msg import  Point, Pose, Quaternion, PoseStamped

import random
import hrl_lib.util
from hrl_lib.keyboard_input import KeyboardInput
from hrl_lib.transforms import rotX, rotY, rotZ
from tf.transformations import *
from hrl_pr2_lib.pr2_arms import PR2Arms
from hrl_pr2_lib.perception_monitor import ArmPerceptionMonitor

# from pr2_gripper_reactive_approach.controller_manager import ControllerManager
from hrl_pr2_lib.hrl_controller_manager import HRLControllerManager as ControllerManager
from pr2_controllers_msgs.msg import JointTrajectoryGoal
import object_manipulator.convert_functions as cf
from object_manipulator.cluster_bounding_box_finder import ClusterBoundingBoxFinder
from tabletop_object_detector.srv import TabletopDetection
from tabletop_object_detector.msg import TabletopDetectionResult

#SETUP_POS = (0.62, 0.0, 0.035)
#SETUP_POS_ANGS = [-0.6260155429349421, -0.53466276262236689, -1.9803303473514324, -1.1593322538276705, -0.89803655400181404, -1.4467120153069799, -2.728422563953746]
#MAX_JERK = 0.2
ARM = 0 # right arm
if ARM == 0:
    armc = 'r'
else:
    armc = 'l'
NUM_X = 2#9#7 #4#7
NUM_Y = 2#15#9 #4#20
NUM_N = 3 #4
NUM_ROT = 12
# near to far, left to right
RECT = ((0.54, 0.00), (0.61, -0.07))#((0.4, 0.35), (0.8, -0.35))#((0.45, 0.10), (0.65, -0.10))#((0.4, 0.20), (0.7, -0.20))#((0.4, 0.35), (0.8, -0.35)) #((0.55, 0.10), (0.7, -0.10)) #((0.4, -0.77), (0.75, 0.23))
HOVER_Z = -0.10
GRASP_DIST = 0.30 
GRASP_TIME = 2.0
GRASP_VELOCITY = 0.28 # 0.15
SETUP_VELOCITY = 0.4 # 0.15
STD_DEV = 2.3 #3.5 #1.9
NOISE_DEV = 0.2
GRIPPER_POINT = np.array([0.23, 0.0, 0.0])
JOINTS_BIAS = [0., -.25, -1., 0., 0., 0.5, 0.]
BIAS_RADIUS = 0.012
DETECT_ERROR = -0.02
STD_DEV_DICT = { "accelerometer" : np.array([2.5, 3.0, 3.0]),
                 "joint_angles" : np.array([1.0, 1.0, 1.0, 1.0, 400.0, 1.0, 400.0]),
                 "joint_efforts" : np.array([7.0, 7.0, 7.0, 7.0, 7.0, 7.0, 7.0]),
                 "joint_velocities" : np.array([1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]),
                 "r_finger_periph_pressure" : np.array([80.0]*6), 
                 "r_finger_pad_pressure" : np.array([80.0]*15), 
                 "l_finger_periph_pressure" : np.array([80.0]*6), 
                 "l_finger_pad_pressure" : np.array([80.0]*15) }
TOL_THRESH_DICT = { "joint_velocities" : np.array([0.08]*7),
                    "joint_angles" : np.array([0.08]*7),
                    "joint_efforts" : np.array([0.08]*7) }
#STD_DEV_DICT = None
PICKLES_LOC = "//src//hrl_pr2_lib//pickles//"
GRASP_CONFIGS_FILE = "grasp_configs.pickle"
GRASP_DATA_FILE = "grasp_data.pickle"
GRASP_MODELS_FILE = "grasp_models.pickle"
ZEROS_FILE = "current_zeros.pickle"
SQR_DIFF_MAP = "sqr_diff_map.pickle"
GRASP_IND_PREFIX = "indexed//grasp_ind"
GRASP_INDEX_FILE = "indexed//grasp_index.pickle"
TEST_DATA_FILE = "test_data.pickle"
MONITOR_WINDOW = 200
PERCEPT_MON_LIST = None #["accelerometer"]
PERCEPT_GRASP_LIST = ["r_finger_periph_pressure", 
                 "r_finger_pad_pressure", 
                 "l_finger_periph_pressure", 
                 "l_finger_pad_pressure"] #["joint_angles"]#["joint_velocities"] #["r_finger_periph_pressure"] #["joint_efforts"] #["joint_angles"]

node_name = "simple_grasp_learner" 

def log(str):
    rospy.loginfo(node_name + ": " + str)

def load_pickle(fn):
    global PACKAGE_LOC
    return hrl_lib.util.load_pickle(PACKAGE_LOC + PICKLES_LOC + fn)

def save_pickle(p, fn):
    global PACKAGE_LOC
    hrl_lib.util.save_pickle(p, PACKAGE_LOC + PICKLES_LOC + fn)

def setup_package_loc():
    global PACKAGE_LOC
    import os
    grep = os.popen("rospack find hrl_pr2_lib|grep hrl_pr2_lib")
    PACKAGE_LOC = grep.readlines()[0].rstrip()

def save_parameters(param_filename):
    params = {  "ARM" :                   ARM,
                "NUM_X" :                 NUM_X,
                "NUM_Y" :                 NUM_Y,
                "NUM_N" :                 NUM_N,
                "NUM_ROT" :               NUM_ROT,
                "RECT" :                  RECT,
                "HOVER_Z" :               HOVER_Z,
                "GRASP_DIST" :            GRASP_DIST,
                "GRASP_TIME" :            GRASP_TIME,
                "GRASP_VELOCITY" :        GRASP_VELOCITY,
                "SETUP_VELOCITY" :        SETUP_VELOCITY,
                "STD_DEV" :               STD_DEV,
                "NOISE_DEV" :             NOISE_DEV,
                "GRIPPER_POINT" :         GRIPPER_POINT,
                "JOINTS_BIAS" :           JOINTS_BIAS,
                "BIAS_RADIUS" :           BIAS_RADIUS,
                "DETECT_ERROR" :          DETECT_ERROR,
                "STD_DEV_DICT" :          STD_DEV_DICT,
                "PICKLES_LOC" :           PICKLES_LOC,
                "GRASP_CONFIGS_FILE" :    GRASP_CONFIGS_FILE,
                "GRASP_DATA_FILE" :       GRASP_DATA_FILE,
                "GRASP_MODELS_FILE" :     GRASP_MODELS_FILE,
                "ZEROS_FILE" :            ZEROS_FILE,
                "SQR_DIFF_MAP" :          SQR_DIFF_MAP,
                "GRASP_IND_PREFIX" :      GRASP_IND_PREFIX,
                "GRASP_INDEX_FILE" :      GRASP_INDEX_FILE,
                "TEST_DATA_FILE" :        TEST_DATA_FILE,
                "MONITOR_WINDOW" :        MONITOR_WINDOW,
                "PERCEPT_MON_LIST" :      PERCEPT_MON_LIST }
    save_pickle(params, param_filename)

def load_parameters():
    params = load_pickle(param_filename)
    for k in params:
        globals()[k] = params[k]

##
# Transforms the given position by the offset position in the given quaternion
# rotation frame
#
# @param pos the current positions
# @param quat quaternion representing the rotation of the frame
# @param off_point offset to move the position inside the quat's frame
# @return the new position as a matrix column
def transform_in_frame(pos, quat, off_point):
    invquatmat = np.mat(quaternion_matrix(quat))
    invquatmat[0:3,3] = np.mat(pos).T
    trans = np.matrix([off_point[0],off_point[1],off_point[2],1.]).T
    transpos = invquatmat * trans
    return transpos.T.A[0,0:3]

# def get_setup_pos_angs():
#     arms = PR2Arms()
#     arms.move_arm(ARM, SETUP_POS, rotY(np.pi / 2.), 4.)
#     arms.wait_for_arm_completion(ARM)
#     print arms.get_joint_angles(ARM)

def get_xyr_list():
    grasp_xyr_list = []
    for x in np.linspace(RECT[0][0], RECT[1][0], NUM_X):
        for y in np.linspace(RECT[0][1], RECT[1][1], NUM_Y):
            for r in np.linspace(0., np.pi, NUM_ROT+1)[0:-1]:
                grasp_xyr_list += [(x,y,r)]
    return grasp_xyr_list

def create_goal_pose(x, y, z, gripper_rot= 0.):
    gripper_rot = normalize_rot(gripper_rot)
    quat1 = quaternion_about_axis(np.pi/2., (0, 1, 0))
    quat2 = quaternion_about_axis(gripper_rot, (0, 0, 1))
    quat = quaternion_multiply(quat2, quat1)
    point = [x, y, z]
    point = transform_in_frame(point, quat, -GRIPPER_POINT).tolist()
    pose = point + quat.tolist()
    goal_pose = cf.create_pose_stamped(pose, "torso_lift_link")
    goal_pose.header.stamp = rospy.Time.now()
    return goal_pose

def move_to_grasp_pos(cm, grasp_pose, block=True):
    grasp_pose.header.stamp = rospy.Time.now()
    cm.move_cartesian_ik(grasp_pose, collision_aware = False, blocking = block,
                      step_size = .005, pos_thres = .02, rot_thres = .1,
                      settling_time = rospy.Duration(1.0),
                      vel = SETUP_VELOCITY)

def upward_lift(cm, grasp_pose, block=True):
    grasp_pose.header.stamp = rospy.Time.now()
    cm.move_cartesian_ik(grasp_pose, collision_aware = False, blocking = block,
                      step_size = .005, pos_thres = .02, rot_thres = .1,
                      settling_time = rospy.Duration(1.0),
                      vel = GRASP_VELOCITY,
                      joints_bias = -np.array(JOINTS_BIAS), bias_radius = BIAS_RADIUS)

def downward_grasp(cm, goal_pose, block=True):
    goal_pose.header.stamp = rospy.Time.now()
    return cm.move_cartesian_ik(goal_pose, collision_aware = False, blocking = block,
                      step_size = .005, pos_thres = .02, rot_thres = .1,
                      settling_time = rospy.Duration(GRASP_TIME),
                      joints_bias = JOINTS_BIAS, bias_radius = BIAS_RADIUS,
                      vel = GRASP_VELOCITY)


def save_grasp_configurations():
    arms = PR2Arms()

    grasp_xyr_list = get_xy_list()
    grasp_configs = []
    setup = False

    for xy in grasp_xyr_list:
#       if not setup:
#           # Move to setup position in the middle of the grasp space
#           print "Setting up"
#           arms.set_joint_angles(ARM, SETUP_POS_ANGS, 3.)
#           arms.wait_for_arm_completion(ARM)
#           rospy.sleep(0.5)
#           setup = True

        if arms.can_move_arm(ARM, [xy[0], xy[1], HOVER_Z], rotY(np.pi / 2.)):
            print "Moving to pos (%1.2f, %1.2f)" % xy
            arms.grasp_biased_move_arm(ARM, [xy[0], xy[1], HOVER_Z], rotY(np.pi / 2.), 3.)
            arms.wait_for_arm_completion(ARM)
            rospy.sleep(0.5)
            angs = arms.get_joint_angles(ARM)
            grasp_configs += [(xy, angs)]
            setup = False
        else:
            print "Can't move to to pos (%1.2f, %1.2f)" % xy
            # grasp_configs += [(xy, None)]

    save_pickle(grasp_configs, GRASP_CONFIGS_FILE)
    print "Configurations:"
    print_configs(grasp_configs)

def print_configs(grasp_configs):
    for config in grasp_configs:
        if config[1] is not None:
            print "(%1.2f, %1.2f):" % config[0], ", ".join(["%1.2f" % x for x in config[1]])
        else:
            print "(%1.2f, %1.2f):" % config[0], "No config"

def trim_bad_grasps(filename):
    grasp_configs = load_pickle(filename)
    print_configs(grasp_configs)
    new_configs = []
    for config in grasp_configs:
        if config[1] is not None:
            new_configs += [config]
    print_configs(new_configs)
    save_pickle(new_configs, filename)

def collect_grasp_data(generate_models=False, skip_grasp=False):
    cm = ControllerManager(armc)
    apm = ArmPerceptionMonitor(ARM, percept_mon_list=None)

    #    if restart:
    #        grasp_data = load_pickle(GRASP_DATA)
    #        grasp_xyr_list = zip(*grasp_data)[0]
    #    else:
    #        grasp_xyr_list = get_xy_list()
    #        grasp_data = []
    grasp_xyr_list = get_xyr_list()
    grasp_data = []

    print "Opening gripper"
    cm.command_gripper(0.08, -1.0, False)
    cm.gripper_action_client.wait_for_result(rospy.Duration(4.0))

    for xyr in grasp_xyr_list:
        if rospy.is_shutdown():
            return
        zeros = None
        # Do grasping num_n times
        for i in range(NUM_N):
            # Move to grasp position
            print "Moving to grasp position (%1.2f, %1.2f, %1.2f)" % xyr
            grasp_pose = create_goal_pose(xyr[0], xyr[1], HOVER_Z, gripper_rot = xyr[2])
            setup_result = cm.move_arm_pose_biased(grasp_pose, JOINTS_BIAS, SETUP_VELOCITY, 
                                    blocking = True)
            rospy.sleep(0.5)
            if skip_grasp:
                break
            if setup_result is not None:
                if zeros is None:
                    # wait for a bit to get the zeros here
                    zeros = apm.get_zeros()

                goal_pose = create_goal_pose(xyr[0], xyr[1], 
                                              HOVER_Z - GRASP_DIST, gripper_rot=xyr[2])
                # start gathering data
                apm.start_training()
                # move arm down
                print "Moving arm down"
                result = downward_grasp(cm, goal_pose, block=True)
                print result
                print "Finished moving arm"
                apm.stop_training()
                rospy.sleep(0.5)
            else:
                break

        # can't move to initial position
        if setup_result is None or skip_grasp:
            continue

        if result != "no solution" and generate_models:
            models = apm.generate_models()
        else:
            models = None
        if result != "no solution":
            grasp_data += [(xyr, None, apm.datasets, models, zeros)]
        else:
            print "Grasp Failed, not adding data"
        apm.clear_vars()

    save_pickle(grasp_data, GRASP_DATA_FILE)
    return grasp_data

def load_data_and_generate(grasp_data):
    ret = []
    n = 0
    for grasp in grasp_data:
        apm = ArmPerceptionMonitor(ARM, percept_mon_list=PERCEPT_MON_LIST)
        apm.datasets = grasp[2]
        apm.generate_models()
        ret += [(grasp[0], grasp[1], grasp[2], apm.models, grasp[4])]
        n += 1
        print "Generated %d models" % (n)
    return ret

def test_monitor(grasp_data):
    apm = ArmPerceptionMonitor(ARM)
    j = 0
    while grasp_data[j][1] is None:
        j += 1
    apm.models = grasp_data[j][3]
    def print_warn():
        print "Warning! Outside model"
    apm.begin_monitoring(contingency=print_warn)
    raw_input()
    apm.end_monitoring()

def save_current_zeros(filename=ZEROS_FILE):
    apm = ArmPerceptionMonitor(ARM, percept_mon_list=PERCEPT_MON_LIST)
    zeros = apm.get_zeros()
    print "Zeros:", zeros
    save_pickle(zeros, filename)

def load_current_zeros(filename=ZEROS_FILE):
    return load_pickle(filename)

def open_gripper(cm=None, blocking = False):
    if cm is None:
        cm = ControllerManager(armc)
    cm.command_gripper(0.08, -1.0, False)
    if blocking:
        cm.gripper_action_client.wait_for_result(rospy.Duration(4.0))

def perform_grasp(x, y, z=None, gripper_rot = np.pi / 2., grasp=None, is_place=False,
                  is_grasp=True, collide = True, return_pose=True,
                  zeros = None, cm=None, apm=None):
    print "Performing grasp (%1.2f, %1.2f), rotation: %1.2f" % (x, y, gripper_rot)
    gripper_rot = normalize_rot(gripper_rot)

    if cm is None:
        cm = ControllerManager(armc)
    if apm is None:
        apm = ArmPerceptionMonitor(ARM, percept_mon_list=PERCEPT_GRASP_LIST)

    if grasp is None:
        grasp = get_grasp_model(x, y, gripper_rot)

    #apm.datasets = grasp[2]
    #apm.models = grasp[3]
    #apm.model_zeros = grasp[4]
    #print "Model zeros:", grasp[4]

    print "Beginning grasp"

    # Move to grasp position
    print "Moving to initial grasp position"
    # cm.command_joint_trajectory([grasp[1]], SETUP_VELOCITY, blocking = True)

    # print "Moving to final grasp position"
    grasp_pose = create_goal_pose(x, y, HOVER_Z, gripper_rot)
    cm.move_arm_pose_biased(grasp_pose, JOINTS_BIAS, SETUP_VELOCITY, blocking = False)
    if not is_place and is_grasp:
        # open gripper
        print "Opening gripper"
        cm.command_gripper(0.08, -1.0, False)
        cm.gripper_action_client.wait_for_result(rospy.Duration(2.0))
    cm.wait_joint_trajectory_done()
    rospy.sleep(0.1)

    #if zeros is None:
    zeros = apm.get_zeros(0.6)
    print "Current zeros:", zeros

    goal_pose = create_goal_pose(x, y, HOVER_Z - GRASP_DIST, gripper_rot)

    class Collision():
        def __init__(self):
            self.collided = False
        # start gathering data
        def on_collision(self):
            print "Collision!"
            self.collided = True
            while not cm.check_joint_trajectory_done():
                cm.joint_action_client.cancel_all_goals()
                rospy.sleep(0.01)
                if rospy.is_shutdown():
                    return None
    col = Collision()
    def rotate_acceleration(data):
        return data
        data -= zeros["accelerometer"]
        a = gripper_rot
        data[1] = np.cos(a) * data[1] - np.sin(a) * data[2]
        data[2] = np.sin(a) * data[1] + np.cos(a) * data[2]
        data += zeros["accelerometer"]
        return data

    transforms = { "accelerometer" : rotate_acceleration }
        
    apm.begin_monitoring(models = grasp[3], model_zeros = grasp[4], 
                         contingency=col.on_collision, window_size=MONITOR_WINDOW,
                         current_zeros=zeros, std_dev_default=STD_DEV, 
                         std_dev_dict = STD_DEV_DICT,
                         tol_thresh_dict = TOL_THRESH_DICT,
                         noise_dev_default=NOISE_DEV, collide=collide,
                         transform_dict = transforms) 
    # move arm down
    print "Moving arm down"
    downward_grasp(cm, goal_pose, block = False)
    if z is None:
        while not cm.check_joint_trajectory_done():
            if col.collided:
                cm.joint_action_client.cancel_all_goals()
            rospy.sleep(0.01)
            if rospy.is_shutdown():
                return None
    else:
        while not cm.check_joint_trajectory_done():
            if col.collided:
                cm.joint_action_client.cancel_all_goals()
            wrist_pose = cm.get_current_wrist_pose_stamped("torso_lift_link")
            p = wrist_pose.pose.position
            o = wrist_pose.pose.orientation
            affector_pos = transform_in_frame([p.x, p.y, p.z],
                                              [o.x, o.y, o.z, o.w], GRIPPER_POINT)
            if affector_pos[2] <= z:
                print "Reached z position"
                print "Affector position:", affector_pos
                while not cm.check_joint_trajectory_done():
                    cm.joint_action_client.cancel_all_goals()
                    rospy.sleep(0.01)
                break
            rospy.sleep(0.01)
            if rospy.is_shutdown():
                return None

    print "Finished moving arm"

    avg_list = apm.end_monitoring()
    rospy.sleep(0.1)

    if not is_place and is_grasp:
        print "Closing gripper"
        cm.command_gripper(0.0, 30.0, True)
        print "Gripper closed"
    elif is_place:
        print "Opening gripper"
        cm.command_gripper(0.08, -1.0, True)
        print "Gripper opened"

    if return_pose and is_grasp:
        print "Moving back to grasp position"
        cm.move_arm_pose_biased(grasp_pose, JOINTS_BIAS, SETUP_VELOCITY, blocking = True)
    #upward_lift(cm, grasp_pose, block=True)
    print "Grasp complete!"
    
    return grasp, avg_list, col.collided, zeros

# def perform_template_grasp(grasp):
#     cm = ControllerManager(armc)
#     apm = ArmPerceptionMonitor(ARM, percept_mon_list=["accelerometer"])
# 
#     apm.datasets = grasp[2]
#     apm.models = grasp[3]
# 
#     # Move to grasp position
#     print "Moving to grasp position"
#     cm.command_joint(grasp[1])
#     cm.wait_joint_trajectory_done()
#     rospy.sleep(0.5)
# 
#     goal_pose = create_goal_pose(grasp[0][0], grasp[0][1], HOVER_Z - GRASP_DIST)
# 
#     # start gathering data
#     def print_collision():
#         print "Collision!"
#         cm.freeze_arm()
#     apm.begin_monitoring(contingency=print_collision, window_size=MONITOR_WINDOW)
# 
#     # move arm down
#     print "Moving arm down"
#     downward_grasp(cm, goal_pose, block = False)
#     cm.wait_joint_trajectory_done()
#     print "Finished moving arm"
# 
#     avg_list = apm.end_monitoring()
#     rospy.sleep(0.5)
# 
#     return avg_list

def display_grasp_data(grasps, percept="accelerometer", indicies=range(3), 
                       std_dev=STD_DEV, noise_dev_add=NOISE_DEV, monitor_data=[], 
                       std_dev_dict=STD_DEV_DICT,
                       tol_thresh_dict=TOL_THRESH_DICT,
                       model_zeros=None, monitor_zeros=None,
                       plot_data=False, colors=None):
    import matplotlib.pyplot as plt
    if colors is None:
        colors = ['r', 'b', 'g', 'c']
    j = 0
    rows = len(grasps)
    cols = len(indicies)
    for i, grasp in enumerate(grasps):
        models = grasp[3]
        means = models[percept]["mean"]
        vars = models[percept]["variance"]
        signals = models[percept]["smoothed_signals"]
        noise_var = models[percept]["noise_variance"]
        noise_dev = np.sqrt(noise_var)
        print "noise variance", noise_var

        zip_means = np.array(zip(*means))
        zip_vars = np.array(zip(*vars))
        zip_signals = [ zip(*sig) for sig in signals ]
        # print "monitor_data", monitor_data
        zip_monitors = []
        for d in monitor_data:
            zip_monitors += [zip(*d[percept])]
        graph_means, graph_devs, mmax, mmin = [], [], [], []
        for w in indicies:
            graph_means += [zip_means[w]]
            graph_devs += [np.sqrt(zip_vars[w])]

            if std_dev_dict is not None and percept in std_dev_dict:
                std_dev = std_dev_dict[percept][w]
            if tol_thresh_dict is not None and percept in tol_thresh_dict:
                tol_thresh = tol_thresh_dict[percept][w]
            else:
                tol_thresh = 0.

            mmax += [graph_means[w] + graph_devs[w] * std_dev + noise_dev[w] * noise_dev_add
                                                                             + tol_thresh]
            mmin += [graph_means[w] - graph_devs[w] * std_dev - noise_dev[w] * noise_dev_add
                                                                             - tol_thresh]

        for k in range(len(indicies)):
            plt.subplot(rows, cols, i*cols + 1 + k)
            cnum = 0
            if plot_data:
                for stream in grasp[2][percept]:
                    # s_mag = [np.sqrt(x[1][0]**2 + x[1][1]**2 + x[1][2]**2) for x in stream]
                    # plt.plot(s_mag,colors[cnum])
                    plt.plot([x[1][k] for x in stream],colors[cnum])
                    cnum += 1
                    cnum %= len(colors)
            for sig in zip_signals:
                plt.plot(sig[indicies[k]], colors[2])
            zip_monitor = zip_monitors[i]
            len_diff = len(graph_means[k]) - len(zip_monitor[indicies[k]])
            add_vals = [zip_monitor[indicies[k]][0]] * MONITOR_WINDOW
            # add_vals = [zip_monitor[indicies[k]][0]] * len_diff
            print len_diff
            g = np.array(add_vals + list(zip_monitor[indicies[k]]))
            g += grasp[4][percept][indicies[k]] - monitor_zeros[i][percept][indicies[k]]
            plt.plot(g.tolist(),colors[3])
            plt.plot(graph_means[k], colors[0])
            plt.plot(mmax[k], colors[1])
            plt.plot(mmin[k], colors[1])
            plt.title("%1.2f, %1.2f: coord %d" % (grasp[0][0], grasp[0][1], k))
        j += 1

    plt.show()

def die():
    sys.exit()

def test_num_samples(percept="accelerometer"):
    # This function proves that adding more than 3-4 grasps per location is unnecessary
    # Grasping trajectories are very repeatable given a specific grasping location.
    # The issue comes from more from shifting of the actual trajectory from expected
    # given a grasping location just a few cm off.  The models can handle the trajectory
    # so long as it is not much more than 5cm away from the training model.

    grasp_data = load_pickle(GRASP_DATA_FILE)[0:1]
    data_list = grasp_data[0][2][percept]
    for i in [3, 6, 9]:
        apm = ArmPerceptionMonitor(ARM, percept_mon_list=PERCEPT_MON_LIST)
        grasp_data[0][2][percept] = data_list[0:i+1]
        apm.datasets = grasp_data[0][2]
        apm.generate_models()
        grasp_data[0][3][percept] = apm.models[percept]
        if i != 3:
            colors = ['m', 'y', 'k', 'r']
        else:
            colors = None
        display_grasp_data(grasp_data, percept, rows=1)

def detect_tabletop_objects():
    cbbf = ClusterBoundingBoxFinder()
    object_detector = rospy.ServiceProxy("/object_detection", TabletopDetection)
    detects = object_detector(True, False).detection
    object_detector.close()
    if detects.result != 4:
        print "Detection failed (err %d)" % (detects.result)
    table_z = detects.table.pose.pose.position.z
    objects = []
    for cluster in detects.clusters:
        (object_points, 
         object_bounding_box_dims, 
         object_bounding_box, 
         object_to_base_link_frame, 
         object_to_cluster_frame) = cbbf.find_object_frame_and_bounding_box(cluster)
        # print "bounding box:", object_bounding_box
        (object_pos, object_quat) = cf.mat_to_pos_and_quat(object_to_cluster_frame)
        angs = euler_from_quaternion(object_quat)
        print "angs:", angs
        # position is half of height
        object_pos[2] = table_z + object_bounding_box[1][2] / 2. + DETECT_ERROR
        print "pos:", object_pos
        print "table_z:", table_z
        objects += [[object_pos, angs[2]]]
    return objects

def grasp_object(obj, grasp=None, collide=True, is_place=False, zeros=None, cm=None, apm=None):
    if collide:
        return perform_grasp(obj[0][0], obj[0][1], is_place=is_place,
                             gripper_rot=obj[1], grasp=grasp, zeros=zeros, cm=cm, apm=apm)
    else:
        return perform_grasp(obj[0][0], obj[0][1], z=obj[0][2], is_place=is_place,
                             gripper_rot=obj[1], grasp=grasp, zeros=zeros, cm=cm, apm=apm)

def grasp_closest_object(x, y, grasp=None, collide=True, zeros=None, cm=None, apm=None):
    objects = detect_tabletop_objects()
    if len(objects) > 0:
        def dist(o):
            return (o[0][0] - x) ** 2 + (o[0][1] - y) ** 2
        obj = min(objects, key=dist)
        (grasp, avg_list, collided, zeros) = grasp_object(obj, grasp=grasp, 
                                                   collide=collide, zeros=zeros, cm=cm, apm=apm)
        return obj, grasp, avg_list, collided, zeros
    else:
        print "No objects near point"
        return None

def grasp_demo():
    cm = ControllerManager(armc)
    apm = ArmPerceptionMonitor(ARM, percept_mon_list=PERCEPT_MON_LIST)
    grasps, avg_lists = [], []
    (obj1, grasp, avg_list, collided, zeros) = grasp_closest_object(0.45, 0.1, cm=cm, apm=apm)
    grasps += [grasp]
    avg_lists += [avg_list]
    obj1pl = [[obj1[0][0], obj1[0][1] - 0.18], obj1[1]]
    (grasp, avg_list, collided, zeros) = grasp_object(obj1pl, is_place=True, zeros=zeros, cm=cm, apm=apm)
    grasps += [grasp]
    avg_lists += [avg_list]
    (obj2, grasp, avg_list, collided, zeros) = grasp_closest_object(0.7, 0.1, zeros=zeros, cm=cm, apm=apm)
    grasps += [grasp]
    avg_lists += [avg_list]
    (grasp, avg_list, collided, zeros) = grasp_object(obj1, is_place=True, zeros=zeros, cm=cm, apm=apm)
    grasps += [grasp]
    avg_lists += [avg_list]
    (obj3, grasp, avg_list, collided, zeros) = grasp_closest_object(obj1pl[0][0], obj1pl[0][1], zeros=zeros, cm=cm, apm=apm)
    grasps += [grasp]
    avg_lists += [avg_list]
    (grasp, avg_list, collided, zeros) = grasp_object(obj2, is_place=True, zeros=zeros, cm=cm, apm=apm)
    grasps += [grasp]
    avg_lists += [avg_list]
    display_grasp_data(grasps[0:3], "accelerometer", monitor_data=avg_lists[0:3])
    display_grasp_data(grasps[3:-1], "accelerometer", monitor_data=avg_lists[3:-1])

def trim_test_data(grasp_data=None):
    if grasp_data is None:
        grasp_data = load_pickle(GRASP_DATA_FILE)
    new_data = []
    for grasp in grasp_data:
        new_data += [(grasp[0], grasp[1], None, grasp[3], grasp[4])]
    save_pickle(new_data, GRASP_MODELS_FILE)
    return new_data

def split_model_data(data=None):
    if data is None:
        data = load_pickle(GRASP_MODELS_FILE)
    xyr_index = []
    n = 1
    for grasp in data:
        filename = GRASP_IND_PREFIX + "%03d-%03d-%03d.pickle" % (int(grasp[0][0]*100),int(grasp[0][1]*100),int(grasp[0][2]*100))
        xyr_index += [[grasp[0], filename]]
        save_pickle(grasp, filename)
        n += 1
    save_pickle(xyr_index, GRASP_INDEX_FILE)

def normalize_rot(gripper_rot):
    while gripper_rot >= np.pi:
        gripper_rot -= np.pi
    while gripper_rot < 0.:
        gripper_rot += np.pi
    return gripper_rot

def get_grasp_model(x, y, r, xyr_index = None):
    r = normalize_rot(r)
    if xyr_index is None:
        xyr_index = load_pickle(GRASP_INDEX_FILE)
    if len(xyr_index) > 0:
        def dist(o):
            if np.allclose(o[0][2], 0.0):
                # for loop around
                rot_dist = min((np.pi - r) ** 2, (0. - r) ** 2)
            else:
                rot_dist = (o[0][2] - r) ** 2
            return (o[0][0] - x) ** 2 + (o[0][1] - y) ** 2 + rot_dist
        xyr = min(xyr_index, key=dist)
        print "Distance to grasp model:", dist(xyr), "rotation diff:", xyr[0][2] - r 
        return load_pickle(xyr[1])
    else:
        print "Bad index file"
        return None

def compute_sqr_diff_map(percept="accelerometer"):
    xys = get_xy_list()
    def get_xy(i, j):
        return xys[i * NUM_Y + j]
    def model_sqr_err(m1, xy, i, j):
        n = 0
        sum = 0.
        cxy = get_xy(i, j)
        g2 = get_grasp_model(cxy[0], cxy[1])
        if np.allclose(g2[0], xy):
            return [-1.]
        m2 = g2[3][percept]["mean"]
        for i in range(min(len(m1),len(m2))):
            sum += (m1[i] - m2[i]) ** 2
            n += 1
        return sum / n
    xy_index = load_pickle(GRASP_INDEX_FILE)
    if len(xys) > 0:
        map = [] 
        for i in range(NUM_X):
            map += [[]]
            for j in range(NUM_Y):
                cen_xy = get_xy(i, j)
                cen_grasp = get_grasp_model(cen_xy[0], cen_xy[1])
                cen_grasp_model = cen_grasp[3][percept]["mean"]
                if not np.allclose(cen_xy, cen_grasp[0]):
                    map[-1] += [0.]
                    continue
                else:
                    err = 0.
                    n = 0
                    new_err = model_sqr_err(cen_grasp_model, cen_xy, i+1, j)
                    if new_err[0] != -1.:
                        err += new_err
                        n += 1
                    new_err = model_sqr_err(cen_grasp_model, cen_xy, i-1, j)
                    if new_err[0] != -1.:
                        err += new_err
                        n += 1
                    new_err = model_sqr_err(cen_grasp_model, cen_xy, i, j+1)
                    if new_err[0] != -1.:
                        err += new_err
                        n += 1
                    new_err = model_sqr_err(cen_grasp_model, cen_xy, i, j-1)
                    if new_err[0] != -1.:
                        err += new_err
                        n += 1
                    err = np.linalg.norm(err) ** 2 / len(err)
                    if n > 0:
                        map[-1] += [err / n]
                    else:
                        map[-1] += [0.]
        return map
    else:
        print "Bad index file"
        return None

def sqr_diff_viz():
    # save_pickle(compute_sqr_diff_map(), SQR_DIFF_MAP)
    map = load_pickle(SQR_DIFF_MAP)
    map.reverse()
    maxarg = max([max(row) for row in map])
    print np.mat(map)
    for i in range(len(map)):
        for j in range(len(map[i])):
            if map[i][j] == -1.:
                map[i][j] = maxarg*1.5
    import matplotlib.pyplot as plt
    fig = plt.figure()
    ax = fig.add_subplot(111)
    ax.matshow(map)
    plt.show()

def process_data(grasp_data=None):
    print "Loading data"
    if grasp_data is None:
        grasp_data = load_pickle(GRASP_DATA_FILE)
    grasp_data = load_data_and_generate(grasp_data)
    print "Saving models"
    save_pickle(grasp_data, GRASP_DATA_FILE)
    print "Trimming test data"
    model_data = trim_test_data(grasp_data)
    print "Splitting models"
    split_model_data(model_data)
    print "Done processing data"

def random_grasp():
    xs = (RECT[1][0] - RECT[0][0]) / (NUM_X - 1)
    ys = (RECT[0][1] - RECT[1][1]) / (NUM_Y - 1)
    x = random.uniform(RECT[0][0]-xs/2., RECT[1][0]+xs/2.)
    y = random.uniform(RECT[1][1]-ys/2., RECT[0][1]+ys/2.)
    r = random.uniform(0., np.pi)
    return x, y, r

def test_random_grasps(num_grasps=100):
    cm = ControllerManager(armc)
    apm = ArmPerceptionMonitor(ARM, percept_mon_list=PERCEPT_GRASP_LIST)
    monitor_data = []
    grasps = []
    collided_list = []
    num_collided = 0
    test_data = []
    zeros = None
    open_gripper(cm=cm)

    for i in range(num_grasps):
        if rospy.is_shutdown():
            break
        x, y, rot = random_grasp()

        (grasp, monitor, collided, zeros) = perform_grasp(x, y, gripper_rot = rot, 
                                           collide=False, is_grasp = False, 
                                           zeros=zeros, cm=cm, apm=apm)
        test_data += [{"loc" : (x, y, rot), 
            #"model" : grasp, 
                       "monitor" : monitor, 
                       "collided" : collided,
                       "zeros" : zeros}]
    
        if collided:
            print "COLLIDED\n"*10
            num_collided += 1

    print "Accuracy: %d collisions out of %d grasps (%1.2f)" % (num_collided, num_grasps, 1. - float(num_collided) / num_grasps)
    save_pickle(test_data, TEST_DATA_FILE)

def calc_false_pos(test_data=None, xyr_index=None, apm=None):
    if test_data is None:
        test_data = load_pickle(TEST_DATA_FILE)
    if apm is None:
        apm = ArmPerceptionMonitor(ARM, percept_mon_list=PERCEPT_GRASP_LIST)
    num_collisions = 0
    indicies = {}
    for test in test_data:
        model = get_grasp_model(test["loc"][0], test["loc"][1], test["loc"][2], 
                                xyr_index=xyr_index)
        collision = apm.simulate_monitoring(test["monitor"], models=model[3], 
                             model_zeros = test["zeros"],
                             window_size=MONITOR_WINDOW,
                             std_dev_default=STD_DEV, 
                             std_dev_dict = STD_DEV_DICT,
                             tol_thresh_dict = TOL_THRESH_DICT,
                             noise_dev_default=NOISE_DEV)
        if collision is not None:
            num_collisions += 1
            k, index, diff = collision
            if not k in indicies:
                indicies[k] = [0]*len(model[3][k]["mean"][0])
            indicies[k][index] += 1
    print "Accuracy: %d collisions out of %d grasps (%1.2f)" % (num_collisions, len(test_data), 1. - float(num_collisions) / len(test_data))
    print indicies
    return float(num_collisions) / len(test_data)

# def dynamic_parameter_tune(alpha = 0.1, dev_seed = 1.2, seed_dict=None):
#     global STD_DEV_DICT
#     x_old = { "accelerometer" : [dev_seed]*3,
#               "joint_angles" : [dev_seed]*7,
#               "joint_velocities" : [dev_seed]*7,
#               "joint_efforts" : [dev_seed]*7,
#               "r_finger_periph_pressure" : [dev_seed]*6,
#               "r_finger_pad_pressure" : [dev_seed]*15, 
#               "l_finger_periph_pressure" : [dev_seed]*6,
#               "l_finger_pad_pressure" : [dev_seed]*15, ]
#     for k in STD_DEV_DICT:
#         STD_DEV_DICT[k] = np.array(STD_DEV_DICT[k])
#     test_data = load_pickle(TEST_DATA_FILE)
#     apm = ArmPerceptionMonitor(ARM, percept_mon_list=PERCEPT_GRASP_LIST)
#     def F(x):
#         sum = 0.
#         for k in x:
#             sum += np.sum(x[k])
#         global STD_DEV_DICT
#         STD_DEV_DICT = x
#         print "Evaluating:", x
#         fp = calc_false_pos(test_data=test_data)
#         print "False positive rate:", fp
#         return fp + alpha * sum
#     def add_x(x, delta, step):
#         
#     def get_grad(x_old, F_old, x_new, F_new):
#         grad = {}
#         for k in old:
#             grad[k] = (F_new - F_old) / (new[k] - old[k])
# 
#     step = 0.2
#     F_old = F(x_old)
#     x_new = copy.deepcopy(x_old)
#     for k in x_new:
#         x_new[k] += step
#     F_new = F(x_new)
#     
# 
#     for k in
# 
#     
#     for dev in devs:
#         fp = calc_false_pos(test_data=test_data)
#         print "std dev:", dev
#         fp_rate += [fp]



def main():
    rospy.init_node(node_name)
    # rospy.on_shutdown(die)
    setup_package_loc()
    ki = KeyboardInput()

    #grasp_data = collect_grasp_data(generate_models=False, skip_grasp=False)
    #return 0

    #process_data(grasp_data)
    #return 0

    #trim_test_data()
    # return 0

    #split_model_data()
    #return 0

    # print get_grasp_model(0., 0.)
    # return 0

    #grasp_demo()
    #return 0

    #test_random_grasps(250)
    #return 0

    #global STD_DEV_DICT
    #xdev = 2.5
    #devs = np.linspace(1.5, 4., 18)
    #fp_rate = []
    #test_data = load_pickle(TEST_DATA_FILE)
    #for dev in devs:
    #    STD_DEV_DICT = {"accelerometer" : [xdev, dev, dev] }
    #    fp = calc_false_pos(test_data=test_data)
    #    print "std dev:", dev
    #    fp_rate += [fp]

    #print devs
    #print fp_rate
    #return 0
    
    #monitor_data = []
    #grasp_data = load_data_and_generate(load_pickle(GRASP_DATA_FILE))
    #save_pickle(grasp_data, GRASP_DATA_FILE)
    #grasp_data = load_pickle(GRASP_DATA_FILE)
    #display_grasp_data(grasp_data[0], "accelerometer", monitor_data=monitor_data, rows=1)
    #return 0

    # print detect_tabletop_objects()
    # return 0

    # sqr_diff_viz()
    # return 0

    # get_setup_pos_angs()
    # print_configs(load_pickle(GRASP_CONFIGS_FILE))

    # save_grasp_configurations()
    # return 0
    # import random
    # data = load_pickle(GRASP_CONFIGS_FILE)
    # random.shuffle(data)

    cm = ControllerManager(armc)
    apm = ArmPerceptionMonitor(ARM, percept_mon_list=PERCEPT_GRASP_LIST) 
    # data = load_pickle(GRASP_CONFIGS_FILE)
    # new_data = []
    # xys = get_xy_list()
    # for grasp in data:
    #     for xy in xys:
    #         if np.allclose(xy, grasp[0]):
    #             new_data += [grasp]

    # print "length:", len(new_data)
    # collect_grasp_data(new_data)
    # collect_grasp_data(load_pickle(GRASP_CONFIGS_FILE))
    # return 0
    # trim_bad_grasps("gcb2.pickle")
    # return 0
    # save_current_zeros()
    # return 0
    # test_num_samples()
    # return 0

    # print "Generating data"
    # grasp_data = load_data_and_generate(load_pickle(GRASP_DATA_FILE))
    # save_pickle(grasp_data, GRASP_DATA_FILE)
    # print "Done generating data"
    # return 0

    # grasp_data = load_pickle(GRASP_DATA_FILE)
    #grasp = get_grasp_model(0., 0.)

    # monitor_data += [grasp_closest_object(0.48, 0.07, cm=cm, apm=apm)]
    # monitor_data += [grasp_closest_object(grasp_data, 0.48, 0.07, cm=cm, apm=apm)]
    # grasp_data = load_pickle(GRASP_DATA_FILE)
    # print grasp_data[0][0]
    # monitor_data = perform_template_grasp(grasp_data[0])
    # display_grasp_data(grasp_data, "accelerometer", monitor_data=monitor_data, rows=1)
    # display_grasp_data(grasp_data, "r_finger_periph_pressure", rows=1)
    # monitor_data = perform_grasp(grasp_data, .58, .14, gripper_rot = 0.)
    
    monitor_data = []
    monitor_zeros = []
    grasps = []
    collided_list = []
    num_grasps = 50
    num_collided = 0
    zeros = None

    for i in range(num_grasps):
        if rospy.is_shutdown():
            break
        #x, y, rot = random.uniform(.45, .65), random.uniform(-.2, .2), random.uniform(0., 3.14)
        x, y, rot = random_grasp()

        if True:
            #rot = 0.
            #global STD_DEV_DICT
            #STD_DEV_DICT = None
            (grasp, monitor, collided, zeros) = perform_grasp(x, y, gripper_rot = rot, 
                                               collide=True, is_grasp = False, 
                                               zeros=zeros, cm=cm, apm=apm)
        else:
            (obj, grasp, monitor, collided, zeros) = grasp_closest_object(x, y, collide=True, zeros=zeros, cm=cm, apm=apm)
            x, y, rot = random_grasp()
            perform_grasp(x, y, gripper_rot=rot, zeros = zeros, collide=True, is_place=True,
                                                                 cm=cm, apm=apm)
        grasps += [grasp]
        monitor_data += [monitor]
        collided_list += [collided]
        monitor_zeros += [zeros]
    
        if collided:
            print "COLLIDED"
            print "COLLIDED"
            print "COLLIDED"
            num_collided += 1

        if ki.kbhit():
            if PERCEPT_GRASP_LIST is None:
                percept = "accelerometer"
            else:
                percept = PERCEPT_GRASP_LIST[0]
            display_grasp_data(grasps[-3:], percept, monitor_data=monitor_data[-3:], monitor_zeros=monitor_zeros[-3:])
            break

    print "Accuracy: %d collisions out of %d grasps (%1.2f)" % (num_collided, num_grasps, 1. - float(num_collided) / num_grasps)
    test_data = [grasps, monitor_data, collided_list]
    return 0
    save_pickle(test_data, "test_runs.pickle")
    # if False:
    #     new_grasp = get_grasp_model(x+.05, y)
    #     if new_grasp is not None:
    #         grasps += [new_grasp] 
    #     new_grasp = get_grasp_model(x-.05, y)
    #     if new_grasp is not None:
    #         grasps += [new_grasp] 
    #     new_grasp = get_grasp_model(x, y+.05)
    #     if new_grasp is not None:
    #         grasps += [new_grasp] 
    #     new_grasp = get_grasp_model(x, y-.05)
    #     if new_grasp is not None:
    #         grasps += [new_grasp] 

    # new_monitor_data = []
    # for j in range(len(monitor_data)):
    #     ret_mon = []
    #     for i in range(len(monitor_data[j]["accelerometer"])):
    #         ret_mon += [np.sqrt(monitor_data[j]["accelerometer"][i][1] ** 2 + monitor_data[j]["accelerometer"][i][2] ** 2)]
    #     new_monitor_data += [np.array(ret_mon)]

    # for i in range(3000):
    #     monitor_data[0]["accelerometer"][i][1] = new_monitor_data[0][i] - new_monitor_data[1][i]
    #     monitor_data[1]["accelerometer"][i][1] = 0.
    #     monitor_data[2]["accelerometer"][i][1] = 0.

    # monitor_data += [perform_grasp(grasp_data, .55, .15, gripper_rot = 0., is_place=True)]
    # monitor_data += [perform_grasp(grasp_data, .56, .10, gripper_rot = 0.)]
    # monitor_data += [perform_grasp(grasp_data, .57, .10, gripper_rot = 0.)]
    # monitor_data += [perform_grasp(grasp_data, .58, .10, gripper_rot = 0.)]

    # for i in range(2):
    #     monitor_data += [perform_grasp(grasp_data, .55, .10, gripper_rot = 0., cm=cm, apm=apm)]
    #     monitor_data += [perform_grasp(grasp_data, .55, .15, gripper_rot = 0., is_place=True, cm=cm, apm=apm)]
    #     monitor_data += [perform_grasp(grasp_data, .55, .15, gripper_rot = 0., cm=cm, apm=apm)]
    #     monitor_data += [perform_grasp(grasp_data, .55, .10, gripper_rot = 0., is_place=True, cm=cm, apm=apm)]
    # monitor_data += [perform_grasp(grasp_data, .55, .10, z=HOVER_Z-0.14, gripper_rot = 0., is_place=False, cm=cm, apm=apm)]
    display_grasp_data(grasps, "accelerometer", monitor_data=monitor_data)
    raw_input()
    open_gripper(cm=cm)
    # test_monitor(load_pickle(GRASP_DATA_FILE))
    return 0

if __name__ == "__main__":
    sys.exit(main())
    
