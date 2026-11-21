"""工作区文件接口特性测试：鉴权、列表、下载与路径越界。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.auth import get_current_user
from app.main import app, download_workspace_file


@pytest.fixture
def client(workspace):
    """覆盖鉴权依赖，返回可访问工作区接口的客户端。"""
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(user_id="u1")
    test_client = TestClient(app)
    yield test_client
    test_client.close()
    app.dependency_overrides.clear()


def test_requires_login(workspace):
    """未登录访问文件列表返回 401。"""
    app.dependency_overrides.clear()
    response = TestClient(app).get("/api/workspace/files")
    assert response.status_code == 401


def test_list_files(client, workspace):
    """列表返回工作区内全部文件及相对路径、大小。"""
    (workspace / "a.md").write_text("abc", encoding="utf-8")
    (workspace / "sub").mkdir()
    (workspace / "sub" / "b.txt").write_text("hello", encoding="utf-8")

    response = client.get("/api/workspace/files")
    assert response.status_code == 200
    files = {item["name"]: item["size"] for item in response.json()["files"]}
    assert files == {"a.md": 3, "sub/b.txt": 5}


def test_download_file(client, workspace):
    """下载返回文件内容。"""
    (workspace / "报告.md").write_text("购车清单", encoding="utf-8")
    response = client.get("/api/workspace/files/报告.md")
    assert response.status_code == 200
    assert response.content.decode("utf-8") == "购车清单"


def test_download_missing_file(client):
    """文件不存在返回 404。"""
    assert client.get("/api/workspace/files/missing.md").status_code == 404


def test_download_rejects_path_outside_workspace(workspace):
    """越界路径返回 400。"""
    with pytest.raises(HTTPException) as exc:
        download_workspace_file("../forbidden.md", None)
    assert exc.value.status_code == 400
    assert exc.value.detail == "非法文件路径"
