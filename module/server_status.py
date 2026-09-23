"""游戏服务器网关状态查询。

公共服务器状态 API 不可用时，本模块直接请求各地区的游戏网关，取得与
API 相同的原始服务器状态。这里刻意不引入异步服务、缓存或 Web 框架：
调度器本身是同步调用，后备查询只需要读取当前配置中的一个服务器。
"""

import json
import socket
import struct
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit


MSG_CS_10018 = 10018
MSG_SC_10019 = 10019

ServerState = Literal[
    'normal', 'maintenance', 'full', 'reg_full', 'unopened', 'unknown'
]


@dataclass(frozen=True)
class RegionEndpoint:
    """游戏服务器列表网关的连接信息。"""

    protocol: Literal['tcp', 'http']
    host: str = ''
    port: int = 0
    url: str = ''


# 与 AzurLaneServerStatus 项目保持一致。CN iOS 和渠道服使用 HTTP，其他
# ALAS 支持的地区使用游戏的 10018/10019 TCP 协议。
REGION_ENDPOINTS: dict[str, RegionEndpoint] = {
    'cn': RegionEndpoint('tcp', host='118.178.152.242', port=80),
    'cn_ios': RegionEndpoint(
        'http', url='http://203.107.54.122/?cmd=load_server?'
    ),
    'cn_channel': RegionEndpoint(
        'http', url='http://203.107.54.70/?cmd=load_server?'
    ),
    'en': RegionEndpoint('tcp', host='blhxusgate.yo-star.com', port=80),
    'jp': RegionEndpoint('tcp', host='blhxjploginapi.azurlane.jp', port=80),
    'tw': RegionEndpoint('tcp', host='prod-all-login.azurlane.tw', port=10080),
}

_STATUS_MAP: dict[int, ServerState] = {
    0: 'normal',
    1: 'maintenance',
    2: 'full',
    3: 'reg_full',
    99: 'unopened',
}


class ServerStatusProtocolError(ValueError):
    """网关响应的协议或数据结构不符合预期。"""


class ServerStatusQueryError(ConnectionError):
    """后备网关查询失败。

    Attributes:
        code: 稳定的故障类型，供日志和调用方诊断。
    """

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class GatewayServer:
    """游戏网关返回的单个服务器原始信息。"""

    id: int
    name: str
    state: int
    tag_state: int
    sort: int

    @property
    def status(self) -> ServerState:
        """将游戏协议中的状态数字转换为调度器使用的状态文本。"""
        return _STATUS_MAP.get(self.state, 'unknown')


FieldEntry = tuple[Literal['varint', 'bytes', '32bit'], int | bytes]
FieldMap = dict[int, list[FieldEntry]]


def _encode_varint(value: int) -> bytes:
    """编码无符号 protobuf varint。"""
    if value < 0:
        raise ValueError('Varint value must not be negative')

    result = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            byte |= 0x80
        result.append(byte)
        if not value:
            return bytes(result)


def _encode_varint_field(field_number: int, value: int) -> bytes:
    """编码 protobuf 的 varint 字段。"""
    return _encode_varint(field_number << 3) + _encode_varint(value)


def _decode_varint(data: bytes, offset: int = 0) -> tuple[int, int]:
    """解码 protobuf varint，并拒绝截断或超长的数据。"""
    result = 0
    shift = 0
    while True:
        if offset >= len(data) or shift >= 64:
            raise ServerStatusProtocolError('无效的 protobuf varint')
        byte = data[offset]
        result |= (byte & 0x7F) << shift
        offset += 1
        if not byte & 0x80:
            return result, offset
        shift += 7


def decode_protobuf_message(data: bytes, offset: int = 0) -> FieldMap:
    """解码本协议使用的 protobuf varint、bytes 与 fixed32 字段。"""
    fields: FieldMap = {}
    while offset < len(data):
        tag, offset = _decode_varint(data, offset)
        field_number = tag >> 3
        wire_type = tag & 0x7
        if wire_type == 0:
            value, offset = _decode_varint(data, offset)
            fields.setdefault(field_number, []).append(('varint', value))
        elif wire_type == 2:
            length, offset = _decode_varint(data, offset)
            end = offset + length
            if end > len(data):
                raise ServerStatusProtocolError('protobuf bytes 字段被截断')
            fields.setdefault(field_number, []).append(('bytes', data[offset:end]))
            offset = end
        elif wire_type == 5:
            if offset + 4 > len(data):
                raise ServerStatusProtocolError('protobuf fixed32 字段被截断')
            value = struct.unpack_from('<I', data, offset)[0]
            fields.setdefault(field_number, []).append(('32bit', value))
            offset += 4
        else:
            raise ServerStatusProtocolError(f'不支持的 protobuf wire type: {wire_type}')
    return fields


