"""MCP 接口鉴权的单元测试。"""

import asyncio
import unittest

from module.webui import mcp_auth


def _headers(**kwargs):
    """把关键字参数转成 ASGI 风格的请求头列表。"""
    return [
        (name.replace("_", "-").encode("latin-1"), value.encode("latin-1"))
        for name, value in kwargs.items()
    ]


class TestMcpAuthState(unittest.TestCase):
    def setUp(self):
        mcp_auth._reset()

    def tearDown(self):
        mcp_auth._reset()

    def test_default_disabled(self):
        self.assertFalse(mcp_auth.enabled())
        self.assertFalse(mcp_auth.deny_all())
        self.assertFalse(mcp_auth.check("anything"))

    def test_configure_blank_key_is_disabled(self):
        mcp_auth.configure("   ")
        self.assertFalse(mcp_auth.enabled())
        mcp_auth.configure("key")
        self.assertTrue(mcp_auth.enabled())

    def test_deny_all_only_when_public_bind(self):
        mcp_auth.configure(None, public_bind=False)
        self.assertFalse(mcp_auth.deny_all())
        mcp_auth.configure(None, public_bind=True)
        self.assertTrue(mcp_auth.deny_all())
        # 配置了密码就不再是兜底拒绝状态
        mcp_auth.configure("key", public_bind=True)
        self.assertFalse(mcp_auth.deny_all())

    def test_check(self):
        mcp_auth.configure("s3cret")
        self.assertTrue(mcp_auth.check("s3cret"))
        self.assertFalse(mcp_auth.check("wrong"))
        self.assertFalse(mcp_auth.check(None))
        self.assertFalse(mcp_auth.check(""))

    def test_check_non_ascii_password(self):
        # compare_digest 对含非 ASCII 的 str 会抛 TypeError，必须先编码
        mcp_auth.configure("密码123")
        self.assertTrue(mcp_auth.check("密码123"))
        self.assertFalse(mcp_auth.check("密码124"))

    def test_configure_clears_sessions(self):
        mcp_auth.configure("key")
        mcp_auth.register_session("a" * 32)
        self.assertTrue(mcp_auth.is_authorized_session("a" * 32))
        mcp_auth.configure("key")
        self.assertFalse(mcp_auth.is_authorized_session("a" * 32))


class TestExtractCredential(unittest.TestCase):
    def setUp(self):
        mcp_auth._reset()

    def test_bearer_header(self):
        for value in ("Bearer key", "bearer key", "BEARER key"):
            self.assertEqual(
                mcp_auth.extract_credential(_headers(authorization=value), b""), "key"
            )

    def test_bearer_requires_prefix(self):
        self.assertIsNone(
            mcp_auth.extract_credential(_headers(authorization="key"), b"")
        )

    def test_x_api_key_header(self):
        self.assertEqual(
            mcp_auth.extract_credential(_headers(x_api_key="key"), b""), "key"
        )

    def test_query_parameter(self):
        self.assertEqual(mcp_auth.extract_credential([], b"key=key"), "key")
        self.assertEqual(mcp_auth.extract_credential([], b"api_key=key"), "key")
        self.assertEqual(mcp_auth.extract_credential([], b"token=key"), "key")

    def test_query_parameter_percent_encoded(self):
        self.assertEqual(
            mcp_auth.extract_credential([], b"key=%E5%AF%86%E7%A0%81"), "密码"
        )

    def test_query_parameter_raw_non_ascii(self):
        self.assertEqual(
            mcp_auth.extract_credential([], "key=密码".encode("utf-8")), "密码"
        )

    def test_invalid_query_bytes_do_not_raise(self):
        # 非 UTF-8 的原始字节退回 latin-1，只要求不抛异常且匹配不上
        candidate = mcp_auth.extract_credential([], b"key=\xff\xfe")
        self.assertIsInstance(candidate, str)
        mcp_auth.configure("s3cret")
        self.assertFalse(mcp_auth.check(candidate))
        mcp_auth._reset()

    def test_multiple_values_use_first(self):
        self.assertEqual(
            mcp_auth.extract_credential([], b"key=first&key=second"), "first"
        )

    def test_header_takes_priority_over_query(self):
        self.assertEqual(
            mcp_auth.extract_credential(
                _headers(authorization="Bearer fromheader"), b"key=fromquery"
            ),
            "fromheader",
        )

    def test_no_credential(self):
        self.assertIsNone(mcp_auth.extract_credential([], b"lines=10"))


