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

## draft 세팅 경계

`POST /api/admin/adcopy/draft-plan`은 API payload만 계산한다.

`POST /api/admin/adcopy/draft-execute`는 단계별 실행이며 `confirm=true`가 필요하다.

실행 단계:

1. 계정 확인
2. 캠페인 draft 생성
3. 이미지 업로드
4. 광고그룹 draft 생성
5. 소재 draft 생성
6. 운영자 최종 확인 후 active 전환

광고그룹 기본 CPM 입찰가는 운영자가 입력한 KRW 값을 `max_bid_micros`로 변환한다. 예: `7,000원` -> `7,000,000`.
