"""HBM2E 8-Hi 레이어 스택을 3D-ICE Stack Description File(.stk)로 변환하는 순수 로직 모듈.

3D-ICE(EPFL, https://github.com/esl-epfl/3d-ice)는 오픈소스 컴팩트 열해석 툴로,
Icepak 결과 교차검증(vault research/04-validation-anchors.md, 실측 대비 <10% 공인
합격선)에 사용한다. 이 모듈은 3D-ICE 바이너리에 의존하지 않는 순수 텍스트 생성
로직만 담당한다 — WSL 등 3D-ICE가 없는 환경에서도 전부 테스트 가능하다.

단위 변환 (실측 검증, docs/03-cross-validation-3d-ice.md 참고):
    3D-ICE 내부 단위계는 길이=마이크로미터(µm) 기준 파생 단위를 쓴다.
    - 길이: µm (그대로 사용, model_config.py 스펙과 동일 단위)
    - 열전도율: W/(µm·K) = W/(m·K) × 1e-6
    - 체적비열: J/(µm³·K) = J/(m³·K) × 1e-18  (본 모듈에서는 미사용 — steady-state만 다룸)
    - HTC: W/(µm²·K) = W/(m²·K) × 1e-12
    - 온도: 켈빈(K) = °C + 273.15
    이 변환은 1D 열저항망 손계산(HTC 전용 경로 dT=4.0000K vs 3D-ICE 실측 4.0030K,
    HTC+전도 경로 dT=4.0034K)으로 4자리 유효숫자까지 검증됨.
"""
from __future__ import annotations

from hbm_thermal.model_config import build_geometry_spec, build_material_spec, build_power_spec

# --- 단위 변환 상수 ---------------------------------------------------------
_K_W_MK_TO_W_UMK = 1e-6  # W/(m·K) -> W/(µm·K)
_HTC_W_M2K_TO_W_UM2K = 1e-12  # W/(m²·K) -> W/(µm²·K)
_CELSIUS_TO_KELVIN_OFFSET = 273.15

# 3D-ICE 레이어명 접두어가 die 블록 내에서 source/layer로 분기되는 규칙과 동일하게,
# 전력이 할당되는 레이어(dies)만 "source"로 만들고 나머지는 "layer"로 만든다.
_POWER_BEARING_PREFIXES = ("base_die", "dram_die", "top_die")

# 셀 격자 해상도: 균질화 layer-cake 모델은 층 내부가 균일 물성이므로 조대한
# 격자로도 충분 — footprint를 4x4 셀(각 방향 4분할)로 나눈다 (기본값, 필요시 조정).
_DEFAULT_CELL_DIVISIONS = 4


def celsius_to_kelvin(temp_c: float) -> float:
    """섭씨를 켈빈으로 변환한다 (3D-ICE는 온도를 켈빈으로 받음)."""
    return temp_c + _CELSIUS_TO_KELVIN_OFFSET


def conductivity_w_mk_to_3dice(k_w_mk: float) -> float:
    """W/(m·K) 열전도율을 3D-ICE 내부 단위(W/(µm·K))로 변환한다."""
    return k_w_mk * _K_W_MK_TO_W_UMK


def htc_w_m2k_to_3dice(htc_w_m2k: float) -> float:
    """W/(m²·K) HTC를 3D-ICE 내부 단위(W/(µm²·K))로 변환한다."""
    return htc_w_m2k * _HTC_W_M2K_TO_W_UM2K


def _is_power_bearing(layer_name: str) -> bool:
    return layer_name.startswith(_POWER_BEARING_PREFIXES)


def _material_id_for_layer_name(material_name: str) -> str:
    """model_config.py의 재료명(hbm_tsv_die_mat 등)을 3D-ICE 식별자로 정리한다.

    3D-ICE의 material 식별자는 영숫자/언더스코어만 허용되는 것으로 가정하고,
    기존 재료명이 이미 그 조건을 만족하므로 그대로 사용한다(변환 없음, 검증만).
    """
    if not material_name.replace("_", "").isalnum():
        raise ValueError(f"3D-ICE 식별자로 부적합한 재료명: {material_name!r}")
    return material_name


_VHC_J_M3K_TO_J_UM3K = 1e-18  # J/(m³·K) -> J/(µm³·K)


