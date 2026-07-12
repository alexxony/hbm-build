"""HBM2E 8-Hi 스택 균질화 유효 열전도율 계산 핵심 모듈.

레이어 내부에 서로 다른 물질(예: Si 매트릭스 + Cu TSV)이 섞여 있을 때,
수직(z, 스택 적층 방향) 및 면내(xy, 다이 평면 방향) 유효 열전도율을
균질화 모델로 근사한다.
"""
import math

from hbm_thermal.materials import (
    K_CU,
    K_EMC,
    K_SI,
    K_SIO2,
    K_SOLDER,
    K_UNDERFILL,
)

_FRACTION_SUM_TOLERANCE = 1e-6


def k_z_mixing(fractions: dict[str, float], k_values: dict[str, float]) -> float:
    """수직 방향 부피가중 혼합법칙(rule of mixtures).

    k_z = Σ f_i · k_i

    적층 방향(z)은 각 물질이 직렬이 아니라 전열 경로상 병렬로 놓인
    관통형 구조(예: Si 매트릭스를 관통하는 Cu TSV)에 대한 근사이며,
    부피분율 가중 평균으로 계산한다.

    Args:
        fractions: 물질명 -> 부피분율. 합이 1 ± 1e-6이어야 함.
        k_values: 물질명 -> 열전도율(W/m·K). fractions와 동일한 키 집합.

    Returns:
        유효 수직 열전도율 k_z (W/m·K).

    Raises:
        ValueError: fractions의 합이 1 ± 1e-6을 벗어나는 경우.
    """
    total = sum(fractions.values())
    if abs(total - 1.0) > _FRACTION_SUM_TOLERANCE:
        raise ValueError(
            f"fractions 합이 1이 아닙니다 (합={total}). 1 ± {_FRACTION_SUM_TOLERANCE} 범위여야 함."
        )
    return sum(f * k_values[name] for name, f in fractions.items())


def k_xy_hasselman_johnson(
    k_matrix: float, k_inclusion: float, volume_fraction: float
) -> float:
    """면내 방향 Hasselman-Johnson/Maxwell-Eucken형 2D 복합재 유효 전도율.

    원통형 개재물(예: TSV, µbump)이 매트릭스 내에 분산된 2D 단면에 대한
    근사식이며, 계면 열저항은 무시하는 단순형이다:

        k_eff = k_m · [(k_i + k_m + f·(k_i − k_m)) / (k_i + k_m − f·(k_i − k_m))]

    Args:
        k_matrix: 매트릭스(연속상) 열전도율 (W/m·K).
        k_inclusion: 개재물(분산상) 열전도율 (W/m·K).
        volume_fraction: 개재물의 면적(부피)분율 f. [0, 0.9] 범위.

    Returns:
        유효 면내 열전도율 k_xy (W/m·K).

    Raises:
        ValueError: volume_fraction이 [0, 0.9] 범위를 벗어나는 경우.
    """
    if not (0.0 <= volume_fraction <= 0.9):
        raise ValueError(
            f"volume_fraction은 [0, 0.9] 범위여야 합니다 (입력값={volume_fraction})."
        )
    km, ki, f = k_matrix, k_inclusion, volume_fraction
    numerator = ki + km + f * (ki - km)
    denominator = ki + km - f * (ki - km)
    return km * (numerator / denominator)


# --- HBM2E 8-Hi 레이어 스택 기하 가정 -------------------------------------
# TSV: 지름 5.5 µm, pitch 48 µm, 정방 배열 가정
#   f_Cu = π·(d/2)^2 / pitch^2
_TSV_DIAMETER_UM = 5.5
_TSV_PITCH_UM = 48.0
_F_CU_TSV = math.pi * (_TSV_DIAMETER_UM / 2) ** 2 / _TSV_PITCH_UM**2  # ≈ 0.0103

# µbump: 지름 25 µm, 높이 20 µm, pitch 55 µm, staggered 배열 가정
#   f_solder = π·(d/2)^2 / pitch^2 (staggered 배열도 단위셀 면적 pitch^2로 근사)
_BUMP_DIAMETER_UM = 25.0
_BUMP_HEIGHT_UM = 20.0
_BUMP_PITCH_UM = 55.0
_F_SOLDER_BUMP = math.pi * (_BUMP_DIAMETER_UM / 2) ** 2 / _BUMP_PITCH_UM**2  # ≈ 0.1623