class TestSessionRegistry(unittest.TestCase):
    def setUp(self):
        mcp_auth._reset()

    def tearDown(self):
        mcp_auth._reset()

    def test_register_and_check(self):
        mcp_auth.register_session("a" * 32)
        self.assertTrue(mcp_auth.is_authorized_session("a" * 32))
        self.assertFalse(mcp_auth.is_authorized_session("b" * 32))
        self.assertFalse(mcp_auth.is_authorized_session(None))
        self.assertFalse(mcp_auth.is_authorized_session(""))

    def test_expire_keeps_grace_window(self):
        mcp_auth.register_session("a" * 32)
        mcp_auth.expire_session("a" * 32, grace=60)
        self.assertTrue(mcp_auth.is_authorized_session("a" * 32))
        mcp_auth.expire_session("a" * 32, grace=0)
        self.assertFalse(mcp_auth.is_authorized_session("a" * 32))

    def test_expire_unknown_session_is_noop(self):
        mcp_auth.expire_session("b" * 32)
        self.assertFalse(mcp_auth.is_authorized_session("b" * 32))

    def test_capacity_evicts_oldest(self):
        for index in range(mcp_auth.SESSION_MAX_ENTRIES + 10):
            mcp_auth.register_session(f"{index:032x}")
        self.assertFalse(mcp_auth.is_authorized_session(f"{0:032x}"))
        self.assertTrue(
            mcp_auth.is_authorized_session(f"{mcp_auth.SESSION_MAX_ENTRIES + 9:032x}")
        )

    def test_extract_session_id(self):
        self.assertEqual(
            mcp_auth.extract_session_id(b"session_id=" + b"a" * 32), "a" * 32
        )
        self.assertEqual(
            mcp_auth.extract_session_id(b"session_id=" + b"A" * 32), "a" * 32
        )
        self.assertIsNone(mcp_auth.extract_session_id(b"session_id=not-a-uuid"))
        self.assertIsNone(mcp_auth.extract_session_id(b""))


