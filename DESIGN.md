# OpenAI 광고 사내 도구 디자인 기준

이 프로젝트는 `VoltAgent/awesome-design-md`의 디자인 분석 중 `Linear`와 `IBM Carbon` 계열이 가장 적합하다.

## 선택한 방향

- Linear: 정밀한 업무툴 감각, 얇은 hairline border, 작은 반경, 밀도 있는 카드 위계
- IBM Carbon: 엔터프라이즈 운영툴 톤, 평평한 표/입력/상태 체계, 명확한 상태 색상
- 적용 제외: 과한 그라디언트, 큰 히어로, 장식성 카드, 마케팅 랜딩 페이지식 구성

## 토큰

- Canvas: `#f4f4f4`
- Panel: `#ffffff`
- Ink: `#161616`
- Muted: `#525252`
- Hairline: `#d9dde5`
- Brand action: `#e60012`
- Info blue: `#0f62fe`
- Radius: `4px`, `6px`, `8px`
- Shadow: 기본적으로 쓰지 않고, sticky 입력부와 하단 notice에만 약하게 사용

## 컴포넌트 규칙

- 탭: 3개 탭은 항상 같은 폭의 가로 grid로 유지한다. 활성 탭은 채워진 배경, 비활성 탭은 흰 배경과 얇은 테두리.
- 카드: 질문/답변 카드는 왼쪽 브랜드 컬러 레일과 1px border로 구분한다.
- 출처: 출처 영역은 답변 하단에 고정하고 `공식`, `내부운영`, `확인대기`, `근거 없음` 배지를 같은 크기로 표시한다.
- 표: 헤더는 옅은 회색, 행은 hairline으로 나누고 hover에서만 아주 약하게 들어 올린다.
- 입력: `textarea`는 회색 surface 위에 두고 focus 시 검정 테두리와 얇은 파란 focus ring을 사용한다.
- 버튼: 기본 primary는 검정, hover와 주요 액션 강조는 브랜드 레드.

## 금지

- 랜딩 페이지식 히어로, 큰 장식 이미지, gradient orb, 과한 그림자
- 한 화면에서 지나치게 많은 브랜드 컬러 사용
- 탭/배지/표가 서로 다른 반경이나 그림자 규칙을 갖는 것
