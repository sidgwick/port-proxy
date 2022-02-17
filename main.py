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


def read_prefix_meta(sock):
    data = sock.recv(6)
    if len(data) != 6:
        raise Exception("unable to read prefix meta")

    port = struct.unpack(">H", data[:2])[0]
    length = struct.unpack(">L", data[2:])[0]

    return port, length


def prefix_meta(port):

    def _prefix_meta(data):
        _port = struct.pack(">H", port)
        _length = struct.pack(">L", len(data))
        return _port + _length + data

    return _prefix_meta


def send_data(sock, data):
    print(data)
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
        raise Exception('failed to send all data')

    return l


def forward_data(sock, remote, length=None, middleware=None):
    if length is None:
        return _forward_data(sock, remote, middleware=middleware)

    while length > 0:
        l = _forward_data(sock, remote, max_len=length, middleware=middleware)
        length -= l

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

        middleware = {
            "recv": [],
            "resp": [],
        }
        if self.type == "http":
            middleware["recv"].append(self.http_proxy)

        middleware["recv"].append(prefix_meta(self.remote))

        while True:
            conn, addr = socketServer.accept()

            print("{} received connection from {}".format(self, addr))

            server.register_proxy(self.remote, conn)

    def run(self):
        try:
            self.serve()
        except Exception as e:
            print(e)
            print("{} closed".format(self))


class Server(object):

    def __init__(self, cfg_path):
        config = {}
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
        self.proxy_socks = {}

    def __str__(self):
        return "Server({}:{})".format(self.host, self.port)

    def get_fdset(self):
        res = []

        if self.remote_client is not None:
            res.append(self.remote_client)

        for i in self.proxy_socks:
            res.append(self.proxy_socks.get(i))

        return res

    def get_proxy_sock(self, port):
        return self.proxy_socks[port]

    def get_port_by_app_sock(self, sock):
        for port in self.proxy_socks:
            s = self.proxy_socks.get(port)
            if s == sock:
                return port

        raise Exception("unknown application port")

    def register_proxy(self, port, conn):
        self.proxy_socks[port] = conn

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
        try:
            cnt = 1
            while True:
                print("main loop: {}".format(cnt))
                cnt += 1

                sock = self.remote_client

                fdset = self.get_fdset()
                r, w, e = select.select(fdset, [], [], 1)
                if sock in r:
                    port, length = read_prefix_meta(sock)
                    app = self.get_proxy_sock(port)
                    # 将 sock 收到的数据转发到 app
                    forward_data(sock, app, length=length)

                for app in r:
                    if app == sock:
                        continue

                    # 首先找到 port 信息
                    port = self.get_port_by_app_sock(app)

                    # 将 app 里面收到的数据, 通过 sock 发送出去
                    forward_data(app, sock, middleware=[prefix_meta(port)])

        except Exception as e:
            print(e)
            raise (e)
        finally:
            print("main loop closed")

    def serve(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        server.bind((self.host, self.port))
        server.listen(5)

        msg = "{} start to accepting connections".format(self)

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


class Client(object):

    def __init__(self, cfg_path):
        config = {}
        with open(cfg_path) as fh:
            config = yaml.load(fh.read(), Loader=yaml.Loader)
            config = config.get("client")

        host, port = config.get('server').split(":")

        self.host = host
        self.port = int(port)

        self.app = {}

    def get_app(self, port):
        app = self.app.get(port)
        if app is not None:
            return app

        _app = ("127.0.0.1", port)
        app = socket.create_connection(_app)
        self.app[port] = app
        return app

    def get_fdset(self, additional):
        fdset = [self.app.get(x) for x in self.app]
        fdset.append(additional)

        return fdset

    def get_port_by_app_sock(self, sock):
        for port in self.app:
            s = self.app.get(port)
            if s == sock:
                return port

        raise Exception("unknown application port")

    def start(self):
        ar = (self.host, self.port)
        sock = socket.create_connection(ar)

        print("proxy client connect to server {}:{}".format(
            self.host, self.port))

        try:
            while True:
                fdset = self.get_fdset(sock)
                r, w, e = select.select(fdset, [], [])
                if sock in r:
                    port, length = read_prefix_meta(sock)
                    app = self.get_app(port)
                    # 将 sock 收到的数据转发到 app
                    forward_data(sock, app, length=length)

                for app in r:
                    if app == sock:
                        continue

                    # 首先找到 port 信息
                    port = self.get_port_by_app_sock(app)

                    # 将 app 里面收到的数据, 通过 sock 发送出去
                    forward_data(app, sock, middleware=[prefix_meta(port)])

        except Exception as e:
            print(e)
            raise (e)
        finally:
            print("socket closed")
            sock.close()


if __name__ == '__main__':
    t = sys.argv[1]
    if t == "server":
        server = Server("conf.yaml")
        server.start()
    elif t == "client":
        server = Client("conf.yaml")
        server.start()
