import sys
import time

import yaml
import socket
import struct
import select
import threading

# 数据交换指令
InsInitialRemoteServer = 0x0000
InsInitialConnection = 0x0001
InsHeartbeat = 0x0002
InsData = 0x0003
InsCloseConnection = 0x0004


class UnableReadSocketException(Exception):

    def __init__(self, message, sock):
        self.message = message
        self.sock = sock


class TargetSocketNotExist(Exception):
    pass


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

    def __init__(self, server, name, config):
        self.remote_server_name = name
        self.server = server

        self.type = config.get("type")
        self.remote = int(config.get("remote"))

        host, port = config.get("bind").split(":")
        self.host = host
        self.port = int(port)

    def __str__(self):
        return "Proxy({}:{} -> {}:{})".format(self.host, self.port, self.server.host, self.remote)

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

            try:
                identity = ip_port_to_int(addr[0], addr[1])
                print("{} received connection from {}, id={}".format(self, addr, identity))

                server.register_connection(self.remote_server_name, self.remote, identity, conn)
            except Exception as e:
                print("proxy connection error: {}".format(e))


class BaseServer(object):

    def __init__(self):
        self.conn_list = {}

    def load_config(self, path):
        with open(path) as fh:
            config = yaml.load(fh.read(), Loader=yaml.Loader)
            return config

    def get_fdset(self, sock_list):
        res = sock_list[:]

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

    def initial_remote_server(self, sock, name):
        '''这个消息是远程服务端发送给服务端的'''
        raise Exception("Server must override initial_remote_server")

    def initial_application_connection(self, transSock, port, _id):
        '''这个消息是服务端发送给远程服务端的'''
        sock = self.get_sock(_id)
        if sock is not None:
            raise Exception("connection {} already existed".format(_id))

        try:
            ip = "127.0.0.1"
            print("try to connect local: {}:{}, id={}".format(ip, port, _id))
            sock = socket.create_connection((ip, port))

            self.conn_list[_id] = {"id": _id, "port": port, "sock": sock}
        except Exception as e:
            # 目标连接不上, 通知服务端关闭连接
            data = self.build_close_connection_message(_id)
            transSock.send(data)

    def close_application_connection(self, _id):
        '''这个指令服务端/远程服务端都可能收到'''
        sock = self.get_sock(_id)
        sock.close()
        self.delete_conncetion(_id)

    def swap_data(self, sock, _id, length):
        app = self.get_sock(_id)
        if app is None:
            raise TargetSocketNotExist(_id)

        # 将 sock 收到的数据转发到 app
        l = forward_data(sock, app, length=length)
        # print("data received {}, fetch length: {}".format(length, l))
        if l == 0:
            return -1

    def parse_message(self, sock):
        # 指令长度 16 位, 目标端口 16 位, _id 48 位, length 32 位
        # initial_remote_server + length + name
        # initial_connection + _id + target port
        # heartbeat
        # data + _id + length
        # close_connection + _id
        data = sock.recv(2)
        if len(data) < 2:
            msg = "Expect 16bits instructions, found: {}".format(data)
            raise UnableReadSocketException(msg, sock)

        ins = struct.unpack("!H", data)[0]

        if ins == InsInitialRemoteServer:
            data = sock.recv(4)
            length = struct.unpack("!L", data)[0]
            name = sock.recv(length)
            return self.initial_remote_server(sock, name)
        elif ins == InsInitialConnection:
            data = sock.recv(8)
            data = struct.unpack("!Q", data)[0]
            _id = (data & 0xFFFFFFFFFFFF0000) >> 16
            port = data & 0x000000000000FFFF
            self.initial_application_connection(sock, port, _id)
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

    def build_initial_remote_server_message(self, name):
        ins = struct.pack("!H", InsInitialRemoteServer)
        length = struct.pack("!L", len(name))
        return ins + length + name.encode("utf-8")

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

    def get_remote_pair_sock(self, sock_list, _id):
        '''获取与 _id 连接对应的另一条连接'''
        raise Exception("Server must override initial_remote_server")

    def _main_loop(self, sock_list):
        fdset = self.get_fdset(sock_list)
        r, w, e = select.select(fdset, [], [], 1)

        for app in r:
            if app in sock_list:
                # sock_list 里面的连接, 是 Proxy Server 和 Remote Server 之间的连接
                # 上面流的数据都是按照数据交换协议组织的
                self.parse_message(app)
            else:
                # 非 sock_list 里面的连接
                # 在 Proxy Server 端是 proxy 和客户应用程序的连接
                # 在 Remote Server 端是 client 和应用程序连接
                _id = self.get_sock_id(app)
                if _id is None and app.fileno() == -1:
                    continue

                # app -> sock, 目标 sock 一定在 sock_list 里面, 怎么将它找到呢?
                sock = self.get_remote_pair_sock(sock_list, _id)

                # 将 app 里面收到的数据, 通过 sock 发送出去
                l = forward_data(app, sock, middleware=[self.build_data_message(_id)])
                if l == 0:
                    app.close()
                    self.delete_conncetion(_id)
                    sock.send(self.build_close_connection_message(_id))


