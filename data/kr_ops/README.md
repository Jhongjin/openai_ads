# kr_ops 문서 위치

완성된 영업 가이드 문서(P0~P9)와 관리자가 승인한 OpenAI 담당자 회신 확정 내용을 `.md` 또는 `.txt`로 넣습니다.

메일 원문 전체를 이 폴더에 직접 넣지 마세요. OpenAI 담당자 메일은 Google Sheet에 먼저 영구 누적하고, 관리자가 `approved_summary`로 정리해 `approved_for_rag` 승인한 요약만 임시 RAG 문서로 생성해 인덱싱합니다.

크리테오 원문은 이 폴더에 넣지 마세요. 파일명에 `criteo`, `Criteo`, `크리테오`가 포함된 문서는 인덱싱에서 자동 제외됩니다.
