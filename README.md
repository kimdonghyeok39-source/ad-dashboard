# 📊 퍼포먼스 광고 통합 대시보드

메타 · 구글 · 네이버 · 카카오 광고 성과 CSV를 GitHub에 올리기만 하면
자동으로 통합되어 웹 대시보드에 반영되는 스타터 키트입니다.

**동작 구조**

```
플랫폼에서 CSV 다운로드
        ↓ (data/raw/<플랫폼>/ 폴더에 업로드)
GitHub Actions가 자동 실행 (scripts/merge.py)
        ↓
docs/data.json 으로 통합 + 커밋
        ↓
GitHub Pages 대시보드 자동 갱신 (docs/index.html)
```

---

## 1. 초기 설정 (최초 1회, 약 5분)

1. GitHub에서 새 저장소를 만듭니다. 광고 데이터가 들어가므로 **Private 권장**.
   (Private 저장소에서 GitHub Pages를 쓰려면 Pro 플랜 필요. 무료 플랜이면 Public으로 만들되 민감한 캠페인명은 주의하세요.)
2. 이 폴더의 모든 파일을 저장소에 업로드(또는 push)합니다.
3. 저장소 **Settings → Pages** 에서
   - Source: `Deploy from a branch`
   - Branch: `main` / 폴더: `/docs` 선택 → Save
4. 저장소 **Settings → Actions → General → Workflow permissions** 에서
   `Read and write permissions` 선택 → Save
5. 1~2분 후 `https://<아이디>.github.io/<저장소이름>/` 에서 대시보드 확인.
   처음에는 포함된 **샘플 데이터**가 표시됩니다.

## 2. 평소 사용법 (데이터 업데이트)

1. 각 광고 플랫폼에서 **일별 × 캠페인별** 성과 리포트를 CSV로 다운로드합니다.
2. GitHub 웹에서 해당 폴더에 드래그 앤 드롭으로 업로드 후 커밋:

   | 플랫폼 | 업로드 위치 |
   |---|---|
   | 메타 광고 관리자 | `data/raw/meta/` |
   | 구글 애즈 | `data/raw/google/` |
   | 네이버 검색광고 | `data/raw/naver/` |
   | 카카오모먼트 | `data/raw/kakao/` |

3. 끝! 커밋하면 Actions가 자동으로 돌고 1~2분 내 대시보드가 갱신됩니다.

- 파일명은 자유입니다 (`meta_0601.csv` 등 날짜를 붙이면 관리 편함).
- 같은 날짜+캠페인 데이터가 여러 파일에 있으면 **나중 파일 기준**으로 유지됩니다.
- 샘플 데이터를 지우려면 `*_sample.csv` 파일들을 삭제하세요.

## 3. CSV 컬럼이 매칭되지 않을 때

플랫폼 리포트 설정에 따라 컬럼명이 다를 수 있습니다.
Actions 로그에 `필수 컬럼을 찾지 못해 건너뜀` 경고가 보이면,
`scripts/merge.py` 상단의 `COLUMN_MAP`에 실제 컬럼명을 추가하면 됩니다.

```python
"naver": {
    "date": ["기준일", "날짜", "여기에_실제_컬럼명_추가"],
    ...
```

필수 컬럼은 **날짜 / 캠페인 / 비용** 3가지이며, 나머지(노출·클릭·전환·매출)는
없으면 0으로 처리됩니다. 인코딩(utf-8, cp949)은 자동 인식합니다.

## 4. 대시보드 기능

- **기간 필터**: 최근 7 / 14 / 30일 / 전체 — 직전 동일 기간 대비 증감률 표시
- **플랫폼 필터**: 칩을 눌러 켜고 끄기
- **KPI**: 지출, 노출, 클릭, CTR, CPC, 전환, CPA, ROAS
- **일별 추이**: 지표 선택(지출/노출/클릭/전환/매출), 플랫폼별 누적 막대
- **캠페인 테이블**: 열 클릭으로 정렬

## 5. 다음 단계: API 자동화로 업그레이드

수동 다운로드가 번거로워지면, `merge.py` 앞단에 수집 스크립트를 추가하고
워크플로에 `schedule`(cron)을 걸어 완전 자동화할 수 있습니다.

| 플랫폼 | API | 비고 |
|---|---|---|
| 메타 | Marketing API | 비교적 발급 쉬움, 액세스 토큰 필요 |
| 구글 | Google Ads API | 개발자 토큰 심사 필요 (수일 소요) |
| 네이버 | 검색광고 API | API 키 발급 즉시 가능, 난이도 낮음 |
| 카카오 | 카카오모먼트 API | 비즈니스 인증 필요 |

API 키는 절대 코드에 넣지 말고 **Settings → Secrets and variables → Actions** 에
저장한 뒤 워크플로에서 `${{ secrets.이름 }}`으로 참조하세요.
네이버 검색광고 API가 가장 시작하기 쉬우니 첫 자동화 대상으로 추천합니다.

## 폴더 구조

```
├── .github/workflows/update-data.yml   # 자동 통합 워크플로
├── scripts/merge.py                    # CSV → JSON 통합 스크립트
├── data/raw/{meta,google,naver,kakao}/ # CSV 업로드 위치
└── docs/
    ├── index.html                      # 대시보드 (GitHub Pages)
    └── data.json                       # 통합 데이터 (자동 생성)
```
