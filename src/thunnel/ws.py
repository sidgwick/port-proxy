from __future__ import annotations
import logging
import socket
import struct
import hashlib
import base64

from .. import util
from . import ThunnelClient, ThunnelServer, ThunnelConnection
from ..exception import WebsocketReadError

WS_MAGIC_STRING = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

_opContFrame = 0x0
_opTextFrame = 0x1
_opBinFrame = 0x2
_opCloseFrame = 0x8
_opPingFrame = 0x9
_opPongFrame = 0xA


def _decode(data: bytearray) -> tuple[int, WebsocketFrame]:
    '''decode frame from data

    Returns:
    Frame: 帧结果
    '''

    def readx(l) -> tuple[bytearray, bytearray]:
        xl = len(data)
        if xl < l:
            raise WebsocketReadError(f"获取不到合法的 websocket 数据帧: {xl} < {l}")
        return data[0:l], data[l:]

    raw = len(data)
    b, data = readx(2)

    fin = b[0] & 0x80 > 0
    opcode = b[0] & 0x0F
    masked = b[1] & 0x80 > 0
    length = b[1] & 0x7F

    if length == 0x7E:
        b, data = readx(2)
        length = struct.unpack('>H', b)[0]
    elif length == 0x7F:
        b, data = readx(8)
        length = struct.unpack('>Q', b)[0]

    mask = None
    if masked:
        mask, data = readx(4)

    _data, data = readx(length)
    if masked:
        _data = [_data[i] ^ mask[i % 4] for i in range(length)]

    frame = WebsocketFrame(fin=fin, opcode=opcode, length=length, data=_data)

    cl = raw - len(data)
    logging.debug(f"websocket frame found(cl={cl}bytes): {frame}")

    return cl, frame


def decode(data: bytearray) -> tuple[int, WebsocketFrame]:
    try:
        cl, frame = _decode(data)
        return cl, frame
    except Exception as e:
        logging.error(f"decode websocket frame error: {e}")

    return 0, None


def encode(data: bytearray) -> bytearray:
    '''构造 websocket 数据帧(网络传输)'''
    result = bytearray()

    if type(data) == bytes:
        data = bytearray(data)

    fin = 1  # 1
    opcode = _opBinFrame
    masked = 0x00

    b0 = (fin << 7 | opcode)
    b1 = masked

    length = b''
    _length = len(data)

    if _length > 0xFFFF:
        b1 |= 0x7f  # 8bytes length
        length = struct.pack('>Q', _length)
    elif _length >= 0x7E:
        b1 |= 0x7e  # 2bytes length
        length = struct.pack('>H', _length)
    else:
        b1 |= _length

    result = bytearray()
    result.append(b0)
    result.append(b1)

    if len(length):
        result.extend(length)

    result.extend(data)

    return result


class WebsocketFrame():

    def __init__(self, fin=False, opcode=None, mask=None, length=0, data: bytearray = []):
        self.fin: bool = fin
        self.rsv1 = None
        self.rsv2 = None
        self.rsv3 = None
        self.opcode = opcode
        self.mask = mask

        self.length: int = length
        self.data: bytearray = data

    def __str__(self):
        return f"WSFrame({self.fin}, {self.length})"

    def append(self, data: bytearray) -> int:
        '''往非结束数据帧里面追加数据'''
        if len(data) == 0:
            return 0

        if self.fin:
            return 0

        cl, frame = decode(data)
        if frame is None:
            return 0

        self.fin = frame.fin
        self.length += frame.length
        self.data.extend(frame.data)

        return cl


class FrameCache():

    def __init__(self, sock: socket.socket):
        super(FrameCache, self).__init__()
        self.sock = sock

        self.buffer: bytearray = bytearray()
        self.data: bytearray = bytearray()
        self.frame: WebsocketFrame = None

    def set_socket(self, sock: socket.socket):
        self.sock = sock

    def add_cache(self, data: bytes):
        self.buffer += data

    def read(self, n):
        length = len(self.data)
        if length == 0:
            return None

        if length < n:
            n = length

        res = self.data[:n]
        self.data = self.data[n:]
        return res

    def readall_from_socket(self):
        try:
            self._readall()
        except BlockingIOError as e:
            logging.debug(f"read all from socket error: {e}")

    def _readall(self):
        while True:
            _data = self.sock.recv(1024)
            _data = bytearray(_data)
            self.buffer.extend(_data)
            if len(_data) < 1024:
                break

    def decode_all_frame(self):
        data = self.buffer
        frame = self.frame

        while True:
            _data, frame = self._decode_all_frame(data, frame)
            if len(data) == len(_data):
                break

            data = _data
            if frame.fin:
                self.data.extend(frame.data)
                frame = None

        self.buffer = data
        self.frame = frame

    def _decode_all_frame(self, data: bytearray, frame: WebsocketFrame) -> tuple[bytearray, WebsocketFrame]:
        if len(data) == 0:
            return data, frame

        _cl = 0
        if frame is None:
            _cl, frame = decode(data)

        # 无法再从缓存中解析出数据帧, 就可以退出函数了
        if frame is None:
            return data, None

        # 更正消费掉的数据
        data = data[_cl:]

        if not frame.fin:
            cl = frame.append(data)
            data = data[cl:]

        return data, frame


