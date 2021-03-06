#!usr/bin/env python3
# -*- coding: utf-8 -*-

import numpy as np
import math
import time
import sys

sys.path.append('../..')
from envs.airCombateEnv.customization import init_posture
from envs.airCombateEnv.customization import REGISTRY_STATE as registry_state
from argument.argManage import args
from envs.unit import REGISTRY as registry_unit

if sys.version_info.major == 2:
    import Tkinter as tk
else:
    import tkinter as tk

np.set_printoptions(suppress=True)


class Env(object):
    def __init__(self):
        '''
        基类构造函数：
            还至少需要设置 state_space, action_space, state_dim, action_dim
            包含 单位实例列表 red_unit_list, blue_unit_list
        '''
        # 地图设置
        self.AREA = args.map_area  # 地图范围
        # 可视化显示参数
        self.SCALE = args.map_scale  # 比例尺
        self.SCOPE = self.AREA * self.SCALE  # Tkinter显示范围

        # 训练参数
        self.t = args.map_t  # 时间间隔（步长，秒)
        self.td = self.t / args.map_t_n  # 每个步长计算次数
        self.Sum_Oil = 100  # 油量，即每个episode的最大step数量

        ## 飞机列表
        self.red_unit_list = []
        self.blue_unit_list = []

    def _seed(self, seed):
        '''
        设置随机种子
        '''
        np.random.seed(seed)

    def reset(self):
        '''
        环境初始化
        输出：
            当前状态（所有飞机的当前状态）
        '''
        raise NotImplementedError

    def step(self, *action):
        '''
        输入：
            动作（环境内所有飞机的动作）
        输出：
            <下一状态，奖励值，done>，当前状态可以省略
        
        待扩展：
            局部可观察obs，额外状态信息（全局状态）state
        '''
        raise NotImplementedError

    def _get_reward(self, *args):
        '''
        根据当前飞机信息，给出奖励函数。
        最好是输入设置为当前环境能够给出的所有信息，返回的是奖励值。
        这样当使用时可以不用管中间的逻辑实现，只需看输入、输出；
        当想创建新的奖励函数模型时，只需要根据环境所能提供的信息，来实现此函数内逻辑的实现。
        '''
        raise NotImplementedError

    def render(self):
        '''
        环境的可视化显示
        '''
        raise NotImplementedError

    def close(self):
        '''
        可视化关闭
        '''
        raise NotImplementedError

    # Partially Observable Env for Multi-Agent
    # 部分可观察的多智能体环境使用
    def get_state(self):
        raise NotImplementedError

    def get_state_shape(self):
        raise NotImplementedError

    def get_agent_obs(self, agent_id):
        raise NotImplementedError

    def get_agent_obs_shape(self):
        raise NotImplementedError

    def _get_avail_actions(self):
        raise NotImplementedError

    def _get_agent_avail_actions(self, agent_id):
        raise NotImplementedError


