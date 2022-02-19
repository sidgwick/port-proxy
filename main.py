import sys
import time

import yaml
import socket
import struct
import select
import threading

# 本程序实现以下功能
# 假设有 A/B 两台机器, 因为某些原因, B 只能对外开放 1 个端口, 但是在 B 上又需要部署很多服务(比方说同时有 ssh, sftp 等)
#

# 指令设计
# 在打开的数据通道上, 数据传输的时候都加上指令前缀, 根据指令前缀做出不同的动作:
#
# initial_connection + _id + target port
# heartbeat
# data + _id + length
# close_connection + _id

InsInitialConnection = 0x0000
InsHeartbeat = 0x0001
InsData = 0x0002
InsCloseConnection = 0x0003


class UnableReadSocketException(Exception): pass


class TargetSocketNotExist(Exception): pass


def ip_port_to_int(_ip, port):
    ip = struct.unpack("!I", socket.inet_aton(_ip))[0]

    return (ip << 16) + int(port)

def six_bytes_id_to_int(data):
    _id_a = struct.unpack("!L", data[:4])[0]
    _id_b = struct.unpack("!H", data[4:6])[0]
    return (_id_a << 16) + _id_b


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
        l = _forward_data(sock, remote, max_len=length - cnt, middleware=middleware)
        cnt += l

        if l == 0:
            raise Exception("数据长度不足")

    return cnt


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

    def run(self):
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

    def get_sock(self, _id) -> socket.socket:
        conn = self.conn_list.get(_id, {})
        return conn.get("sock")

    def get_sock_id(self, sock):
        for _id, conn in self.conn_list.items():
            s = conn.get("sock")
            if s == sock:
                return _id

        return None

    def initial_application_connection(self, port, _id):
        '''这个消息是服务端发送给远程客户端的'''
        sock = self.get_sock(_id)
        if sock is not None:
            raise Exception("connection {} already existed".format(_id))

        ip = "127.0.0.1"
        print("try to connect local: {}:{}, id={}".format(ip, port, _id))
        sock = socket.create_connection((ip, port))

        self.conn_list[_id] = {"port": port, "sock": sock}

    def close_application_connection(self, _id):
        '''这个指令服务端/远程客户端都可能收到'''
        sock = self.get_sock(_id)
        sock.close()
        self.delete_conncetion(_id)

    def swap_data(self, sock, _id, length):
        app = self.get_sock(_id)
        if app is None:
            raise TargetSocketNotExist(_id)

        # 将 sock 收到的数据转发到 app
        l = forward_data(sock, app, length=length)
        if l == 0:
            return -1

    def parse_message(self, sock):
        # 指令长度 16 位, 目标端口 16 位, _id 48 位, length 32 位
        # initial_connection + _id + target port
        # heartbeat
        # data + _id + length
        # close_connection + _id
        data = sock.recv(2)
        ins = struct.unpack("!H", data)[0]

        if ins == InsInitialConnection:
            data = sock.recv(8)
            data = struct.unpack("!Q", data)[0]
            _id = (data & 0xFFFFFFFFFFFF0000) >> 16
            port = data & 0x000000000000FFFF
            self.initial_application_connection(port, _id)
        elif ins == InsData:
            data = sock.recv(10)
            _id = six_bytes_id_to_int(data[:6])
            length = struct.unpack("!L", data[6:])[0]
            return self.swap_data(sock, _id, length)
        elif ins == InsCloseConnection:
            data = sock.recv(6)
            _id = six_bytes_id_to_int(data)
            self.close_application_connection(_id)
        elif ins == InsHeartbeat:
            pass
        else:
            raise Exception("Unknown data swap instruction: 0x{:X}".format(ins))

    def build_initial_connection_message(self, identity, port):
        ins_and_id = (InsInitialConnection << 48) + identity
        ins_and_id = struct.pack("!Q", ins_and_id)
        _port = struct.pack("!H", port)
        return ins_and_id + _port

    def build_close_connection_message(self, identity):
        ins_and_id = (InsCloseConnection << 48) + identity
        ins_and_id = struct.pack("!Q", ins_and_id)
        return ins_and_id

    def build_heartbeat_message(self):
        ins = struct.pack("!H", InsHeartbeat)
        return ins

    def build_data_message(self, identity=None):
        def _build_data_message(data):
            ins_and_id = (InsData << 48) + identity
            ins_and_id = struct.pack("!Q", ins_and_id)
            length = struct.pack("!L", len(data))
            return ins_and_id + length + data

        return _build_data_message

    def delete_conncetion(self, _id):
        print("connection {} closed and delete it now".format(_id))
        del self.conn_list[_id]

    def _main_loop(self, sock):
        fdset = self.get_fdset(sock)
        r, w, e = select.select(fdset, [], [], 0.1)
        if sock in r:
            self.parse_message(sock)

        for app in r:
            if app == sock:
                continue

            # 非 sock 的文件描述符有数据可读的情况, 都是希望发送数据交换的
            # 在 server 端, app 就是 proxy 和客户应用程序的连接
            # 在远端 client 断, app 是 client 和应用程序连接
            _id = self.get_sock_id(app)
            if _id is None and app.fileno() == -1:
                continue

            # 将 app 里面收到的数据, 通过 sock 发送出去
            l = forward_data(app, sock, middleware=[self.build_data_message(_id)])
            if l == 0:
                app.close()
                self.delete_conncetion(_id)
                sock.send(self.build_close_connection_message(_id))


