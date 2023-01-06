import logging
import socket
import threading
import selectors

from .. import message, util


class Proxy(threading.Thread):

    def __init__(self, _id: int, server, config: dict):
        super(Proxy, self).__init__()

        self.daemon = True

        self.id = _id
        self.server = server

        self.config = config
        self.local = config.get("local")
        self.remote = config.get("remote")

        self.sel = selectors.DefaultSelector()

    def __str__(self):
        return f"Proxy<{self.id} - {self.config}>"

    def register_connection(self, sock: socket.socket):
        _id = util.sock_id(sock)
        self.connection[_id] = sock

    def remote_response(self, message: message.Message):
        '''remote server 发回来的响应数据
        数据流动路径: app server -> remote server -> [local server -> local proxy] -> app client'''
        conn = self.connection[message.id]
        if conn is None:
            return

        conn.send_to_app_client(message)

    def send_to_local_server(self, msg: message.Message):
        msg.port = self.remote
        self.server.send(msg)

    def init_app_client_conn(self, sock: socket.socket):
        _id = util.sock_id(sock)
        msg = message.initial_connection_message(_id, self.remote)
        self.send_to_local_server(msg)

    def close_app_client_connection(self, sock: socket.socket):
        _id = util.sock_id(sock)
        ip, port = sock.getpeername()

        logging.info(f"closing connection to app client proxy {ip}:{port}")

        self.sel.unregister(sock)
        sock.close()

        msg = message.close_connection_message(_id, self.remote)
        self.send_to_local_server(msg)

    def read_from_app_client_write_to_local_server(self, sock: socket.socket):
        data = sock.recv(1024)
        if data is None or len(data) == 0:
            return self.close_app_client_connection(sock)

        _id = util.sock_id(sock)
        msg = message.data_message(_id, data)
        self.send_to_local_server(msg)

    def read_from_local_server_write_to_app_client(self, sock: socket.socket):
        # if data.outb:
        # print(f"Echoing {data.outb!r} to {data.addr}")
        # sent = sock.send(data.outb)  # Should be ready to write
        # data.outb = data.outb[sent:]
        pass

    def service_connection(self, key, mask):
        sock = key.fileobj

        if mask & selectors.EVENT_READ:
            self.read_from_app_client_write_to_local_server(sock)

        if mask & selectors.EVENT_WRITE:
            self.read_from_local_server_write_to_app_client(sock)

    def accept_wrapper(self, sock: socket.socket):
        conn, addr = sock.accept()
        logging.info(f"{self} received connection from {addr}")

        conn.setblocking(False)

        events = selectors.EVENT_READ | selectors.EVENT_WRITE
        self.sel.register(conn, events, data=1)

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