class AirCombatEnv(Env):
    def __init__(self):
        super(AirCombatEnv, self).__init__()
        # 飞机参数
        self.red = registry_unit["default"](None, 200, 80)  # 红方飞机
        self.blue = registry_unit["default"](None, 200, 80)  # 蓝方飞机
        # reward判断指标
        self.AA_range = 60  # 视界角范围
        self.ATA_range = 30  # 天线拂擦角范围
        self.Dis_max = 500  # 距离最大值
        self.Dis_min = 100  # 距离最小值
        self.adv_count = 0  # 持续建立优势的次数
        # 初始想定模式：0随机，1进攻，2防御，3同向，4中立
        self.init_scen = args.init_scen
        # 强化学习动作接口
        self.action_space = ['l', 's', 'r']  # 向左滚转、维持滚转、向右滚转
        self.n_actions = len(self.action_space)
        self.action_dim = self.n_actions
        self.state_dim = len(registry_state[args.state_setting](self.red, self.blue, self.adv_count))
        # reward条件
        self.success = 0

    def reset_selfPlay(self):
        # 初始化参数
        self.reward_b = 0
        self.reward_r = 0
        self.done = False
        self.success = 0
        self.acts = [[], []]
        self.advs = []
        self.ATA_b = self.AA_b = 100
        self.ATA_r = self.AA_r = 100
        self.adv_count = 0
        # 初始化红蓝方飞机
        init_posture(self.init_scen, self.red, self.blue, args.random_r, args.random_b)
        self.red.oil = args.Sum_Oil
        self.blue.oil = args.Sum_Oil
        # print(self.red.ac_pos)
        # print(self.blue.ac_pos)
        # 计算ATA，AA
        self.ATA_b, self.AA_b = self._getAngle(self.red.ac_pos, self.blue.ac_pos, self.red.ac_heading,
                                               self.blue.ac_heading)
        self.ATA_r, self.AA_r = self._getAngle(self.blue.ac_pos, self.red.ac_pos, self.blue.ac_heading,
                                               self.red.ac_heading)
        # 计算距离
        dis = self._get_dis(self.red.ac_pos, self.blue.ac_pos)
        # 计算优势
        self.adv_count = self._calculate_Advantages(self.adv_count, dis, self.AA_r, self.ATA_r, self.AA_b, self.ATA_b)
        # reward shaping
        RA_b = 1 - ((1 - math.fabs(self.ATA_b) / 180) + (1 - math.fabs(self.AA_b) / 180))
        RA_r = 1 - ((1 - math.fabs(self.ATA_r) / 180) + (1 - math.fabs(self.AA_r) / 180))
        RD = math.exp(-(math.fabs(dis - ((self.Dis_max + self.Dis_min) / 2)) / 180 * 0.1))
        Rbl_b = RA_b * RD
        Rbl_r = RA_r * RD
        self.fai_b = -0.01 * Rbl_b
        self.fai_r = -0.01 * Rbl_r
        # 返回红蓝飞机状态
        s_b = registry_state[args.state_setting](self.red, self.blue, self.adv_count)
        s_r = registry_state[args.state_setting](self.blue, self.red, self.adv_count)
        return s_b, s_r

    def step_selfPlay(self, action_b, action_r):
        # 记录动作
        self.acts[0].append(action_b)
        self.acts[1].append(action_r)
        # 执行动作
        self.blue.move(action_b)
        self.red.move(action_r)
        # print(self.red.ac_pos)
        # print(self.blue.ac_pos)
        # 返回红蓝飞机状态
        s_b = registry_state[args.state_setting](self.red, self.blue, self.adv_count)
        s_r = registry_state[args.state_setting](self.blue, self.red, self.adv_count)
        # 计算reward
        self.reward_b, self.reward_r, self.done, self.adv_count = self._get_reward(self.red.ac_pos, self.red.ac_heading,
                                                                                   self.blue.ac_pos,
                                                                                   self.blue.ac_heading,
                                                                                   self.adv_count)
        # print(s_b, s_r, self.reward_b, self.reward_r, self.done)
        return s_b, s_r, self.reward_b, self.reward_r, self.done

    def _getAngle(self, agent_A_pos, agent_B_pos, agent_A_heading, agent_B_heading):
        """
        param:
            agent_A_pos:             飞机A的坐标
            agent_B_pos:             飞机B的坐标
            agent_A_heading:         飞机A的朝向角
            agent_B_heading:         飞机B的朝向角
        return:
            B的AA和ATA角
        主要逻辑：
            分别输入两架飞机的位置坐标 和 朝向角，
            计算 第二架飞机B的 ATA 和 AA 角（见doc/pic/envs_airCombateEnv_001.png）
        """
        theta_br = 180 * math.atan2((agent_A_pos[1] - agent_B_pos[1]), (agent_A_pos[0] - agent_B_pos[0])) / math.pi
        theta_rb = 180 * math.atan2((agent_B_pos[1] - agent_A_pos[1]), (agent_B_pos[0] - agent_A_pos[0])) / math.pi
        if theta_br < 0:
            theta_br = 360 + theta_br
        if theta_rb < 0:
            theta_rb = 360 + theta_rb
        ATA = agent_B_heading - theta_br
        AA = 180 + agent_A_heading - theta_rb
        if ATA > 180:
            ATA = 360 - ATA
        elif ATA < -180:
            ATA = 360 + ATA
        if AA > 180:
            AA = 360 - AA
        elif AA < -180:
            AA = 360 + AA
        return ATA, AA

    def _get_reward(self, ac_pos_r, ac_heading_r, ac_pos_b, ac_heading_b, adv_count):
        dis = math.sqrt((ac_pos_r[0] - ac_pos_b[0]) * (ac_pos_r[0] - ac_pos_b[0])
                        + (ac_pos_r[1] - ac_pos_b[1]) * (ac_pos_r[1] - ac_pos_b[1]))
        # 计算ATA和AA
        self.ATA_b, self.AA_b = self._getAngle(ac_pos_r, ac_pos_b, ac_heading_r, ac_heading_b)
        self.ATA_r, self.AA_r = self._getAngle(ac_pos_b, ac_pos_r, ac_heading_b, ac_heading_r)
        # 计算优势
        adv_count = self._calculate_Advantages(adv_count, dis, self.AA_r, self.ATA_r, self.AA_b, self.ATA_b)
        # reward shaping
        RA_b = 1 - ((1 - math.fabs(self.ATA_b) / 180) + (1 - math.fabs(self.AA_b) / 180))
        RA_r = 1 - ((1 - math.fabs(self.ATA_r) / 180) + (1 - math.fabs(self.AA_r) / 180))
        RD = math.exp(-(math.fabs(dis - ((self.Dis_max + self.Dis_min) / 2)) / 180 * 0.1))
        Rbl_b = RA_b * RD
        Rbl_r = RA_r * RD
        self.old_fai_b = self.fai_b
        self.old_fai_r = self.fai_r
        self.fai_b = -0.01 * Rbl_b
        self.fai_r = -0.01 * Rbl_r
        # 计算reward和终止条件
        # print(adv_count)
        if adv_count >= 9:
            done = True
            self.success = 1
            reward_b = 2.0
            reward_r = -2.0
            # print("bsuccess")
        elif adv_count <= -9:
            done = True
            self.success = -1
            reward_b = -2.0
            reward_r = 2.0
            # print("rsuccess")
        elif self.red.oil <= 0 and self.blue.oil <= 0:
            done = True
            self.success = 0
            reward_b = -1.0
            reward_r = -1.0
        elif (ac_pos_b[0] > args.map_area) or ((0 - ac_pos_b[0]) > args.map_area) or \
                (ac_pos_b[1] > args.map_area) or ((0 - ac_pos_b[1]) > args.map_area):
            done = True
            self.success = 0
            reward_b = -1.0
            reward_r = (self.fai_r - self.old_fai_r) - 0.001
        elif (ac_pos_r[0] > args.map_area) or ((0 - ac_pos_r[0]) > args.map_area) or \
                (ac_pos_r[1] > args.map_area) or ((0 - ac_pos_r[1]) > args.map_area):
            done = True
            self.success = 0
            reward_b = (self.fai_b - self.old_fai_b) - 0.001
            reward_r = -1.0
        else:
            done = False
            reward_b = (self.fai_b - self.old_fai_b) - 0.001
            reward_r = (self.fai_r - self.old_fai_r) - 0.001
        return reward_b, reward_r, done, adv_count

    def _calculate_Advantages(self, adv_count, dis, AA_r, ATA_r, AA_b, ATA_b):
        """
        计算红蓝方优势次数
        :param adv_count:优势次数：-1为红方优势态势，1为蓝方优势态势
        :param dis:距离
        :param AA_r:红方AA角
        :param ATA_r:红方ATA角
        :param AA_b:蓝方AA角
        :param ATA_b:蓝方ATA角
        :return:优势次数
        """
        # 计算优势
        if (dis < self.Dis_max) and (dis > self.Dis_min) \
                and (abs(AA_b) < self.AA_range) and (abs(ATA_b) < self.ATA_range):
            if adv_count >= 0:  # 如果之前蓝方已经是优势态势，优势累加
                adv_count += 1
            else:  # 如果之前是红方优势态势，优势交替
                adv_count = 1
        elif (dis < self.Dis_max) and (dis > self.Dis_min) \
                and (abs(AA_r) < self.AA_range) and (abs(ATA_r) < self.ATA_range):
            if adv_count <= 0:
                adv_count -= 1
            else:
                adv_count = -1
        else:
            adv_count = 0
        self.advs.append(adv_count)
        return adv_count

    def _get_dis(self, pos_a, pos_b):
        """
        计算坐标A和坐标B的距离
        :param pos_a: 坐标A
        :param pos_b: 坐标B
        :return: 坐标A和坐标B的距离
        """
        dis = math.sqrt((pos_a[0] - pos_b[0]) * (pos_a[0] - pos_b[0])
                        + (pos_a[1] - pos_b[1]) * (pos_a[1] - pos_b[1]))
        return dis

    def creat_ALG(self):
        self.Tk = tk.Tk()
        self.Tk.title('1V1')
        self.Tk.canvas = tk.Canvas(self.Tk, bg='white',
                                   height=args.map_area * args.map_scale * 2,
                                   width=args.map_area * args.map_scale * 2)
        self.Tk.canvas.pack()

    def render(self):
        # 刷新红方飞机
        self.r_show = self.xyz2abc(self.red.ac_pos)
        self.r = self.Tk.canvas.create_oval(
            self.r_show[0] - 1, self.r_show[1] - 1,
            self.r_show[0] + 1, self.r_show[1] + 1,
            fill='red')

        # 刷新蓝方飞机
        self.b_show = self.xyz2abc(self.blue.ac_pos)
        self.b = self.Tk.canvas.create_oval(
            self.b_show[0] - 1, self.b_show[1] - 1,
            self.b_show[0] + 1, self.b_show[1] + 1,
            fill='blue')

        self.Tk.update()
        time.sleep(0.05)
        if self.done:
            time.sleep(0.1)
            self.Tk.destroy()

    def close(self):
        self.Tk.destroy()

    def xyz2abc(self, pos):
        pos_show = np.array([0, 0])
        pos_show[0] = pos[0] * args.map_scale + args.map_area * args.map_scale
        pos_show[1] = args.map_area * args.map_scale - pos[1] * args.map_scale
        return pos_show


