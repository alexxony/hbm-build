"""Mesh convergence 스터디 순수 로직 모듈.

레벨 파싱, Student 512K mesh 예산 가드, 발산 가드, 연속 레벨 간 수렴 판정,
CSV 행 구성을 담당한다. pyaedt에 의존하지 않으므로 AEDT 없는 환경(WSL)에서도
전부 테스트 가능하다. 실제 AEDT 모델 빌드/해석은
scripts/mesh_convergence.py 에서 이 모듈의 결과를 사용해 오케스트레이션한다.
"""
from __future__ import annotations

from dataclasses import dataclass

# Icepak Student 라이선스 mesh 상한 (elements). 근거: vault research/01-ansys-student-limits.md
ICEPAK_STUDENT_MESH_LIMIT = 512_000

# AEDT 솔버 온도 상한 5000K(=4726.85°C) 발산 캡보다 훨씬 낮은 물리적 상한선.
# 근거: docs/run-on-windows.md §5.0.1 — 반도체 패키지에서 500°C 초과는 항상 발산.
DIVERGENCE_THRESHOLD_C = 500.0

# 연속 레벨 간 base_die max 온도 변화율이 이 값 이하이면 수렴으로 판정.
CONVERGENCE_CHANGE_PCT = 1.0

# mesh resolution 레벨 유효 범위 — pyaedt MeshRegionResolution 정수 1~5.
_MIN_LEVEL = 1
_MAX_LEVEL = 5

CSV_FIELDNAMES = [
    "level",
    "n_elements",
    "base_die_avg_c",
    "base_die_max_c",
    "top_die_avg_c",
    "top_die_max_c",
    "solve_time_s",
    "skipped_over_budget",
    "diverged",
    "converged",
    "change_pct",
    "error",
]


@dataclass
class ConvergenceLevelResult:
    """한 mesh resolution 레벨의 스윕 결과.

    skipped_over_budget=True인 경우 온도/시간 필드는 None일 수 있다
    (512K 초과가 실행 후에야 확인되므로, 확인 시점까지의 값만 채워질 수 있음).
    error가 not None이면 해당 레벨의 빌드/해석/후처리 중 예외가 발생해
    다른 필드는 신뢰할 수 없다 — 스윕 전체를 죽이지 않고 이 레벨만
    실패로 기록하기 위한 필드(Task 3 Windows 실행 크래시 대응).
    """

    level: int
    n_elements: int | None
    base_die_avg_c: float | None
    base_die_max_c: float | None
    top_die_avg_c: float | None
    top_die_max_c: float | None
    solve_time_s: float | None
    skipped_over_budget: bool
    diverged: bool
    converged: bool
    change_pct: float | None
    error: str | None = None


def build_error_result(level: int, error_message: str) -> ConvergenceLevelResult:
    """레벨 실행 중 예외가 발생했을 때 기록할 에러 플래그 결과를 만든다."""
    return ConvergenceLevelResult(
        level=level,
        n_elements=None,
        base_die_avg_c=None,
        base_die_max_c=None,
        top_die_avg_c=None,
        top_die_max_c=None,
        solve_time_s=None,
        skipped_over_budget=False,
        diverged=False,
        converged=False,
        change_pct=None,
        error=error_message,
    )


def parse_levels(levels_arg: str | None) -> list[int]:
    """`--levels` CLI 인자 문자열을 정수 레벨 목록으로 파싱한다.

    Args:
        levels_arg: "1,2,3" 형식의 콤마 구분 문자열. None이면 기본 범위(1~5) 사용.

    Returns:
        정수 레벨 목록 (파싱된 순서 유지).

    Raises:
        ValueError: 빈 문자열, 정수 변환 실패, 범위(1~5) 밖 값, 중복 레벨.
    """
    if levels_arg is None:
        return list(range(_MIN_LEVEL, _MAX_LEVEL + 1))

    parts = [p.strip() for p in levels_arg.split(",")]
    if any(p == "" for p in parts):
        raise ValueError(f"levels 문자열이 비어있거나 잘못된 형식입니다: {levels_arg!r}")

    levels: list[int] = []
    for p in parts:
        try:
            level = int(p)
        except ValueError as exc:
            raise ValueError(f"levels 값이 정수가 아닙니다: {p!r}") from exc
        if not (_MIN_LEVEL <= level <= _MAX_LEVEL):
            raise ValueError(
                f"level은 {_MIN_LEVEL}~{_MAX_LEVEL} 범위여야 합니다 (입력값={level})."
            )
        levels.append(level)

    if len(levels) != len(set(levels)):
        raise ValueError(f"중복된 level이 있습니다: {levels_arg!r}")

    return levels


