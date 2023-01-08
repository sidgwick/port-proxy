from __future__ import annotations
import logging
import socket
import time

from .. import util
from . import ThunnelClient, ThunnelServer


class TcpConnect():

    def __init__(self, addr):
        super(TcpConnect, self).__init__()

        ip, port = util.parse_ip_port(addr)

        self.ip = ip
        self.port = port
        self.sock = None

    def __str__(self):
        return f'tcp://{self.ip}:{self.port}'

    def fileno(self):
        return self.sock.fileno()

    def send(self, data):
        res = self.sock.send(data)
        return res

    def recv(self, len=None):
        res = self.sock.recv(len)
        return res


class Client(TcpConnect, ThunnelClient):

    def __init__(self, addr):
        TcpConnect.__init__(self, addr)

    def connect(self):
        '''connect to remote server'''

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((self.ip, self.port))

    def disconnect(self):
        '''disconnect from remote server'''
        self.sock.close()


class Server(TcpConnect, ThunnelServer):

    def __init__(self, addr):
        TcpConnect.__init__(self, addr)

    def serve(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        sock.bind((self.ip, self.port))
        sock.listen()
        sock.setblocking(False)

        self.sock = sock

    def accept(self) -> tuple[socket.socket, socket._RetAddress]:
        return self.sock.accept()