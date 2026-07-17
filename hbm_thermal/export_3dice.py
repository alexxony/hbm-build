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

from hbm_thermal.model_config import (
    BASE_DIE_BLOCK_NAMES,
    build_geometry_spec,
    build_material_spec,
    build_power_spec,
)

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

# P3 T5 — power_scenario 모드(base_die 블록별 전력맵) 전용 격자 해상도.
# 기본 4분할(cell 2750x2500um)은 가장 좁은 PHY 띠(폭 비율 0.20 -> 11000um*0.20
# =2200um)보다 셀이 커서(2750um) PHY 띠 내부에 셀 경계가 하나도 들어가지
# 않는다 — element별 전력이 걸린 셀과 아닌 셀이 뭉개져 3D-ICE의 uniform grid
# 열용량 분배가 왜곡된다(T3 오매핑 사고의 2차 원인, docs 07 §T5 참고). PHY
# 띠에 최소 4셀이 들어가도록 20x20 분할(cell 550x500um)로 세분화한다 —
# 3D-ICE는 전 레이어 공통 uniform grid라 이 해상도가 스택 전체에 적용된다.
_SCENARIO_CELL_DIVISIONS = 20


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


def build_heat_sink_block(
    htc_w_m2k: float, ambient_c: float, bottom_htc_w_m2k: float | None = None
) -> str:
    """히트싱크 근사 BC 블록을 만든다 (Icepak assign_stationary_wall_with_htc와 등가).

    P4 T2 — bottom_htc_w_m2k가 지정되면 하단(비 heatsink측) 냉각 BC도 함께
    출력한다. 3D-ICE 문법(bison/stack_description_parser.y)의 heatsink_opt
    규칙이 ``topsink``, ``bottomsink``, ``topsink bottomsink`` 조합을 전부
    허용하고, bottomsink 규칙(``BOTTOM HEAT SINK ':' HEAT TRANSFER
    COEFFICIENT DVALUE ';' TEMPERATURE DVALUE ';'``)이 topsink와 완전히
    대칭 구조임을 실측 확인(R1 판정: 하단 냉각 BC 지원). None(기본)이면
    기존 top-only 동작 그대로 — 회귀 방지.

    Args:
        htc_w_m2k: 상단 히트싱크 HTC (W/m²K).
        ambient_c: 주변 온도 (°C, top/bottom 공통).
        bottom_htc_w_m2k: 하단 히트싱크 HTC (W/m²K). None이면 top-only
            (기존 동작 무변경).

    Returns:
        3D-ICE .stk heat sink 블록 텍스트 (top 단독 또는 top+bottom).
    """
    htc_3dice = htc_w_m2k_to_3dice(htc_w_m2k)
    temp_k = celsius_to_kelvin(ambient_c)
    text = (
        "top heat sink :\n"
        f"   heat transfer coefficient {htc_3dice:.6e} ;\n"
        f"   temperature               {temp_k:.4f} ;\n"
    )
    if bottom_htc_w_m2k is not None:
        bottom_htc_3dice = htc_w_m2k_to_3dice(bottom_htc_w_m2k)
        text += (
            "\nbottom heat sink :\n"
            f"   heat transfer coefficient {bottom_htc_3dice:.6e} ;\n"
            f"   temperature               {temp_k:.4f} ;\n"
        )
    return text


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


# P3 T5 — base_die 블록명(model_config.BASE_DIE_BLOCK_NAMES) -> 3D-ICE
# floorplan element id(짧은 식별자). .flp의 element IDENTIFIER와 Tflpel의
# die.element_id 참조가 이 짧은 이름으로 일치해야 한다(bison/floorplan_parser.y
# "IDENTIFIER ':' ic_elements optional_power_values_list" 문법 확인,
# bison/stack_description_parser.y의 "TFLPEL '(' IDENTIFIER '.' IDENTIFIER ..."
# 문법이 <die_id>.<floorplan_element_id> 형식을 요구함을 실측 확인).
_BASE_DIE_ELEMENT_IDS = {
    "base_die_phy": "phy",
    "base_die_tsva": "tsva",
    "base_die_da": "da",
}