def volumetric_heat_capacity_j_m3k_to_3dice(rho_cp_j_m3k: float) -> float:
    """J/(m³·K) 체적 열용량을 3D-ICE 내부 단위(J/(µm³·K))로 변환한다.

    검증 근거: docs/03-cross-validation-3d-ice.md §3 — 3D-ICE 공식 예제
    example_steady.stk의 SILICON VHC 값(1.628e-12 J/µm³·K)이 Si 벌크
    1.63e6 J/(m³·K)(=RHO_SI*CP_SI)와 오차 0.12%로 일치함을 손계산으로 확인.
    """
    return rho_cp_j_m3k * _VHC_J_M3K_TO_J_UM3K


def build_materials_block(material_spec: dict) -> str:
    """재료명 -> {k_x, k_y, k_z, rho_cp} dict로부터 3D-ICE material 블록 텍스트를 만든다.

    volumetric heat capacity는 T1 균질화 rho_cp 실값(hbm_thermal.model_config.
    build_material_spec()이 layer_stack_hbm2e()에서 레이어별 rho_cp를 재료
    역할별로 취합한 값)을 사용한다 — steady-state 해석에는 영향이 없지만
    (정상상태 방정식에 시간미분항 없음), transient 해석(P2 T3)에서는 τ=RC
    시상수를 결정하는 핵심 물성이므로 placeholder를 쓰면 안 된다(경고:
    hbm_thermal/rc_extract.py 모듈 docstring 참고 — 과거 placeholder
    1.628e-12 J/µm³·K는 문법 통과용 Si 벌크 단일값이었고 재료별 실제 값이
    아니었다).

    Args:
        material_spec: build_material_spec() 결과 — 각 값에 "rho_cp"(J/m³·K)
            키가 있어야 한다(model_config.py T3 확장).

    Returns:
        3D-ICE .stk material 블록 전체 텍스트.
    """
    blocks = []
    for mat_name, props in material_spec.items():
        mat_id = _material_id_for_layer_name(mat_name)
        kx = conductivity_w_mk_to_3dice(props["k_x"])
        ky = conductivity_w_mk_to_3dice(props["k_y"])
        kz = conductivity_w_mk_to_3dice(props["k_z"])
        vhc = volumetric_heat_capacity_j_m3k_to_3dice(props["rho_cp"])
        blocks.append(
            f"material {mat_id} :\n"
            f"   thermal conductivity     {kx:.6e}, {ky:.6e}, {kz:.6e} ;\n"
            f"   volumetric heat capacity {vhc:.6e} ;\n"
        )
    return "\n".join(blocks)


def build_heat_sink_block(htc_w_m2k: float, ambient_c: float) -> str:
    """상단 히트싱크 근사 BC 블록을 만든다 (Icepak assign_stationary_wall_with_htc와 등가).

    Args:
        htc_w_m2k: 히트싱크 HTC (W/m²K).
        ambient_c: 주변 온도 (°C).

    Returns:
        3D-ICE .stk top heat sink 블록 텍스트.
    """
    htc_3dice = htc_w_m2k_to_3dice(htc_w_m2k)
    temp_k = celsius_to_kelvin(ambient_c)
    return (
        "top heat sink :\n"
        f"   heat transfer coefficient {htc_3dice:.6e} ;\n"
        f"   temperature               {temp_k:.4f} ;\n"
    )


def build_dimensions_block(
    footprint_mm: tuple[float, float], cell_divisions: int = _DEFAULT_CELL_DIVISIONS
) -> str:
    """dimensions 블록을 만든다. footprint(mm)를 µm로 변환하고 정사각 격자로 분할한다.

    Args:
        footprint_mm: (x, y) 다이 풋프린트 (mm).
        cell_divisions: 각 방향 셀 분할 수 (기본 4 — 균질화 모델은 층내 균일하므로 조대해도 무방).

    Returns:
        3D-ICE .stk dimensions 블록 텍스트.
    """
    x_um = footprint_mm[0] * 1000.0
    y_um = footprint_mm[1] * 1000.0
    cell_x_um = x_um / cell_divisions
    cell_y_um = y_um / cell_divisions
    return (
        "dimensions :\n"
        f"   chip length {x_um:.4f}, width {y_um:.4f} ;\n"
        f"   cell length {cell_x_um:.4f}, width {cell_y_um:.4f} ;\n"
        "   non-uniform false ;\n"
    )


