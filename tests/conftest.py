"""tests/ 진입점 conftest. teleop 관련 단위 테스트 공용 설정.

server/control/tests/conftest.py 와 분리 — 여기 테스트들은 DB 가 필요 없다.
"""

import pathlib
import sys

# admin-ui 모듈 (services/, widgets/) 을 import 가능하게.
ADMIN_UI = pathlib.Path(__file__).resolve().parents[1] / "ui" / "admin-ui"
if str(ADMIN_UI) not in sys.path:
    sys.path.insert(0, str(ADMIN_UI))
