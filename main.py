import sys
import yaml
import logging
import socket
import struct
import select
import threading


# 本程序实现以下功能
# 假设有 A/B 两台机器, 因为某些原因, B 只能对外开放 1 个端口, 但是在 B 上又需要部署很多服务(比方说同时有 ssh, sftp 等)
#

def ip_port_to_int(_ip, port):
    ip = struct.unpack("!I", socket.inet_aton(_ip))[0]

    return (ip << 16) + int(port)


def read_prefix_meta(sock):
    data = sock.recv(12)
    if len(data) != 12:
        raise Exception("unable to read prefix meta")

    tmp = struct.unpack("!Q", data[:8])[0]
    length = struct.unpack("!L", data[8:])[0]

    identity = (tmp & 0xFFFFFFFFFFFF0000) >> 16
    port = tmp & 0x000000000000FFFF
    return identity, port, length


def prefix_meta(_id, port):
    id_and_port = (_id << 16) + port

    def _prefix_meta(data):
        prefix = struct.pack("!Q", id_and_port)
        length = struct.pack("!L", len(data))
        return prefix + length + data

    return _prefix_meta


def send_data(sock, data):
    bytes_sent = 0
    while True:
        r = sock.send(data[bytes_sent:])
        if r < 0:
            return r
        bytes_sent += r
        if bytes_sent == len(data):
            return bytes_sent


def _forward_data(sock, remote, max_len=None, middleware=[]):
    # 一次最多读取 4096 字节, 再多的分多次读取
    if max_len is None or max_len > 4096:
        max_len = 4096

    data = sock.recv(max_len)

    l = len(data)
    if l <= 0:
        return 0

    middleware = middleware if middleware is not None else []
    for m in middleware:
        data = m(data)

    result = send_data(remote, data)
    if result < l:
        raise Exception('failed to send all data: {} < {}'.format(result, l))

    return l


def forward_data(sock, remote, length=None, middleware=None):
    if length is None:
        return _forward_data(sock, remote, middleware=middleware)

    cnt = 0
    while cnt < length:
        l = _forward_data(sock, remote, max_len=length, middleware=middleware)
        cnt += l

        if l == 0:
            raise Exception("数据长度不足")

    return length


# 将发送到 sock 的数据流转发到 ar 对应的远端地址上
def handle_tcp(args):
    try:
        sock = args.get("conn")
        remote = args.get("remote")
        middleware = args.get("middleware", {})
        _handle_tcp(sock, remote, middleware)
    except Exception as e:
        print(e)
        raise (e)
    finally:
        print("socket closed")
        sock.close()
        remote.close()


def _handle_tcp(sock, remote, middleware):
    fdset = [sock, remote]
    while True:
        r, w, e = select.select(fdset, [], [])
        if sock in r:
            _middleware = middleware.get("recv")
            forward_data(sock, remote, middleware=_middleware)

        if remote in r:
            _middleware = middleware.get("resp")
            # 读出来 prefix meta
            port, length = read_prefix_meta(remote)
            forward_data(remote, sock, length=length, middleware=_middleware)


class Proxy():

    def __init__(self, server, config):
        self.server = server

        self.type = config.get("type")
        self.remote = int(config.get("port"))

        host, port = config.get("bind").split(":")
        self.host = host
        self.port = int(port)

    def __str__(self):
        return "Proxy({}:{} -> {}:{})".format(self.host, self.port,
                                              self.server.host, self.remote)

    def http_proxy(self, data):
        rh, rp = (self.server.host, self.remote)

        h = 'Host: {}:{}'.format(self.host, self.port).encode('ascii')
        hr = 'Host: {}:{}'.format(rh, rp).encode('ascii')

        return data.replace(h, hr)

    def serve(self):
        socketServer = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        socketServer.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        socketServer.bind((self.host, self.port))
        socketServer.listen(5)

        print("{} start to accepting connections".format(self))

        while True:
            conn, addr = socketServer.accept()

            identity = ip_port_to_int(addr[0], addr[1])
            print("{} received connection from {}, id={}".format(self, addr, identity))

            server.register_connection(self.remote, identity, conn)

    def run(self):
        try:
            self.serve()
        except Exception as e:
            print(e)
            print("{} closed".format(self))


