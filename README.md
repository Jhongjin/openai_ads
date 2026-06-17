# 사내용 ChatGPT 광고 도구

나스미디어 영업팀이 ChatGPT 광고 상품 관련 질문을 확인하고, 광고주 랜딩 URL의 OpenAI 광고 크롤러 접근 가능 여부와 파비콘 규격을 1차 셀프 체크할 수 있는 경량 PoC입니다.

첫 화면(`/`)은 `광고 Q&A`입니다. 같은 페이지의 탭에서 `랜딩 URL 검사`, `파비콘 검사`, `집행 의뢰 접수`, `광고주 안내 자료`, `캠페인 세팅 가이드`를 사용할 수 있습니다.

## 광고 Q&A

- `POST /chat`으로 질문을 보내면 공식·국내운영·확인대기 근거를 검색합니다.
- 답변 UI에는 공식=파랑, 내부운영=회색, 확인대기=주황 배지를 표시합니다.
- 크리테오 관련 확정 운영값(최소금액, 과금, 수수료, 구좌제, 인보이스, 소재 세팅)은 `내부운영` 출처로 직접 답하고, 운영 중 개별 이슈만 크리테오 코리아 담당자 확인으로 안내합니다.
- Account Spend Cap은 계정 단위 lifetime cap으로 답하고, 최소 집행 약정과 섞어 안내하지 않습니다.
- 크롤러 429는 Too Many Requests(rate limit)로 안내하되, 전체 에러코드 목록은 확인 대기 톤을 유지합니다.
- 확인 대기 항목은 "현재 OpenAI 확인 대기 중입니다. 확정 후 정확히 안내드리겠습니다."로 고정 응답합니다.
- 확정 회신된 최소 집행금액, VAT, 트래커, 수수료/마크업, 10% 노출 제한, 인벤토리 공유, 입찰/과금, 인보이스, 한글 소재 자수는 `내부운영` 출처로 답합니다.
- 근거가 없거나 범위 밖인 질문은 "제공된 자료에서 확인할 수 없습니다."로 답합니다.
- Supabase/임베딩 환경이 비어 있어도 config의 공식 근거 노트를 읽는 fallback 검색으로 500을 피합니다.

## OAI 광고 크롤러 셀프 체크

`랜딩 URL 검사` 탭은 OAI-AdsBot / OAI-SearchBot robots.txt 셀프 체크 도구입니다.

- 사용자가 URL을 한 줄에 하나씩 입력합니다.
- 서버가 각 URL의 `{origin}/robots.txt`를 10초 타임아웃으로 가져옵니다.
- `OAI-AdsBot`, `OAI-SearchBot`, `User-agent: *` 그룹을 보수적으로 분석합니다.
- 결과는 `✅ 접근 가능`, `⚠️ 확인 필요`, `🚫 광고 로봇 접근 막힘` 배지와 사유/권장 조치로 표시됩니다.
- 기본 판정이 `✅`이어도 CDN/방화벽 흔적이 있으면 노란 `방화벽 뒤 — 추가 확인 권장` 배지를 함께 표시합니다.
- 각 행에서 `크롤러 허용 설정(robots.txt) 원문 보기`를 펼칠 수 있습니다.
- CSV 내보내기를 지원합니다.

API 직접 호출:

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://localhost:8000/check `
  -ContentType "application/json" `
  -Body '{"urls":["https://example.com/landing","https://example.co.kr/itg/ln/page"]}'
```

판정 원칙:

- `robots.txt` 404: `✅ robots.txt 없음 = 전체 허용으로 간주`
- Cloudflare/challenge 계열 403: `🚫 방화벽 차단`
- 타임아웃/연결 실패/기타 4xx·5xx: `⚠️ 확인 불가`
- OAI 봇 명시 그룹 `Disallow: /`: `🚫 OAI 봇 명시적 전체 차단`
- `User-agent: *`의 `Disallow: /`: `🚫 전체 봇 차단`
- 특정 봇만 있고 OAI 또는 `*` 그룹이 없으면: `⚠️ 개발팀 확인 권장`
- 기본 판정이 `✅`여도 입력 URL path가 적용 그룹의 `Disallow`에 걸리면 `⚠️`로 낮춥니다.

## 파비콘 규격 셀프 체크

