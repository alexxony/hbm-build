"""pytest 루트 앵커 — repo 루트를 sys.path에 보장.

bare `pytest` 호출(예: rtk 래퍼)은 `python -m pytest`와 달리 cwd를
sys.path에 넣지 않아 `hbm_thermal` import가 깨진다. 루트 conftest가
있으면 pytest가 rootdir을 sys.path에 삽입해 두 호출 방식 모두 동작.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
