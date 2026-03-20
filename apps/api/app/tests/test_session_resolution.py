import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.main import _resolve_channel_session
from app.main import _resolve_kakao_session
from app.repositories import create_session


class SessionResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        self.session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    def test_create_session_keeps_requested_id(self) -> None:
        with self.session_factory() as db:
            session = create_session(
                db,
                channel="web",
                user_id=None,
                message="안녕하세요",
                session_id="web-session-001",
            )

        self.assertEqual(session.id, "web-session-001")

    def test_resolve_channel_session_keeps_requested_id_for_new_session(self) -> None:
        with self.session_factory() as db:
            session = _resolve_channel_session(
                db,
                channel="web",
                session_id="web-session-002",
                internal_user_id=None,
                message="최근 메일 3개 보여줘",
            )

        self.assertEqual(session.id, "web-session-002")

    def test_resolve_channel_session_reuses_existing_session(self) -> None:
        with self.session_factory() as db:
            created = create_session(
                db,
                channel="web",
                user_id=None,
                message="첫 메시지",
                session_id="web-session-003",
            )

            resolved = _resolve_channel_session(
                db,
                channel="web",
                session_id="web-session-003",
                internal_user_id=None,
                message="다음 메시지",
            )

        self.assertEqual(created.id, resolved.id)
        self.assertEqual(resolved.last_message, "다음 메시지")

    def test_resolve_kakao_session_keeps_requested_id_for_new_session(self) -> None:
        with self.session_factory() as db:
            session = _resolve_kakao_session(
                db,
                session_id="kakao-session-001",
                user_id=None,
                utterance="안녕",
            )

        self.assertEqual(session.id, "kakao-session-001")

    def test_create_session_ignores_overlong_requested_id(self) -> None:
        long_session_id = "x" * 40

        with self.session_factory() as db:
            session = create_session(
                db,
                channel="web",
                user_id=None,
                message="안녕하세요",
                session_id=long_session_id,
            )

        self.assertNotEqual(session.id, long_session_id)
        self.assertEqual(len(session.id), 36)


if __name__ == "__main__":
    unittest.main()