class TestAuthorize(unittest.TestCase):
    def setUp(self):
        mcp_auth._reset()
        mcp_auth.configure("s3cret")

    def tearDown(self):
        mcp_auth._reset()

    def test_non_mcp_path_is_not_intercepted(self):
        self.assertEqual(
            mcp_auth.authorize("/mcp/other", "GET", [], b""), (True, None)
        )

    def test_missing_credential(self):
        self.assertEqual(
            mcp_auth.authorize("/mcp/sse", "GET", [], b""), (False, 401)
        )
        self.assertEqual(
            mcp_auth.authorize("/mcp/messages", "POST", [], b"session_id=" + b"a" * 32),
            (False, 401),
        )

    def test_wrong_credential(self):
        self.assertEqual(
            mcp_auth.authorize("/mcp/sse", "GET", _headers(authorization="Bearer no"), b""),
            (False, 401),
        )

    def test_correct_credential(self):
        self.assertEqual(
            mcp_auth.authorize(
                "/mcp/sse", "GET", _headers(authorization="Bearer s3cret"), b""
            ),
            (True, None),
        )
        self.assertEqual(
            mcp_auth.authorize("/mcp/sse", "GET", [], b"key=s3cret"), (True, None)
        )

    def test_method_whitelist(self):
        self.assertEqual(
            mcp_auth.authorize(
                "/mcp/sse", "POST", _headers(authorization="Bearer s3cret"), b""
            ),
            (False, 405),
        )
        self.assertEqual(
            mcp_auth.authorize("/mcp/messages", "GET", [], b"key=s3cret"),
            (False, 405),
        )

    def test_messages_fallback_to_authorized_session(self):
        session_id = "a" * 32
        query = f"session_id={session_id}".encode()
        self.assertEqual(
            mcp_auth.authorize("/mcp/messages", "POST", [], query), (False, 401)
        )
        mcp_auth.register_session(session_id)
        self.assertEqual(
            mcp_auth.authorize("/mcp/messages", "POST", [], query), (True, None)
        )
        # 会话兜底只对 /messages 生效，不能拿去连 SSE
        self.assertEqual(
            mcp_auth.authorize("/mcp/sse", "GET", [], query), (False, 401)
        )

    def test_deny_all_when_key_missing_on_public_bind(self):
        mcp_auth.configure(None, public_bind=True)
        self.assertEqual(
            mcp_auth.authorize("/mcp/sse", "GET", [], b""), (False, 503)
        )
        self.assertEqual(
            mcp_auth.authorize(
                "/mcp/sse", "GET", _headers(authorization="Bearer anything"), b""
            ),
            (False, 503),
        )

    def test_open_when_key_missing_on_loopback(self):
        mcp_auth.configure(None, public_bind=False)
        self.assertEqual(
            mcp_auth.authorize("/mcp/sse", "GET", [], b""), (True, None)
        )


class TestRedact(unittest.TestCase):
    def test_query_parameters(self):
        self.assertEqual(mcp_auth.redact("/mcp/sse?key=abc"), "/mcp/sse?key=***")
        self.assertEqual(mcp_auth.redact("/mcp/sse?api_key=abc"), "/mcp/sse?api_key=***")
        self.assertEqual(mcp_auth.redact("/mcp/sse?token=abc"), "/mcp/sse?token=***")
        self.assertEqual(
            mcp_auth.redact("/mcp/messages?session_id=deadbeef"),
            "/mcp/messages?session_id=***",
        )

    def test_keeps_other_parameters(self):
        self.assertEqual(
            mcp_auth.redact("/mcp/messages?session_id=abc&lines=20"),
            "/mcp/messages?session_id=***&lines=20",
        )

    def test_bearer_header(self):
        self.assertEqual(
            mcp_auth.redact("Authorization: Bearer abc.def"), "Authorization: Bearer ***"
        )

    def test_access_log_line(self):
        self.assertEqual(
            mcp_auth.redact(
                '127.0.0.1:1234 - "GET /mcp/sse?key=abc HTTP/1.1" 200'
            ),
            '127.0.0.1:1234 - "GET /mcp/sse?key=*** HTTP/1.1" 200',
        )

    def test_empty_input(self):
        self.assertEqual(mcp_auth.redact(""), "")
        self.assertIsNone(mcp_auth.redact(None))


