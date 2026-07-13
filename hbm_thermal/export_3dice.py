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


def build_materials_block(material_spec: dict) -> str:
    """재료명 -> {k_x, k_y, k_z} dict로부터 3D-ICE material 블록 텍스트를 만든다.

    volumetric heat capacity는 steady-state 해석에는 사용되지 않지만 3D-ICE
    문법상 material 블록에 필수이므로, 물리적으로 타당한 대표값(Si 벌크
    1.628e-12 J/(µm³·K), 3D-ICE 공식 예제 example_steady.stk 값)을 모든
    재료에 공통 적용한다. steady-state 해에는 영향 없음(과도항에만 사용).

    Args:
        material_spec: build_material_spec() 결과.

    Returns:
        3D-ICE .stk material 블록 전체 텍스트.
    """
    # 근거: example_steady.stk의 SILICON VHC 값. steady 해석에서 열용량은
    # 해에 영향을 주지 않으므로(정상상태 방정식에 시간미분항 없음) 공통값 사용.
    vhc_placeholder = 1.628e-12

    blocks = []
    for mat_name, props in material_spec.items():
        mat_id = _material_id_for_layer_name(mat_name)
        kx = conductivity_w_mk_to_3dice(props["k_x"])
        ky = conductivity_w_mk_to_3dice(props["k_y"])
        kz = conductivity_w_mk_to_3dice(props["k_z"])
        blocks.append(
            f"material {mat_id} :\n"
            f"   thermal conductivity     {kx:.6e}, {ky:.6e}, {kz:.6e} ;\n"
            f"   volumetric heat capacity {vhc_placeholder:.6e} ;\n"
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


def build_floorplan_file(footprint_mm: tuple[float, float], power_w: float | None) -> str:
    """단일 사각형 영역 floorplan(.flp) 텍스트를 만든다.

    Args:
        footprint_mm: (x, y) 다이 풋프린트 (mm).
        power_w: 이 레이어의 전력(W). None이면 0W(비전력 레이어, layer 다이용).

    Returns:
        3D-ICE .flp 파일 전체 텍스트.
    """
    x_um = footprint_mm[0] * 1000.0
    y_um = footprint_mm[1] * 1000.0
    power = power_w if power_w is not None else 0.0
    return (
        "Whole :\n"
        "   position 0, 0 ;\n"
        f"   dimension {x_um:.4f}, {y_um:.4f} ;\n"
        f"   power values {power:.6f} ;\n"
    )


def build_output_block(die_names: list[str]) -> str:
    """die별 평균/최대 온도를 파일로 export하는 output 블록을 만든다.

    Args:
        die_names: 온도를 추출할 die 이름 목록 (stack의 die 인스턴스명, die_ 접두어 아님).

    Returns:
        3D-ICE .stk output 블록 텍스트.
    """
    lines = ["output:"]
    for name in die_names:
        lines.append(f'   Tflp ( {name}, "{name}_avg.txt", average, final ) ;')
        lines.append(f'   Tflp ( {name}, "{name}_max.txt", maximum, final ) ;')
    return "\n".join(lines) + "\n"


def build_solver_block(ambient_c: float) -> str:
    """steady-state solver 블록을 만든다."""
    temp_k = celsius_to_kelvin(ambient_c)
    return (
        "solver:\n"
        "   steady ;\n"
        f"   initial temperature {temp_k:.4f} ;\n"
        "   numofcores 1 ;\n"
    )


def build_stack_description(
    footprint_mm: tuple[float, float] = (11.0, 10.0),
    total_power_w: float = 16.0,
    base_die_fraction: float = 0.55,
    ambient_c: float = 40.0,
    htc_w_m2k: float = 2500.0,
) -> dict[str, str]:
    """전체 .stk 파일 + 레이어별 .flp 파일 텍스트를 한 번에 생성한다.

    Icepak(build_icepak_model.py)과 동일한 기본 경계조건을 사용해 교차검증
    대상이 동등 조건이 되도록 한다: base_die 8.8W + DRAM die 8장 각 0.9W(=16W),
    ambient 40°C, 상단 HTC 2500 W/m²K, 전도 전용.

    Args:
        footprint_mm: (x, y) 다이 풋프린트 (mm).
        total_power_w: 스택 총 발열량 (W).
        base_die_fraction: base_die 전력 비율.
        ambient_c: 주변 온도 (°C).
        htc_w_m2k: 히트싱크 HTC (W/m²K).

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
    output_block = build_output_block(die_names_in_stack_order)
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

    files = {"stack.stk": stk_text}
    for layer in geometry:
        name = layer["name"]
        power_w = power_spec.get(name)
        flp_text = build_floorplan_file(footprint_mm, power_w)
        flp_name = f"{name}.flp" if name in power_spec else f"{name}_nopower.flp"
        files[flp_name] = flp_text

    return files