`파비콘 검사` 탭 또는 `POST /check-favicon`에서 OpenAI 광고 등록용 파비콘 URL을 1차 점검합니다.

- 줄바꿈 또는 쉼표로 여러 URL을 입력합니다.
- `TBD` 또는 빈 값은 `⏳ 광고주 회신 대기`로 분류합니다.
- Google Drive/Docs 공유 뷰어 링크, `/view`, `?usp=sharing`, `text/html` 응답은 직접 이미지 링크가 아니므로 `🚫`로 판정합니다.
- `image/*` 응답만 Pillow로 열어 실제 픽셀을 검사합니다.
- `.ico`는 포함된 최대 해상도 프레임 기준으로 판정합니다.
- 256×256 미만은 `🚫 교체 필요`, 비정사각형/투명 배경은 `⚠️ 확인 필요`, 직접 링크 + 256×256 이상 + 정사각형 + 불투명 배경은 `✅ 사용 가능`입니다.
- 파일명에 `16x16`, `32x32` 등이 있으면 실측과 별개로 저해상도 의심을 사유에 병기합니다.

API 직접 호출:

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://localhost:8000/check-favicon `
  -ContentType "application/json" `
  -Body '{"urls":["https://example.com/favicon.png","TBD"]}'
```

## 집행 의뢰 접수 폼

`집행 의뢰 접수` 탭 또는 `/intake`는 광고 계정 생성과 캠페인 세팅에 필요한 정보를 구글 시트로 접수합니다.

- OpenAI 공식 워크북 구조에 맞춰 `campaigns`, `adgroups`, `ads` 3개 탭에 업로드용 컬럼을 기록하고, 운영팀 추가 항목은 `ops_meta` 탭에 분리 기록합니다.
- 캠페인 1개, 광고그룹 1개, 소재 N개 구조입니다. 소재를 2개 넣으면 `ads` 탭에 2행이 추가됩니다.
- 청구 통화는 `KRW`, 시간대는 `Asia/Seoul`로 고정 표시합니다.
- 크리테오 경유 선택 시 캠페인 목표는 CPM(Views)으로 고정되고, 소재 글자수 상한은 제목 30자 / 설명 60자로 전환됩니다.
- OpenAI 직접 CBT는 공식 워크북 기준 제목 24자 / 설명 48자 상한을 적용합니다.
- 예산 기준은 경고만 표시하고 제출을 막지 않습니다.
- 카드 정보는 수집하지 않고 준비 여부만 체크합니다.
- 제출 성공 시 `KT-OAI-YYYYMMDD-NNN` 형식의 접수번호와 KST 타임스탬프를 반환합니다.

서버는 `GOOGLE_SHEETS_WEBHOOK_URL`로 JSON을 전달하며, body는 `secret` + `data` 구조로 맞춥니다. Apps Script 웹앱은 `secret` 값을 Script Properties의 `SHEETS_SHARED_SECRET`와 비교해 검증합니다. 예시 코드는 [apps_script/intake_webhook.gs](apps_script/intake_webhook.gs)에 있으며, Apps Script의 Script Properties에 `SHEETS_SHARED_SECRET` 값을 등록한 뒤 새 버전으로 배포합니다.

Apps Script로 전달되는 최종 body:

```json
{
    "secret": "환경변수 SHEETS_SHARED_SECRET 값",
    "data": {
      "campaign": {
        "campaign_name": "summer_sale",
        "budget_max": "5000000",
        "budget_type": "lifetime",
        "launch_date": "2026-07-01",
        "end_date": "2026-07-31",
        "objective": "views",
        "target_countries": ["KR"]
      },
      "adgroups": [
        { "adgroup_name": "ag_main", "max_bid": "", "keywords": ["키워드1", "키워드2"] }
      ],
      "ads": [
        { "adgroup_name": "ag_main", "title": "여름 특가", "copy": "지금 준비하세요", "link": "https://example.com", "image_link": "https://example.com/img.png" },
        { "adgroup_name": "ag_main", "title": "두 번째 소재", "copy": "또 다른 메시지", "link": "https://example.com/2", "image_link": "https://example.com/img2.png" }
      ],
      "ops": {
        "route": "OpenAI 직접 CBT",
        "advertiser_name": "광고주명",
        "legal_name": "법인 정식 명칭",
        "brn": "123-45-67890",
        "homepage": "https://example.com",
        "invoice_email": "invoice@example.com",
        "contact_name": "홍길동",
        "contact_phone": "010-0000-0000",
        "contact_email": "client@example.com",
        "sales_owner": "영업담당자명",
        "ready_ads_manager": true,
        "ready_payment": true,
        "ready_crawler": true,
        "ready_favicon": true,
        "note": ""
      }
    }
}
```

