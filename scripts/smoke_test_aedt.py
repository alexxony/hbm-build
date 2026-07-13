#!/usr/bin/env python3
r"""AEDT-PyAEDT 연결 스모크 테스트 — 모델 생성 없이 연결만 검증한다.

build_icepak_model.py가 "AEDT 창은 뜨는데 아무것도 안 만들어짐" 증상을 보일 때,
문제를 (a) gRPC 연결 실패 vs (b) 모델 생성 API 실패로 분리하기 위한 최소 재현.

단계별로 진행 상황을 print하므로, 어디서 멈추는지/죽는지 콘솔 출력 전체를
그대로 복사해서 가져오면 된다.

실행 (Windows, 저장소 루트에서):
    python scripts\smoke_test_aedt.py

이미 수동으로 gRPC 서버를 띄운 AEDT에 붙는 모드:
    (AEDT를 먼저 이렇게 실행: ansysedt.exe -grpcsrv 50051)
    python scripts\smoke_test_aedt.py --attach-port 50051
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback


def _force_student_session_detection() -> None:
    """pyaedt 세션 감지가 Student 프로세스를 보도록 강제하는 몽키패치.

    pyaedt(1.1.0 및 1.2.0에서 확인)의 is_grpc_session_active()는 내부에서
    active_sessions()를 인자 없이 호출한다. student_version 기본값이 False라
    타깃 프로세스가 ["ansysedt.exe"]로 고정되어, Student판(ansysedtsv.exe)이
    gRPC 포트를 물고 있어도 "세션 없음"으로 판정한다(업스트림 이슈 #7891과
    동일 계통, 1.1.0에도 존재함을 소스로 확인). 이 머신은 Student판 전용이므로
    student_version=True를 무조건 강제한다.
    """
    import ansys.aedt.core.desktop as desktop_mod
    from ansys.aedt.core.generic import general_methods

    orig = general_methods.active_sessions

    def _active_sessions_student(version=None, student_version=False, non_graphical=None):
        return orig(version=version, student_version=True, non_graphical=non_graphical)

    general_methods.active_sessions = _active_sessions_student
    # desktop.py가 `from ... import active_sessions`로 직접 바인딩한 참조도 교체.
    desktop_mod.active_sessions = _active_sessions_student
    print("      (패치 적용: 세션 감지 student_version=True 강제)")


def main() -> int:
    parser = argparse.ArgumentParser(description="AEDT-PyAEDT 연결 스모크 테스트")
    parser.add_argument(
        "--attach-port",
        type=int,
        default=None,
        help="이미 -grpcsrv <port>로 떠 있는 AEDT에 붙는다 (새로 띄우지 않음)",
    )
    parser.add_argument(
        "--non-graphical", action="store_true", help="GUI 없이 실행"
    )
    args = parser.parse_args()

    print(f"[1/6] Python: {sys.version}")

    try:
        import ansys.aedt.core

        print(f"[2/6] pyaedt import OK — version: {ansys.aedt.core.__version__}")
    except ImportError:
        print("[2/6] 실패: pyaedt 미설치. `pip install pyaedt` 후 재시도.")
        traceback.print_exc()
        return 1

    from ansys.aedt.core import Desktop, settings

    # Student판 gRPC 대응 설정 (build_icepak_model.py와 동일).
    os.environ["PYAEDT_USE_PRE_GRPC_ARGS"] = "True"
    settings.grpc_secure_mode = False
    settings.desktop_launch_timeout = 600
    settings.enable_debug_logger = True
    settings.enable_debug_grpc_api_logger = True

    _force_student_session_detection()

    print("[3/6] 설정 완료 — Desktop 기동/연결 시도 (최대 600초 대기)...")

    desktop_kwargs = dict(
        non_graphical=args.non_graphical,
        close_on_exit=False,
        student_version=True,
    )
    if args.attach_port is not None:
        desktop_kwargs.update(new_desktop=False, port=args.attach_port)
        print(f"      (기존 AEDT gRPC 포트 {args.attach_port}에 붙는 모드)")
    else:
        desktop_kwargs.update(new_desktop=True)

    try:
        desktop = Desktop(**desktop_kwargs)
    except Exception:
        print("[4/6] 실패: Desktop 기동/연결 예외 발생 ↓")
        traceback.print_exc()
        print(
            "\n[안내] %TEMP% 아래 최신 pyaedt_*.log / batch.log 내용도 함께 가져오면"
            " 원인 특정에 도움이 된다."
        )
        return 2

    print(f"[4/6] Desktop 연결 OK — AEDT version: {desktop.release}")

    try:
        project = desktop.odesktop.NewProject()
        project_name = project.GetName()
        print(f"[5/6] 빈 프로젝트 생성 OK — 이름: {project_name}")

        project.InsertDesign("Icepak", "smoke_icepak", "", "")
        print("[6/6] Icepak 디자인 삽입 OK — 연결 계통 전부 정상.")
        print("      → build_icepak_model.py 실패 원인은 연결이 아니라 모델 생성 API 쪽.")
    except Exception:
        print("[5-6/6] 실패: 프로젝트/디자인 생성 예외 ↓")
        traceback.print_exc()
        print("      → 연결은 됐지만 자동화 API가 막혀 있는 패턴 (Student 제한 의심).")
        return 3
    finally:
        # 창은 남겨서 눈으로 확인 가능하게 한다.
        desktop.release_desktop(close_projects=False, close_on_exit=False)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
