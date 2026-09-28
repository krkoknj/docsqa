import json

from sqlalchemy import text

from tests.integration.conftest import signup, wait_until_indexed

HANDBOOK = (
    "# 핸드북\n\n배포는 매일 오전 10시와 오후 3시에 진행한다. 금요일 오후 3시 이후에는 배포를 금지한다.\n".encode()
)


def parse_sse(body: str) -> list[tuple[str, object]]:
    events = []
    for block in body.replace("\r\n", "\n").strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.split("\n") if ": " in line)
        if "event" in fields:
            events.append((fields["event"], json.loads(fields["data"])))
    return events


def upload(session, name="handbook.md", data=HANDBOOK):
    return session.post("/api/documents", files={"file": (name, data, "text/markdown")})


def chat(session, question="배포는 언제 해?", **body):
    res = session.post("/api/chat", json={"question": question, **body})
    assert res.status_code == 200, res.text
    return parse_sse(res.text)


# --- auth -------------------------------------------------------------------------------


def test_signup_sets_http_only_session_cookie_and_me_returns_user(client):
    res, email = signup(client)

    assert res.status_code == 201
    set_cookie = res.headers["set-cookie"].lower()
    assert "docsqa_session=" in set_cookie and "httponly" in set_cookie and "samesite=lax" in set_cookie
    assert client.get("/api/auth/me").json()["email"] == email


def test_duplicate_email_is_rejected_case_insensitively(client):
    _, email = signup(client)
    res, _ = signup(client, email=email.upper())
    assert res.status_code == 409


def test_login_checks_password_and_does_not_reveal_which_part_was_wrong(client):
    _, email = signup(client)
    client.cookies.clear()

    wrong_password = client.post("/api/auth/login", json={"email": email, "password": "wrong-password"})
    unknown_email = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "password123"})
    ok = client.post("/api/auth/login", json={"email": email, "password": "password123"})

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()
    assert ok.status_code == 200


def test_logout_clears_cookie(client):
    signup(client)
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_protected_endpoints_require_login(client):
    client.cookies.clear()
    assert client.get("/api/documents").status_code == 401
    assert client.get("/api/conversations").status_code == 401
    assert client.post("/api/chat", json={"question": "hi"}).status_code == 401


def test_tampered_token_is_rejected(new_user):
    user = new_user()
    user.token = user.token[:-4] + ("AAAA" if not user.token.endswith("AAAA") else "BBBB")
    assert user.get("/api/auth/me").status_code == 401


# --- documents & indexing queue ------------------------------------------------------------


def test_upload_is_queued_then_indexed_by_worker(new_user):
    user = new_user()

    res = upload(user)

    assert res.status_code == 202
    assert res.json()["status"] == "pending"
    doc = wait_until_indexed(user, res.json()["id"])
    assert doc["status"] == "ready"
    assert doc["chunk_count"] >= 1


def test_unreadable_file_fails_with_message_and_can_be_retried(new_user):
    user = new_user()
    doc_id = upload(user, name="broken.pdf", data=b"not really a pdf").json()["id"]

    doc = wait_until_indexed(user, doc_id)

    assert doc["status"] == "failed"
    assert doc["error"]
    retried = user.post(f"/api/documents/{doc_id}/retry")
    assert retried.status_code == 200 and retried.json()["status"] == "pending"


def test_rejects_unsupported_extension_before_queueing(new_user):
    res = upload(new_user(), name="image.png", data=b"\x89PNG")
    assert res.status_code == 415


def test_deleting_document_cascades_to_chunks(client, new_user):
    user = new_user()
    doc_id = upload(user).json()["id"]
    wait_until_indexed(user, doc_id)

    assert user.delete(f"/api/documents/{doc_id}").status_code == 204

    async def count_chunks():
        async with client.app.state.db.engine.connect() as conn:
            return await conn.scalar(text("SELECT count(*) FROM chunks WHERE document_id = :id"), {"id": doc_id})

    assert client.portal.call(count_chunks) == 0


# --- isolation between users -----------------------------------------------------------


def test_users_cannot_see_or_delete_each_others_documents(new_user):
    alice, bob = new_user(), new_user()
    doc_id = upload(alice).json()["id"]
    wait_until_indexed(alice, doc_id)

    assert bob.get("/api/documents").json() == []
    assert bob.delete(f"/api/documents/{doc_id}").status_code == 404
    assert len(alice.get("/api/documents").json()) == 1


def test_chat_never_retrieves_other_users_chunks(new_user):
    alice, bob = new_user(), new_user()
    doc_id = upload(alice).json()["id"]
    wait_until_indexed(alice, doc_id)

    # Bob has no documents; even naming Alice's document id explicitly must not reach it.
    for body in ({}, {"document_ids": [doc_id]}):
        events = chat(bob, **body)
        sources = [s for e, d in events if e == "sources" for s in d]
        assert sources == []


def test_chat_retrieves_own_documents(new_user):
    alice = new_user()
    doc_id = upload(alice).json()["id"]
    wait_until_indexed(alice, doc_id)

    events = chat(alice)

    sources = next(d for e, d in reversed(events) if e == "sources")
    assert {s["document_id"] for s in sources} == {doc_id}
    assert events[-1][0] == "done"


# --- conversations ------------------------------------------------------------------------


def test_conversation_is_created_saved_and_continued(new_user):
    user = new_user()
    wait_until_indexed(user, upload(user).json()["id"])

    first = chat(user, question="배포는 언제 해?")
    event, conversation = first[0]
    assert event == "conversation"
    assert conversation["title"] == "배포는 언제 해?"

    second = chat(user, question="금요일은?", conversation_id=conversation["id"])
    assert second[0][1]["id"] == conversation["id"]

    listed = user.get("/api/conversations").json()
    assert [c["id"] for c in listed] == [conversation["id"]]
    detail = user.get(f"/api/conversations/{conversation['id']}").json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant", "user", "assistant"]
    assert detail["messages"][1]["sources"]  # sources are persisted with the answer
    assert detail["messages"][1]["grounded"] is True


def test_users_cannot_read_or_continue_each_others_conversations(new_user):
    alice, bob = new_user(), new_user()
    conversation_id = chat(alice)[0][1]["id"]

    assert bob.get(f"/api/conversations/{conversation_id}").status_code == 404
    assert bob.post("/api/chat", json={"question": "hi", "conversation_id": conversation_id}).status_code == 404
    assert bob.delete(f"/api/conversations/{conversation_id}").status_code == 404


def test_chat_validates_question(new_user):
    assert new_user().post("/api/chat", json={"question": ""}).status_code == 422
