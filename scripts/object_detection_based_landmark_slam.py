#!/usr/bin/env python
#! coding:utf-8

import numpy as np
import math
import matplotlib.pyplot as plt
import matplotlib.patches as patches

import ros

# EKF state covariance
Q = np.diag([0.5, 0.5, np.deg2rad(30.0)])**2

# Simulation parameter
observation_noise = np.diag([0.2, np.deg2rad(1.0)])**2 # landmark observation noise
Rsim = np.diag([1.0, np.deg2rad(10.0)])**2 # input noise

DT = 0.1  # time tick [s]
SIM_TIME = 50.0  # simulation time [s]
MAX_RANGE = 20.0  # maximum observation range
M_DIST_TH = 2.0  # Threshold of Mahalanobis distance for data association.
STATE_SIZE = 3  # State size [x,y,yaw]
LM_SIZE = 2  # LM state size [x,y]

CHI_2 = 9.21934 # X^2, 99%

show_animation = True

class ObjectDetectionBasedLandmarkSLAM:
    def __init__(self):
        self.hoge = 0

def ekf_slam(xEst, PEst, u, z):

    # Predict
    S = STATE_SIZE
    xEst[0:S] = motion_model(xEst[0:S], u)
    G, Fx = jacob_motion(xEst[0:S], u)
    #PEst[0:S, 0:S] = G.T * PEst[0:S, 0:S] * G + Fx.T * Q * Fx
    #PEst[0:S, 0:S] = np.dot(np.dot(Fx, PEst[0:S, 0:S]), Fx.T) + np.dot(np.dot(G, Q), G.T)
    PEst[0:S, 0:S] = np.dot(np.dot(Fx, PEst[0:S, 0:S]), Fx.T) + Q# + np.dot(np.dot(G, Q), G.T)
    initP = np.eye(2)

    # Update
    print(str(len(z)) + " landmarks detected")
    for iz in range(len(z[:, 0])):  # for each observation
        minid = search_correspond_LM_ID(xEst, PEst, z[iz, 0:2])

        nLM = calc_n_LM(xEst)
        if minid == nLM:
            print("New LM")
            # Extend state and covariance matrix
            xAug = np.vstack((xEst, calc_LM_Pos(xEst, z[iz, :])))
            PAug = np.vstack((np.hstack((PEst, np.zeros((len(xEst), LM_SIZE)))),
                              np.hstack((np.zeros((LM_SIZE, len(xEst))), initP))))
            xEst = xAug
            PEst = PAug
        lm = get_LM_Pos_from_state(xEst, minid)
        y, S, H = calc_innovation(lm, xEst, PEst, z[iz, 0:2], minid)

        K = np.dot(np.dot(PEst, H.T), np.linalg.inv(S))
        xEst = xEst + np.dot(K, y)
        PEst = np.dot((np.eye(len(xEst)) - np.dot(K, H)), PEst)

    xEst[2] = pi_2_pi(xEst[2])

    return xEst, PEst


def calc_input():
    v = 1.0  # [m/s]
    yawrate = 0.1  # [rad/s]
    u = np.array([[v, yawrate]]).T
    return u


def observation(xTrue, xd, u, RFID):

    xTrue = motion_model(xTrue, u)

    # add noise to gps x-y
    z = np.zeros((0, 3))

    for i in range(len(RFID[:, 0])):

        dx = RFID[i, 0] - xTrue[0, 0]
        dy = RFID[i, 1] - xTrue[1, 0]
        d = math.sqrt(dx**2 + dy**2)
        angle = pi_2_pi(math.atan2(dy, dx) - xTrue[2, 0])
        # observable landmark
        if d <= MAX_RANGE:
            # recognition probablirity
            if np.random.rand(1) > 0.70:
                dn = d + np.random.randn() * observation_noise[0, 0]  # add noise
                anglen = angle + np.random.randn() * observation_noise[1, 1]  # add noise
                zi = np.array([dn, anglen, i])
                z = np.vstack((z, zi))

    # add noise to input
    ud = np.array([[
        u[0, 0] + np.random.randn() * Rsim[0, 0],
        u[1, 0] + np.random.randn() * Rsim[1, 1]]]).T

    xd = motion_model(xd, ud)
    return xTrue, z, xd, ud


