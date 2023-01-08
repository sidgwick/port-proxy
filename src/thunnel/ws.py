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


def _decode(data: bytes) -> tuple[int, WebsocketFrame]:
    '''decode frame from data

    Returns:
    Frame: 帧结果
    '''

    def readx(l) -> tuple[bytes, bytes]:
        if len(data) < l:
            raise WebsocketReadError(f"获取不到合法的 websocket 数据帧")
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

    frame = WebsocketFrame(fin, opcode, length=length, data=_data)
    logging.debug(f"websocket frame found: {frame}")
    return raw - len(data), frame


def decode(data) -> tuple[int, WebsocketFrame]:
    try:
        cl, frame = _decode(data)
        return cl, frame
    except Exception as e:
        logging.error(f"decode websocket frame error: {e}")

    return 0, None


def encode(data: bytes) -> bytes:
    '''构造 websocket 数据帧(网络传输)'''
    result = b''

    fin = 1  # 1
    opcode = _opBinFrame
    masked = 0

    b0 = (fin << 7 | opcode)
    b1 = masked
    length = b''

    _length = len(data)

    if _length > 0xFFFF:
        b1 |= 0x7f  # 8bytes length
        length = struct.pack('>Q', _length)
    elif _length > 0xFF:
        b1 |= 0x7e  # 2bytes length
        length = struct.pack('>H', _length)
    else:
        b1 |= _length

    result = bytearray()
    result.append(b0)
    result.append(b1)
    result.extend(length)
    result.extend(data)

    return result


class WebsocketFrame():

    def __init__(self, fin=False, opcode=None, mask=None, length=0, data=b''):
        self.fin: bool = fin
        self.rsv1 = None
        self.rsv2 = None
        self.rsv3 = None
        self.opcode = opcode
        self.mask = mask

        self.length: int = length
        self.data: bytes = data

    def __str__(self):
        return f"WSFrame({self.fin}, {self.length})"

    def append(self, data: bytes) -> int:
        '''往非结束数据帧里面追加数据'''
        if len(data) == 0:
            return 0

        if self.fin:
            return 0

        cl, frame = decode(data)

        self.fin = frame.fin
        self.length += frame.length
        self.data += frame.data

        return cl


class WebsocketConnection(ThunnelConnection):

    def __init__(self, name='', sock: socket.socket = None):
        super(WebsocketConnection, self).__init__()

        self.name = name
        self.sock = sock

        self.ip = None
        self.port = None

        self.buffer: bytes = b''
        self.recv_data: bytes = b''
        self.frame: WebsocketFrame = None

    def __str__(self):
        return f'ws://{self.ip}:{self.port}'

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
        res = self.sock.sendall(frame)
        return res

    def recv(self, n=1024):
        if n != 0 and len(self.recv_data) > n:
            res = self.recv_data[:n]
            self.recv_data = self.recv_data[n:]
            return res

        if self.sock is None:
            return None

        print(f'aaaaaaaa: {self.recv_data}')
        self.recv_frame()
        print(f'bbbbbbbb: {self.recv_data}')

        if n > len(self.recv_data):
            n = len(self.recv_data)

        res = self.recv_data[:n]
        self.recv_data = self.recv_data[n:]
        return res

    def disconnect(self):
        if self.sock is None:
            return

        self.sock.close()

    def recv_frame(self):

        def read_all(sock: socket.socket) -> bytes:
            _data = bytearray()
            while True:
                tmp = self.sock.recv(1024)
                print(f'recv_frame data read: {tmp}')
                _data.extend(tmp)
                if len(tmp) < 1024:
                    break

            return _data

        def decode_all(data: bytes, frame: WebsocketFrame) -> tuple[bytes, WebsocketFrame]:
            if len(data) == 0:
                return data, None

            _cl = None
            if frame is None:
                _cl, frame = decode(data)

            # 无法再从缓存中解析出数据帧, 就可以退出函数了
            if frame is None:
                return data, None

            # 更正消费掉的数据
            data = data[_cl:]

            if frame.fin:
                self.recv_data += frame.data
                frame = None

            if frame and frame.fin:
                cl = frame.append(data)
                data = data[cl:]

            # 继续解析后续的数据帧
            data, frame = decode_all(data, frame)
            return data, frame

        _data = b''
        try:
            # 从套接字中读取全部数据, 存到对象缓存中
            _data = read_all(self.sock)
        except BlockingIOError as e:
            print(f"socket buffer empty, use local buffer")

        try:
            data = self.buffer + _data
            self.buffer, self.frame = decode_all(data, self.frame)
        except WebsocketReadError as e:
            print(f"Error decoding websocket frame, error={e}")


class Client(WebsocketConnection, ThunnelClient):

    def __init__(self, name="", ip=None, port=None):
        WebsocketConnection.__init__(self, name=name, sock=None)
        self.ip = ip
        self.port = port
        self.name = name
        self.sock = None

    def connect(self):
        '''connect to remote server'''
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((self.ip, self.port))

        self.sock = sock
        self.http_upgrade_request()
        self.websocket_client_handshake()
        sock.setblocking(False)

    def websocket_client_handshake(self):
        sock = self.sock
        data = sock.recv(1024)

        logging.info(f"websocket handshake response :\n{data}")

        first, headers, body = util.parse_http(data)

        if first == "HTTP/1.1 101 Switching Protocols":
            self.buffer += body
            return

        if first == "HTTP/1.1 400 Bad Request":
            self.sock.close()

    def http_upgrade_request(self):
        '''发送建立 websocket 链接请求'''
        req = "HTTP/1.1 101 Switching Protocols\r\n" + \
              "Upgrade: websocket\r\n" + \
              "Connection: Upgrade\r\n" + \
              "Sec-WebSocket-Key: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=\r\n\r\n"

        req = req.encode()
        n = self.sock.send(req)
        logging.info(f"websocket request send:\n{req}")


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
        conn.buffer = data

        sock.setblocking(False)
        return conn

    def websocket_server_handshake(self, sock: socket.socket) -> bytes:
        '''初始化 websocket 链接, 完成握手等动作, 为后续的接收/发送数据做准备'''
        data = sock.recv(1024)

        logging.debug(f"websocket handshake request:\n{data}")

        first, headers, body = util.parse_http(data)
        if first != "HTTP/1.1 101 Switching Protocols":
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
        key = headers.get("Sec-WebSocket-Key")

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
        logging.debug(f"websocket handshake response:\n{resp}")
        sock.send(resp)

        # 正常情况下 body 是没有数据的, 因为握手完成之前应该没有帧数据
        return body
