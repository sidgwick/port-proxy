from __future__ import annotations
import logging
import socket
import threading
import selectors
from typing import TYPE_CHECKING

from .. import message, util

if TYPE_CHECKING:
    from .. import local


class LocalProxy(threading.Thread):

    def __init__(self, _id: int, server: local.LocalServer, config: dict):
        super(LocalProxy, self).__init__()

        self.daemon = True

        self.id = _id
        self.server = server

        self.config = config
        self.local = config.get("local")
        self.remote = config.get("remote")

        self.sel = selectors.DefaultSelector()
        self.connection: dict[int, socket.socket] = {}

    def __str__(self):
        _id = self.id
        protocol = self.config.get("type")
        local = self.local
        remote = self.remote
        return f"Proxy({_id}, {protocol}://{local}->{remote})"

    def register_connection(self, sock: socket.socket):
        _id = util.sock_id(sock)
        self.connection[_id] = sock

    def unregister_connection(self, sock: socket.socket):
        _id = util.sock_id(sock)
        del self.connection[_id]

    def send_to_local_server(self, msg: message.Message):
        msg.port = self.remote
        self.server.send(msg)

    def init_app_client_conn(self, sock: socket.socket):
        self.register_connection(sock)

        # 将套接字+proxy 对象一起注册到 local server 里面, 后面 local 收到数据才知道怎么发回来
        self.server.register_app_client_conn(self, sock)

        msg = message.initial_connection_message(self.remote, sock=sock)
        self.send_to_local_server(msg)

    def close_app_client_connection(self, sock: socket.socket):
        ip, port = sock.getpeername()

        logging.info(f"closing connection to app client proxy {ip}:{port}")

        msg = message.close_connection_message(sock=sock)
        self.send_to_local_server(msg)

        self.unregister_connection(sock)
        self.sel.unregister(sock)
        self.server.unregister_app_client_conn(sock)
        sock.close()

    def read_from_app_client_write_to_local_server(self, sock: socket.socket):
        data = sock.recv(1024)
        if data is None or len(data) == 0:
            return self.close_app_client_connection(sock)

        msg = message.data_message(data, sock=sock)
        self.send_to_local_server(msg)

    def read_from_local_server_write_to_app_client(self, msg: message.Message):
        _id = msg.id
        sock = self.connection[_id]

        if msg.ins == message.InsInitialConnection:
            pass
        elif msg.ins == message.InsData:
            sock.send(msg.data)
        elif msg.ins == message.InsCloseConnection:
            self.close_app_client_connection(sock)
        elif msg.ins == message.InsHeartbeat:
            pass

    def service_connection(self, key, mask):
        sock = key.fileobj

        if mask & selectors.EVENT_READ:
            self.read_from_app_client_write_to_local_server(sock)

    def accept_wrapper(self, sock: socket.socket):
        conn, addr = sock.accept()
        logging.info(f"{self} received connection from {addr}")

        conn.setblocking(False)

        self.sel.register(conn, selectors.EVENT_READ, data=1)

        self.init_app_client_conn(conn)

    def run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        sock.bind(('0', self.local))
        sock.listen()
        sock.setblocking(False)

        self.sel.register(sock, selectors.EVENT_READ, data=None)

        logging.info(f"local proxy server {self} start to accepting connections")

        try:
            while True:
                events = self.sel.select(timeout=None)
                for key, mask in events:
                    if key.data is None:
                        self.accept_wrapper(key.fileobj)
                    else:
                        self.service_connection(key, mask)
        except KeyboardInterrupt:
            print("Caught keyboard interrupt, exiting")
        finally:
            self.sel.close()