def build_die_blocks_and_stack(
    geometry: list[dict], power_spec: dict
) -> tuple[str, str]:
    """레이어별 die 정의 블록과 stack 블록을 만든다.

    각 레이어를 독립된 die로 취급한다 (모두 동일 footprint를 공유하는
    layer-cake 스택이므로, die 내부에 여러 층을 두는 대신 die 하나 = 레이어
    하나로 단순화 — floorplan도 단일 사각형 영역으로 매핑).

    3D-ICE 문법 제약(bison/stack_description_parser.y의 `die` 규칙:
    `DIE IDENTIFIER ':' die_top_layers_list die_source_layer
    die_bottom_layers_list`)상 **모든 die는 정확히 하나의 source 층을
    포함해야 한다** — 순수 layer만으로 구성된 die는 문법 오류(실측 확인:
    "unexpected keyword die, expecting keyword layer or keyword source").
    따라서 비전력 레이어(bump/EMC)도 source로 선언하되 전력값을 0으로 둔다
    (물리적으로 layer와 동등 — source 전력 0이면 발열원이 없을 뿐).

    **stack 블록 순서 = 위→아래(top→bottom), model_config.py z축과 반대.**
    3D-ICE는 stack 블록에 먼저 나열된 die를 "가장 위(topmost, 히트싱크에
    가장 가까운 층)"로 해석한다(bison/stack_description_parser.y 주석
    "parser processes elements in the stack from the top most" +
    `tmost = ...list_begin(...)` 코드로 확인). model_config.py의 geometry는
    반대로 z=0(최하단, base_die)부터 위로 쌓는 순서다. 순서를 그대로 stack:
    블록에 쓰면 base_die가 히트싱크 바로 아래(최상단)로 배치되어 물리적으로
    반전된 구조가 된다(실측 확인: base_die가 top_die보다 낮은 온도로 나와
    Icepak 결과와 구배 방향이 뒤집힘) — 따라서 stack: 블록에는 geometry를
    역순으로 써서 EMC(실제 최상단, 히트싱크 노출면)가 먼저, base_die(실제
    최하단)가 마지막에 오도록 한다. die 정의 블록 자체의 순서는 무관하다.

    Args:
        geometry: build_geometry_spec() 결과 (레이어 순서 = z 방향 적층 순서,
            base_die가 첫 원소 = 스택 최하단).
        power_spec: build_power_spec() 결과 (레이어명 -> 전력 W).

    Returns:
        (die_blocks_text, stack_block_text) 튜플.
    """
    die_blocks = []
    stack_lines = ["stack:"]

    for layer in geometry:
        name = layer["name"]
        mat_id = _material_id_for_layer_name(layer["material_name"])
        thickness_um = layer["size_mm"][2] * 1000.0
        die_id = f"die_{name}"

        # 모든 die는 source 층 정확히 하나를 요구하므로(문법 제약, 위 docstring
        # 참고) 비전력 레이어도 source로 선언한다. 전력은 floorplan(.flp)에서
        # 0으로 지정 — die 정의 자체에는 전력값이 없다(power values 라인은
        # .flp 쪽 책임).
        die_blocks.append(f"die {die_id} :\n   source {thickness_um:.4f} {mat_id} ;\n")

    # stack: 블록은 geometry 역순(EMC가 최상단=먼저, base_die가 최하단=마지막) —
    # docstring 설명 참고.
    for layer in reversed(geometry):
        name = layer["name"]
        die_id = f"die_{name}"
        flp_ref = f'"./{name}.flp"' if name in power_spec else f'"./{name}_nopower.flp"'
        stack_lines.append(f"   die {name} {die_id} floorplan {flp_ref} ;")

    stack_block = "\n".join(stack_lines) + "\n"
    return "\n".join(die_blocks), stack_block


