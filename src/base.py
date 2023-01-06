import sys
import time

import yaml
import socket
import struct
import select
import threading





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

