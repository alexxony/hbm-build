"""HBM2E 8-Hi 레이어 스택을 Icepak(PyAEDT) 입력 스펙으로 변환하는 순수 로직 모듈.

이 모듈은 AEDT/PyAEDT에 의존하지 않는다 (pyaedt import 없음) — WSL 등
AEDT가 없는 환경에서도 전부 테스트 가능하도록 지오메트리/전력/재료 스펙 계산만
담당한다. 실제 Icepak 모델 생성은 scripts/build_icepak_model.py 에서 이 스펙을
읽어 pyaedt 호출로 옮긴다.
"""
from __future__ import annotations

from hbm_thermal.homogenize import layer_stack_hbm2e

_UM_TO_MM = 1e-3

# 레이어명이 어느 다이 그룹에 속하는지 판별하는 접두어.
_BASE_DIE_NAME = "base_die"
_TOP_DIE_NAME = "top_die"
_DRAM_DIE_PREFIX = "dram_die"

# --- P3 T1: base die 블록별 전력맵(MHS) ---
#
# base_die를 x방향 3분할한 블록명. footprint x방향으로만 분할하고
# y·z(풋프린트 전폭, 두께)는 기존 base_die box와 동일하게 공유한다.
BASE_DIE_PHY_NAME = "base_die_phy"
BASE_DIE_TSVA_NAME = "base_die_tsva"
BASE_DIE_DA_NAME = "base_die_da"
BASE_DIE_BLOCK_NAMES = (BASE_DIE_PHY_NAME, BASE_DIE_TSVA_NAME, BASE_DIE_DA_NAME)

# base die 블록 폭 비율(x방향, PHY:TSVA:DA 순). **출처 없는 가정** —
# 특허(US11599458·US11232029, Intel US11854935B2)는 PHY(에지 띠)/TSVA(중앙)/
# DA(반대편 에지 띠) 3분할 배치의 위치 관계만 확립하며, 정확한 면적비는
# TechInsights 등 유료 리포트 영역이라 공개 1차 소스가 없다
# (vault research/06-base-die-power-map.md §3). 합은 1.0이어야 한다.
BASE_DIE_BLOCK_WIDTH_FRACTIONS = {
    BASE_DIE_PHY_NAME: 0.20,
    BASE_DIE_TSVA_NAME: 0.65,
    BASE_DIE_DA_NAME: 0.15,
}

# base die 블록별 전력 배분 시나리오 (PHY, TSVA, DA 비율 순). 각 시나리오는
# base_power_w(= total_w * base_die_fraction)를 3블록에 분배하는 가정이며,
# docs/07-p3-power-map-design.md §1.2에서 사전 등록한 민감도 스윕이다.
# 공개 1차 소스가 없는 가정값 — 단일 확정값 대신 3종 스윕으로 처리한다.
POWER_SCENARIOS = {
    # 면적 비례 배분 — 균일(단일 base_die) 배분과 물리적으로 등가.
    # 회귀 게이트: 이 시나리오는 기존 단일 base_die 배분과 총합이 같아야 한다.
    "s0_uniform": (0.20, 0.65, 0.15),
    # 문헌 방향성(PHY+로직 우세)을 완만하게 반영한 가정.
    "s1_phy_moderate": (0.50, 0.40, 0.10),
    # PHY 집중 극단 — 민감도 상한 가정.
    "s2_phy_heavy": (0.70, 0.25, 0.05),
}