class Server(BaseServer):

    def __init__(self, cfg_path):
        super(Server, self).__init__()

        with open(cfg_path) as fh:
            config = yaml.load(fh.read(), Loader=yaml.Loader)
            config = config.get("server")

        self.config = config
        # 服务监听 地址:端口
        host, port = config.get('bind').split(":")

        self.host = host
        self.port = int(port)

        # 远端客户端
        self.remote_client = None

    def __str__(self):
        return "Server({}:{})".format(self.host, self.port)

    def register_connection(self, port, _id, sock):
        self.conn_list[_id] = {"port": port, "sock": sock}

        # 向远程客户端发送初始化连接请求
        data = self.build_initial_connection_message(_id, port)
        self.remote_client.send(data)

    def main_loop(self):
        cnt = 1
        while True:
            sock = self.remote_client  # type: socket.socket
            try:
                print("main loop: {}".format(cnt))
                cnt += 1
                self._main_loop(sock)
            except UnableReadSocketException as e:
                print("remote client conncetion closed: {}".format(e))
                sock.close()
                self.remote_client = None

    def serve(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((self.host, self.port))
        server.listen(5)

        print("{} start to accepting connections".format(self))

        while True:
            conn, addr = server.accept()
            print("remote client {} connected".format(addr))
            self.remote_client = conn

    def start(self):
        # 初始化服务, 接受来自目标服务器的请求, 将来数据可以转发到目标机器
        threads = []

        st = threading.Thread(target=self.serve)
        threads.append(st)

        # 启动本地代理端口监听服务
        for proxy_cfg in self.config.get('proxy'):
            proxy = Proxy(server, proxy_cfg)
            t = threading.Thread(target=proxy.run)
            threads.append(t)

        # 开启主循环
        t = threading.Thread(target=self.main_loop)
        threads.append(t)

        for t in threads:
            t.start()


class Client(BaseServer):

    def __init__(self, cfg_path):
        super(Client, self).__init__()

        with open(cfg_path) as fh:
            config = yaml.load(fh.read(), Loader=yaml.Loader)
            config = config.get("client")

        host, port = config.get('server').split(":")

        self.host = host
        self.port = int(port)

    def heartbeat(self, sock):
        while True:
            try:
                print("client heartbeat send")
                sock.send(self.build_heartbeat_message())
            except:
                break
            time.sleep(1)

    def start(self):
        ar = (self.host, self.port)

        while True:
            sock = socket.create_connection(ar)
            try:
                t = threading.Thread(target=self.heartbeat, args=(sock,))
                t.start()

                while True:
                    self._main_loop(sock)
            except Exception as e:
                raise(e)
                print("client exception", e)
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
