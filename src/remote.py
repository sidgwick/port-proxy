import threading
import socket
import selectors
import logging

from . import util, message, base


class RemoteServer(base.BaseServer):
    '''远端服务
    1. 打开服务端口, 准备接受 local server 的连接请求
    2. 接受 local server 发过来的数据包, 并转发到特定的 remote app
    '''

    def __init__(self, cfg_path):
        super(RemoteServer, self).__init__()

        self.config = self.load_config(cfg_path)

        self.sock = None
        self.lock = threading.Lock()

        self.sel = selectors.DefaultSelector()
        self.app_sel = selectors.DefaultSelector()
        self.conns: dict[int, socket.socket] = {}

        # app_server 保存了 remote server 和 app server 之间的 sock 信息
        # 因为数据还需要传回到 local server, 因此还会记录对应的 local/remote server 之间的 sock
        # value 里面第一个套接字是 local/remote, 第二个是 remote/app
        self.app_server: dict[int, tuple[socket.socket, socket.socket]] = {}

    def init_conn_to_app_server(self, conn: socket.socket, _id, port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(('0', port))

        self.app_server[_id] = (conn, sock)
        self.app_sel.register(sock, selectors.EVENT_READ, data=2)

    def close_conn_to_app_server(self, _id):
        _, sock = self.app_server[_id]
        del self.app_server[_id]
        self.app_sel.unregister(sock)
        sock.close()

    def write_to_app_server(self, _id, data):
        _, sock = self.app_server[_id]
        sock.send(data)

    def send_message(self, sock, msg):
        logging.debug(f"sending {msg} to {sock}")
        _msg = msg.encode()
        sock.send(_msg)

    def write_back_to_local_server(self, sock):
        data = sock.recv(1024)
        if len(data) <= 0:
            # 关闭连接
            return

        _id = None
        conn = None

        for x, (c, s) in self.app_server.items():
            if s == sock:
                _id = x
                conn = c
                break

        msg = message.data_message(data, _id=_id)
        self.send_message(conn, msg)

    def dispatch_message(self, sock: socket.socket, msg: message.Message):
        if msg.ins == message.InsInitialConnection:
            self.init_conn_to_app_server(sock, msg.id, msg.port)
        elif msg.ins == message.InsData:
            self.write_to_app_server(msg.id, msg.data)
        elif msg.ins == message.InsCloseConnection:
            self.close_conn_to_app_server(msg.id)
        elif msg.ins == message.InsHeartbeat:
            logging.debug(f"heartbeat message received from {sock}")

    def service_connection(self, key, mask):
        sock = key.fileobj

        if mask & selectors.EVENT_READ:
            msg = message.fetch_message(sock)
            if msg is not None:
                self.dispatch_message(sock, msg)

    def service_app_connection(self, key, mask):
        sock = key.fileobj

        if mask & selectors.EVENT_READ:
            self.write_back_to_local_server(sock)

    def accept_wrapper(self, sock: socket.socket):
        conn, addr = sock.accept()
        logging.info(f"{self} received connection from {addr}")

        conn.setblocking(False)
        self.app_sel.register(conn, selectors.EVENT_READ, data=1)

    def swap(self):
        try:
            while True:
                events = self.app_sel.select(timeout=None)
                for key, mask in events:
                    if key.data == 1:
                        self.service_connection(key, mask)
                    else:
                        self.service_app_connection(key, mask)
        except KeyboardInterrupt:
            print("Caught keyboard interrupt, exiting")
        finally:
            self.app_sel.close()

    def _serve(self):
        # remote server socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        _addr = self.config.get("bind")
        ip, port = util.parse_ip_port(_addr)

        sock.bind((ip, port))
        sock.listen()
        sock.setblocking(False)

        self.sel.register(sock, selectors.EVENT_READ, data=None)

        logging.info(f"remote server {self} start to accepting connections")

        try:
            while True:
                events = self.sel.select(timeout=None)
                for key, mask in events:
                    self.accept_wrapper(key.fileobj)
        except KeyboardInterrupt:
            print("Caught keyboard interrupt, exiting")
        finally:
            self.sel.close()

    def serve(self):
        swap = threading.Thread(target=self.swap)
        swap.daemon = True
        swap.start()

        self._serve()