def _build_packet(msg_id: int, body: bytes) -> bytes:
    """构造游戏网关使用的消息帧。"""
    remaining = 5 + len(body)
    return (
        struct.pack('>H', remaining)
        + b'\x00'
        + struct.pack('>H', msg_id)
        + struct.pack('>H', 0)
        + body
    )


def _parse_tcp_response(data: bytes) -> list[GatewayServer]:
    """校验 10019 消息帧并解析服务器列表。"""
    if len(data) < 7:
        raise ServerStatusProtocolError('TCP 响应长度不足')
    remaining = struct.unpack_from('>H', data, 0)[0]
    if remaining < 5 or len(data) != remaining + 2:
        raise ServerStatusProtocolError('TCP 响应长度无效')
    msg_id = struct.unpack_from('>H', data, 3)[0]
    if msg_id != MSG_SC_10019:
        raise ServerStatusProtocolError(f'预期消息 10019，实际为 {msg_id}')
    return decode_serverlist(data[7:])


def _decode_name(value: bytes) -> str:
    """解码服务器名称；国服名称可能是 GBK，其他地区使用 UTF-8。"""
    try:
        return value.decode('utf-8')
    except UnicodeDecodeError:
        return value.decode('gbk', errors='replace')


def _entry_bytes(entry: FieldEntry) -> bytes | None:
    """取得 protobuf bytes 字段的内容。"""
    value = entry[1]
    return value if entry[0] == 'bytes' and isinstance(value, bytes) else None


def _entry_varint(entry: FieldEntry) -> int | None:
    """取得 protobuf varint 字段的内容。"""
    value = entry[1]
    return value if entry[0] == 'varint' and isinstance(value, int) else None


def decode_serverinfo(data: bytes) -> GatewayServer:
    """解析 ServerInfo：1=id、4=state、5=name、6=tag、7=sort。"""
    server_id = 0
    name = ''
    state = 0
    tag_state = 0
    sort = 0
    for field_number, entries in decode_protobuf_message(data).items():
        for entry in entries:
            if field_number == 1:
                value = _entry_varint(entry)
                if value is not None:
                    server_id = value
                value_bytes = _entry_bytes(entry)
                if value_bytes is not None:
                    offset = 0
                    while offset < len(value_bytes):
                        server_id, offset = _decode_varint(value_bytes, offset)
            elif field_number == 4:
                value = _entry_varint(entry)
                if value is not None:
                    state = value
            elif field_number == 5:
                value = _entry_bytes(entry)
                if value is not None:
                    name = _decode_name(value)
            elif field_number == 6:
                value = _entry_varint(entry)
                if value is not None:
                    tag_state = value
            elif field_number == 7:
                value = _entry_varint(entry)
                if value is not None:
                    sort = value
    return GatewayServer(server_id, name, state, tag_state, sort)


def decode_serverlist(data: bytes) -> list[GatewayServer]:
    """解析 10019 消息体中的重复 ServerInfo 字段。"""
    servers = []
    for entry in decode_protobuf_message(data).get(1, []):
        server_data = _entry_bytes(entry)
        if server_data is not None:
            servers.append(decode_serverinfo(server_data))
    return servers


def _read_exactly(sock: socket.socket, size: int) -> bytes:
    """从 TCP 流读取指定长度，连接提前关闭视为协议错误。"""
    chunks = bytearray()
    while len(chunks) < size:
        chunk = sock.recv(size - len(chunks))
        if not chunk:
            raise ServerStatusProtocolError('TCP 响应被截断')
        chunks.extend(chunk)
    return bytes(chunks)