## 광고주 안내 자료

`광고주 안내 자료` 탭 또는 `/slides`는 광고주 전달용 5장 슬라이드 문서입니다.

- 16:9 슬라이드형 레이아웃으로 소재 준비물, 랜딩 페이지 기술 준비, 집행 조건, 다음 단계를 안내합니다.
- 내부 출처 배지, 내부 분류, 확인 대기 표현은 노출하지 않습니다.
- 상단에는 `최종 업데이트: 2026-06-17`을 표시합니다.
- `PDF로 저장` 버튼은 `ChatGPT광고_집행준비안내_케이티나스미디어_YYYYMMDD.pdf` 형식의 파일명을 브라우저 인쇄 저장 기본값으로 유도합니다.
- 슬라이드 4에는 "OpenAI ChatGPT Ads 베타 기준이며, 정책 및 금액은 변동될 수 있습니다. VAT 등 세부 정산 조건은 별도 안내드립니다." 문구를 포함합니다.
- `PDF로 저장` 버튼은 브라우저 인쇄(`window.print()`)를 호출하며, 인쇄 CSS에서 슬라이드 한 장이 한 페이지로 분리됩니다.

## 캠페인 세팅 가이드

`캠페인 세팅 가이드` 탭은 Ads Manager에서 캠페인, 광고그룹, 광고를 만드는 절차를 5장 슬라이드형 HTML 문서로 안내합니다.

- `PDF로 저장` 버튼은 `ChatGPT광고_캠페인세팅가이드_케이티나스미디어_YYYYMMDD.pdf` 파일명을 브라우저 인쇄 저장 기본값으로 유도합니다.
- 캡처 이미지는 `public/images/guide/`에 아래 파일명으로 넣으면 자동 반영됩니다.
- 파일이 없으면 점선 placeholder와 `캡처 이미지 삽입 위치` 안내가 표시됩니다.

이미지 파일명:

- `campaign_step1.png`: 캠페인 만들기 화면
- `campaign_step2.png`: 광고그룹 만들기 화면
- `campaign_step3.png`: 광고 만들기 화면
- `campaign_preview.png`: 광고 소재 미리보기

## 구조

- `official`: OpenAI 공식 Help Center, 정책, 공지 URL
- `kr_ops`: 완성된 국내 영업 가이드와 OpenAI 담당자 회신 확정 정보
- `pending`: OpenAI 확인 대기 항목
- 벡터 저장소: Supabase Postgres + `pgvector`
- DB schema: `openai_ads_rag`
- 크롤러 체크 API: `POST /check`
- 파비콘 체크 API: `POST /check-favicon`
- RAG 챗 API: `POST /chat`
- 집행 의뢰 접수 API: `POST /intake`
- 광고주 안내 자료 페이지: `GET /slides`

공식 가이드 허브: <https://help.openai.com/ko-kr/collections/20001223-chatgpt-ads>

크리테오 원문은 인덱싱하지 않습니다. 로컬 문서 파일명에 `criteo`, `Criteo`, `CRITEO`, `크리테오`가 포함되면 자동 제외됩니다.

## 설치