class BaseServer(object):
    def __init__(self):
        self.conn_list = {}

    def get_fdset(self, sock):
        res = []

        if sock is not None:
            res.append(sock)

        for conn in self.conn_list.values():
            res.append(conn.get("sock"))

        return res

    def _get_sock(self, _id):
        conn = self.conn_list.get(_id, {})
        return conn.get("sock")

    def get_sock(self, _id, port) -> socket.socket:
        pass

    def get_sock_port(self, sock):
        for _id, conn in self.conn_list.items():
            s = conn.get("sock")
            if s == sock:
                return _id, conn.get("port")

        raise Exception("unknown socket port")

    def register_connection(self, port, _id, sock):
        self.conn_list[_id] = {"port": port, "sock": sock}

    def delete_conncetion(self, _id):
        print("connection {} closed and delete it now".format(_id))
        del self.conn_list[_id]

    def _main_loop(self, sock):
        fdset = self.get_fdset(sock)
        r, w, e = select.select(fdset, [], [], 1)
        if sock in r:
            _id, port, length = read_prefix_meta(sock)
            app = self.get_sock(_id, port)
            # 将 sock 收到的数据转发到 app
            l = forward_data(sock, app, length=length)
            if l == 0:
                print(sock)
                sock.close()
                self.delete_conncetion(_id)

        for app in r:
            if app == sock:
                continue

            # 首先找到 port 信息
            _id, port = self.get_sock_port(app)

            # 将 app 里面收到的数据, 通过 sock 发送出去
            l = forward_data(app, sock, middleware=[prefix_meta(_id, port)])
            if l == 0:
                print(app)
                app.close()
                self.delete_conncetion(_id)
                pass


class Server(BaseServer):

    def __init__(self, cfg_path):
        super(Server, self).__init__()

        with open(cfg_path) as fh:
            config = yaml.load(fh.read(), Loader=yaml.Loader)
            config = config.get("server")

        # 服务监听 地址:端口
        host, port = config.get('bind').split(":")

        self.host = host
        self.port = int(port)

        # 代理配置列表
        self.proxy_config_list = config.get('proxy')

        # 代理服务线程列表
        self.proxy = []

        # 远端客户端
        self.remote_client = None

    def __str__(self):
        return "Server({}:{})".format(self.host, self.port)

    def get_sock(self, _id, port):
        return self._get_sock(_id)

    def handle_remote_client(self, conn):
        self.remote_client = conn
        return

        # 链接一开始, 首先发送自己的身份信息: 2 字节数据长度, N 字节的身份标识
        # 此后此连接用于发送普通数据 + 心跳包
        data = conn.recv(2)
        if len(data) != 2:
            raise Exception("bad initial connection meta info - length")

        length = struct.unpack(">H", data)[0]

        data = conn.recv(length)
        if len(data) != length:
            raise Exception("bad initial connection meta info - name")

        name = str(struct.unpack("s", data)[0])
        sl = self.remote_client.get(name)
        if sl is None:
            sl = []

        sl.append(conn)
        self.remote_client[name] = sl

    def main_loop(self):
        cnt = 1
        while True:
            try:
                print("main loop: {}".format(cnt))
                cnt += 1
                self._main_loop(self.remote_client)
            except Exception as e:
                print(e)

    def serve(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        server.bind((self.host, self.port))
        server.listen(5)

        msg = "{} start to accepting connections".format(self)
        print(msg)

        while True:
            try:
                conn, addr = server.accept()

                print("remote client {} connected".format(addr))

                self.handle_remote_client(conn)
            except Exception as e:
                print(e)

    def init_proxy(self):
        for proxy_cfg in self.proxy_config_list:
            proxy = Proxy(server, proxy_cfg)

            t = threading.Thread(target=proxy.run)
            t.start()

            self.proxy.append(proxy)

    def start(self):
        # 初始化服务, 接受来自目标服务器的请求, 将来数据可以转发到目标机器
        st = threading.Thread(target=self.serve)
        st.start()

        # 监听本地代理端口
        self.init_proxy()

        alt = threading.Thread(target=self.main_loop)
        alt.start()


class Client(BaseServer):

    def __init__(self, cfg_path):
        super(Client, self).__init__()

        with open(cfg_path) as fh:
            config = yaml.load(fh.read(), Loader=yaml.Loader)
            config = config.get("client")

        host, port = config.get('server').split(":")

        self.host = host
        self.port = int(port)

    def get_sock(self, _id, port):
        sock = self._get_sock(_id)
        if sock is not None:
            return sock

        ip = "127.0.0.1"
        print("try to connect local: {}:{}, id={}".format(ip, port, _id))
        sock = socket.create_connection((ip, port))

        self.register_connection(port, _id, sock)
        return sock

    def start(self):
        ar = (self.host, self.port)

        while True:
            sock = socket.create_connection(ar)
            try:
                while True:
                    self._main_loop(sock)
            except Exception as e:
                print(e)
            finally:
                print("socket closed, try to reopen")
                sock.close()


if __name__ == '__main__':
    t = sys.argv[1]
    if t == "server":
        server = Server("conf.yaml")
        server.start()
    elif t == "client":
        server = Client("conf.yaml")
        server.start()
