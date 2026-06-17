# 사내용 ChatGPT 광고 도구

나스미디어 영업팀이 ChatGPT 광고 상품 관련 질문을 확인하고, 광고주 랜딩 URL의 OpenAI 광고 크롤러 접근 가능 여부와 파비콘 규격을 1차 셀프 체크할 수 있는 경량 PoC입니다.

첫 화면(`/`)은 RAG 챗봇입니다. 같은 페이지의 탭에서 `랜딩 URL 검사`, `파비콘 검사`, `광고주 준비물`을 사용할 수 있습니다.

## RAG 챗봇

- `POST /chat`으로 질문을 보내면 공식·국내운영·확인대기 근거를 검색합니다.
- 답변 UI에는 공식=파랑, 내부운영=회색, 확인대기=주황 배지를 표시합니다.
- 크리테오가 포함된 질문은 "크리테오 경유 세부사항은 크리테오 코리아에 확인이 필요합니다."로 고정 라우팅합니다.
- 확인 대기 항목은 "현재 OpenAI 확인 대기 중입니다. 확정 후 정확히 안내드리겠습니다."로 고정 응답합니다.
- 확정 회신된 최소 집행금액, 10% 노출 제한, 인벤토리 공유, 입찰/과금, 인보이스, 한글 소재 자수는 `내부운영` 출처로 답합니다.
- VAT 별도 여부, 트래커(픽셀) 제출 의무, 크리테오 수수료 정책은 계속 `확인대기`로 답합니다.
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

## 광고주 준비물 체크리스트

`광고주 준비물` 탭은 영업 담당자가 광고주에게 요청할 소재, 랜딩 페이지 기술 요건, 집행 조건, 확인 대기 항목을 한 화면에 정리합니다.

- 항목별로 `공식`, `내부운영`, `확인대기` 출처 등급 배지를 표시합니다.
- `전체 복사`로 광고주 전달용 텍스트를 클립보드에 복사할 수 있습니다.
- `CSV 내보내기`로 섹션/항목/출처 등급/내용 표를 내려받을 수 있습니다.
- 하단에는 기존과 동일하게 베타 기준 변동 가능성과 공식 가이드 확인 안내가 표시됩니다.

## 구조

- `official`: OpenAI 공식 Help Center, 정책, 공지 URL
- `kr_ops`: 완성된 국내 영업 가이드와 OpenAI 담당자 회신 확정 정보
- `pending`: OpenAI 확인 대기 항목
- 벡터 저장소: Supabase Postgres + `pgvector`
- DB schema: `openai_ads_rag`
- 크롤러 체크 API: `POST /check`
- 파비콘 체크 API: `POST /check-favicon`
- RAG 챗 API: `POST /chat`

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

Streamlit:

```powershell
streamlit run ui.py
```

Vercel은 루트 `app.py`의 FastAPI `app`을 zero-config 엔트리포인트로 감지합니다. `/check`는 robots.txt 셀프 체크, `/check-favicon`은 파비콘 규격 체크, `/chat`은 RAG Q&A입니다.

검증:

```powershell
python -m unittest discover -s tests
python -B -m py_compile app.py checker.py favicon_checker.py ingest.py ui.py
```

RAG API 직접 호출:

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
- 크리테오 경유 세부 질문은 "크리테오 경유 세부사항은 크리테오 코리아에 확인이 필요합니다."로 라우팅합니다.
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

배포 전 로컬에서 `python ingest.py`로 Supabase에 문서를 인덱싱합니다. 민감 환경변수를 로컬로 내려받을 수 없는 경우에는 `INGEST_TOKEN`을 설정한 뒤 배포된 `POST /admin/reindex`를 호출해 Vercel 런타임에서 재인덱싱할 수 있습니다.

크롤러 셀프 체크(`/check`)는 Supabase 인덱싱 없이도 동작합니다.

파비콘 셀프 체크(`/check-favicon`)도 Supabase 인덱싱 없이 동작합니다.

## 자동 재인덱싱

`.github/workflows/reindex-openai-help.yml`은 KST 09:00, 21:00에 `python ingest.py --collection official`을 실행합니다. GitHub repository secrets에 아래 값을 등록해야 동작합니다.

- `OPENAI_API_KEY`
- `SUPABASE_DB_URL`
- `SUPABASE_SCHEMA` (기본 `openai_ads_rag`)
- `OPENAI_EMBEDDING_MODEL`, `OPENAI_EMBEDDING_DIMENSIONS`, `EMBEDDING_BATCH_SIZE` (기본값 사용 가능)

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
