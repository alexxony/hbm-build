"""기본 물성 상수 (W/m·K).

각 값의 출처는 아래 주석 참고. 문헌/벤더 스펙의 대표값(단결정/벌크 기준)이며,
실제 공정 조건(도핑, 결정립계, 박막 두께 효과 등)에 따라 달라질 수 있음.
"""

# Si: 단결정 실리콘, 상온(300K) 기준 논문 표준값
# 출처: Glassbrenner & Slack (1964), Phys. Rev. 134, A1058; 일반적으로 148 W/m·K 인용됨
K_SI = 148.0

# Cu: 벌크 구리, 상온 기준 (박막/TSV 충진 시 결정립 경계로 다소 저하될 수 있음)
# 출처: CRC Handbook of Chemistry and Physics, 벌크 Cu 값
K_CU = 385.0

# SiO2: TSV 라이너(절연막)로 사용되는 열산화막, 비정질
# 출처: Touloukian et al., Thermophysical Properties of Matter, Vol.2 (비정질 SiO2)
K_SIO2 = 1.4

# solder (µbump, SnAg 계열 공융/근접공융 솔더)
# 출처: 일반 SAC(SnAgCu) 솔더 합금 대표값, 패키징 열해석 문헌 다수 인용
K_SOLDER = 50.0

# underfill (에폭시 기반, 실리카 필러 포함 통상 제품)
# 출처: 패키징용 언더필 에폭시 벤더 스펙 대표값 (예: Namics, Henkel 계열 제품군)
K_UNDERFILL = 0.5

# EMC (Epoxy Molding Compound, 몰딩 컴파운드)
# 출처: 반도체 패키징용 EMC 벤더 스펙 대표값 (실리카 필러 함유 통상 제품)
K_EMC = 1.0
