#!/usr/bin/env python3
"""9 nav2 params yaml 생성기 — planner × controller 매트릭스.

입력  : controller/gogoping-controller/src/gogoping/gogoping_navigation/params/nav2_params_sim.yaml
출력  : scripts/path_planner_experiment/params/nav2_{Planner}_{Controller}.yaml × 9

각 yaml 은 base 의 controller_server.FollowPath / planner_server.GridBased 만 교체.
나머지 (costmap / smoother / behavior / velocity_smoother) 는 동일 — 공정 비교 위해.

사용:
  python3 generate_params.py
  → ./params/ 에 9 파일 생성. 기존 파일은 덮어씀.

플러그인 params 는 nav2 jazzy 기본값 기반 + Vic Pinky HW 제약 (max_vel 0.20) 반영.
"""

from __future__ import annotations

import copy
from pathlib import Path

import yaml


REPO = Path(__file__).resolve().parents[2]
BASE_YAML = REPO / "controller/gogoping-controller/src/gogoping/gogoping_navigation/params/nav2_params_sim.yaml"
OUT_DIR = Path(__file__).resolve().parent / "params"


# ───────────────────────────── PLANNERS ─────────────────────────────
PLANNERS: dict[str, dict] = {
    "NavFn": {
        "plugin": "nav2_navfn_planner::NavfnPlanner",
        "tolerance": 0.5,
        "use_astar": False,  # Dijkstra (current baseline)
        "allow_unknown": True,
    },
    "Smac2D": {
        "plugin": "nav2_smac_planner::SmacPlanner2D",
        "tolerance": 0.5,
        "downsample_costmap": False,
        "downsampling_factor": 1,
        "allow_unknown": True,
        "max_iterations": 1000000,
        "max_on_approach_iterations": 1000,
        "max_planning_time": 2.0,
        "motion_model_for_search": "MOORE",  # 8-direction
        "cost_travel_multiplier": 2.0,
        "use_final_approach_orientation": False,
    },
    "ThetaStar": {
        "plugin": "nav2_theta_star_planner::ThetaStarPlanner",
        "how_many_corners": 8,
        "w_euc_cost": 1.0,
        "w_traversal_cost": 2.0,
        "use_final_approach_orientation": False,
    },
}


# ──────────────────────────── CONTROLLERS ────────────────────────────
# 공통 HW 제약 :
#   max_linear_vel  = 0.20 m/s
#   max_angular_vel = 1.0 rad/s
#   accel_x         = 1.8 m/s²
#   accel_theta     = 2.0 rad/s²

