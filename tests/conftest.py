"""
إعدادات pytest المشتركة.

الهدف: عزل الاختبارات عن قاعدة بيانات التطوير ومن أي اتصال خارجي.
نستخدم SQLite داخل الذاكرة لكل جلسة اختبار، ونفرض وضع التجربة
(PROMPT_MOCK) داخل الاختبارات نفسها عبر monkeypatch.
"""

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# جعل مجلد المشروع قابلًا للاستيراد عند التشغيل من أي مجلد
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# قاعدة بيانات داخل الذاكرة (مشتركة بين الخيوط عبر StaticPool)
engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


@pytest.fixture(scope="session", autouse=True)
def _prepare_db() -> None:
    """ينشئ الجداول مرة واحدة قبل أي اختبار."""
    from app import models  # noqa: F401 — تسجيل النماذج في metadata
    from app.database import Base

    Base.metadata.create_all(bind=engine)


@pytest.fixture
def override_get_db():
    """FastAPI dependency بديل يشير إلى قاعدة بيانات الاختبار."""
    from app.database import get_db

    def _get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    return _get_db


@pytest.fixture
def client(override_get_db):
    """
    TestClient مع استبدال قاعدة البيانات.

    لا نستخدم `with client` حتى لا يُشغَّل lifespan، لأنه ينشئ مجلدات وينظّف
    ملفات ويصل إلى قاعدة بيانات التطوير (data/promptcraft.db).
    """
    from fastapi.testclient import TestClient

    from app.database import get_db
    from app.main import app

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def auth_client(client):
    """TestClient مسجّل الدخول باسم user واحد — جاهز لطلبات محمية."""
    response = client.post("/api/auth/login", json={"username": "tester"})
    assert response.status_code == 200, response.text
    return client


@pytest.fixture
def mock_prompt_mode(monkeypatch):
    """يفرض وضع التجربة لتوليد البرومبتات داخل الاختبار فقط."""
    from app.config import settings

    monkeypatch.setattr(settings, "PROMPT_MOCK", True, raising=False)
    return settings