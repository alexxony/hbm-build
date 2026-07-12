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


def build_geometry_spec(
    stack: list[dict] | None = None,
    footprint_mm: tuple[float, float] = (11.0, 10.0),
) -> list[dict]:
    """레이어 스택을 Icepak box 지오메트리 스펙 목록으로 변환한다.

    각 레이어는 스택 순서대로 z 방향으로 쌓이며, z=0을 최하단(base_die 하부면)
    으로 두고 누적 두께만큼 위로 쌓아 올린다. footprint(x, y)는 모든 레이어에
    동일하게 적용한다 (HBM2E 다이는 동일 풋프린트로 정렬되는 것으로 근사).

    Args:
        stack: layer_stack_hbm2e() 형식의 레이어 dict 목록. None이면 기본 스택 사용.
        footprint_mm: (x, y) 다이 풋프린트 크기 (mm). 기본값은 HBM2E급 11×10 mm.

    Returns:
        레이어별 dict 목록. 각 dict:
            {name, origin_mm: [x, y, z], size_mm: [dx, dy, dz], material_name}
        z, dz는 µm 누적을 mm로 변환한 값.
    """
    if stack is None:
        stack = layer_stack_hbm2e()

    footprint_x_mm, footprint_y_mm = footprint_mm
    geometry: list[dict] = []
    z_cursor_um = 0.0

    for layer in stack:
        thickness_um = layer["thickness_um"]
        origin_mm = [0.0, 0.0, z_cursor_um * _UM_TO_MM]
        size_mm = [footprint_x_mm, footprint_y_mm, thickness_um * _UM_TO_MM]
        geometry.append(
            {
                "name": layer["name"],
                "origin_mm": origin_mm,
                "size_mm": size_mm,
                "material_name": _material_name_for_layer(layer),
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
    """레이어 스택으로부터 재료명 -> 이방성 열전도율 dict를 만든다.

    같은 역할(재료명)을 갖는 레이어들은 물성이 동일해야 하며, 그렇지 않으면
    ValueError를 낸다 (균질화 가정이 깨졌다는 신호).

    Args:
        stack: layer_stack_hbm2e() 형식의 레이어 dict 목록. None이면 기본 스택 사용.

    Returns:
        재료명 -> {"k_x": float, "k_y": float, "k_z": float} dict.
        k_x == k_y == 레이어의 k_xy (면내 등방 가정), k_z는 레이어의 k_z.
    """
    if stack is None:
        stack = layer_stack_hbm2e()

    materials: dict[str, dict] = {}
    for layer in stack:
        mat_name = _material_name_for_layer(layer)
        props = {"k_x": layer["k_xy"], "k_y": layer["k_xy"], "k_z": layer["k_z"]}
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


def build_power_spec(total_w: float = 16.0, base_die_fraction: float = 0.55) -> dict:
    """총 발열량을 base_die와 DRAM die(dram_die_1~7 + top_die)에 배분한다.

    근거: HBM 열해석 문헌에서 base die(로직/PHY 다이)가 최대 발열원이라는
    결론(vault research/02-hbm-structure.md)에 따라 base_die에 큰 비중을 할당하고,
    나머지는 DRAM 스택 8장(dram_die_1..7 + top_die)에 균등 배분한다.
    정확한 배분 비율은 문헌상 특정되지 않아 파라미터(base_die_fraction)로 노출한다.

    Args:
        total_w: 스택 총 발열량 (W). 기본 16.0 W (문헌 범위 15~20 W 대표값).
        base_die_fraction: base_die가 차지하는 전력 비율. 기본 0.55.

    Returns:
        레이어명 -> 전력(W) dict. base_die + dram_die_1..7 + top_die = 8개 항목.
        합계는 total_w와 일치 (부동소수 오차 허용).

    Raises:
        ValueError: base_die_fraction이 [0, 1] 범위를 벗어나는 경우.
    """
    if not (0.0 <= base_die_fraction <= 1.0):
        raise ValueError(
            f"base_die_fraction은 [0, 1] 범위여야 합니다 (입력값={base_die_fraction})."
        )

    base_power_w = total_w * base_die_fraction
    remaining_w = total_w - base_power_w

    # DRAM 다이 8장 = dram_die_1..7 (7장) + top_die (1장), 균등 배분.
    dram_die_names = [f"dram_die_{i}" for i in range(1, 8)] + [_TOP_DIE_NAME]
    n_dram_dies = len(dram_die_names)
    per_die_power_w = remaining_w / n_dram_dies

    power_spec: dict[str, float] = {_BASE_DIE_NAME: base_power_w}
    for name in dram_die_names:
        power_spec[name] = per_die_power_w

    return power_spec


def total_stack_height_mm(geometry: list[dict]) -> float:
    """지오메트리 스펙으로부터 스택 총 높이(mm)를 계산한다."""
    return sum(layer["size_mm"][2] for layer in geometry)