def build_geometry_spec(
    stack: list[dict] | None = None,
    footprint_mm: tuple[float, float] = (11.0, 10.0),
    power_scenario: str | None = None,
) -> list[dict]:
    """레이어 스택을 Icepak box 지오메트리 스펙 목록으로 변환한다.

    각 레이어는 스택 순서대로 z 방향으로 쌓이며, z=0을 최하단(base_die 하부면)
    으로 두고 누적 두께만큼 위로 쌓아 올린다. footprint(x, y)는 모든 레이어에
    동일하게 적용한다 (HBM2E 다이는 동일 풋프린트로 정렬되는 것으로 근사).

    power_scenario가 None이면 기존 동작을 완전히 보존한다(base_die가 단일
    box). power_scenario에 POWER_SCENARIOS 키를 넘기면 base_die 단일 box
    대신 BASE_DIE_BLOCK_WIDTH_FRACTIONS 비율로 x방향 3분할한 sub-box
    (base_die_phy/tsva/da)를 생성한다 — 같은 z 슬라이스(z_cursor 누적은
    base_die 전체 두께만큼 한 번만 전진), 같은 재료·두께를 공유하고 x
    오프셋·폭만 분배한다(P3 T1). power_scenario 값 자체는 지오메트리
    분할에 영향을 주지 않는다(폭 비율은 항상 BASE_DIE_BLOCK_WIDTH_FRACTIONS
    고정) — build_power_spec()과 시나리오 키를 맞추기 위한 스위치일 뿐이다.

    Args:
        stack: layer_stack_hbm2e() 형식의 레이어 dict 목록. None이면 기본 스택 사용.
        footprint_mm: (x, y) 다이 풋프린트 크기 (mm). 기본값은 HBM2E급 11×10 mm.
        power_scenario: POWER_SCENARIOS 키. None이면 base_die 단일 box(기존
            동작, 하위 호환). 지정 시 base_die를 x방향 3 sub-box로 분할.

    Returns:
        레이어별 dict 목록. 각 dict:
            {name, origin_mm: [x, y, z], size_mm: [dx, dy, dz], material_name}
        z, dz는 µm 누적을 mm로 변환한 값. power_scenario 지정 시 base_die
        항목이 base_die_phy/base_die_tsva/base_die_da 3개로 대체된다.

    Raises:
        ValueError: power_scenario가 POWER_SCENARIOS에 없는 키인 경우.
    """
    if stack is None:
        stack = layer_stack_hbm2e()
    if power_scenario is not None and power_scenario not in POWER_SCENARIOS:
        raise ValueError(
            f"알 수 없는 power_scenario: {power_scenario!r} "
            f"(사용 가능: {sorted(POWER_SCENARIOS)})"
        )

    footprint_x_mm, footprint_y_mm = footprint_mm
    geometry: list[dict] = []
    z_cursor_um = 0.0

    for layer in stack:
        thickness_um = layer["thickness_um"]
        z_origin_mm = z_cursor_um * _UM_TO_MM
        size_z_mm = thickness_um * _UM_TO_MM
        material_name = _material_name_for_layer(layer)

        if power_scenario is not None and layer["name"] == _BASE_DIE_NAME:
            x_cursor_mm = 0.0
            for block_name in BASE_DIE_BLOCK_NAMES:
                width_frac = BASE_DIE_BLOCK_WIDTH_FRACTIONS[block_name]
                block_width_mm = footprint_x_mm * width_frac
                geometry.append(
                    {
                        "name": block_name,
                        "origin_mm": [x_cursor_mm, 0.0, z_origin_mm],
                        "size_mm": [block_width_mm, footprint_y_mm, size_z_mm],
                        "material_name": material_name,
                    }
                )
                x_cursor_mm += block_width_mm
        else:
            geometry.append(
                {
                    "name": layer["name"],
                    "origin_mm": [0.0, 0.0, z_origin_mm],
                    "size_mm": [footprint_x_mm, footprint_y_mm, size_z_mm],
                    "material_name": material_name,
                }
            )

        z_cursor_um += thickness_um

    return geometry


def _material_name_for_layer(layer: dict) -> str:
    """레이어의 물성(k_xy, k_z)에 대응하는 재료명을 결정한다.

    동일 물성(같은 k_xy, k_z 조합)을 갖는 레이어는 같은 재료명을 공유하도록
    "역할 기반" 이름(tsv_die, bump_layer, top_die, EMC)을 사용한다 — base_die와
    dram_die는 동일한 TSV 균질화 물성을 가지므로 같은 재료를 재사용한다.
    """
    name = layer["name"]
    if name == _BASE_DIE_NAME or name.startswith(_DRAM_DIE_PREFIX):
        return "hbm_tsv_die_mat"
    if name.startswith("bump_layer"):
        return "hbm_bump_mat"
    if name == _TOP_DIE_NAME:
        return "hbm_top_die_mat"
    if name == "EMC":
        return "hbm_emc_mat"
    raise ValueError(f"알 수 없는 레이어명: {name!r}")


def build_material_spec(stack: list[dict] | None = None) -> dict:
    """레이어 스택으로부터 재료명 -> 이방성 열전도율 + 체적 열용량 dict를 만든다.

    같은 역할(재료명)을 갖는 레이어들은 물성이 동일해야 하며, 그렇지 않으면
    ValueError를 낸다 (균질화 가정이 깨졌다는 신호).

    Args:
        stack: layer_stack_hbm2e() 형식의 레이어 dict 목록. None이면 기본 스택 사용.

    Returns:
        재료명 -> {"k_x": float, "k_y": float, "k_z": float, "rho_cp": float} dict.
        k_x == k_y == 레이어의 k_xy (면내 등방 가정), k_z는 레이어의 k_z,
        rho_cp는 레이어의 체적 열용량(J/m³·K, T1 hbm_thermal.homogenize 균질화 값 —
        3D-ICE placeholder가 아닌 실값. P2 T3 export_3dice.py transient 확장에 사용).
    """
    if stack is None:
        stack = layer_stack_hbm2e()

    materials: dict[str, dict] = {}
    for layer in stack:
        mat_name = _material_name_for_layer(layer)
        props = {
            "k_x": layer["k_xy"],
            "k_y": layer["k_xy"],
            "k_z": layer["k_z"],
            "rho_cp": layer["rho_cp"],
        }
        if mat_name in materials:
            existing = materials[mat_name]
            if existing != props:
                raise ValueError(
                    f"재료 {mat_name!r}에 서로 다른 물성이 매핑됨: "
                    f"{existing} vs {props} (레이어={layer['name']!r})"
                )
        else:
            materials[mat_name] = props

    return materials