def build_multi_element_floorplan_file(
    footprint_mm: tuple[float, float], blocks: list[dict]
) -> str:
    """base_die 하나의 .flp에 블록별 named element 여러 개를 기입한다.

    3D-ICE .flp 문법(bison/floorplan_parser.y)은 "IDENTIFIER ':' ic_elements
    optional_power_values_list" 형태의 element를 파일 하나에 여러 개 나열
    가능하다(3D-ICE 공식 예제 bin/core.flp에서 Core0~7, Cache0/1, CLK, FPU,
    CrossBar 등 15개 element가 한 .flp에 공존하는 것으로 실측 확인) — 따라서
    P3 설계 문서(docs/07-p3-power-map-design.md) §3 리스크1이 우려한 "die당
    element 1개" 가정은 틀렸다. T3가 만든 "sub-box마다 독립 die" 우회는
    각 die가 전체 footprint(11000x10000um)의 .flp를 갖게 되어 블록이 실제로는
    전체 풋프린트로 겹쳐 쌓이는 오매핑을 낳았다(base_die 60um가 3층 180um로
    적층됨, xy 분할이 z 방향 적층으로 잘못 변환됨) — 이 함수가 정정본이다.

    각 element의 position/dimension은 블록의 실제 origin_mm[0](x 오프셋)과
    size_mm[0](x 폭)에서 가져온다 — y는 풋프린트 전폭 공유(model_config.py
    build_geometry_spec()이 이미 이렇게 분배, x방향 띠 배치).

    Args:
        footprint_mm: (x, y) 다이 풋프린트 (mm) — element의 y 폭에 사용.
        blocks: model_config.build_geometry_spec()이 반환한 base_die_phy/
            tsva/da 3개 항목(dict, origin_mm/size_mm 포함)과 model_config.
            build_power_spec()에서 가져온 해당 전력(W)을 담은
            {"name", "origin_mm", "size_mm", "power_w"} dict 목록.

    Returns:
        3D-ICE .flp 파일 전체 텍스트 (블록마다 하나의 named element).
    """
    _, footprint_y_mm = footprint_mm
    y_um = footprint_y_mm * 1000.0

    parts = []
    for block in blocks:
        name = block["name"]
        element_id = _BASE_DIE_ELEMENT_IDS[name]
        x_offset_um = block["origin_mm"][0] * 1000.0
        width_um = block["size_mm"][0] * 1000.0
        power_w = block["power_w"]
        parts.append(
            f"{element_id} :\n"
            f"   position {x_offset_um:.4f}, 0 ;\n"
            f"   dimension {width_um:.4f}, {y_um:.4f} ;\n"
            f"   power values {power_w:.6f} ;\n"
        )
    return "\n".join(parts)


