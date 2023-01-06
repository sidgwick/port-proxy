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
