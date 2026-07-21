"""HBM 스택 FEM 결과를 2노드 lumped RC 등가 파라미터(r_hbm_sink, c_hbm)로
축약하는 순수 로직 모듈.

이 모듈은 AEDT/PyAEDT에 의존하지 않는다 (pyaedt import 없음). 입력은
Task 5 파라미터 스터디 결과 CSV(results/param_study.csv)와 T1의 레이어별
rho_cp(hbm_thermal.homogenize.layer_stack_hbm2e())이며, 출력은
Compiler_Thermal RcBackend A/B 캘리브레이션에 투입할 rc_params.csv다.

설계 근거: vault docs/06-p2-rc-backport-design.md §2~3.
스코프: HBM 스택만 모델했으므로 축약 가능한 파라미터는 r_hbm_sink, c_hbm
2개뿐(die 쪽 r_die_hbm/r_die_sink/c_die는 legacy 유지 — RcBackend 클래스는
이 모듈에서 무변경).

경고: hbm_thermal/export_3dice.py의 volumetric heat capacity 값(단일 Si
bulk 1.628e-12 J/µm³·K)은 3D-ICE 문법 통과용 placeholder이며 실제 재료별
값이 아니다. C 추출에는 절대 재사용하지 않는다 — 대신 T1의 레이어별
rho_cp(hbm_thermal.homogenize.layer_stack_hbm2e())를 사용한다.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass

from hbm_thermal.homogenize import layer_stack_hbm2e

_UM3_TO_M3 = 1e-18  # µm³ -> m³ (길이 1e-6 세제곱)
_MM_TO_M = 1e-3


@dataclass(frozen=True)
class LayerCContribution:
    """단일 레이어의 열용량 기여분."""

    name: str
    rho_cp_j_m3k: float
    volume_m3: float
    capacitance_j_k: float


def compute_c_hbm(
    stack: list[dict] | None = None,
    footprint_mm: tuple[float, float] = (11.0, 10.0),
) -> tuple[float, list[LayerCContribution]]:
    """HBM 스택 전체의 해석적 열용량 C_hbm = Σ ρ_i·cp_i·V_i (J/K)을 계산한다.

    각 레이어를 footprint(x, y) × thickness(z)의 직육면체로 근사하고,
    레이어별 균질화 체적 열용량(rho_cp, J/m³·K, T1 hbm_thermal.homogenize)을
    곱해 레이어별 열용량을 구한 뒤 전부 합산한다. Lumped 2노드 축약이므로
    스택 전체를 단일 열용량 노드로 본다(설계 문서 §3 리스크1 — 축약 기준은
    "스택 전체 합산"으로 명시. 온도 구배가 아니라 저장 에너지를 다루므로
    base_die/top_die 구분과 무관하게 전체 부피가 기여함).

    Args:
        stack: layer_stack_hbm2e() 형식의 레이어 dict 목록. None이면 기본
            8-Hi 스택 사용.
        footprint_mm: (x, y) 다이 풋프린트 크기 (mm). model_config.py의
            build_geometry_spec() 기본값과 일치시킴(11×10 mm).

    Returns:
        (c_hbm_j_k, contributions) 튜플.
        c_hbm_j_k: 스택 전체 열용량 (J/K).
        contributions: 레이어별 기여분 목록(스택 순서대로), 정렬 없이 원순서.
    """
    if stack is None:
        stack = layer_stack_hbm2e()

    footprint_x_m = footprint_mm[0] * _MM_TO_M
    footprint_y_m = footprint_mm[1] * _MM_TO_M
    footprint_area_m2 = footprint_x_m * footprint_y_m

    contributions: list[LayerCContribution] = []
    total_c_j_k = 0.0

    for layer in stack:
        thickness_um = layer["thickness_um"]
        thickness_m = thickness_um * 1e-6
        volume_m3 = footprint_area_m2 * thickness_m
        rho_cp = layer["rho_cp"]
        capacitance_j_k = rho_cp * volume_m3
        contributions.append(
            LayerCContribution(
                name=layer["name"],
                rho_cp_j_m3k=rho_cp,
                volume_m3=volume_m3,
                capacitance_j_k=capacitance_j_k,
            )
        )
        total_c_j_k += capacitance_j_k

    return total_c_j_k, contributions


@dataclass(frozen=True)
class RHbmSinkCase:
    """r_hbm_sink 산출에 쓰인 개별 냉각 케이스 실측."""

    case_name: str
    delta_t_k: float
    power_w: float
    r_k_w: float


def compute_r_hbm_sink_range(
    param_study_rows: list[dict],
    ambient_c: float = 40.0,
    case_names: tuple[str, ...] = ("baseline_8hi", "cooling_top_bottom"),
    temperature_column: str = "base_die_avg_c",
) -> tuple[list[RHbmSinkCase], float, float]:
    """냉각 BC가 다른 두 케이스에서 R = ΔT / P를 계산해 r_hbm_sink 범위를 낸다.

    설계 근거: Icepak HTC 2500 상단 단면 BC는 A100 실장(히트싱크+TIM)과
    다르므로(설계 문서 §2 "냉각 BC 불일치 처리") 단일 대표값이 아니라 기존
    param_study.csv의 냉각 케이스(baseline_8hi=상단만 vs
    cooling_top_bottom=상단+하단)를 재활용해 범위로 산출한다.

    축약 기준(설계 문서 §3 리스크1): 스택 대표 온도로 base_die_avg_c를
    쓴다 — base_die가 최대 발열원이자(build_power_spec 근거) steady 구배가
    작은(~2K) 이 스택에서 열 경로상 병목에 가장 가까운 지점이기 때문.

    Args:
        param_study_rows: results/param_study.csv를 csv.DictReader로 읽은
            행 목록(문자열 값). name, total_power_w, temperature_column
            컬럼이 있어야 함.
        ambient_c: 주변 온도 (°C). Icepak 설정과 동일(scripts/build_icepak_model.py
            _AMBIENT_TEMP_C = 40.0).
        case_names: R을 계산할 케이스명(param_study.csv의 name 컬럼) 튜플.
            정확히 이 이름들이 모두 있어야 하며 없으면 KeyError.
        temperature_column: 대표 온도로 쓸 컬럼명.

    Returns:
        (cases, r_min_k_w, r_max_k_w) 튜플. cases는 케이스별 계산 상세
        (case_names 순서 보존), r_min/r_max는 그 중 최솟값/최댓값.

    Raises:
        KeyError: case_names 중 param_study_rows에 없는 케이스가 있는 경우.
    """
    rows_by_name = {row["name"]: row for row in param_study_rows}

    cases: list[RHbmSinkCase] = []
    for name in case_names:
        if name not in rows_by_name:
            raise KeyError(
                f"param_study 결과에 케이스 {name!r}가 없습니다. "
                f"사용 가능한 케이스: {sorted(rows_by_name)}"
            )
        row = rows_by_name[name]
        temp_c = float(row[temperature_column])
        power_w = float(row["total_power_w"])
        delta_t_k = temp_c - ambient_c
        r_k_w = delta_t_k / power_w
        cases.append(
            RHbmSinkCase(case_name=name, delta_t_k=delta_t_k, power_w=power_w, r_k_w=r_k_w)
        )

    r_values = [c.r_k_w for c in cases]
    return cases, min(r_values), max(r_values)


def load_param_study_csv(path: str) -> list[dict]:
    """param_study.csv를 dict 행 목록으로 읽는다(순수 I/O 헬퍼, pyaedt 무관)."""
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build_rc_params_rows(
    c_hbm_j_k: float,
    c_contributions: list[LayerCContribution],
    r_cases: list[RHbmSinkCase],
    r_min_k_w: float,
    r_max_k_w: float,
) -> list[dict]:
    """rc_params.csv에 쓸 행 목록을 구성한다.

    컬럼: parameter, value, value_min, value_max, unit, method, basis_case.
    단일값 파라미터(c_hbm)는 value만 채우고 value_min/max는 빈 문자열,
    범위 파라미터(r_hbm_sink)는 value에 대표값(범위 중앙값 근사로 max 사용
    — 보수적 상한. A/B 재계산에서 idle sensitivity와 동형 3점 민감도로
    범위 전체를 사용하는 것은 Compiler_Thermal 쪽(T5) 책임이며, 이 CSV는
    range의 근거만 제공한다), value_min/value_max에 범위를 채운다.
    """
    top3 = sorted(c_contributions, key=lambda c: c.capacitance_j_k, reverse=True)[:3]
    top3_desc = "; ".join(
        f"{c.name}={c.capacitance_j_k:.6e} J/K" for c in top3
    )
    basis_cases_r = ", ".join(c.case_name for c in r_cases)
    r_detail = "; ".join(
        f"{c.case_name}: dT={c.delta_t_k:.3f}K/P={c.power_w:.3f}W->R={c.r_k_w:.6f}K/W"
        for c in r_cases
    )

    return [
        {
            "parameter": "c_hbm",
            "value": f"{c_hbm_j_k:.6e}",
            "value_min": "",
            "value_max": "",
            "unit": "J/K",
            "method": (
                "해석적: Σ rho_cp_i * V_i (레이어별 T1 균질화 rho_cp x "
                "footprint*thickness 부피, hbm_thermal.homogenize.layer_stack_hbm2e)"
            ),
            "basis_case": f"layer_stack_hbm2e() 8-Hi 기본 스택; 상위 기여 3개: {top3_desc}",
        },
        {
            "parameter": "r_hbm_sink",
            "value": f"{r_max_k_w:.6f}",
            "value_min": f"{r_min_k_w:.6f}",
            "value_max": f"{r_max_k_w:.6f}",
            "unit": "K/W",
            "method": (
                "실측: R = (base_die_avg_c - ambient_c) / total_power_w, "
                "냉각 BC 상이한 두 케이스로 범위 산출 (Icepak HTC 단면 BC != A100 실장 "
                "TIM+히트싱크 — 단일값 아닌 범위로 제시)"
            ),
            "basis_case": f"{basis_cases_r} ({r_detail})",
        },
    ]


def write_rc_params_csv(path: str, rows: list[dict]) -> None:
    """rc_params.csv를 기록한다(순수 I/O 헬퍼, pyaedt 무관)."""
    fieldnames = ["parameter", "value", "value_min", "value_max", "unit", "method", "basis_case"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def append_rc_params_csv(path: str, rows: list[dict]) -> None:
    """기존 rc_params.csv에 행을 append한다(기존 c_hbm/r_hbm_sink 행 무변경).

    파일이 이미 존재하고 헤더가 있어야 한다 — 헤더 재작성 없이 데이터
    행만 추가한다. P4 T5 hotspot 지표(별도 파라미터) 추가용.
    """
    fieldnames = ["parameter", "value", "value_min", "value_max", "unit", "method", "basis_case"]
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writerows(rows)


def load_p3_scenario_csv(path: str) -> dict[str, dict[str, float]]:
    """P3 Icepak 시나리오 CSV(die,avg_temp_c,max_temp_c)를 읽어 die명->값 dict로 반환."""
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return {
        row["die"]: {
            "avg_temp_c": float(row["avg_temp_c"]),
            "max_temp_c": float(row["max_temp_c"]),
        }
        for row in rows
    }


@dataclass(frozen=True)
class RHbmSinkMaxCase:
    """r_hbm_sink_max(hotspot 기반) 산출에 쓰인 개별 케이스 실측."""

    case_name: str
    delta_t_k: float
    power_w: float
    r_k_w: float


def compute_r_hbm_sink_max_anchor(
    param_study_rows: list[dict],
    ambient_c: float = 40.0,
    case_names: tuple[str, ...] = ("baseline_8hi", "cooling_top_bottom"),
) -> tuple[list[RHbmSinkMaxCase], float, float]:
    """param_study.csv의 base_die_max_c 기반으로 r_hbm_sink_max 대표 범위를 낸다.

    기존 r_hbm_sink(avg 기반)와 동일한 두 냉각 케이스(top-only vs
    top+bottom)를 재사용하되 온도 컬럼만 base_die_avg_c -> base_die_max_c로
    바꾼다. baseline_8hi 앵커값은 P4 T4/T5에서 이미 산출된 R=5.1386 K/W
    (JOURNAL 2026-07-19T22:29:53+09:00, p4_report.md §5 hotspot R 행)와
    정확히 일치해야 한다 — 앵커 교차검증 대상.

    R = (base_die_max_c - ambient_c) / total_power_w.
    """
    cases_generic, r_min, r_max = compute_r_hbm_sink_range(
        param_study_rows,
        ambient_c=ambient_c,
        case_names=case_names,
        temperature_column="base_die_max_c",
    )
    cases = [
        RHbmSinkMaxCase(
            case_name=c.case_name, delta_t_k=c.delta_t_k, power_w=c.power_w, r_k_w=c.r_k_w
        )
        for c in cases_generic
    ]
    return cases, r_min, r_max


def compute_r_hbm_sink_max_p3_scenarios(
    p3_scenarios: dict[str, dict[str, dict[str, float]]],
    total_power_w: float = 16.0,
    ambient_c: float = 40.0,
    die_name: str = "base_die",
) -> list[RHbmSinkMaxCase]:
    """P3 전력맵 시나리오별(s0/s1/s2) base_die max 기반 R을 계산한다.

    P3 세 시나리오는 top-only 냉각·총전력 16.0W 고정, base_die 내부
    PHY/TSVA/DA 배분만 다르다(build_icepak_model.py --power-scenario,
    base_die_fraction=0.55 고정 — JOURNAL 2026-07-19T22:05:00+09:00
    build_power_spec() 확인: DRAM/bump/EMC 전력은 시나리오 불변).
    p3_scenarios: {시나리오명: load_p3_scenario_csv() 결과} dict.
    """
    cases: list[RHbmSinkMaxCase] = []
    for scenario_name in sorted(p3_scenarios):
        dies = p3_scenarios[scenario_name]
        max_temp_c = dies[die_name]["max_temp_c"]
        delta_t_k = max_temp_c - ambient_c
        r_k_w = delta_t_k / total_power_w
        cases.append(
            RHbmSinkMaxCase(
                case_name=scenario_name,
                delta_t_k=delta_t_k,
                power_w=total_power_w,
                r_k_w=r_k_w,
            )
        )
    return cases


def compute_r_hbm_sink_max_p4_scenarios(
    p4_scenarios: dict[str, dict[str, dict[str, float]]],
    total_power_w: float = 30.0,
    ambient_c: float = 40.0,
    die_name: str = "base_die_phy",
    fallback_die_name: str = "base_die",
) -> list[RHbmSinkMaxCase]:
    """P4 전력맵 시나리오별(A/B계열 x s0/s1/s2) base_die max 기반 R을 계산한다.

    compute_r_hbm_sink_max_p3_scenarios()와 동형(P5 T2b, 설계 문서
    docs/09-p5-analysis-design.md §3 T2 작업1) — 기존 P3 전용 함수는
    무변경. P4는 30W 고정(A/B 두 냉각계열 x S0~S2 전력맵 3종=6케이스),
    S0(균일배분)는 die_name(base_die_phy) 행이 없는 CSV가 있으므로
    fallback_die_name(base_die)로 자동 폴백한다(T1/T3 선례와 동일 패턴,
    설계 §3 T2 작업1 "S0은 base_die_phy 부재 시 base_die max로 폴백").

    p4_scenarios: {시나리오명: load_p3_scenario_csv() 결과} dict. 시나리오명은
        호출부에서 계열·전력맵을 구분해 붙인다(예: "a_s0_uniform").
        load_p3_scenario_csv()는 P4 CSV(동일 스키마: die,avg_temp_c,max_temp_c)도
        그대로 읽을 수 있어 재사용한다.
    """
    cases: list[RHbmSinkMaxCase] = []
    for scenario_name in sorted(p4_scenarios):
        dies = p4_scenarios[scenario_name]
        if die_name in dies:
            max_temp_c = dies[die_name]["max_temp_c"]
            used_die = die_name
        else:
            max_temp_c = dies[fallback_die_name]["max_temp_c"]
            used_die = fallback_die_name
        delta_t_k = max_temp_c - ambient_c
        r_k_w = delta_t_k / total_power_w
        cases.append(
            RHbmSinkMaxCase(
                case_name=f"{scenario_name}[{used_die}]",
                delta_t_k=delta_t_k,
                power_w=total_power_w,
                r_k_w=r_k_w,
            )
        )
    return cases


def build_r_hbm_sink_max_p4_row(p4_cases: list[RHbmSinkMaxCase]) -> dict:
    """rc_params.csv에 append할 P4(30W) hotspot R 확장 행을 구성한다.

    설계 §3 T2 작업4: 기존 r_hbm_sink_max 행(냉각BC 범위 앵커 + P3 3케이스)은
    무변경 유지 — 대표 단일값(value/value_min/value_max)에 전력맵 축을
    섞지 않는다(설계 §3 T2 작업4 명시). P4 6케이스는 신규 행
    r_hbm_sink_max_p4로 분리한다. value/value_min/value_max는 6케이스
    R의 [min, max] 범위를 그대로 채운다(30W 고정이므로 냉각BC 범위
    앵커 재사용 없음 — A/B 두 냉각계열 자체가 이미 범위축 역할).
    """
    r_values = [c.r_k_w for c in p4_cases]
    r_min = min(r_values)
    r_max = max(r_values)
    detail = "; ".join(
        f"{c.case_name}: dT={c.delta_t_k:.3f}K/P={c.power_w:.3f}W->R={c.r_k_w:.6f}K/W"
        for c in p4_cases
    )
    names = ", ".join(c.case_name for c in p4_cases)

    return {
        "parameter": "r_hbm_sink_max_p4",
        "value": f"{r_max:.6f}",
        "value_min": f"{r_min:.6f}",
        "value_max": f"{r_max:.6f}",
        "unit": "K/W",
        "method": (
            "실측(hotspot 기반, P5 T2b): R = (base_die_phy_max - ambient_c) / "
            "total_power_w(30.0 고정), P4 A/B계열 x S0~S2 전력맵 6케이스 — "
            "r_hbm_sink_max(P3 16W, top-only)와 동일 산식·다른 전력·냉각계열축. "
            "S0(균일배분)는 base_die_phy 행이 없어 base_die max로 폴백(대괄호 "
            "표기로 사용된 die 명시, T1/T3 선례와 동일 패턴). "
            "H_T2(전력 선형성): 설계 §2 반증조건(±10%) 참조 — 상세 판정은 "
            "p5_report.md §T2b 기재."
        ),
        "basis_case": f"[P4 전력맵x냉각계열, 30W 고정] {names} ({detail})",
    }


def build_r_hbm_sink_max_row(
    anchor_cases: list[RHbmSinkMaxCase],
    anchor_r_min: float,
    anchor_r_max: float,
    p3_cases: list[RHbmSinkMaxCase],
) -> dict:
    """rc_params.csv에 append할 r_hbm_sink_max(hotspot 기반) 행을 구성한다.

    스키마는 기존 c_hbm/r_hbm_sink 행과 동일(parameter, value, value_min,
    value_max, unit, method, basis_case). 값은 냉각 BC 두 케이스(anchor)
    범위를 대표로 쓰고, P3 전력맵 3케이스(s0/s1/s2, top-only 냉각 고정)는
    basis_case 서술에 개별 명시해 전력맵 의존성도 함께 드러낸다.
    """
    anchor_detail = "; ".join(
        f"{c.case_name}: dT={c.delta_t_k:.3f}K/P={c.power_w:.3f}W->R={c.r_k_w:.6f}K/W"
        for c in anchor_cases
    )
    p3_detail = "; ".join(
        f"{c.case_name}: dT={c.delta_t_k:.3f}K/P={c.power_w:.3f}W->R={c.r_k_w:.6f}K/W"
        for c in p3_cases
    )
    anchor_names = ", ".join(c.case_name for c in anchor_cases)
    p3_names = ", ".join(c.case_name for c in p3_cases)

    return {
        "parameter": "r_hbm_sink_max",
        "value": f"{anchor_r_max:.6f}",
        "value_min": f"{anchor_r_min:.6f}",
        "value_max": f"{anchor_r_max:.6f}",
        "unit": "K/W",
        "method": (
            "실측(hotspot 기반): R = (base_die_max_c - ambient_c) / total_power_w, "
            "r_hbm_sink(avg 기반)와 동일 두 냉각 케이스로 대표 범위 산출 — "
            "hotspot R은 전력맵(base_die 내부 PHY/TSVA/DA 배분)에도 의존하므로 "
            "P3 3-시나리오(top-only 고정, 16W) 개별값을 basis_case에 별도 명시 "
            "(단일 대표값이 아닌 범위 필수 — P4 T5 R=5.1386 K/W 앵커와 정합, "
            "JOURNAL 2026-07-19T22:29:53+09:00)"
        ),
        "basis_case": (
            f"[냉각BC 범위 앵커] {anchor_names} ({anchor_detail}); "
            f"[P3 전력맵 시나리오, top-only 냉각·16W 고정] {p3_names} ({p3_detail})"
        ),
    }