def motion_model(x, u):

    F = np.array([[1.0, 0, 0],
                  [0, 1.0, 0],
                  [0, 0, 1.0]])

    B = np.array([[DT * math.cos(x[2, 0]), 0],
                  [DT * math.sin(x[2, 0]), 0],
                  [0.0, DT]])

    x = np.dot(F, x) + np.dot(B, u)
    return x


def calc_n_LM(x):
    n = int((len(x) - STATE_SIZE) / LM_SIZE)
    return n


def jacob_motion(x, u):

    Fx = np.hstack((np.eye(STATE_SIZE), np.zeros(
        (STATE_SIZE, LM_SIZE * calc_n_LM(x)))))

    jF = np.array([[0.0, 0.0, -DT * u[0] * math.sin(x[2, 0])],
                   [0.0, 0.0, DT * u[0] * math.cos(x[2, 0])],
                   [0.0, 0.0, 0.0]])

    G = np.eye(STATE_SIZE) + np.dot(np.dot(Fx.T, jF), Fx)

    return G, Fx,


def calc_LM_Pos(x, z):
    zp = np.zeros((2, 1))

    zp[0, 0] = x[0, 0] + z[0] * math.cos(x[2, 0] + z[1])
    zp[1, 0] = x[1, 0] + z[0] * math.sin(x[2, 0] + z[1])

    return zp


def get_LM_Pos_from_state(x, ind):

    lm = x[STATE_SIZE + LM_SIZE * ind: STATE_SIZE + LM_SIZE * (ind + 1), :]

    return lm


def search_correspond_LM_ID(xAug, PAug, zi):
    """
    Landmark association with Mahalanobis distance
    """

    nLM = calc_n_LM(xAug)

    mdist = []

    for i in range(nLM):
        lm = get_LM_Pos_from_state(xAug, i)
        y, S, H = calc_innovation(lm, xAug, PAug, zi, i)
        mdist.append(np.dot(np.dot(y.T, np.linalg.inv(S)), y))

    mdist.append(M_DIST_TH)  # new landmark

    minid = mdist.index(min(mdist))

    return minid


def calc_innovation(lm, xEst, PEst, z, LMid):
    # dx, dy
    delta = lm - xEst[0:2]
    # distance^2
    q = np.dot(delta.T, delta)[0, 0]
    # angle in robot frame
    zangle = math.atan2(delta[1, 0], delta[0, 0]) - xEst[2, 0]
    # polar coordinates
    zp = np.array([[math.sqrt(q), pi_2_pi(zangle)]])
    # error in polar coordinates (estimated pose - observed pose)
    y = (z - zp).T
    y[1] = pi_2_pi(y[1])
    H = jacobH(q, delta, xEst, LMid + 1)
    S = np.dot(np.dot(H, PEst), H.T) + Q[0:2, 0:2]

    return y, S, H


def jacobH(q, delta, x, i):
    # distance
    sq = math.sqrt(q)
    # -d*dx, -d*dy, 0, d*dx, d*dy
    # dy, -dx, -1, -dy, dx
    G = np.array([[-sq * delta[0, 0], - sq * delta[1, 0], 0, sq * delta[0, 0], sq * delta[1, 0]],
                  [delta[1, 0], - delta[0, 0], - 1.0, - delta[1, 0], delta[0, 0]]])

    G = G / q
    nLM = calc_n_LM(x)
    F1 = np.hstack((np.eye(3), np.zeros((3, 2 * nLM))))
    F2 = np.hstack((np.zeros((2, 3)), np.zeros((2, 2 * (i - 1))),
                    np.eye(2), np.zeros((2, 2 * nLM - 2 * i))))

    F = np.vstack((F1, F2))

    H = np.dot(G, F)

    return H