def build_output_block(
    die_names: list[str],
    transient: bool = False,
    base_die_element_names: list[str] | None = None,
) -> str:
    """die별 평균/최대 온도를 파일로 export하는 output 블록을 만든다.

    Args:
        die_names: 온도를 추출할 die 이름 목록 (stack의 die 인스턴스명, die_ 접두어 아님).
            base_die_element_names가 지정되면 이 목록에서 "base_die"는
            제외해야 한다(호출측 책임, build_stack_description()이 처리) —
            base_die는 die 단위 Tflp 대신 element 단위 Tflpel로 대체되므로.
        transient: True면 매 slot(3D-ICE 문법상 ``, slot`` 인자, bison/
            stack_description_parser.y의 TDICE_OUTPUT_INSTANT_SLOT)마다
            평균 온도를 시계열로 기록한다(τ 피팅용, T3). False(기본, steady)면
            해석 종료 시점(``final``) 값만 기록한다(기존 동작 무변경 — 회귀 방지).
        base_die_element_names: P3 T5 — 지정 시 base_die die에 대해 die
            단위 Tflp 대신 블록별 Tflpel(die.element_id, ...)을 발행한다
            (model_config.BASE_DIE_BLOCK_NAMES 값, 예:
            ["base_die_phy", "base_die_tsva", "base_die_da"]). 문법:
            ``Tflpel ( <die_id>.<element_id>, "path", average|maximum,
            final|slot )`` (bison/stack_description_parser.y 실측 확인,
            die_id는 stack의 die 인스턴스명 — 항상 "base_die", element_id는
            _BASE_DIE_ELEMENT_IDS 매핑값). None(기본)이면 기존 동작 그대로
            (하위 호환, 회귀 방지).

    Returns:
        3D-ICE .stk output 블록 텍스트.
    """
    instant = "average, slot" if transient else "average, final"
    max_instant = "maximum, slot" if transient else "maximum, final"
    lines = ["output:"]
    for name in die_names:
        lines.append(f'   Tflp ( {name}, "{name}_avg.txt", {instant} ) ;')
        lines.append(f'   Tflp ( {name}, "{name}_max.txt", {max_instant} ) ;')
    if base_die_element_names:
        for block_name in base_die_element_names:
            element_id = _BASE_DIE_ELEMENT_IDS[block_name]
            lines.append(
                f'   Tflpel ( base_die.{element_id}, "{block_name}_avg.txt", {instant} ) ;'
            )
            lines.append(
                f'   Tflpel ( base_die.{element_id}, "{block_name}_max.txt", {max_instant} ) ;'
            )
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
    bottom_htc_w_m2k: float | None = None,
    transient: bool = False,
    initial_temperature_c: float | None = None,
    step_time_s: float = 0.01,
    slot_time_s: float = 1.0,
    n_slots: int = 1,
    power_scenario: str | None = None,
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

    power_scenario가 None이면 기존 동작을 완전히 보존한다(base_die 단일
    die, 회귀 방지). POWER_SCENARIOS 키(예: "s0_uniform")를 넘기면
    model_config.build_geometry_spec()/build_power_spec()이 base_die를
    base_die_phy/tsva/da 3개 sub-box(x방향 띠, 동일 z 슬라이스 공유)로
    분할한다(P3 T1, MHS 블록별 전력맵 — docs/07-p3-power-map-design.md §1.3).

    **P3 T3 오매핑 정정(T5)**: T3는 이 3 sub-box를 "3D-ICE die 3개"로 그대로
    매핑했다 — 각 die는 build_floorplan_file()이 만드는 **전체 footprint**
    .flp(position 0,0 / dimension 11000x10000)를 갖게 되어, xy 평면 분할이
    아니라 **z축(수직) 적층**으로 둔갑했다(base_die 60um 1층 대신 60um die
    3개가 쌓여 180um가 됨 — build_stack_description(power_scenario=...) 반환
    dict의 각 base_die_*.flp가 전부 전체 footprint였음, 실측 확인). 3D-ICE
    .flp 문법은 파일 하나에 named element 여러 개를 허용한다(3D-ICE 공식
    예제 bin/core.flp가 Core0~7/Cache0/1/CLK/FPU/CrossBar 15개 element를
    한 파일에 담는 것으로 실측 확인, bison/floorplan_parser.y의
    "IDENTIFIER ':' ic_elements optional_power_values_list" 목록 문법과
    일치) — 이 함수는 이제 base_die_phy/tsva/da geometry 3 엔트리를 **단일
    base_die die(60um, model_config.build_geometry_spec(power_scenario=None)과
    동일 두께)로 병합**하고, 그 하나의 base_die.flp에 블록별 named element
    3개(phy/tsva/da, build_multi_element_floorplan_file())를 기입한다 —
    None 경로(die/stack 구조·두께)와 완전히 동일하게 유지되며 전력 분포만
    x방향으로 세분화된다. die/stack 정의(die_blocks, stack_block)는 항상
    17개 die(None 경로와 동일 층수)를 유지 — power_scenario는 base_die
    floorplan의 내부 구조에만 영향을 준다(리스크1 완전 해소, sub-box를
    독립 die로 만드는 우회 불필요 확인).

    격자 해상도: power_scenario가 지정되면 PHY 띠(폭 비율 최소 0.20 =
    2200um)가 최소 4셀을 확보하도록 _SCENARIO_CELL_DIVISIONS(20분할, cell
    550x500um)를 쓴다 — 기본 4분할(cell 2750x2500um)은 PHY 띠보다 셀이 커서
    element별 전력 분포를 해상할 수 없다(3D-ICE는 전 레이어 공통 uniform
    grid, dimensions: 블록 하나가 스택 전체에 적용). None 경로는 기존
    _DEFAULT_CELL_DIVISIONS(4분할) 그대로 — 회귀 방지.

    Args:
        footprint_mm: (x, y) 다이 풋프린트 (mm).
        total_power_w: 스택 총 발열량 (W).
        base_die_fraction: base_die 전력 비율.
        ambient_c: 주변 온도 (°C) — heat sink 블록의 BC 온도(steady/transient 공통).
        htc_w_m2k: 상단 히트싱크 HTC (W/m²K).
        bottom_htc_w_m2k: 하단 히트싱크 HTC (W/m²K). None(기본)이면 top-only
            (기존 동작 무변경 — 회귀 방지). 지정 시 build_heat_sink_block()이
            bottom heat sink 블록도 함께 발행한다(P4 T2, R1 판정: 3D-ICE
            bison 문법이 bottomsink를 지원 — 위 build_heat_sink_block()
            docstring 참고).
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
        power_scenario: model_config.POWER_SCENARIOS 키. None이면 base_die
            단일 die(기존 동작, 하위 호환). 지정 시 base_die_phy/tsva/da
            3개 die로 분할되고, base_power_w가 해당 시나리오 비율대로
            배분된다(P3 T3). "s0_uniform"은 면적 비례 배분 — 기존 단일
            base_die 배분과 물리적으로 등가라 회귀 게이트로 쓴다.

    Returns:
        {"stack.stk": 텍스트, "<layer>.flp" 또는 "<layer>_nopower.flp": 텍스트, ...} dict.
        키는 파일명, 값은 해당 파일에 쓸 텍스트. power_scenario 지정 시에도
        die/파일 목록은 None 경로와 동일한 17개 층 구조를 유지한다 —
        base_die.flp 하나가 다중 element(phy/tsva/da) .flp로 바뀔 뿐,
        별도 파일로 늘어나지 않는다(T3의 3파일 확장은 오매핑이었음, 위
        docstring 참고).
    """
    scenario_geometry = build_geometry_spec(footprint_mm=footprint_mm, power_scenario=power_scenario)
    material_spec = build_material_spec()
    power_spec = build_power_spec(
        total_w=total_power_w,
        base_die_fraction=base_die_fraction,
        power_scenario=power_scenario,
    )

    if power_scenario is None:
        geometry = scenario_geometry
        base_die_blocks = None
    else:
        # base_die_phy/tsva/da 3 geometry 엔트리를 단일 base_die die로 병합
        # (None 경로와 동일한 die/stack 구조 유지, docstring §"P3 T3 오매핑
        # 정정" 참고). 블록별 origin_mm/size_mm/전력은 별도로 보존해
        # build_multi_element_floorplan_file()에 전달한다.
        geometry = []
        base_die_blocks = []
        base_die_layer_inserted = False
        for layer in scenario_geometry:
            if layer["name"] in BASE_DIE_BLOCK_NAMES:
                block = dict(layer)
                block["power_w"] = power_spec[layer["name"]]
                base_die_blocks.append(block)
                if not base_die_layer_inserted:
                    first_block = base_die_blocks[0]
                    # 병합 die 폭은 footprint_mm[0] 전체(모든 블록이 x방향
                    # 전폭을 채운다는 불변식 — model_config.build_geometry_spec()이
                    # 항상 BASE_DIE_BLOCK_WIDTH_FRACTIONS 합=1.0으로 생성).
                    merged_layer = {
                        "name": "base_die",
                        "origin_mm": [0.0, first_block["origin_mm"][1], first_block["origin_mm"][2]],
                        "size_mm": [
                            footprint_mm[0],
                            first_block["size_mm"][1],
                            first_block["size_mm"][2],
                        ],
                        "material_name": first_block["material_name"],
                    }
                    geometry.append(merged_layer)
                    base_die_layer_inserted = True
            else:
                geometry.append(layer)

    materials_block = build_materials_block(material_spec)
    heat_sink_block = build_heat_sink_block(htc_w_m2k, ambient_c, bottom_htc_w_m2k=bottom_htc_w_m2k)
    cell_divisions = _SCENARIO_CELL_DIVISIONS if power_scenario is not None else _DEFAULT_CELL_DIVISIONS
    dimensions_block = build_dimensions_block(footprint_mm, cell_divisions=cell_divisions)
    if power_scenario is None:
        die_power_spec = power_spec
    else:
        # die_blocks_and_stack()은 die당 source 필요 여부만 판별하면 되므로,
        # 병합된 base_die 키에 base_power_w(3블록 합)를 넣어 "power_spec
        # 판별용" 딕셔너리를 별도로 만든다(die 정의 자체에는 전력값이 없음 —
        # export_3dice.build_die_blocks_and_stack() docstring 참고, 실제
        # 전력은 .flp 쪽 책임이라 이 값 자체는 die_blocks 텍스트에 쓰이지
        # 않는다. 오직 "이 레이어가 power-bearing인가" 판별에만 쓰인다).
        die_power_spec = {k: v for k, v in power_spec.items() if k not in BASE_DIE_BLOCK_NAMES}
        die_power_spec["base_die"] = sum(power_spec[name] for name in BASE_DIE_BLOCK_NAMES)
    die_blocks, stack_block = build_die_blocks_and_stack(geometry, die_power_spec)
    die_names_in_stack_order = [layer["name"] for layer in geometry]
    if power_scenario is None:
        output_die_names = die_names_in_stack_order
        base_die_element_names = None
    else:
        output_die_names = [n for n in die_names_in_stack_order if n != "base_die"]
        base_die_element_names = list(BASE_DIE_BLOCK_NAMES)
    output_block = build_output_block(
        output_die_names, transient=transient, base_die_element_names=base_die_element_names
    )
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
        if power_scenario is not None and name == "base_die":
            # 병합 die는 전력이 다중 element(phy/tsva/da)로 나뉘므로
            # build_floorplan_file()(단일 사각형)이 아니라
            # build_multi_element_floorplan_file()을 쓴다. n_slots>1
            # (transient)은 현재 이 함수가 지원하지 않음 — power_scenario는
            # steady 전용 경로(P3 설계 범위)라 여기서는 강제하지 않되,
            # transient+scenario 조합은 검증되지 않았음을 주석으로 남긴다.
            flp_text = build_multi_element_floorplan_file(footprint_mm, base_die_blocks)
            files["base_die.flp"] = flp_text
            continue
        power_w = power_spec.get(name)
        flp_text = build_floorplan_file(footprint_mm, power_w, n_slots=flp_n_slots)
        flp_name = f"{name}.flp" if name in power_spec else f"{name}_nopower.flp"
        files[flp_name] = flp_text

    return files