def check_mesh_budget(n_elements: int, limit: int = ICEPAK_STUDENT_MESH_LIMIT) -> bool:
    """element 수가 Student 512K 예산을 초과하는지 확인한다.

    Args:
        n_elements: 실제 생성된 mesh element 수 (실행 후 확인값).
        limit: mesh 상한. 기본 Student 512K.

    Returns:
        True면 예산 초과(skip 대상), False면 예산 내.
    """
    return n_elements > limit


def check_divergence(max_temp_c: float, threshold: float = DIVERGENCE_THRESHOLD_C) -> bool:
    """최고 온도가 물리적으로 불가능한 범위(발산)인지 확인한다.

    근거: docs/run-on-windows.md §5.0.1 — AEDT는 발산해도 "solved correctly"를
    출력하므로 온도값 자체로 판정해야 한다.

    Args:
        max_temp_c: 레벨의 최고 온도 (°C).
        threshold: 발산 판정 임계값. 기본 500°C.

    Returns:
        True면 발산, False면 물리 범위 내.
    """
    return max_temp_c > threshold


def compute_convergence_flags(
    results: list[ConvergenceLevelResult],
) -> list[ConvergenceLevelResult]:
    """연속 레벨 간 base_die max 온도 변화율을 계산해 수렴 플래그를 채운다.

    skip되거나 발산하거나 에러가 난 레벨은 비교 기준(직전 유효 레벨)에서
    제외한다 — 즉 각 유효 레벨은 "가장 최근의 유효(skip/발산/에러 아닌)
    레벨"과 비교한다. 무효 레벨 자신은 항상 converged=False,
    change_pct=None으로 남는다. 에러 레벨은 온도 필드가 None이므로
    is_valid 판정에서 반드시 제외해야 한다(그렇지 않으면 이후 abs() 계산이
    TypeError로 죽는다).

    Args:
        results: 레벨 순서대로 정렬된 결과 목록 (change_pct/converged는 무시하고 재계산).

    Returns:
        change_pct와 converged가 채워진 새 결과 목록 (입력 리스트는 변경하지 않음).
    """
    flagged: list[ConvergenceLevelResult] = []
    last_valid_max_temp: float | None = None

    for result in results:
        is_valid = (
            not result.skipped_over_budget
            and not result.diverged
            and result.error is None
        )

        if not is_valid:
            flagged.append(_with_convergence(result, change_pct=None, converged=False))
            continue

        if last_valid_max_temp is None:
            flagged.append(_with_convergence(result, change_pct=None, converged=False))
        else:
            change_pct = (
                abs(result.base_die_max_c - last_valid_max_temp) / last_valid_max_temp * 100
            )
            converged = change_pct <= CONVERGENCE_CHANGE_PCT
            flagged.append(
                _with_convergence(result, change_pct=change_pct, converged=converged)
            )

        last_valid_max_temp = result.base_die_max_c

    return flagged


def _with_convergence(
    result: ConvergenceLevelResult, change_pct: float | None, converged: bool
) -> ConvergenceLevelResult:
    """result의 change_pct/converged만 교체한 새 인스턴스를 반환한다."""
    return ConvergenceLevelResult(
        level=result.level,
        n_elements=result.n_elements,
        base_die_avg_c=result.base_die_avg_c,
        base_die_max_c=result.base_die_max_c,
        top_die_avg_c=result.top_die_avg_c,
        top_die_max_c=result.top_die_max_c,
        solve_time_s=result.solve_time_s,
        skipped_over_budget=result.skipped_over_budget,
        diverged=result.diverged,
        converged=converged,
        change_pct=change_pct,
        error=result.error,
    )


def build_csv_rows(results: list[ConvergenceLevelResult]) -> list[dict]:
    """결과 목록을 CSV DictWriter에 바로 넘길 수 있는 dict 행 목록으로 변환한다."""
    return [
        {
            "level": r.level,
            "n_elements": r.n_elements,
            "base_die_avg_c": r.base_die_avg_c,
            "base_die_max_c": r.base_die_max_c,
            "top_die_avg_c": r.top_die_avg_c,
            "top_die_max_c": r.top_die_max_c,
            "solve_time_s": r.solve_time_s,
            "skipped_over_budget": r.skipped_over_budget,
            "diverged": r.diverged,
            "converged": r.converged,
            "change_pct": r.change_pct,
            "error": r.error,
        }
        for r in results
    ]
