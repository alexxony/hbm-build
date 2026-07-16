"""materials.py 단위 테스트.

물성 상수(k, rho, cp)가 물리적으로 타당한 범위(양수, 대략적인 문헌 범위)에
있는지 검증한다. 값 자체는 문헌/벤더 스펙 인용이므로 정확한 수치 회귀보다는
누락·오타(자릿수 실수 등) 방지에 초점을 둔다.
"""
from hbm_thermal.materials import (
    CP_CU,
    CP_EMC,
    CP_SI,
    CP_SIO2,
    CP_SOLDER,
    CP_UNDERFILL,
    K_CU,
    K_EMC,
    K_SI,
    K_SIO2,
    K_SOLDER,
    K_UNDERFILL,
    RHO_CU,
    RHO_EMC,
    RHO_SI,
    RHO_SIO2,
    RHO_SOLDER,
    RHO_UNDERFILL,
)

_ALL_K = {
    "Si": K_SI,
    "Cu": K_CU,
    "SiO2": K_SIO2,
    "solder": K_SOLDER,
    "underfill": K_UNDERFILL,
    "EMC": K_EMC,
}
_ALL_RHO = {
    "Si": RHO_SI,
    "Cu": RHO_CU,
    "SiO2": RHO_SIO2,
    "solder": RHO_SOLDER,
    "underfill": RHO_UNDERFILL,
    "EMC": RHO_EMC,
}
_ALL_CP = {
    "Si": CP_SI,
    "Cu": CP_CU,
    "SiO2": CP_SIO2,
    "solder": CP_SOLDER,
    "underfill": CP_UNDERFILL,
    "EMC": CP_EMC,
}


class TestThermalConductivityPositive:
    def test_all_k_positive(self):
        for name, k in _ALL_K.items():
            assert k > 0, f"{name} 열전도율은 양수여야 함"


class TestDensityRange:
    def test_all_rho_positive(self):
        for name, rho in _ALL_RHO.items():
            assert rho > 0, f"{name} 밀도는 양수여야 함"

    def test_cu_denser_than_si(self):
        # Cu(8960)는 Si(2329)보다 훨씬 밀도가 높아야 함 (원자량 차이 반영)
        assert RHO_CU > RHO_SI

    def test_polymer_materials_lighter_than_metals(self):
        # underfill/EMC(에폭시 기반)는 Cu/solder(금속)보다 밀도가 낮아야 함
        assert RHO_UNDERFILL < RHO_CU
        assert RHO_UNDERFILL < RHO_SOLDER
        assert RHO_EMC < RHO_CU
        assert RHO_EMC < RHO_SOLDER

    def test_rho_within_broad_literature_range(self):
        # 대략적 범위 확인(CRC Handbook, Touloukian 등): 자릿수 실수 방지용
        assert 2000 < RHO_SI < 2500
        assert 8000 < RHO_CU < 9500
        assert 1500 < RHO_SIO2 < 2700
        assert 6000 < RHO_SOLDER < 9000
        assert 1000 < RHO_UNDERFILL < 2500
        assert 1000 < RHO_EMC < 2500


class TestSpecificHeatRange:
    def test_all_cp_positive(self):
        for name, cp in _ALL_CP.items():
            assert cp > 0, f"{name} 비열은 양수여야 함"

    def test_metals_lower_cp_than_polymers(self):
        # 금속(Cu, solder)은 통상 폴리머(underfill, EMC)보다 비열이 낮음
        assert CP_CU < CP_UNDERFILL
        assert CP_SOLDER < CP_UNDERFILL
        assert CP_CU < CP_EMC
        assert CP_SOLDER < CP_EMC

    def test_cp_within_broad_literature_range(self):
        assert 500 < CP_SI < 900
        assert 300 < CP_CU < 450
        assert 600 < CP_SIO2 < 900
        assert 150 < CP_SOLDER < 300
        assert 700 < CP_UNDERFILL < 1300
        assert 700 < CP_EMC < 1300


class TestVolumetricHeatCapacityMagnitude:
    def test_rho_cp_same_order_of_magnitude_across_materials(self):
        # 체적 열용량(rho*cp)은 고체 물질 간 대략 1e6~5e6 J/m3K 범위에 들어야
        # 함 (극단적 자릿수 실수 방지용 대략 검사) — 물질별 절대값 차이는
        # 정상이며(금속 vs 폴리머), 자릿수 단위 오차만 걸러낸다.
        for name in _ALL_RHO:
            rho_cp = _ALL_RHO[name] * _ALL_CP[name]
            assert 5e5 < rho_cp < 5e6, f"{name} rho*cp={rho_cp}가 예상 범위를 벗어남"