class TestSniffSessionId(unittest.TestCase):
    """从 SSE 出站流中捕获 session_id 的逻辑。"""

    def setUp(self):
        mcp_auth._reset()
        from mcp_server_sse import _sniff_session_id

        self.sniff = _sniff_session_id
        self.buffer = [b""]
        self.captured = []

    def _body(self, text):
        return {"type": "http.response.body", "body": text}

    def _endpoint_event(self, session_id):
        return (
            f"event: endpoint\r\ndata: /mcp/messages/?session_id={session_id}\r\n\r\n"
        ).encode()

    def test_captures_endpoint_session(self):
        session_id = "ab" * 16
        self.sniff(self._body(self._endpoint_event(session_id)), self.buffer, self.captured)
        self.assertEqual(self.captured, [session_id])
        self.assertTrue(mcp_auth.is_authorized_session(session_id))

    def test_captures_when_split_across_chunks(self):
        # SSE 分块边界不固定，session_id 被切开也要能拼回来
        session_id = "cd" * 16
        event = self._endpoint_event(session_id)
        cut = event.index(b"session_id=") + 8
        self.sniff(self._body(event[:cut]), self.buffer, self.captured)
        self.assertEqual(self.captured, [])
        self.sniff(self._body(event[cut:]), self.buffer, self.captured)
        self.assertEqual(self.captured, [session_id])
        self.assertTrue(mcp_auth.is_authorized_session(session_id))

    def test_ignores_non_body_messages(self):
        self.sniff(
            {"type": "http.response.start", "status": 200}, self.buffer, self.captured
        )
        self.sniff({"type": "http.response.body", "body": b""}, self.buffer, self.captured)
        self.assertEqual(self.captured, [])

    def test_ignores_body_without_session_id(self):
        self.sniff(self._body(b"event: message\ndata: {}\n\n"), self.buffer, self.captured)
        self.assertEqual(self.captured, [])

    def test_stops_after_first_capture(self):
        # 捕获后再出现的 session_id 不应被登记，避免伪造的 SSE 帧扩大会话表
        self.sniff(self._body(self._endpoint_event("ab" * 16)), self.buffer, self.captured)
        self.sniff(self._body(self._endpoint_event("ef" * 16)), self.buffer, self.captured)
        self.assertEqual(self.captured, ["ab" * 16])
        self.assertFalse(mcp_auth.is_authorized_session("ef" * 16))

    def test_non_hex_session_is_not_captured(self):
        self.sniff(self._body(b"data: /mcp/messages/?session_id=not-a-uuid\r\n\r\n"),
                   self.buffer, self.captured)
        self.assertEqual(self.captured, [])

    def test_buffer_is_bounded(self):
        # 长时间无 session_id 的流不应无限占用内存
        for _ in range(50):
            self.sniff(self._body(b"x" * 4096), self.buffer, self.captured)
        self.assertLessEqual(len(self.buffer[0]), 4096)


class TestAsgiGuard(unittest.TestCase):
    """鉴权守卫在真实 ASGI 应用上的行为。"""

    @classmethod
    def setUpClass(cls):
        from mcp_server_sse import mcp_asgi_app

        cls.app = staticmethod(mcp_asgi_app)

    def setUp(self):
        mcp_auth._reset()
        mcp_auth.configure("s3cret")

    def tearDown(self):
        mcp_auth._reset()

    def _request(self, path, method="GET", query=b"", headers=()):
        scope = {
            "type": "http",
            "path": path,
            "method": method,
            "query_string": query,
            "headers": list(headers),
            "client": ("127.0.0.1", 12345),
        }
        messages = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        asyncio.run(self.app(scope, receive, send))
        return messages

    def test_sse_without_credential_is_unauthorized(self):
        messages = self._request("/mcp/sse")
        self.assertEqual(messages[0]["status"], 401)
        # 不带 WWW-Authenticate，避免客户端误判为要求 OAuth
        header_names = [name.lower() for name, _ in messages[0]["headers"]]
        self.assertNotIn(b"www-authenticate", header_names)

    def test_messages_without_credential_is_unauthorized(self):
        messages = self._request(
            "/mcp/messages", method="POST", query=b"session_id=" + b"a" * 32
        )
        self.assertEqual(messages[0]["status"], 401)

    def test_wrong_method_is_rejected(self):
        messages = self._request(
            "/mcp/sse", method="POST", headers=_headers(authorization="Bearer s3cret")
        )
        self.assertEqual(messages[0]["status"], 405)

    def test_deny_all_on_public_bind_without_key(self):
        mcp_auth.configure(None, public_bind=True)
        messages = self._request("/mcp/sse")
        self.assertEqual(messages[0]["status"], 503)

    def test_unknown_path_is_not_found(self):
        messages = self._request("/mcp/unknown", headers=_headers(authorization="Bearer s3cret"))
        self.assertEqual(messages[0]["status"], 404)


if __name__ == "__main__":
    unittest.main()