def build_power_spec(
    stack: list[dict] | None = None,
    total_w: float = 16.0,
    base_die_fraction: float = 0.55,
    power_scenario: str | None = None,
) -> dict:
    """총 발열량을 base_die와 DRAM die(dram_die_1~N + top_die)에 배분한다.

    근거: HBM 열해석 문헌에서 base die(로직/PHY 다이)가 최대 발열원이라는
    결론(vault research/02-hbm-structure.md)에 따라 base_die에 큰 비중을 할당하고,
    나머지는 DRAM 스택(dram_die_1..N + top_die)에 균등 배분한다.
    정확한 배분 비율은 문헌상 특정되지 않아 파라미터(base_die_fraction)로 노출한다.

    stack을 넘기면 다이 이름 목록을 stack에서 직접 도출한다(Task 5 #1 스택
    높이 파라미터 스터디 — n_dram_dies가 다른 layer_stack_hbm2e() 결과를 그대로
    전달하면 4/8/12-Hi 등 어떤 다이 수에도 자동으로 맞춰 배분한다). stack이
    None이면 기존 동작(8-Hi 고정, dram_die_1..7 + top_die)을 그대로 유지한다.

    power_scenario가 None이면 기존 동작을 완전히 보존한다(base_die가 단일
    키). power_scenario에 POWER_SCENARIOS 키(예: "s0_uniform")를 넘기면
    base_die 키 대신 base_die_phy/base_die_tsva/base_die_da 3키로
    base_power_w를 해당 시나리오 비율대로 분배한다(P3 T1, MHS 블록별
    전력맵 — docs/07-p3-power-map-design.md §1.2). "s0_uniform"은 블록
    폭 비율(BASE_DIE_BLOCK_WIDTH_FRACTIONS)과 동일한 면적 비례 배분으로,
    기존 단일 base_die 배분과 물리적으로 등가다(총합 불변, 블록 합=base_power_w).

    Args:
        stack: layer_stack_hbm2e() 형식의 레이어 dict 목록. None이면 기본
            8-Hi 스택(dram_die_1..7 + top_die)으로 배분.
        total_w: 스택 총 발열량 (W). 기본 16.0 W (문헌 범위 15~20 W 대표값).
        base_die_fraction: base_die가 차지하는 전력 비율. 기본 0.55.
        power_scenario: POWER_SCENARIOS 키. None이면 base_die 단일 키(기존
            동작, 하위 호환). 지정 시 base_die_phy/tsva/da 3키로 분배.

    Returns:
        레이어명 -> 전력(W) dict. power_scenario=None: base_die + dram_die_1..N
        + top_die. power_scenario 지정 시: base_die_phy/tsva/da + dram_die_1..N
        + top_die. 합계는 total_w와 일치 (부동소수 오차 허용).

    Raises:
        ValueError: base_die_fraction이 [0, 1] 범위를 벗어나는 경우,
            또는 power_scenario가 POWER_SCENARIOS에 없는 키인 경우.
    """
    if not (0.0 <= base_die_fraction <= 1.0):
        raise ValueError(
            f"base_die_fraction은 [0, 1] 범위여야 합니다 (입력값={base_die_fraction})."
        )
    if power_scenario is not None and power_scenario not in POWER_SCENARIOS:
        raise ValueError(
            f"알 수 없는 power_scenario: {power_scenario!r} "
            f"(사용 가능: {sorted(POWER_SCENARIOS)})"
        )

    base_power_w = total_w * base_die_fraction
    remaining_w = total_w - base_power_w

    if stack is None:
        # 기존 동작 회귀 방지: stack 미지정 시 8-Hi 고정(dram_die_1..7 + top_die).
        dram_die_names = [f"dram_die_{i}" for i in range(1, 8)] + [_TOP_DIE_NAME]
    else:
        dram_die_names = [
            layer["name"]
            for layer in stack
            if layer["name"] == _TOP_DIE_NAME or layer["name"].startswith(_DRAM_DIE_PREFIX)
        ]

    n_dram_dies = len(dram_die_names)
    per_die_power_w = remaining_w / n_dram_dies

    power_spec: dict[str, float] = {}
    if power_scenario is None:
        power_spec[_BASE_DIE_NAME] = base_power_w
    else:
        phy_frac, tsva_frac, da_frac = POWER_SCENARIOS[power_scenario]
        power_spec[BASE_DIE_PHY_NAME] = base_power_w * phy_frac
        power_spec[BASE_DIE_TSVA_NAME] = base_power_w * tsva_frac
        power_spec[BASE_DIE_DA_NAME] = base_power_w * da_frac

    for name in dram_die_names:
        power_spec[name] = per_die_power_w

    return power_spec


def total_stack_height_mm(geometry: list[dict]) -> float:
    """지오메트리 스펙으로부터 스택 총 높이(mm)를 계산한다."""
    return sum(layer["size_mm"][2] for layer in geometry)
