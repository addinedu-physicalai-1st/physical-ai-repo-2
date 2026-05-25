"""``SetBlackboard.srv`` server — control-service 등 외부 핸들러가 BT blackboard 의
특정 키를 직접 set 할 수 있게 한다.

보안: ``_ALLOWED_KEYS`` allowlist 키만 set 허용. 그 외는 ``key_not_allowed``
reason 으로 거부.

main.py 부팅 시 1회 인스턴스화 — service 는 노드 라이프타임 동안 유지된다.

설계 노트:
- py_trees Blackboard 자체가 process-global singleton 이라 별도 lock 없이도
  set 은 thread-safe (GIL 보호). 단 read-modify-write 일관성을 위해 본 모듈은
  set 단위로 처리 — caller (control-service) 가 cumulative list 를 보낸다.
- ``call_async`` 응답을 main.py spin 이 처리하므로 서비스 콜백은 별도 spin 의
  callback group 에서 실행될 수 있음. py_trees blackboard.set 은 thread-safe.
"""
from __future__ import annotations

import json

import py_trees
from py_trees.common import Access
import rclpy.node


# control-service 가 set 가능한 키 — hideseek 의 외부 이벤트 데이터 2종.
# 새 키 추가는 신중히 — 임의 blackboard 키를 외부에서 manipulate 가능하면 BT 무결성
# 위험. 추가 전 사용자 확인 필수 (docs/blackboard-schema.md 도 같이 갱신).
_ALLOWED_KEYS = frozenset({
    "hideseek_registered_ids",
    "hideseek_caught_ids",
    # debug skip flag — Countdown behaviour 가 체크 (countdown phase 즉시 종료)
    "hideseek_skip_countdown",
    # admin [순찰] 단독 모드 — BT_hide_and_seek_sub 가 patrol_sub 만 반환
    "hideseek_patrol_only",
})

SERVICE_NAME = "blackboard/set"   # 노드 namespace 가 /gogoping 이라 /gogoping/blackboard/set


class BlackboardServiceServer:
    """``/gogoping/blackboard/set`` 서비스 서버 — allowlist 키만 set."""

    def __init__(self, node: rclpy.node.Node):
        # lazy import — ROS sourcing 안 된 env 에서 본 모듈 import 가능하게.
        from gogoping_msgs.srv import SetBlackboard

        self._node = node
        self._logger = node.get_logger()

        # py_trees blackboard client — 등록 시 W 권한 한 번만.
        self._bb = py_trees.blackboard.Client(name="blackboard_service_writer")
        for key in _ALLOWED_KEYS:
            self._bb.register_key(key=key, access=Access.WRITE)

        self._srv = node.create_service(
            SetBlackboard, SERVICE_NAME, self._handle,
        )

    def _handle(self, request, response):
        """``SetBlackboard.srv`` 콜백 — allowlist 검사 + JSON 디코드 + bb.set."""
        key = request.key
        if key not in _ALLOWED_KEYS:
            response.ok = False
            response.reason = f"key_not_allowed: {key!r}"
            self._logger.warning(
                f"SetBlackboard 거부: key={key!r} reason=key_not_allowed"
            )
            return response

        try:
            value = json.loads(request.value_json)
        except json.JSONDecodeError as e:
            response.ok = False
            response.reason = f"json_parse_error: {e}"
            self._logger.warning(
                f"SetBlackboard 거부: key={key!r} value_json={request.value_json!r}"
                f" reason=json_parse_error: {e}"
            )
            return response

        self._bb.set(key, value)
        response.ok = True
        response.reason = ""
        self._logger.info(
            f"SetBlackboard {key!r} ← {value!r}"
        )
        return response


__all__ = ["BlackboardServiceServer", "SERVICE_NAME"]
