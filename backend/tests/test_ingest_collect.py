"""원본 수용(매직바이트·검역)과 live 수집기(botocore Stubber) 테스트."""
import socket
import threading
from datetime import datetime, timezone

import boto3
import pytest
from botocore.stub import Stubber

from gapcheck.ingest.ingest import RejectedArtifact, ingest_bytes
from gapcheck.ingest.scanner import ClamdScanner
from gapcheck.observe import aws_collect


def test_extension_content_mismatch_rejected():
    with pytest.raises(RejectedArtifact, match="실제 내용"):
        ingest_bytes("정책.docx", b"%PDF-1.7 fake", "policy_document")


def test_disallowed_extension_rejected():
    with pytest.raises(RejectedArtifact, match="허용하지 않는"):
        ingest_bytes("run.exe", b"MZ", "policy_document")


def test_not_scanned_is_recorded_honestly():
    a = ingest_bytes("x.json", b"{}", "aws_snapshot_file")
    assert a.scan_status == "not_scanned"


def _fake_clamd(reply: bytes):
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)

    def serve():
        conn, _ = srv.accept()
        buf = b""
        while not buf.endswith(b"\0\0\0\0"):
            chunk = conn.recv(65536)
            if not chunk:
                break
            buf += chunk
        conn.sendall(reply)
        conn.close()
    threading.Thread(target=serve, daemon=True).start()
    return srv.getsockname()[1]


def test_clamd_infected_is_rejected():
    port = _fake_clamd(b"stream: Eicar-Test-Signature FOUND\0")
    with pytest.raises(RejectedArtifact, match="악성코드"):
        ingest_bytes("x.json", b"{}", "aws_snapshot_file", ClamdScanner("127.0.0.1", port))


def test_clamd_clean():
    port = _fake_clamd(b"stream: OK\0")
    a = ingest_bytes("x.json", b"{}", "aws_snapshot_file", ClamdScanner("127.0.0.1", port))
    assert a.scan_status == "clean"


def _iam():
    return boto3.client("iam", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="x")


def test_collect_password_policy_ok():
    iam = _iam()
    with Stubber(iam) as st:
        st.add_response("get_account_password_policy", {"PasswordPolicy": {"MinimumPasswordLength": 8}})
        assert aws_collect.collect_password_policy(iam)["PasswordPolicy"]["MinimumPasswordLength"] == 8


def test_collect_password_policy_missing_is_recorded():
    iam = _iam()
    with Stubber(iam) as st:
        st.add_client_error("get_account_password_policy", "NoSuchEntity", http_status_code=404)
        assert aws_collect.collect_password_policy(iam) == {"Error": {"Code": "NoSuchEntity", "Message": ""}}


def test_collect_login_profiles_skips_users_without_password():
    iam = _iam()
    now = datetime(2026, 10, 1, 2, 0, 5, tzinfo=timezone.utc)
    with Stubber(iam) as st:
        st.add_response("list_users", {"Users": [
            {"UserName": "ops-kim", "Path": "/", "UserId": "AIDAEXAMPLE000000001", "Arn": "arn:aws:iam::111111111111:user/ops-kim", "CreateDate": now},
            {"UserName": "svc-batch", "Path": "/", "UserId": "AIDAEXAMPLE000000002", "Arn": "arn:aws:iam::111111111111:user/svc-batch", "CreateDate": now}]})
        st.add_response("get_login_profile", {"LoginProfile": {"UserName": "ops-kim", "CreateDate": now,
                                                               "PasswordResetRequired": False}}, {"UserName": "ops-kim"})
        st.add_client_error("get_login_profile", "NoSuchEntity", http_status_code=404,
                            expected_params={"UserName": "svc-batch"})
        out = aws_collect.collect_login_profiles(iam)
    assert out == {"ops-kim": {"CreateDate": now.isoformat(), "PasswordResetRequired": False}}


def test_wrong_account_aborts(tmp_path):
    class S:
        def client(self, name, **kw):
            c = boto3.client("sts", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="x")
            st = Stubber(c)
            st.add_response("get_caller_identity", {"Account": "999999999999", "Arn": "arn:aws:iam::999999999999:root", "UserId": "x"})
            st.activate()
            return c
    with pytest.raises(RuntimeError, match="계정 불일치"):
        aws_collect.collect_account(S(), "111111111111", tmp_path, "ap-northeast-2")