class Server(BaseServer):

    def __init__(self, cfg_path):
        super(Server, self).__init__()

        config = self.load_config(cfg_path)

        self.config = config
        # 服务监听 地址:端口
        host, port = config.get('bind').split(":")

        self.host = host
        self.port = int(port)

        # 远程服务端
        self.remote_server = {}

    def __str__(self):
        return "Server({}:{})".format(self.host, self.port)

    def remove_remote_server(self, sock):
        sock.close()

        nameList = list(self.remote_server)
        for name in nameList:
            s = self.remote_server.get(name)
            if s != sock:
                continue

            self.remote_server.pop(name, None)

    def initial_remote_server(self, sock, name):
        '''这个消息是远程服务端发送给服务端的'''
        name = name.decode('utf-8')
        self.remote_server[name] = sock
        return name

    def get_remote_pair_sock(self, sock_list, _id):
        info = self.conn_list[_id]
        name = info.get("remote_server_name")
        return self.remote_server.get(name)

    def register_connection(self, remote_name, port, _id, sock):
        remote_server = self.remote_server.get(remote_name)
        if not remote_server:
            sock.close()
            raise Exception("remote server '{}' not ready for connection!".format(remote_name))

        self.conn_list[_id] = {
            "id": _id,
            "remote_server_name": remote_name,
            "port": port,
            "sock": sock,
        }

        # 向远程服务端发送初始化连接请求
        try:
            data = self.build_initial_connection_message(_id, port)
            remote_server.send(data)
        except Exception as e:
            self.remove_remote_server(remote_server)

    def main_loop(self):
        cnt = 1
        while True:
            remote_sock = [sock for (name, sock) in self.remote_server.items() if sock]
            try:
                print("main loop: {}".format(cnt))
                cnt += 1
                self._main_loop(remote_sock)
            except UnableReadSocketException as e:
                print("remote server conncetion closed: {}".format(e.message))
                self.remove_remote_server(e.sock)

    def serve(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((self.host, self.port))
        server.listen(5)

        print("{} start to accepting connections".format(self))

        while True:
            conn, addr = server.accept()
            name = self.parse_message(conn)  # 第一个消息应该是 InitRemoteServer
            print("remote server {}, name: {} connected".format(addr, name))

    def start(self):
        # 初始化服务, 接受来自目标服务器的请求, 将来数据可以转发到目标机器
        threads = []

        st = threading.Thread(target=self.serve)
        threads.append(st)

        # 启动本地代理端口监听服务
        for proxy_cfg in self.config.get('proxy'):
            remote_name = proxy_cfg.get('remote_name')
            for port_cfg in proxy_cfg.get('port_list'):
                proxy = Proxy(server, remote_name, port_cfg)
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

        config = self.load_config(cfg_path)

        self.name = config.get("name")

        server = config.get('server')
        host, port = server.split(":")

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

    def get_remote_pair_sock(self, sock_list, _id):
        return sock_list[0]

    def start(self):
        ar = (self.host, self.port)

        while True:
            sock = None
            try:
                sock = socket.create_connection(ar)

                t = threading.Thread(target=self.heartbeat, args=(sock, ))
                t.start()

                sock.send(self.build_initial_remote_server_message(self.name))

                while True:
                    self._main_loop([sock])
            except Exception as e:
                print("client exception", e)
            finally:
                if sock:
                    print("socket closed, try to reopen")
                    sock.close()
                time.sleep(1)


if __name__ == '__main__':
    t = sys.argv[1]
    if t == "server":
        server = Server("server.yaml")
        server.start()
    elif t == "client":
        server = Client("client.yaml")
        server.start()
