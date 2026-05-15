"""tests/ 진입점 conftest. teleop 관련 단위 테스트 공용 설정.

service/control-service/control_service/tests/conftest.py 와 분리 — 여기 테스트들은 DB 가 필요 없다.
"""

import pathlib
import sys

# admin-app 모듈 (services/, widgets/) 을 import 가능하게.
ADMIN_APP = pathlib.Path(__file__).resolve().parents[1] / "app" / "admin-app"
if str(ADMIN_APP) not in sys.path:
    sys.path.insert(0, str(ADMIN_APP))