def build_floorplan_file(
    footprint_mm: tuple[float, float], power_w: float | None, n_slots: int = 1
) -> str:
    """단일 사각형 영역 floorplan(.flp) 텍스트를 만든다.

    3D-ICE의 ``power values``는 슬롯별 전력 리스트다(문법: 콤마로 구분된
    값 목록, 값 개수 = 시뮬레이션이 진행할 슬롯 수 — 값이 1개면 슬롯 1개
    후 TDICE_END_OF_SIMULATION으로 종료됨을 실측 확인, bin/core.flp 등
    3D-ICE 공식 예제에서 동일 값을 반복해 슬롯을 늘리는 패턴 확인). steady는
    슬롯 개념이 없어 n_slots=1(기존 동작)이면 충분하지만, transient
    스텝 응답(P2 T3)은 여러 슬롯에 걸쳐 동일한 상시 전력을 유지해야
    시간축 전체를 시뮬레이션할 수 있으므로 같은 값을 n_slots번 반복한다.

    Args:
        footprint_mm: (x, y) 다이 풋프린트 (mm).
        power_w: 이 레이어의 전력(W). None이면 0W(비전력 레이어, layer 다이용).
        n_slots: power values 리스트에 반복할 슬롯 수. steady(기본 1)는
            영향 없음(steady solver는 슬롯 축 자체를 안 씀). transient에서는
            시뮬레이션할 총 슬롯 수와 같아야 한다(호출측 책임).

    Returns:
        3D-ICE .flp 파일 전체 텍스트.

    Raises:
        ValueError: n_slots가 1 미만인 경우.
    """
    if n_slots < 1:
        raise ValueError(f"n_slots는 1 이상이어야 합니다 (입력값={n_slots}).")

    x_um = footprint_mm[0] * 1000.0
    y_um = footprint_mm[1] * 1000.0
    power = power_w if power_w is not None else 0.0
    power_values = ", ".join(f"{power:.6f}" for _ in range(n_slots))
    return (
        "Whole :\n"
        "   position 0, 0 ;\n"
        f"   dimension {x_um:.4f}, {y_um:.4f} ;\n"
        f"   power values {power_values} ;\n"
    )


def build_output_block(die_names: list[str], transient: bool = False) -> str:
    """die별 평균/최대 온도를 파일로 export하는 output 블록을 만든다.

    Args:
        die_names: 온도를 추출할 die 이름 목록 (stack의 die 인스턴스명, die_ 접두어 아님).
        transient: True면 매 slot(3D-ICE 문법상 ``, slot`` 인자, bison/
            stack_description_parser.y의 TDICE_OUTPUT_INSTANT_SLOT)마다
            평균 온도를 시계열로 기록한다(τ 피팅용, T3). False(기본, steady)면
            해석 종료 시점(``final``) 값만 기록한다(기존 동작 무변경 — 회귀 방지).

    Returns:
        3D-ICE .stk output 블록 텍스트.
    """
    instant = "average, slot" if transient else "average, final"
    max_instant = "maximum, slot" if transient else "maximum, final"
    lines = ["output:"]
    for name in die_names:
        lines.append(f'   Tflp ( {name}, "{name}_avg.txt", {instant} ) ;')
        lines.append(f'   Tflp ( {name}, "{name}_max.txt", {max_instant} ) ;')
    return "\n".join(lines) + "\n"


def build_solver_block(
    ambient_c: float,
    transient: bool = False,
    step_time_s: float = 0.01,
    slot_time_s: float = 1.0,
) -> str:
    """solver 블록을 만든다 (steady 또는 transient).

    Args:
        ambient_c: 초기온도로 사용할 기준 온도 (°C). steady는 주변온도,
            transient는 스텝 전력 인가 전 정상상태 온도를 넣는 것이 물리적으로
            맞다(호출측 책임 — 이 함수는 그대로 켈빈 변환만 한다).
        transient: True면 transient step-response solver 블록을 만든다
            (bison 문법: ``transient step <StepTime>, slot <SlotTime> ;``,
            docs/03-cross-validation-3d-ice.md 참고 문법 검증 절차와 동일하게
            stack_description_parser.y 1752행대 확인). False(기본)면 기존
            steady 블록 그대로 반환 — 회귀 방지.
        step_time_s: transient 적분 스텝 크기 (초). SlotTime보다 작아야 하며
            0보다 커야 한다(문법 파서가 검증, 3D-ICE-Emulator 실행 시 오류).
        slot_time_s: transient 출력 슬롯 길이 (초). output 블록의 ``slot``
            인스턴트가 이 주기로 기록된다.

    Returns:
        3D-ICE .stk solver 블록 텍스트.
    """
    temp_k = celsius_to_kelvin(ambient_c)
    if not transient:
        return (
            "solver:\n"
            "   steady ;\n"
            f"   initial temperature {temp_k:.4f} ;\n"
            "   numofcores 1 ;\n"
        )
    return (
        "solver:\n"
        f"   transient step {step_time_s:.6f}, slot {slot_time_s:.6f} ;\n"
        f"   initial temperature {temp_k:.4f} ;\n"
        "   numofcores 1 ;\n"
    )


