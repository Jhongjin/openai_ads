from __future__ import annotations

import httpx
import streamlit as st

from rag_chatbot.config import load_settings


settings = load_settings()

st.set_page_config(page_title="ChatGPT 광고 Q&A", page_icon="💬", layout="centered")
st.title("ChatGPT 광고 Q&A")

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message.get("sources"):
            with st.expander("근거"):
                st.dataframe(message["sources"], use_container_width=True)

question = st.chat_input("질문을 입력하세요")
if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("근거 확인 중"):
            try:
                response = httpx.post(
                    f"{settings.chat_api_base_url.rstrip('/')}/chat",
                    json={"question": question},
                    timeout=120,
                )
                response.raise_for_status()
                payload = response.json()
                answer = payload["answer"]
                sources = payload.get("sources") or []
            except Exception as exc:
                answer = f"오류가 발생했습니다: {exc}"
                sources = []

        st.markdown(answer)
        if sources:
            with st.expander("근거"):
                st.dataframe(sources, use_container_width=True)
        st.session_state.messages.append(
            {"role": "assistant", "content": answer, "sources": sources}
        )
