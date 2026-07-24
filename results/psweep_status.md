# 파워 스윕 5케이스 + 30W_S2 컨투어 진행 상태

케이스당 완료 시 이 파일을 갱신한다(디스크 상태 이중화, 대화 보고와 별개).

## 케이스 목록

| 케이스 | 상태 | CSV | base_die_phy max_temp_c | 완료 시각(epoch) | 완료 시각(ISO 8601) |
|---|---|---|---|---|---|
| 30W_A_S2 (컨투어 목적 재솔브) | 완료 (CSV만, 컨투어 블로커) | `results/psweep_icepak_a_30w_s2.csv` | 230.19622 | 1753299 (05:47 KST 로그 기준, 정확 epoch 미기록 — 아래 참고) | 2026-07-24T05:47:00+09:00 (근사) |
| 20W_A_S0 | 완료 | `results/psweep_icepak_a_20w_s0.csv` | 142.45211 | 1784853780 | 2026-07-24T09:43:00+09:00 |
| 20W_A_S2 | 완료 | `results/psweep_icepak_a_20w_s2.csv` | 166.79727 | 1784854080 | 2026-07-24T09:48:00+09:00 |
| 24W_A_S0 | 완료 | `results/psweep_icepak_a_24w_s0.csv` | 162.94280 | 1784854380 | 2026-07-24T09:53:00+09:00 |
| 24W_A_S2 | 완료 | `results/psweep_icepak_a_24w_s2.csv` | 192.15673 | 1784854680 | 2026-07-24T09:58:00+09:00 |

## 30W_A_S2 상세

- 실행: `bash scripts/run_icepak_case.sh psweep_30w_s2_contour --power-scenario s2_phy_heavy --total-power 30.0 --output-csv results/psweep_icepak_a_30w_s2.csv --export-contour-png charts/icepak_contour_30w_8hi.png --non-graphical`
- 로그: Windows 클론 `logs/psweep_30w_s2_contour.log` (WSL 쪽 회수 안 됨 — run_icepak_case.sh는 CSV만 회수, 로그는 회수 안 하는 기존 동작)
- **재현성 스팟체크(팀리드 지시 3항)**: 신규 CSV `base_die_phy` max_temp_c = 230.19622°C, 기존 `results/p4_icepak_scenarios/p4_icepak_a_s2.csv`(P4 T3, 2026-07-19)의 동일 행 = 230.19607°C. 차이 0.00015°C(≈0.00007%) — **재현성 확인(사실상 동일)**.
- **컨투어 export 블로커**: `create_fieldplot_cutplane`/`create_fieldplot_surface`/`create_fieldplot_volume` 3가지 방식 전부 `plot.create()`가 False 반환(예외 아님). AEDT 네이티브 메시지 매니저(`GetMessages`) 회수 결과: `"Plot '...' has been removed due to deletion of quantity expression"` — quantity="Temp"가 field-plot 등록 목록에 없음. `ipk.post.available_report_quantities()` 조회 결과 `['Residual.Continuity', 'Residual.Energy', 'Residual.XVelocity', 'Residual.YVelocity', 'Residual.ZVelocity']`만 반환 — Temp 자체가 report/field-plot용 quantity 레지스트리에 없음(반면 `get_scalar_field_value(quantity="Temp", ...)`는 정상 동작 — CSV export 경로는 다른 calculator 경로 사용 추정). 재솔브 없이 기존 `.aedt` 프로젝트(`C:\Users\<user>\Documents\Ansoft\hbm2e_8hi_layercake.aedt`)를 재오픈해 진단 — 재솔브는 하지 않았음(솔브 결과 그대로 보존).
- **경로**: 재솔브 없이 열어서 시도(팀리드 지시 3항의 "결과 남아있으면 재솔브 없이 export 시도" 경로) — 시도했으나 API 차원의 근본 문제로 실패, 재솔브로도 해결 안 될 가능성 높음(quantity 자체가 등록 안 된 것으로 보임).
- 상태: **컨투어는 블로커로 보류, CSV/재현성은 완료.** 팀리드에 보고 후 지시 대기.

## 선형성 스팟체크 (팀리드 지시 5항)

ΔT_hotspot = base_die_phy max_temp_c(S2) − base_die_phy max_temp_c(S0), 기존 앵커(16W=19.48K, 30W=36.037K)로 만든 선형 추세선(slope=1.1826 K/W, intercept=0.5577 K)과 비교.

| 파워(W) | ΔT_hotspot 실측(K) | 선형 추세 예측(K) | 잔차 | 잔차(%) |
|---|---|---|---|---|
| 20 | 24.3452 (=166.79727−142.45211) | 24.2106 | +0.1346 | +0.56% |
| 24 | 29.2139 (=192.15673−162.94280) | 28.9411 | +0.2728 | +0.94% |

두 중간점 모두 16W·30W 앵커가 만드는 선형 추세선 부근(±1% 이내)에 위치 — 정성적으로 선형성과 일치하는 것으로 보임. 최종 PASS/FAIL 판정은 오케스트레이터 몫(원 지시).

## 프로세스/환경 체크 로그

- 각 케이스 실행 전후 AEDT 프로세스 0 확인(PowerShell Get-Process ansysedt*,ansyscl*,fluent*) — 매 실행 전 확인 완료.
- PII 게이트: 신규 파일 전체(`results/psweep_icepak_a_*.csv`, `results/psweep_status.md`) 대상 `grep -rn 'kimsh\|LG-PC'` 실행 — 최초 1건 발견(본 파일 자체의 .aedt 경로 인용, `<user>`로 치환 완료) 후 재스캔 0건.
