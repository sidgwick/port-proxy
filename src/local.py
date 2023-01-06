import threading
import socket
import time
import logging

from . import util, message
from .proxy.local import LocalProxy
from .base import BaseServer


class LocalServer(BaseServer):
    '''本地服务
    1. 解析需要代理的 proxy, 并逐个启动它们
    2. 把上面启动好的代理 proxy 注册到 local server
    3. proxy 监听网络流量, 然后委托给 local server 转发给 remote server
    '''

    def __init__(self, cfg_path):
        super(LocalServer, self).__init__()

        self.config = self.load_config(cfg_path)

        self.sock = None
        self.lock = threading.Lock()

        self.app_client: dict[int, LocalProxy] = {}

    def init_remote_server(self):
        if self.sock != None:
            self.sock.close()
            self.sock = None

        remote_server = self.config.get("remote-server")
        ip, port = util.parse_ip_port(remote_server)

        while True:
            try:
                logging.info(f"建立 local server -> remote server 的连接, remote_server={ip}:{port}")
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.connect((ip, port))
                break
            except Exception as e:
                logging.error(f"建立到 remote server 连接失败: {e}, 稍后即将重试...")
                time.sleep(2)

        return sock

    def init_proxy_server(self, _id, cfg):
        proxy = LocalProxy(_id, self, cfg)
        proxy.start()
        return proxy

    def register_app_client_conn(self, proxy: LocalProxy, sock: socket.socket):
        _id = util.sock_id(sock)
        self.app_client[_id] = proxy

    def unregister_app_client_conn(self, sock: socket.socket):
        _id = util.sock_id(sock)
        del self.app_client[_id]

    def send(self, msg: message.Message):
        self.lock.acquire()

        try:
            logging.debug(f"data send to remote server {msg}")
            _msg = msg.encode()
            self.sock.send(_msg)
        except Exception as e:
            logging.error(f"data send to remote server send error: {e}")
            return False

        self.lock.release()
        return True

    def heartbeat(self):
        '''发送心跳包给 remote server, 一秒钟发送一个'''
        status = True
        while status:
            msg = message.heartbeat_message()
            status = self.send(msg)
            time.sleep(15)

    def read_remote_server(self):
        msg = None

        while True:
            try:
                msg = message.fetch_message(self.sock)
            except Exception as e:
                logging.error(f"fetch message from remote server error {e}")
                logging.info("restarting connection to remote server")
                self.sock = self.init_remote_server()

            if msg is None:
                continue

            logging.debug(f"received message from remote server {msg}")

            proxy = self.app_client[msg.id]
            proxy.read_from_local_server_write_to_app_client(msg)

    def serve(self):
        '''启动 local server'''
        self.sock = self.init_remote_server()

        # 启动所有的本地 proxy
        proxy_list = self.config.get('proxy_list')
        for _id, cfg in enumerate(proxy_list):
            logging.info(f"启动本地 proxy server, proxy_id={_id}, proxy_config={cfg}")

            self.init_proxy_server(_id, cfg)

        # 维持与 remote server 的心跳
        heartbeat = threading.Thread(target=self.heartbeat)
        heartbeat.daemon = True
        heartbeat.start()

        # 尝试从 remote server 获取数据, 并按照响应的内容分发到 local proxy
        read_remote_server = threading.Thread(target=self.read_remote_server)
        read_remote_server.daemon = True
        read_remote_server.start()

        # 永远服务下去
        heartbeat.join()