class AirCombatEnvMultiUnit(Env):
    def __init__(self):
        super(AirCombatEnv, self).__init__()

        # 初始化双方飞机
        id_number = 0
        for name in args.red_unit_type_list:  # args.red_unit_type_list为飞机类型名字列表
            red_unit = registry_unit[name](id_number)
            self.red_unit_list.append(red_unit)
            id_number = id_number + 1

        id_number = 0
        for name in args.blue_unit_type_list:
            blue_unit = registry_unit[name](id_number)
            self.blue_unit_list.append(blue_unit)
            id_number = id_number + 1

        self.n_red_unit = len(args.red_unit_type_list)
        self.n_blue_unit = len(args.blue_unit_type_list)

        # 强化学习动作接口
        # 【方案一】 直接使用联结动作空间，即 [a1, a2, ..., an, a1, a2, ..., an, ...]
        # 注意：如果红蓝双方飞机数量不一致，则分别定义
        self.single_action_space = ['l', 's', 'r']  # 向左滚转、维持滚转、向右滚转
        self.action_space = self.single_action_space * self.n_red_unit
        # # 【方案二】 使用decentralized policy，即动作空间只包含单独一个agent的
        # self.action_space = ['l', 's', 'r']

        self.action_dim = self.n_actions = len(self.action_space)
        self.state_dim = 5  # 需要定义

        # todo：reward判断指标

    def reset_selfPlay(self):
        self.done = False
        self.success = 0
        self.acts = [[], []]  # todo-levin: 只保存一个agent的acts，还是两个acgent的acts？

        # 1°初始化红蓝红方飞机
        # todo:
        # 【方案一】：
        # 按照实际阵型构建初始化阵型函数，初始化中心飞机的位置，确定每个飞机的位置
        # 【方案二】：
        # 随机初始化一个区域，在区域内随机初始各飞机的位置

        # 遍历列表初始化飞机的状态：滚转角、油量等

        # 2°得到初始状态
        for unit in self.red_unit_list:
            # 分别得到红、蓝双方的联结状态空间
            pass
        for unit in self.blue_unit_list:
            pass

    # levin - [done]： add both actions
    def step_selfPlay(self, action_blue_list, action_red_list):
        '''
        Parms:
            action_b: list or tuple
            action_r: list or tuple
        '''
        # 1° 双方飞机移动
        self._unit_move(self.blue_unit_list, action_blue_list)
        self._unit_move(self.red_unit_list, action_red_list)

    # 2° todo：得到联结状态空间
    # 3° todo：得到奖励值和done

    def _unit_move(self, unit_list, action_list):
        # todo：判断unit_list和action_list的维度匹配
        for unit, action in zip(unit_list, action_list):
            unit.move(action)


# 环境测试程序
if __name__ == '__main__':
    env = AirCombatEnv()
    env.init_scen = 4
    args.random_r = 1
    args.random_b = 1
    s = env.reset_selfPlay()
    env.creat_ALG()
    env.render()
    while True:
        if env.done:
            s = env.reset_selfPlay()
            env.creat_ALG()
        # a = np.random.randint(0,3)
        a_b = 1
        a_r = 1
        env.step_selfPlay(a_b, a_r)
        env.render()