def query_tcp(host: str, port: int, timeout: float = 10.0) -> list[GatewayServer]:
    """向 TCP 游戏网关发送 10018 请求并读取服务器列表。"""
    request = _build_packet(MSG_CS_10018, _encode_varint_field(1, 0))
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(request)
            header = _read_exactly(sock, 2)
            remaining = struct.unpack('>H', header)[0]
            return _parse_tcp_response(header + _read_exactly(sock, remaining))
    except ServerStatusQueryError:
        raise
    except (TimeoutError, socket.timeout) as e:
        raise ServerStatusQueryError('timeout') from e
    except (ServerStatusProtocolError, UnicodeDecodeError) as e:
        raise ServerStatusQueryError('protocol_error') from e
    except OSError as e:
        raise ServerStatusQueryError('network_error') from e


def _parse_http_body(data: bytes) -> list[GatewayServer]:
    """校验 HTTP 200 响应并将 JSON 列表转换为服务器信息。"""
    separator = data.find(b'\r\n\r\n')
    if separator == -1:
        raise ServerStatusProtocolError('HTTP 响应缺少头部')
    status_line = data[:separator].decode('latin-1').split('\r\n', 1)[0]
    if not status_line.startswith('HTTP/') or ' 200 ' not in status_line:
        raise ServerStatusProtocolError(f'HTTP 响应异常: {status_line}')
    payload = json.loads(data[separator + 4:].decode('utf-8'))
    if not isinstance(payload, list):
        raise ServerStatusProtocolError('HTTP 服务器列表不是数组')

    servers = []
    for item in payload:
        if not isinstance(item, dict):
            raise ServerStatusProtocolError('HTTP 服务器项不是对象')
        try:
            server_id = int(item['id'])
            name = str(item['name'])
            state = int(item['state'])
            tag_state = int(item.get('flag', 0))
            sort = int(item.get('sort', 0))
        except (KeyError, TypeError, ValueError) as e:
            raise ServerStatusProtocolError('HTTP 服务器项字段无效') from e
        servers.append(GatewayServer(server_id, name, state, tag_state, sort))
    return servers


def query_http(url: str, timeout: float = 10.0) -> list[GatewayServer]:
    """通过原始 HTTP 请求查询国服 iOS 或渠道服列表。"""
    parts = urlsplit(url)
    host = parts.hostname
    if host is None:
        raise ServerStatusQueryError('invalid_endpoint')
    port = parts.port or 80
    path = parts.path or '/'
    if parts.query:
        path = f'{path}?{parts.query}'

    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            request = (
                f'GET {path} HTTP/1.1\r\n'
                f'Host: {host}\r\n'
                'Connection: close\r\n\r\n'
            )
            sock.sendall(request.encode('ascii'))
            chunks = bytearray()
            while chunk := sock.recv(65536):
                chunks.extend(chunk)
        return _parse_http_body(bytes(chunks))
    except ServerStatusQueryError:
        raise
    except (TimeoutError, socket.timeout) as e:
        raise ServerStatusQueryError('timeout') from e
    except (ServerStatusProtocolError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ServerStatusQueryError('protocol_error') from e
    except OSError as e:
        raise ServerStatusQueryError('network_error') from e


def query_region(region: str, timeout: float = 10.0) -> list[GatewayServer]:
    """查询一个地区的完整服务器列表。"""
    endpoint = REGION_ENDPOINTS[region]
    if endpoint.protocol == 'tcp':
        return query_tcp(endpoint.host, endpoint.port, timeout)
    return query_http(endpoint.url, timeout)


def query_server(region: str, server_id: int, timeout: float = 10.0) -> GatewayServer:
    """查询指定地区和 ID 的服务器。

    Args:
        region: 网关地区键，例如 ``cn_ios`` 或 ``jp``。
        server_id: 游戏网关中的服务器 ID。
        timeout: 单次连接、收发的超时时间（秒）。

    Raises:
        ServerStatusQueryError: 网关无法访问、响应无效或未找到指定服务器。
    """
    try:
        servers = query_region(region, timeout)
    except KeyError as e:
        raise ServerStatusQueryError('invalid_region') from e

    for server in servers:
        if server.id == server_id:
            return server
    raise ServerStatusQueryError('not_found')