def build_stack_description(
    footprint_mm: tuple[float, float] = (11.0, 10.0),
    total_power_w: float = 16.0,
    base_die_fraction: float = 0.55,
    ambient_c: float = 40.0,
    htc_w_m2k: float = 2500.0,
    transient: bool = False,
    initial_temperature_c: float | None = None,
    step_time_s: float = 0.01,
    slot_time_s: float = 1.0,
    n_slots: int = 1,
) -> dict[str, str]:
    """전체 .stk 파일 + 레이어별 .flp 파일 텍스트를 한 번에 생성한다.

    Icepak(build_icepak_model.py)과 동일한 기본 경계조건을 사용해 교차검증
    대상이 동등 조건이 되도록 한다: base_die 8.8W + DRAM die 8장 각 0.9W(=16W),
    ambient 40°C, 상단 HTC 2500 W/m²K, 전도 전용.

    transient=True면 P2 T3(τ=RC 대조 검증)용 스텝 응답 입력을 생성한다 —
    die/재료/BC 정의는 steady와 완전히 동일하고(교차검증 등가성 유지), solver와
    output 블록만 transient 형식으로 바뀐다. 전력은 .flp에서 상시 total_power_w로
    선언되므로(3D-ICE 문법에 시간축 전력 스케줄이 없음 — floorplan은 상수),
    initial_temperature_c를 전력 인가 전 온도(보통 ambient)로 지정하면
    t=0에서 전력이 계단형으로 인가되는 것과 동일한 효과를 낸다(초기값 ≠
    최종 정상상태이므로 해가 시간에 따라 initial->steady로 지수적으로
    수렴 — 이 상승 궤적이 τ 피팅 대상).

    Args:
        footprint_mm: (x, y) 다이 풋프린트 (mm).
        total_power_w: 스택 총 발열량 (W).
        base_die_fraction: base_die 전력 비율.
        ambient_c: 주변 온도 (°C) — heat sink 블록의 BC 온도(steady/transient 공통).
        htc_w_m2k: 히트싱크 HTC (W/m²K).
        transient: True면 transient 스텝 응답 입력 생성. False(기본)면 기존
            steady 동작 그대로 — 회귀 방지.
        initial_temperature_c: transient 초기온도(°C). None이면 ambient_c
            사용(전력 인가 전 완전 냉각 상태 가정 — 가장 단순한 스텝 응답).
            steady(transient=False)에서는 무시된다.
        step_time_s: transient 적분 스텝 크기 (초, transient에서만 사용).
        slot_time_s: transient 출력 슬롯 길이 (초, transient에서만 사용).
        n_slots: transient 시뮬레이션할 총 슬롯 수(=총 시뮬레이션 시간 /
            slot_time_s). 3D-ICE는 .flp의 power values 리스트 길이만큼만
            슬롯을 진행하고 종료하므로(build_floorplan_file docstring 참고,
            실측 확인) τ 피팅에 필요한 만큼(예: τ_analytic의 5~10배 구간을
            덮도록) 호출측이 계산해 넘겨야 한다. steady(transient=False)에서는
            무시된다(기존 동작 n_slots=1과 동치).

    Returns:
        {"stack.stk": 텍스트, "<layer>.flp" 또는 "<layer>_nopower.flp": 텍스트, ...} dict.
        키는 파일명, 값은 해당 파일에 쓸 텍스트.
    """
    geometry = build_geometry_spec(footprint_mm=footprint_mm)
    material_spec = build_material_spec()
    power_spec = build_power_spec(total_w=total_power_w, base_die_fraction=base_die_fraction)

    materials_block = build_materials_block(material_spec)
    heat_sink_block = build_heat_sink_block(htc_w_m2k, ambient_c)
    dimensions_block = build_dimensions_block(footprint_mm)
    die_blocks, stack_block = build_die_blocks_and_stack(geometry, power_spec)
    die_names_in_stack_order = [layer["name"] for layer in geometry]
    output_block = build_output_block(die_names_in_stack_order, transient=transient)
    if transient:
        solver_init_c = ambient_c if initial_temperature_c is None else initial_temperature_c
        solver_block = build_solver_block(
            solver_init_c, transient=True, step_time_s=step_time_s, slot_time_s=slot_time_s
        )
    else:
        solver_block = build_solver_block(ambient_c)

    stk_text = "\n".join(
        [
            materials_block,
            heat_sink_block,
            dimensions_block,
            die_blocks,
            stack_block,
            solver_block,
            output_block,
        ]
    )

    flp_n_slots = n_slots if transient else 1
    files = {"stack.stk": stk_text}
    for layer in geometry:
        name = layer["name"]
        power_w = power_spec.get(name)
        flp_text = build_floorplan_file(footprint_mm, power_w, n_slots=flp_n_slots)
        flp_name = f"{name}.flp" if name in power_spec else f"{name}_nopower.flp"
        files[flp_name] = flp_text

    return files
