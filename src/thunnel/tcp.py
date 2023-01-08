from __future__ import annotations
import socket

from .. import util
from . import ThunnelClient, ThunnelServer, ThunnelConnection


class TcpConnection(ThunnelConnection):

    def __init__(self, name='', sock: socket.socket = None):
        super(TcpConnection, self).__init__()
        self.sock = sock

        self.ip = None
        self.port = None
        self.name = name

    def __str__(self):
        return f'tcp://{self.ip}:{self.port}'

    def alive_check(self):
        if self.sock is None:
            raise Exception('tcp connection not initialized')

        return True

    def fileno(self):
        return self.sock.fileno()

    def getpeername(self):
        if self.sock is None:
            return ''

        return self.sock.getpeername()

    def name(self):
        return self.name

    def send(self, data):
        res = self.sock.send(data)
        return res

    def recvall(self):
        pass

    def recv(self, len=None):
        if self.sock is None:
            return None

        res = self.sock.recv(len)
        return res

    def disconnect(self):
        if self.sock is None:
            return

        self.sock.close()


class Client(TcpConnection, ThunnelClient):

    def __init__(self, name="", ip=None, port=None):
        TcpConnection.__init__(self, name=name, sock=None)

        self.ip = ip
        self.port = port
        self.name = name
        self.sock = None

    def connect(self):
        '''connect to remote server'''
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((self.ip, self.port))
        sock.setblocking(False)

        self.sock = sock


class Server(ThunnelServer):

    def __init__(self, name="", ip=None, port=None):
        self.ip = ip
        self.port = port
        self.name = name
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
        sock.setblocking(False)

        conn = TcpConnection(sock=sock)
        return conn