Python 3.11 이상에서 동작하며, Vercel 배포 환경과 맞추기 위해 `.python-version`은 `3.12`로 고정했습니다.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
Copy-Item config.example.yaml config.yaml
```

`.env`에 `OPENAI_API_KEY`를 입력합니다.

Supabase는 기존 프로젝트 DB와 분리되도록 별도 schema를 사용합니다.

```dotenv
SUPABASE_URL=https://yotbhhtwvvshwxxcxazl.supabase.co
SUPABASE_SCHEMA=openai_ads_rag
SUPABASE_DB_URL=postgresql://postgres.yotbhhtwvvshwxxcxazl:[YOUR-PASSWORD]@[YOUR-POOLER-HOST]:6543/postgres?sslmode=require
```

`SUPABASE_DB_URL`은 Supabase Dashboard의 pooled connection string을 권장합니다.

## 문서 배치

- 국내 운영 확정 문서: `data/kr_ops/*.md` 또는 `data/kr_ops/*.txt`
- 확인 대기 문서: `data/pending/*.md` 또는 `data/pending/*.txt`
- 공식 URL 목록: `config.yaml`의 `collections.official.urls`

각 청크에는 `source_tier`, `source_url`, `title`, `crawled_at` 메타데이터가 저장됩니다.

## 인덱싱

최초 1회는 `supabase/migrations/001_openai_ads_rag.sql`을 Supabase SQL Editor에서 실행하거나, DB 사용자에게 schema/extension 생성 권한이 있다면 `python ingest.py`가 자동으로 schema와 table을 생성합니다.

먼저 `SUPABASE_DB_URL`이 실제 pooled Postgres URL인지 확인해야 합니다. placeholder 호스트나 잘못된 비밀번호 상태에서는 인덱싱이 config fallback으로만 동작해 새 크롤링 결과가 RAG 검색에 반영되지 않습니다.

전체 재인덱싱:

```powershell
python ingest.py
```

특정 컬렉션만 재인덱싱:

```powershell
python ingest.py --collection official
python ingest.py --collection kr_ops --collection pending
```

`official` 컬렉션은 `config.example.yaml`의 한/영 ChatGPT Ads Help Center 컬렉션 시작점에서 하위 컬렉션과 article 링크를 매번 재탐색합니다. article별 `content_hash`가 같으면 임베딩을 건너뛰고, 변경된 문서만 기존 chunk를 교체합니다. 실행 로그에는 KO/EN article 수, 변경 문서 수, 실패 URL 수가 표시됩니다.

공식 문서는 `robots.txt`를 확인한 뒤 크롤링합니다. 크롤링 실패 URL은 경고로 출력됩니다. `config.yaml`의 `collections.*.documents`에 있는 공식·내부운영·확인대기 근거 노트도 함께 인덱싱되므로, 공식 사이트가 일시적으로 403을 반환해도 PoC 답변 근거가 비지 않도록 구성했습니다.

## 실행

FastAPI:

```powershell
uvicorn app:app --reload --port 8000
```

Streamlit 선택 UI:

```powershell
python -m pip install streamlit
streamlit run ui.py
```

Vercel은 루트 `app.py`의 FastAPI `app`을 zero-config 엔트리포인트로 감지합니다. `/check`는 robots.txt 셀프 체크, `/check-favicon`은 파비콘 규격 체크, `/chat`은 광고 Q&A입니다.

검증:

```powershell
python -m unittest discover -s tests
python -B -m py_compile app.py checker.py favicon_checker.py ingest.py ui.py
```

광고 Q&A API 직접 호출:

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://localhost:8000/chat `
  -ContentType "application/json" `
  -Body '{"question":"ChatGPT 광고 최소 집행금액 얼마야?"}'
```

## 답변 가드레일

- 공식 출처: `✅공식`
- 국내 운영 확정 출처: `🟡국내운영`
- 확인 대기 출처: `⚠️확인대기`
- `pending`만 검색되면 확정 답변 대신 "현재 OpenAI 확인 대기 중입니다"로 답합니다.
- 검색 근거가 없으면 "제공된 자료에서 확인할 수 없습니다."로 답합니다.
- 크리테오 경유 확정 운영값은 내부운영 출처로 직접 답합니다. 운영 중 개별 이슈는 크리테오 코리아 담당자 확인이 필요하다고 안내합니다.
- 페이지 하단에는 베타 기준 변동 가능성과 OpenAI 공식 가이드/담당자 확인 안내가 고정 표시됩니다.

## 운영 팁

- 공식 URL이 바뀌면 `config.yaml`만 수정한 뒤 `python ingest.py --collection official`을 실행합니다. 한국어 공식 가이드 허브는 <https://help.openai.com/ko-kr/collections/20001223-chatgpt-ads> 입니다.
- OpenAI 담당자 회신으로 확정된 항목은 `pending`에서 제거하고 `kr_ops` 문서로 옮긴 뒤 두 컬렉션을 재인덱싱합니다.
- Supabase 안의 다른 프로젝트 테이블과 충돌하지 않도록 앱은 `openai_ads_rag.documents`만 읽고 씁니다.

## Vercel 배포

Vercel 프로젝트 환경변수에 아래 값을 등록합니다.

- `OPENAI_API_KEY`
- `OPENAI_CHAT_MODEL`
- `OPENAI_EMBEDDING_MODEL`
- `OPENAI_EMBEDDING_DIMENSIONS`
- `SUPABASE_URL`
- `SUPABASE_DB_URL`
- `SUPABASE_SCHEMA`
- `RAG_CONFIG_PATH`
- `EMBEDDING_BATCH_SIZE`
- `INGEST_TOKEN` (선택, 배포 후 보호된 `/admin/reindex`를 호출할 때 사용)
- `GOOGLE_SHEETS_WEBHOOK_URL` (집행 의뢰 접수용 Apps Script 웹앱 URL)
- `SHEETS_SHARED_SECRET` (Apps Script와 동일한 공유 토큰)

배포 전 로컬에서 `python ingest.py`로 Supabase에 문서를 인덱싱합니다. 민감 환경변수를 로컬로 내려받을 수 없는 경우에는 `INGEST_TOKEN`을 설정한 뒤 배포된 `POST /admin/reindex`를 호출해 Vercel 런타임에서 재인덱싱할 수 있습니다.

크롤러 셀프 체크(`/check`)는 Supabase 인덱싱 없이도 동작합니다.

파비콘 셀프 체크(`/check-favicon`)도 Supabase 인덱싱 없이 동작합니다.

## 자동 재인덱싱

`.github/workflows/reindex-openai-help.yml`은 KST 09:00, 21:00에 `python ingest.py --collection official`을 실행합니다. GitHub repository secrets에 아래 값을 등록해야 동작합니다.

- `OPENAI_API_KEY`
- `SUPABASE_DB_URL`
- `SUPABASE_SCHEMA` (기본 `openai_ads_rag`)
- `OPENAI_EMBEDDING_MODEL`, `OPENAI_EMBEDDING_DIMENSIONS`, `EMBEDDING_BATCH_SIZE` (기본값 사용 가능)

GitHub-hosted runner에서 OpenAI Help Center 원문 요청이 403으로 막히는 경우가 있어, 워크플로는 `HELP_CENTER_CRAWL_MODE=reader`와 `ENABLE_READER_FALLBACK=true`로 공식 URL reader fallback을 사용합니다. 저장되는 `source_url`은 원래 OpenAI 공식 URL을 유지하고, fallback 수집 문서는 갱신일을 파싱하지 못하면 `source_updated_at_is_fallback=true`로 표시됩니다. reader 요청은 `READER_FALLBACK_DELAY_SECONDS=1.2`와 429 백오프로 천천히 실행합니다. `REQUIRE_HELP_CENTER_MIN_ARTICLES=30` 보호 조건이 있어 KO/EN Help Center article을 충분히 수집하지 못하면 크론 실행은 실패로 종료됩니다.

## OpenAI 담당자 메일 수집

`.github/workflows/collect-openai-mail.yml`은 KST 09:15, 21:15에 Daum IMAP을 읽기 전용으로 열어 OpenAI 광고 담당자 관련 메일만 수집합니다. 수집된 메일은 먼저 Google Sheet에 영구 누적되며, 기본 상태는 `needs_review`입니다. 원문 메일은 자동으로 RAG에 들어가지 않습니다.

RAG 반영은 관리자 승인 게이트를 통과한 행만 대상으로 합니다.

1. 수집 워크플로가 조건에 맞는 메일을 Sheet `openai_mail_rag`에 적재합니다.
2. 관리자가 Sheet에서 내용을 확인한 뒤 RAG에 반영할 행만 `review_status`를 `approved_for_rag`로 바꿉니다.
3. 관리자가 `approved_summary`에 실제 챗봇 근거로 쓸 확정 요약을 직접 작성합니다. 필요하면 `approved_title`에 안전한 표시 제목을 적습니다.
4. 이전 안내가 새 메일로 바뀐 경우 기존 행은 `review_status=superseded`로 바꾸거나, 새 행의 `supersedes_duplicate_hash`에 이전 행의 `duplicate_hash`를 기입합니다.
5. 워크플로가 승인된 요약만 `data/kr_ops/openai_email_approved_updates.md` 임시 문서로 생성하고 `python ingest.py --collection kr_ops`를 실행합니다.

이 구조는 메일을 비교·감사용으로 누적 보관하면서도, 베타 단계에서 바뀔 수 있는 내용을 관리자가 확인하기 전에는 챗봇 근거로 쓰지 않기 위한 안전장치입니다. 생성 파일 `data/kr_ops/openai_email_approved_updates.md`는 메일 원문 보호를 위해 Git에 커밋하지 않습니다.

수집 조건은 2단계입니다.

- Daum 자동분류에서 프로젝트 전용 메일함으로 1차 분류합니다.
- 코드에서 `to/cc`에 `openai@nasmedia.co.kr`가 있거나, 발신자가 `michaelcho@openai.com`, `harrisonk@openai.com`, `ads-korea@openai.com`, `nigel@openai.com`인 메일만 2차 통과시킵니다.

GitHub repository secrets에 아래 값을 등록합니다.

- `MAIL_COLLECTOR_USER`: Daum ID
- `MAIL_COLLECTOR_PASSWORD`: Daum 앱 비밀번호
- `MAIL_COLLECTOR_FOLDER`: Daum 프로젝트 전용 메일함 이름
- `MAIL_COLLECTOR_HOST`, `MAIL_COLLECTOR_PORT`, `MAIL_COLLECTOR_SECURE` (기본 `imap.daum.net`, `993`, `true`)
- `MAIL_COLLECTOR_TOP` (워크플로 기본 `1000`. 하루 2회 실행 기준 전용 메일함이 12시간에 1000건 미만이면 `1000` 유지 권장)
- `MAIL_COLLECTOR_SHEETS_WEBHOOK_URL`: 메일 누적용 Apps Script 웹앱 URL
- `MAIL_COLLECTOR_SHEETS_SHARED_SECRET`: Apps Script와 공유하는 토큰. 별도 값이 없으면 기존 `SHEETS_SHARED_SECRET`을 재사용할 수 있습니다.
- `OPENAI_API_KEY`, `SUPABASE_DB_URL`, `SUPABASE_SCHEMA`, `OPENAI_EMBEDDING_MODEL`, `OPENAI_EMBEDDING_DIMENSIONS`, `EMBEDDING_BATCH_SIZE`

로컬 점검:

```powershell
python -m rag_chatbot.mail_collector --dry-run
python -m rag_chatbot.mail_collector --diagnostics --post-sheet
python -m rag_chatbot.mail_collector --write-approved-rag-doc data/kr_ops/openai_email_approved_updates.md --require-approved-summary
python ingest.py --collection kr_ops
```

메일 누적용 Apps Script 예시는 [apps_script/mail_collector_webhook.gs](apps_script/mail_collector_webhook.gs)에 있습니다. 별도 Google Sheet 웹앱으로 배포하거나 기존 Apps Script에 병합해 사용합니다. 이 예시는 `duplicate_hash` 기준으로 이미 적재된 메일을 다시 append하지 않고, `review_status=approved_for_rag`와 `approved_summary`가 있는 행만 RAG 승인 데이터로 반환합니다. 원문 메일 제목은 자동 RAG 문서에 쓰지 않으며, 관리자가 입력한 `approved_title`만 표시 제목으로 사용합니다.

## 연동 필요 정보

Vercel:

- GitHub repo: `https://github.com/Jhongjin/openai_ads.git`
- Framework: FastAPI/Python Function
- Entry: 루트 `app.py`의 FastAPI `app` (custom `functions` 설정 없음)
- Python version: `.python-version`의 `3.12`
- Environment Variables: 위 `Vercel 배포` 섹션의 값

Supabase:

- Project URL: `https://yotbhhtwvvshwxxcxazl.supabase.co`
- Database connection string: Supabase Dashboard에서 복사한 pooled Postgres URL
- Schema: `openai_ads_rag`
- Migration: `supabase/migrations/001_openai_ads_rag.sql`
- Required extension: `vector` (`pgvector`)
