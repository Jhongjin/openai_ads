# AI 카피 생성기 계약

이 문서는 OpenAI Ads 관리자 화면의 `AI 카피 생성기`가 받는 입력, 생성하는 표준 산출물, 검수 상태, draft 세팅 경계를 정의한다.

## 원칙

- 생성기는 캠페인, 광고그룹, 소재를 바로 active로 만들지 않는다.
- 외부 repo 산출물은 실행 엔진으로 의존하지 않고, JSON 산출물만 우리 표준 스키마로 정규화한다.
- OpenAI Ads draft 세팅 단계는 운영자가 버튼으로 단계별 실행하며, 모든 신규 객체의 기본 상태는 `paused`다.
- `active` 전환은 별도 버튼과 확인창을 통과해야 한다.

## 표준 generated.json

```json
{
  "policy": { "banned_terms": ["무조건"] },
  "campaigns": [
    {
      "campaign_name": "캠페인명",
      "budget_max": 30000,
      "budget_type": "daily",
      "launch_date": "2026-07-10",
      "end_date": "2026-07-31",
      "objective": "Views",
      "target_countries": ["KR"]
    }
  ],
  "adgroups": [
    {
      "campaign_name": "캠페인명",
      "adgroup_name": "01_광고그룹",
      "keywords": [{ "text": "키워드", "origin": "customer_data" }],
      "required_phrases": ["필수 문구"],
      "trace": {
        "source_type": "AI 생성",
        "generation_basis": "브리프 기반",
        "validation_status": "운영 검수 필요",
        "review_comment": "",
        "exclusion_reason": "",
        "confidence_score": 0.8
      }
    }
  ],
  "ads": [
    {
      "ad_name": "AD_001",
      "adgroup_name": "01_광고그룹",
      "title": "제목",
      "copy": "카피",
      "link": "https://example.com",
      "image_link": "https://example.com/image.jpg",
      "trace": {
        "validation_status": "운영 검수 필요",
        "review_comment": "",
        "exclusion_reason": ""
      }
    }
  ]
}
```

## 외부 산출물 호환 입력

다음 형태를 `/api/admin/adcopy/import`에서 흡수한다.

- 표준 `generated.json`
- AI팀 스타일 `campaign`, `ad_groups`, `creatives`
- workbook dump 스타일 `sheets[].name = campaigns | adgroups_검수 | ads_검수`
- 검수 workbook에서 나온 `keywords`, `keywords_origin`, `validation_status`, `검수상태`, `review_comment`

검수 상태 매핑:

| 외부 값 | 내부 운영 상태 |
| --- | --- |
| `무수정 승인`, `수정 후 승인`, `확인 완료 검수`, `approved` | `승인` |
| `부분 재생성`, `광고주 확인 필요`, `보류`, `needs` | `수정 필요` |
| `사용 불가`, `제외`, `excluded` | `제외` |
| 공백 또는 미확인 | `운영 검수 필요` |

## 자동 검수

검수는 다음 항목을 확인한다.

- 캠페인 필수값, 예산, 국가
- 광고그룹 이름, Context Hints 개수, `max_bid` 미입력 여부
- 소재 제목 24자 이하, 카피 48자 이하, URL 형식
- 금지어와 필수 포함 문구
- 동일 제목·카피 중복
- 정책상 민감할 수 있는 표현
- 소재별 랜딩 도메인 불일치

품질 패널은 `score`, `grade`, `readiness`, `policy_risk_count`, `landing_domain_count`를 표시한다.

## 운영 검수 저장

`POST /api/admin/adcopy/review-state`는 현재 화면의 `generated.json`과 자동 검수 리포트를 저장한다.

저장은 검수 상태 보존용이며, OpenAI Ads 객체 생성이나 활성화와 무관하다.

저장본 관리:

- `GET /api/admin/adcopy/review-state?limit=20`: 최근 저장본 목록
- `GET /api/admin/adcopy/review-state/{id}`: 저장본 상세와 `generated.json` 복원
- `DELETE /api/admin/adcopy/review-state/{id}`: 저장본 삭제

운영 UI에서는 저장본을 불러오면 미리보기, 검수 상태, 내보내기 기준, draft plan 기준을 모두 해당 저장본으로 갱신한다.

## 엑셀 흡수

`GET /api/admin/adcopy/sample-workbook`는 운영 테스트용 샘플 `review.xlsx`를 내려준다. 이 API는 파일 생성만 수행하며 OpenAI Ads 캠페인·광고그룹·소재를 생성하지 않는다.

`POST /api/admin/adcopy/import-workbook`는 `review.xlsx` 파일을 업로드받아 외부 JSON 흡수와 동일한 `generated.json` 스키마로 정규화한다.

지원 시트명:

- 캠페인: `campaigns`, `campaigns_검수`, `캠페인`, `캠페인 목록`
- 광고그룹: `adgroups`, `adgroups_검수`, `광고그룹`, `광고그룹 목록`
- 소재: `ads`, `ads_검수`, `소재`, `소재 목록`, `카피`, `카피 목록`

첫 번째 데이터 행 전에 단일 셀 안내문이 있으면 preamble로 처리하고, 첫 번째 다중 셀 행을 헤더로 사용한다. 파일 크기는 8MB 이하의 `.xlsx`만 허용한다.

## draft 세팅 경계

`POST /api/admin/adcopy/draft-plan`은 API payload만 계산한다.

`POST /api/admin/adcopy/draft-preflight`는 read-only 리허설이다. 광고주 Ads API 키와 계정 메타, paused payload, 검수 오류, 예산, 입찰가, 이미지 URL, 소재 수를 확인하지만 캠페인·광고그룹·소재를 생성하지 않는다.

`POST /api/admin/adcopy/draft-execute`는 단계별 실행이며 `confirm=true`가 필요하다.

실행 단계:

0. Draft 리허설: read-only, 생성 없음
1. 계정 확인: read-only
2. 캠페인 draft 생성: paused
3. 이미지 업로드
4. 광고그룹 draft 생성: paused
5. 소재 draft 생성: paused
6. 운영자 최종 확인 후 active 전환: 현재 금지

광고그룹 기본 CPM 입찰가는 운영자가 입력한 KRW 값을 `max_bid_micros`로 변환한다. 예: `7,000원` -> `7,000,000`.

현재 운영 정책상 `activate_all`은 기본 비활성화되어 있으며, `ADS_DRAFT_ALLOW_ACTIVATION=1`을 명시하지 않으면 API가 400으로 차단한다. UI도 활성화 버튼을 실행 불가 상태로 둔다. 실제 캠페인 live 전환은 별도 승인 전까지 금지한다.