class WebsocketConnection(ThunnelConnection):

    def __init__(self, name='', sock: socket.socket = None):
        self.name = name
        self.sock = sock

        self.ip = None
        self.port = None

        self.cache = FrameCache(sock)

    def __str__(self):
        return f'ws://{self.ip}:{self.port}'

    def set_socket(self, sock: socket.socket):
        self.sock = sock
        self.cache.set_socket(sock)

    def add_cache(self, data: bytes):
        self.cache.add_cache(data)

    def alive_check(self):
        if self.sock is None:
            raise Exception('tcp connection not initialized')

        return True

    def fileno(self):
        return self.sock.fileno()

    def name(self):
        return self.name

    def getpeername(self):
        if self.sock is None:
            return ''

        return self.sock.getpeername()

    def send(self, data):
        frame = encode(data)
        self.sock.sendall(frame)
        return None

    def recvall(self):
        self.cache.readall_from_socket()
        self.cache.decode_all_frame()

    def recv(self, n=1024):
        res = self.cache.read(n)
        return res

    def disconnect(self):
        if self.sock is None:
            return

        self.sock.close()


class Client(WebsocketConnection, ThunnelClient):

    def __init__(self, name="", ip=None, port=None):
        WebsocketConnection.__init__(self, name=name, sock=None)
        self.ip = ip
        self.port = port
        self.name = name
        self.sock: socket.socket = None

    def connect(self):
        '''connect to remote server'''
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((self.ip, self.port))

        self.set_socket(sock)
        self.http_upgrade_request()
        self.websocket_client_handshake()
        sock.setblocking(False)

    def websocket_client_handshake(self):
        data = self.sock.recv(1024)

        # logging.info(f"websocket handshake response :\n{data}")

        first, headers, body = util.parse_http(data)

        if first == "HTTP/1.1 101 Switching Protocols":
            self.add_cache(body)
            return

        if first == "HTTP/1.1 400 Bad Request":
            logging.error(f"bad websocket handshake response :\n{data}")
            self.sock.close()

    def http_upgrade_request(self):
        '''发送建立 websocket 链接请求'''
        req = "GET / HTTP/1.1\r\n" + \
              "Upgrade: websocket\r\n" + \
              "Connection: Upgrade\r\n" + \
              "Sec-WebSocket-Key: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=\r\n\r\n"

        req = req.encode()
        self.sock.send(req)
        # logging.info(f"websocket request send:\n{req}")


class Server(ThunnelServer):

    def __init__(self, name="", ip=None, port=None):
        self.ip = ip
        self.port = port
        self.name = name
        self.is_server = True
        self.sock: socket.socket = None

    def __str__(self):
        return f'tcp://{self.ip}:{self.port}'

    def fileno(self):
        return self.sock.fileno()

    def serve(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        sock.bind((self.ip, self.port))
        sock.listen()
        sock.setblocking(False)

        self.sock = sock

    def accept(self) -> ThunnelConnection:
        sock, _addr = self.sock.accept()
        sock.setblocking(True)

        conn = WebsocketConnection(sock=sock)
        data = self.websocket_server_handshake(sock)
        conn.add_cache(data)

        sock.setblocking(False)
        return conn

    def websocket_server_handshake(self, sock: socket.socket) -> bytes:
        '''初始化 websocket 链接, 完成握手等动作, 为后续的接收/发送数据做准备'''
        data = b''
        while True:
            _data = sock.recv(1024)
            data += _data
            if len(_data) < 1024:
                break

        # logging.debug(f"websocket handshake request:\n{data}")

        first, headers, body = util.parse_http(data)
        if first[:3] == "GET" and first[-8:] == "HTTP/1.1":
            raise Exception('Websocket Switching Protocols request except')

        # is it a websocket request?
        connection = headers.get("Connection")
        upgrade = headers.get("Upgrade")
        is_websocket_req = connection == "Upgrade" and upgrade == "websocket"
        if not is_websocket_req:
            resp = "HTTP/1.1 400 Bad Request\r\n" + \
                    "Content-Type: text/plain\r\n" + \
                    "Connection: close\r\n" + \
                    "\r\n" + \
                    "Incorrect request"

            resp = resp.encode()
            logging.debug(f"bad websocket handshake response:\n{resp}")
            sock.send(resp)
            sock.close()

            return body

        # let's shake hands shall we?
        key = headers.get("Sec-Websocket-Key")

        # calculating response as per protocol RFC
        key = key + WS_MAGIC_STRING

        h = hashlib.sha1(key.encode()).digest()
        resp_key = base64.standard_b64encode(h)
        resp_key = resp_key.decode()

        resp = "HTTP/1.1 101 Switching Protocols\r\n" + \
               "Upgrade: websocket\r\n" + \
               "Connection: Upgrade\r\n" + \
               f"Sec-WebSocket-Accept: {resp_key}\r\n\r\n"

        resp = resp.encode()
        # logging.debug(f"websocket handshake response:\n{resp}")
        sock.send(resp)

        # 正常情况下 body 是没有数据的, 因为握手完成之前应该没有帧数据
        return body