def pi_2_pi(angle):
    return (angle + math.pi) % (2 * math.pi) - math.pi

def calculate_error_ellipse(P):
    _lambda, _v = np.linalg.eig(P)
    max_index = np.argmax(_lambda)
    min_index = np.argmin(_lambda)
    a = math.sqrt(CHI_2 * _lambda[max_index])
    b = math.sqrt(CHI_2 * _lambda[min_index])
    ellipse_angle = math.atan2(_v[max_index, 1], _v[max_index, 0])
    return a, b, ellipse_angle

def main():
    print(__file__ + " start!!")

    time = 0.0

    # RFID positions [x, y]
    RFID = np.array([[10.0, -2.0],
                     [15.0, 10.0],
                     [3.0, 15.0],
                     [-5.0, 20.0]])

    # State Vector [x y yaw v]'
    xEst = np.zeros((STATE_SIZE, 1))
    xTrue = np.zeros((STATE_SIZE, 1))
    PEst = np.eye(STATE_SIZE)

    xDR = np.zeros((STATE_SIZE, 1))  # Dead reckoning

    # history
    hxEst = xEst
    hxTrue = xTrue
    hxDR = xTrue

    while SIM_TIME >= time:
        time += DT
        u = calc_input()

        xTrue, z, xDR, ud = observation(xTrue, xDR, u, RFID)

        xEst, PEst = ekf_slam(xEst, PEst, ud, z)

        # robot error ellipse
        a, b, ellipse_angle = calculate_error_ellipse(PEst[0:2, 0:2])

        x_state = xEst[0:STATE_SIZE]

        # store data history
        hxEst = np.hstack((hxEst, x_state))
        hxDR = np.hstack((hxDR, xDR))
        hxTrue = np.hstack((hxTrue, xTrue))

        if show_animation:  # pragma: no cover
            plt.cla()
            ax = plt.gca()

            plt.plot(RFID[:, 0], RFID[:, 1], "*k")
            plt.plot(xEst[0], xEst[1], ".r")

            p = patches.Ellipse(xy = (xEst[0], xEst[1]), width = a, height = b, alpha = 1, angle = math.degrees(ellipse_angle), color = "cyan")
            ax.add_patch(p)
            ax.annotate('', xy=[xEst[0]+math.cos(xEst[2]), xEst[1]+math.sin(xEst[2])], xytext=[xEst[0], xEst[1]],
                        arrowprops=dict(shrink=0, width=1, headwidth=8,
                                        headlength=10, connectionstyle='arc3',
                                        facecolor='gray', edgecolor='gray')
            )

            # plot landmark
            for i in range(calc_n_LM(xEst)):
                plt.plot(xEst[STATE_SIZE + i * 2],
                         xEst[STATE_SIZE + i * 2 + 1], "xg")
                a, b, ellipse_angle = calculate_error_ellipse(PEst[(STATE_SIZE + i * 2):(STATE_SIZE + i * 2) + 2, (STATE_SIZE + i * 2):(STATE_SIZE + i * 2) + 2])
                p = patches.Ellipse(xy = (xEst[STATE_SIZE + i * 2], xEst[STATE_SIZE + i * 2 + 1]), width = a, height = b, alpha = 1, angle = math.degrees(ellipse_angle), color = "Magenta")
                ax.add_patch(p)

            plt.plot(hxTrue[0, :],
                     hxTrue[1, :], "-b", label="Ground Truth")
            plt.plot(hxDR[0, :],
                     hxDR[1, :], "-k", label="Dead Reckoning")
            plt.plot(hxEst[0, :],
                     hxEst[1, :], "-r", label="Estimated Pose")

            plt.legend()

            plt.axis("equal")
            plt.grid(True)
            plt.pause(0.001)


if __name__ == '__main__':
    main()
