from __future__ import annotations
import socket

from .. import util
from . import ThunnelClient, ThunnelServer, ThunnelConnection


class TcpConnection(ThunnelConnection):

    def __init__(self, sock: socket.socket):
        super(TcpConnection, self).__init__()
        self.sock = sock

        self.ip = None
        self.port = None

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

    def send(self, data):
        res = self.sock.send(data)
        return res

    def recv(self, len=None):
        if self.sock is None:
            return ''

        res = self.sock.recv(len)
        return res

    def disconnect(self):
        if self.sock is None:
            return

        self.sock.close()


class Client(TcpConnection, ThunnelClient):

    def __init__(self, addr):
        TcpConnection.__init__(self, sock=None)

        ip, port = util.parse_ip_port(addr)

        self.ip = ip
        self.port = port
        self.sock = None

    def connect(self):
        '''connect to remote server'''
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((self.ip, self.port))

        self.sock = sock


class Server(ThunnelServer):

    def __init__(self, addr):
        ip, port = util.parse_ip_port(addr)

        self.ip = ip
        self.port = port
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

        conn = TcpConnection(sock)
        return conn
