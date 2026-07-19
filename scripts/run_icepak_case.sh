#!/usr/bin/env bash
# Icepak 케이스 러너 래퍼 — WSL에서 실행, Windows 클론(/mnt/c/workspace/hbm_build)의
# AEDT/PyAEDT 스택을 powershell.exe 인터롭으로 구동한다.
#
# 순서: pull 선행(ff-only) -> AEDT 프로세스 제로 확인 -> 케이스 실행 -> 결과 CSV 회수.
#
# 주의(호출자 책임): 이 스크립트는 JOURNAL.md append도, git commit도 하지 않는다.
# 케이스 실행 성공 후 결과를 기록·커밋하는 것은 이 스크립트를 호출한
# executor/오케스트레이터의 몫이다.
#
# 사용법:
#   scripts/run_icepak_case.sh <실행명> [build_icepak_model.py 인자...]
#
# 예:
#   scripts/run_icepak_case.sh a_s1 --power-scenario s1_phy_moderate --total-power 30.0
#
# <실행명>은 로그 파일명(results/p4_icepak_scenarios/<실행명>.log)에만 쓰인다.
# --output-csv 등 build_icepak_model.py 자체 인자는 그 뒤에 그대로 패스스루한다.

set -u

WSL_REPO="/home/kimsh/workspace/hbm_build"
WIN_REPO="/mnt/c/workspace/hbm_build"
RESULTS_DIR="results/p4_icepak_scenarios"

die() {
    echo "[run_icepak_case] ERROR: $*" >&2
    exit 1
}

[ "$#" -ge 1 ] || die "사용법: $0 <실행명> [build_icepak_model.py 인자...]"
RUN_NAME="$1"
shift
SCRIPT_ARGS=("$@")

[ -d "$WIN_REPO" ] || die "Windows 클론 경로가 없음: $WIN_REPO"
[ -d "$WSL_REPO/.git" ] || die "WSL repo가 아님: $WSL_REPO"

# ---------------------------------------------------------------------------
# 1) pull 선행: Windows 클론이 origin(WSL repo)과 정확히 일치하는지 확인 후 ff-only.
# ---------------------------------------------------------------------------
echo "[run_icepak_case] 1/4 pull 선행 확인..."

git -C "$WIN_REPO" fetch origin || die "fetch 실패"

# fetch 후 유입될 커밋에 포함된 파일과 현재 untracked 파일의 경로 충돌을 검사.
INCOMING_FILES=$(git -C "$WIN_REPO" diff --name-only HEAD origin/master 2>/dev/null || true)
UNTRACKED_FILES=$(git -C "$WIN_REPO" status --porcelain --untracked-files=all | awk '{print $2}')

if [ -n "$INCOMING_FILES" ] && [ -n "$UNTRACKED_FILES" ]; then
    while IFS= read -r f; do
        [ -z "$f" ] && continue
        if echo "$UNTRACKED_FILES" | grep -qxF "$f"; then
            # 개행만 다른지(CRLF vs LF) 비교. 실제 내용 차이면 중단.
            incoming_content=$(git -C "$WIN_REPO" show "origin/master:$f" 2>/dev/null | tr -d '\r')
            local_content=$(tr -d '\r' < "$WIN_REPO/$f" 2>/dev/null)
            if [ "$incoming_content" != "$local_content" ]; then
                die "untracked 파일 '$f'이 유입 커밋과 내용 충돌(개행 무시해도 다름) — 수동 확인 필요"
            fi
            echo "[run_icepak_case]   주의: '$f'는 CRLF 차이만 있는 동일 내용 — 진행"
        fi
    done <<< "$INCOMING_FILES"
fi

git -C "$WIN_REPO" merge --ff-only origin/master || die "ff-only merge 실패 — Windows 클론이 origin과 발산했을 수 있음"

WSL_HEAD=$(git -C "$WSL_REPO" rev-parse HEAD)
WIN_HEAD=$(git -C "$WIN_REPO" rev-parse HEAD)
[ "$WSL_HEAD" = "$WIN_HEAD" ] || die "HEAD 불일치: WSL=$WSL_HEAD, Windows=$WIN_HEAD"
echo "[run_icepak_case]   HEAD 일치 확인: $WIN_HEAD"

