# 데이터 자동 갱신 (auto-update)

대시보드 데이터(`power_data.js`·`consumption_data.js`·`wolbo_data.js`)를 주기적으로 재생성한다.

## 구성

| 스크립트 | 소스 | 출력 | 자동화 |
|---|---|---|---|
| `fetch_data.py` | EPSIS **온라인** API | `power_data.js`, `consumption_data.js` | ✅ 완전 자동 |
| `kepco_wolbo.py` | `dl\kepco_YYYY_MM.xlsx` **로컬 월보 엑셀** | `wolbo_data.js` | ⚠️ 엑셀은 수동 투입 |
| `update_data.py` | 위 둘을 오케스트레이션 | 백업·검증·복원·로그 | — |

## 자동 실행 (Windows 작업 스케줄러)

- 작업 이름: **`ElecDashboardDataUpdate`**
- 주기: **매월 5일 09:00** (로그인 상태에서 실행)
- 동작: `python update_data.py` 실행

### 관리 명령
```
schtasks /Run    /TN ElecDashboardDataUpdate      # 지금 즉시 1회 실행
schtasks /Query  /TN ElecDashboardDataUpdate /FO LIST   # 상태·다음 실행시각
schtasks /Delete /TN ElecDashboardDataUpdate /F   # 자동 갱신 해제
```
주기를 바꾸려면 위 작업을 지우고 다른 `/SC`(예: `/SC WEEKLY`)로 재등록.

## update_data.py 가 하는 일
1. 현재 JS를 `data_backup\` 에 백업
2. `fetch_data.py` → EPSIS에서 설비·발전·소비 재수집
3. `kepco_wolbo.py` → `dl\` 월보 엑셀에서 6버킷 재생성
4. 결과 파일 **검증**(마커·크기) → 손상 시 **백업 자동 복원**
5. `update_log.txt` 에 결과 기록

수동 실행: `python update_data.py`

## ⚠️ 월보(wolbo) 새 달 반영 — 유일한 수동 단계 (엑셀 파일만 떨구면 끝)
`kepco_wolbo.py`는 **로컬 엑셀**만 읽는다(한전 사이트는 다운로드를 설문/UUID 게이트로 막아 자동수집 불가). 새 월보가 나오면:

1. 한전 전력통계월보에서 해당 호차 엑셀을 받아 **`dl\kepco_YYYY_MM.xlsx`** 형식으로 저장
   (예: 2026년 8월호 → `dl\kepco_2026_08.xlsx`)
2. **끝.** `kepco_wolbo.py`가 `dl\` 폴더를 스캔해 **연도별 최신 월호를 자동 인식**한다
   (`EDITIONS` 코드 수정 불필요 — 같은 해에 더 늦은 월 파일이 있으면 그걸 자동 채택)
3. 다음 자동 실행(매월 5일) 또는 즉시 `python update_data.py` 에서 반영됨

> 즉 **월 작업 = "엑셀 1개 받아 `dl\`에 규칙대로 저장"** 한 가지뿐. 다운로드만 사람이 하고(설문 게이트는 5초면 통과), 파싱·검증·갱신·빌드는 전부 자동.

EPSIS(연단위 설비·발전·소비)는 손댈 것 없이 자동 갱신된다.

## 참고 / 한계
- `fetch_data.py` 의 소비량 파서는 최신 EPSIS 연도를 **2024 기준**으로 라벨링한다. EPSIS가 2025 연간을 추가하면 그 부분 보정이 필요할 수 있다(검증 로그의 전국합 기대치로 점검).
- 송전망 부하 접속 여유 등 **비공개 데이터는 자동화 대상이 아니다**(대시보드는 수급 기준 1차 스크리닝 범위).