CONTROLLERS: dict[str, dict] = {
    # ─── RPP : current production baseline ───
    "RPP": {
        "plugin": "nav2_regulated_pure_pursuit_controller::RegulatedPurePursuitController",
        "desired_linear_vel": 0.20,
        "lookahead_dist": 1.2,
        "min_lookahead_dist": 0.3,
        "max_lookahead_dist": 0.9,
        "lookahead_time": 1.5,
        "rotate_to_heading_angular_vel": 0.5,
        "transform_tolerance": 0.1,
        "use_velocity_scaled_lookahead_dist": True,
        "min_approach_linear_velocity": 0.05,
        "approach_velocity_scaling_dist": 0.6,
        "use_collision_detection": False,
        "max_allowed_time_to_collision_up_to_carrot": 3.0,
        "use_regulated_linear_velocity_scaling": True,
        "use_cost_regulated_linear_velocity_scaling": True,
        "regulated_linear_scaling_min_radius": 0.4,
        "regulated_linear_scaling_min_speed": 0.05,
        "use_rotate_to_heading": False,
        "rotate_to_heading_min_angle": 3.14,
        "max_angular_accel": 1.5,
        "allow_reversing": False,
        "max_robot_pose_search_dist": 10.0,
        "cost_scaling_dist": 0.3,
        "cost_scaling_gain": 1.0,
        "inflation_cost_scaling_factor": 2.5,
    },

    # ─── DWB : Dynamic Window Approach (legacy default) ───
    "DWB": {
        "plugin": "dwb_core::DWBLocalPlanner",
        "debug_trajectory_details": True,
        # velocity / acceleration limits (HW)
        "min_vel_x": 0.0,
        "min_vel_y": 0.0,
        "max_vel_x": 0.20,
        "max_vel_y": 0.0,
        "max_vel_theta": 1.0,
        "min_speed_xy": 0.0,
        "max_speed_xy": 0.20,
        "min_speed_theta": 0.0,
        "acc_lim_x": 1.8,
        "acc_lim_y": 0.0,
        "acc_lim_theta": 2.0,
        "decel_lim_x": -1.8,
        "decel_lim_y": 0.0,
        "decel_lim_theta": -2.0,
        # trajectory sampling
        "vx_samples": 20,
        "vy_samples": 5,
        "vtheta_samples": 20,
        "sim_time": 1.7,
        "linear_granularity": 0.05,
        "angular_granularity": 0.025,
        "transform_tolerance": 0.2,
        "xy_goal_tolerance": 0.30,
        "trans_stopped_velocity": 0.25,
        "short_circuit_trajectory_evaluation": True,
        "stateful": True,
        # critic plugins
        "critics": [
            "RotateToGoal",
            "Oscillation",
            "BaseObstacle",
            "GoalAlign",
            "PathAlign",
            "PathDist",
            "GoalDist",
        ],
        "RotateToGoal.scale": 32.0,
        "RotateToGoal.slowing_factor": 5.0,
        "RotateToGoal.lookahead_time": -1.0,
        "Oscillation.scale": 1.0,
        "BaseObstacle.scale": 0.02,
        "PathAlign.scale": 32.0,
        "PathAlign.forward_point_distance": 0.1,
        "GoalAlign.scale": 24.0,
        "GoalAlign.forward_point_distance": 0.1,
        "PathDist.scale": 32.0,
        "GoalDist.scale": 24.0,
    },

    # ─── MPPI : Model Predictive Path Integral (최신 권장) ───
    "MPPI": {
        "plugin": "nav2_mppi_controller::MPPIController",
        # core MPC params
        "time_steps": 56,
        "model_dt": 0.05,
        "batch_size": 2000,
        "ax_max": 1.8,
        "ax_min": -1.8,
        "ay_max": 0.0,
        "az_max": 2.0,
        "vx_std": 0.2,
        "vy_std": 0.0,
        "wz_std": 0.4,
        "vx_max": 0.20,
        "vx_min": -0.10,
        "vy_max": 0.0,
        "wz_max": 1.0,
        "iteration_count": 1,
        "prune_distance": 1.7,
        "transform_tolerance": 0.1,
        "temperature": 0.3,
        "gamma": 0.015,
        "motion_model": "DiffDrive",
        "visualize": False,
        "TrajectoryVisualizer": {
            "trajectory_step": 5,
            "time_step": 3,
        },
        "AckermannConstraints": {
            "min_turning_r": 0.2,
        },
        "critics": [
            "ConstraintCritic",
            "ObstaclesCritic",
            "GoalCritic",
            "GoalAngleCritic",
            "PathAlignCritic",
            "PathFollowCritic",
            "PathAngleCritic",
            "PreferForwardCritic",
        ],
        "ConstraintCritic.enabled": True,
        "ConstraintCritic.cost_power": 1,
        "ConstraintCritic.cost_weight": 4.0,
        "GoalCritic.enabled": True,
        "GoalCritic.cost_power": 1,
        "GoalCritic.cost_weight": 5.0,
        "GoalCritic.threshold_to_consider": 1.4,
        "GoalAngleCritic.enabled": True,
        "GoalAngleCritic.cost_power": 1,
        "GoalAngleCritic.cost_weight": 3.0,
        "GoalAngleCritic.threshold_to_consider": 0.5,
        "PreferForwardCritic.enabled": True,
        "PreferForwardCritic.cost_power": 1,
        "PreferForwardCritic.cost_weight": 5.0,
        "PreferForwardCritic.threshold_to_consider": 0.5,
        "ObstaclesCritic.enabled": True,
        "ObstaclesCritic.cost_power": 1,
        "ObstaclesCritic.repulsion_weight": 1.5,
        "ObstaclesCritic.critical_weight": 20.0,
        "ObstaclesCritic.consider_footprint": False,
        "ObstaclesCritic.collision_cost": 10000.0,
        "ObstaclesCritic.collision_margin_distance": 0.10,
        "ObstaclesCritic.near_goal_distance": 0.5,
        "PathAlignCritic.enabled": True,
        "PathAlignCritic.cost_power": 1,
        "PathAlignCritic.cost_weight": 14.0,
        "PathAlignCritic.max_path_occupancy_ratio": 0.07,
        "PathAlignCritic.trajectory_point_step": 4,
        "PathAlignCritic.threshold_to_consider": 0.5,
        "PathAlignCritic.offset_from_furthest": 20,
        "PathAlignCritic.use_path_orientations": False,
        "PathFollowCritic.enabled": True,
        "PathFollowCritic.cost_power": 1,
        "PathFollowCritic.cost_weight": 5.0,
        "PathFollowCritic.offset_from_furthest": 5,
        "PathFollowCritic.threshold_to_consider": 1.4,
        "PathAngleCritic.enabled": True,
        "PathAngleCritic.cost_power": 1,
        "PathAngleCritic.cost_weight": 2.0,
        "PathAngleCritic.offset_from_furthest": 4,
        "PathAngleCritic.threshold_to_consider": 0.5,
        "PathAngleCritic.max_angle_to_furthest": 1.2,
    },
}


def generate_one(base: dict, planner_name: str, controller_name: str) -> dict:
    out = copy.deepcopy(base)
    out["planner_server"]["ros__parameters"]["GridBased"] = PLANNERS[planner_name]
    out["controller_server"]["ros__parameters"]["FollowPath"] = CONTROLLERS[controller_name]
    return out


def main() -> int:
    if not BASE_YAML.exists():
        print(f"❌ base yaml not found: {BASE_YAML}")
        return 1

    with BASE_YAML.open() as f:
        base = yaml.safe_load(f)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    generated = []
    for planner_name in PLANNERS:
        for controller_name in CONTROLLERS:
            out = generate_one(base, planner_name, controller_name)
            out_path = OUT_DIR / f"nav2_{planner_name}_{controller_name}.yaml"
            with out_path.open("w") as f:
                f.write(
                    f"# auto-generated by generate_params.py — do not edit by hand.\n"
                    f"# planner={planner_name}, controller={controller_name}\n"
                    f"# base={BASE_YAML.relative_to(REPO)}\n\n"
                )
                yaml.safe_dump(out, f, sort_keys=False, allow_unicode=True)
            generated.append(out_path.name)

    print(f"✅ {len(generated)} yaml generated in {OUT_DIR}/")
    for name in generated:
        print(f"  - {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
