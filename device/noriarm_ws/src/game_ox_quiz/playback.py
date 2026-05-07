# 실행: python device/noriarm_ws/src/game_ox_quiz/playback.py device/noriarm_ws/src/game_ox_quiz/episode_0_trajectory.json

import time
import json
import argparse
import torch
import numpy as np
from lerobot.robots.omx_follower import OmxFollowerConfig
from lerobot.robots.utils import make_robot_from_config
from lerobot.utils.robot_utils import precise_sleep

def run_playback(json_path):
    # 1. 데이터 로드
    print(f"📖 Loading trajectory from {json_path}...")
    with open(json_path, "r") as f:
        data = json.load(f)
    
    trajectory = data["trajectory"]
    hz = data["hz"]
    num_frames = data["num_frames"]
    
    # 관절 이름 명단 (확인된 값)
    joint_names = [
        'shoulder_pan.pos', 'shoulder_lift.pos', 'elbow_flex.pos', 
        'wrist_flex.pos', 'wrist_roll.pos', 'gripper.pos'
    ]
    
    print(f"✅ Loaded {num_frames} frames at {hz}Hz.")

    # 2. 로봇 초기화
    print("🤖 Initializing Robot...")
    robot_config = OmxFollowerConfig(port="/dev/omx_follower")
    robot = make_robot_from_config(robot_config)
    robot.connect()
    print("✅ Robot connected.")

    def create_action_dict(pose_list):
        # [값1, 값2, ...] 리스트를 {'관절1.pos': 값1, '관절2.pos': 값2, ...} 형태로 변환
        action_dict = {}
        for name, val in zip(joint_names, pose_list):
            action_dict[name] = torch.tensor(val)
        return action_dict

    try:
        # 3. 시작 위치로 이동
        first_pose_action = create_action_dict(trajectory[0])
        
        print(f"🏠 Moving to starting position...")
        robot.send_action(first_pose_action)
        time.sleep(2.0)

        print("🚀 Starting Playback in 3 seconds...")
        time.sleep(3.0)

        # 4. 궤적 재생
        for i, pose in enumerate(trajectory):
            # 매 프레임마다 관절별 이름이 붙은 딕셔너리 생성
            action = create_action_dict(pose)
            robot.send_action(action)
            
            if i % 30 == 0:
                print(f"▶️ Playing: {i}/{num_frames} frames ({(i/num_frames)*100:.1f}%)")
            
            precise_sleep(1/hz)
            
        print(f"🏁 Playback finished!")

    except KeyboardInterrupt:
        print("\n🛑 Playback interrupted.")
    except Exception as e:
        print(f"❌ Error during playback: {e}")
    finally:
        robot.disconnect()
        print("👋 Robot disconnected.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("file", help="Path to the trajectory JSON file")
    args = parser.parse_args()
    
    run_playback(args.file)