# ---------------------------------------------------------------------------
# 2) 프로세스 제로 확인: ansysedt*/ansyscl*/fluent* 전부 미기동이어야 함(단일 인스턴스 원칙).
# ---------------------------------------------------------------------------
echo "[run_icepak_case] 2/4 AEDT 프로세스 제로 확인..."

PROC_COUNT=$(powershell.exe -NoProfile -Command \
    "(Get-Process -Name ansysedt*,ansyscl*,fluent* -ErrorAction SilentlyContinue | Measure-Object).Count" \
    2>/dev/null | tr -d '\r\n ')

case "$PROC_COUNT" in
    ''|*[!0-9]*) die "프로세스 카운트 조회 실패(비정상 출력: '$PROC_COUNT')" ;;
esac

[ "$PROC_COUNT" -eq 0 ] || die "AEDT 관련 프로세스가 이미 실행 중(COUNT=$PROC_COUNT) — 단일 인스턴스 원칙 위반, 중단"
echo "[run_icepak_case]   PROC_COUNT=0 확인"

# ---------------------------------------------------------------------------
# 3) 케이스 실행: powershell.exe 인터롭, PYTHONIOENCODING 강제, .venv python.
# ---------------------------------------------------------------------------
echo "[run_icepak_case] 3/4 케이스 실행: $RUN_NAME"

LOG_REL="$RESULTS_DIR/${RUN_NAME}.log"
LOG_WIN="$WIN_REPO/$LOG_REL"
mkdir -p "$(dirname "$LOG_WIN")"

# build_icepak_model.py 인자를 PowerShell 커맨드라인으로 안전하게 이어붙임.
PS_ARGS=""
for a in "${SCRIPT_ARGS[@]}"; do
    esc=${a//\`/\`\`}
    esc=${esc//\"/\`\"}
    PS_ARGS="$PS_ARGS \"$esc\""
done

PS_CMD="\$env:PYTHONIOENCODING='utf-8'; cd 'C:\\workspace\\hbm_build'; & '.venv\\Scripts\\python.exe' 'scripts\\build_icepak_model.py'$PS_ARGS"

powershell.exe -NoProfile -Command "$PS_CMD" > "$LOG_WIN" 2>&1
EXIT_CODE=$?

[ -s "$LOG_WIN" ] || echo "[run_icepak_case]   경고: 로그 파일이 비어있음 ($LOG_WIN)"

if [ "$EXIT_CODE" -ne 0 ]; then
    die "케이스 실행 실패(exit=$EXIT_CODE) — 로그 확인: $LOG_REL"
fi
echo "[run_icepak_case]   실행 완료(exit=0), 로그: $LOG_REL"

# ---------------------------------------------------------------------------
# 4) 결과 회수: 생성 CSV를 WSL repo 동일 경로로 복사(개행 정규화), 존재/비어있지 않음 검증.
# ---------------------------------------------------------------------------
echo "[run_icepak_case] 4/4 결과 CSV 회수..."

# --output-csv가 지정됐으면 그 값을, 아니면 스크립트 기본값을 사용.
OUTPUT_CSV="hbm2e_die_temperatures.csv"
prev_was_flag=""
for a in "${SCRIPT_ARGS[@]}"; do
    if [ "$prev_was_flag" = "1" ]; then
        OUTPUT_CSV="$a"
        prev_was_flag=""
        continue
    fi
    case "$a" in
        --output-csv) prev_was_flag="1" ;;
        --output-csv=*) OUTPUT_CSV="${a#--output-csv=}" ;;
    esac
done

SRC_CSV="$WIN_REPO/$OUTPUT_CSV"
[ -f "$SRC_CSV" ] || die "결과 CSV가 생성되지 않음: $SRC_CSV"

DEST_CSV="$WSL_REPO/$OUTPUT_CSV"
mkdir -p "$(dirname "$DEST_CSV")"
tr -d '\r' < "$SRC_CSV" > "$DEST_CSV" || die "CSV 복사/개행정규화 실패"

[ -s "$DEST_CSV" ] || die "회수된 CSV가 비어있음: $DEST_CSV"

echo "[run_icepak_case]   CSV 회수 완료: $DEST_CSV"
echo "[run_icepak_case] 완료. JOURNAL append + git commit은 호출자 책임."

exit 0
