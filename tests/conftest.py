"""tests/ 진입점 conftest.

1) admin-app 모듈 (services/, widgets/) 을 import 가능하게.
2) ROS 2 런타임 (rclpy / gogoping_msgs / geometry_msgs 등) sys.modules stub —
   rclpy/rosidl 없이 빌더·단위 테스트가 BT behavior 를 import 할 수 있게 한다.
   빌더 단위 테스트는 setup() (ROS node inject) 호출 안 하므로 stub 으로 충분.

service/control-service/control_service/tests/conftest.py 와는 분리 — 거기 테스트는 DB 가 필요.
"""

import pathlib
import sys
import types
from unittest.mock import MagicMock

# admin-app 모듈 (services/, widgets/) 을 import 가능하게.
ADMIN_APP = pathlib.Path(__file__).resolve().parents[1] / "app" / "admin-app"
if str(ADMIN_APP) not in sys.path:
    sys.path.insert(0, str(ADMIN_APP))


def _stub_hierarchy(dotted: str) -> None:
    """dotted.name 의 모든 prefix 를 ModuleType stub 으로 등록.

    각 stub 모듈의 __getattr__ 가 모든 attribute 접근에 대해 MagicMock 을 반환 —
    'from module import Name' 패턴 (NavigateToVertex 등) 을 import 가능하게.
    """
    parts = dotted.split(".")
    for i in range(1, len(parts) + 1):
        key = ".".join(parts[:i])
        if key not in sys.modules:
            mod = types.ModuleType(key)
            mod.__getattr__ = lambda name, _m=mod: MagicMock()  # type: ignore[method-assign]
            sys.modules[key] = mod


_ROS_STUBS = [
    "gogoping_msgs",
    "gogoping_msgs.action",
    "gogoping_msgs.msg",
    "gogoping_msgs.srv",
    "rclpy",
    "rclpy.action",
    "rclpy.qos",
    "rclpy.node",
    "rclpy.subscription",
    "rclpy.publisher",
    "rclpy.callback_groups",
    "rclpy.executors",
    "rclpy.client",
    "rclpy.service",
    "rclpy.timer",
    "rclpy.clock",
    "rclpy.duration",
    "rclpy.time",
    "rclpy.parameter",
    "geometry_msgs",
    "geometry_msgs.msg",
    "nav_msgs",
    "nav_msgs.msg",
    "std_msgs",
    "std_msgs.msg",
    "sensor_msgs",
    "sensor_msgs.msg",
    "action_msgs",
    "action_msgs.msg",
    "builtin_interfaces",
    "builtin_interfaces.msg",
    "rcl_interfaces",
    "rcl_interfaces.msg",
]

for _pkg in _ROS_STUBS:
    _stub_hierarchy(_pkg)


collect_ignore = [
    "test_utils_geo.py",
]