_DRAM_DIE_THICKNESS_UM = 45.0
_BASE_DIE_THICKNESS_UM = 60.0
_TOP_DIE_THICKNESS_UM = 45.0
_EMC_THICKNESS_UM = 100.0
_N_DRAM_DIES = 7  # 8-Hi = base 1 + DRAM 7 (top 포함 8층 다이 스택 중 base 제외)


def _tsv_die_layer(name: str, thickness_um: float) -> dict:
    """TSV를 포함하는 Si 다이 층(base_die 또는 dram_die)의 균질화 물성 계산.

    k_z: 혼합법칙 (Cu f_Cu + Si 나머지). TSV 라이너(SiO2)는 두께가 매우 얇아
    (통상 서브미크론) 부피분율이 무시 가능한 수준이므로 생략함.
    k_xy: Hasselman-Johnson (매트릭스 Si, 개재물 Cu).
    """
    fractions = {"Cu": _F_CU_TSV, "Si": 1.0 - _F_CU_TSV}
    k_values = {"Cu": K_CU, "Si": K_SI}
    k_z = k_z_mixing(fractions, k_values)
    k_xy = k_xy_hasselman_johnson(k_matrix=K_SI, k_inclusion=K_CU, volume_fraction=_F_CU_TSV)
    return {
        "name": name,
        "thickness_um": thickness_um,
        "k_xy": k_xy,
        "k_z": k_z,
        "근거": (
            "TSV 함유 Si 다이: k_z=혼합법칙(Cu TSV f≈0.0103 + Si 나머지, "
            "SiO2 라이너는 두께 무시 가능 수준이라 생략), "
            "k_xy=Hasselman-Johnson(매트릭스 Si, 개재물 Cu, f≈0.0103)"
        ),
    }


def _bump_layer(name: str) -> dict:
    """µbump + underfill 층의 균질화 물성 계산.

    k_z: 혼합법칙 (solder f + underfill 나머지).
    k_xy: Hasselman-Johnson (매트릭스 underfill, 개재물 solder).
    """
    fractions = {"solder": _F_SOLDER_BUMP, "underfill": 1.0 - _F_SOLDER_BUMP}
    k_values = {"solder": K_SOLDER, "underfill": K_UNDERFILL}
    k_z = k_z_mixing(fractions, k_values)
    k_xy = k_xy_hasselman_johnson(
        k_matrix=K_UNDERFILL, k_inclusion=K_SOLDER, volume_fraction=_F_SOLDER_BUMP
    )
    return {
        "name": name,
        "thickness_um": _BUMP_HEIGHT_UM,
        "k_xy": k_xy,
        "k_z": k_z,
        "근거": (
            "µbump 층: k_z=혼합법칙(solder f≈0.1623 + underfill 나머지), "
            "k_xy=Hasselman-Johnson(매트릭스 underfill, 개재물 solder, f≈0.1623), "
            "staggered 배열을 pitch^2 단위셀 면적으로 근사"
        ),
    }


def layer_stack_hbm2e() -> list[dict]:
    """HBM2E 8-Hi 스택의 기본 레이어 구성을 반환한다.

    구성: base_die(TSV 함유 Si) / [bump_layer + dram_die(TSV 함유)] × 7
          / top_die(TSV 없음 Si) / EMC
    총 17개 레이어 (1 + 7*2 + 1 + 1).

    Returns:
        레이어별 dict 목록. 각 dict: {name, thickness_um, k_xy, k_z, 근거}.
    """
    layers: list[dict] = []

    layers.append(_tsv_die_layer("base_die", _BASE_DIE_THICKNESS_UM))

    for i in range(1, _N_DRAM_DIES + 1):
        layers.append(_bump_layer(f"bump_layer_{i}"))
        layers.append(_tsv_die_layer(f"dram_die_{i}", _DRAM_DIE_THICKNESS_UM))

    layers.append(
        {
            "name": "top_die",
            "thickness_um": _TOP_DIE_THICKNESS_UM,
            "k_xy": K_SI,
            "k_z": K_SI,
            "근거": "최상단 다이는 TSV 없음 → 순수 Si 벌크값 사용",
        }
    )

    layers.append(
        {
            "name": "EMC",
            "thickness_um": _EMC_THICKNESS_UM,
            "k_xy": K_EMC,
            "k_z": K_EMC,
            "근거": "몰딩 컴파운드, 등방성 벌크값 사용",
        }
    )

    return layers


def total_stack_height_um(layers: list[dict]) -> float:
    """레이어 스택의 총 높이(µm)를 계산한다."""
    return sum(layer["thickness_um"] for layer in layers)
