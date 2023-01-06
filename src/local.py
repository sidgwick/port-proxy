import threading
import socket
import time
import logging

from . import util, message
from .proxy.proxy import Proxy
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
        self.proxy_server = {}

    def init_remote_server(self):
        if self.sock != None:
            self.sock.close()
            self.sock = None

        remote_server = self.config.get("remote-server")
        ip, port = util.parse_ip_port(remote_server)

        logging.info(f"建立 local server -> remote server 的连接, remote_server={remote_server}")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((ip, port))

        return sock

    def init_proxy_server(self, _id, cfg):
        proxy = Proxy(_id, self, cfg)
        proxy.start()
        return proxy

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

            time.sleep(1)

    def proxy_register(self, _id, proxy):
        self.proxy_server[_id] = proxy

    def serve(self):
        '''启动 local server'''
        self.sock = self.init_remote_server()

        # 启动所有的本地 proxy
        proxy_list = self.config.get('proxy_list')
        for _id, cfg in enumerate(proxy_list):
            logging.info(f"启动本地 proxy server, proxy_id={_id}, proxy_config={cfg}")

            proxy = self.init_proxy_server(_id, cfg)
            self.proxy_register(_id, proxy)

        # 维持与 remote server 的心跳
        heartbeat = threading.Thread(target=self.heartbeat)
        heartbeat.daemon = True
        heartbeat.start()

        # 永远服务下去
        heartbeat.join()
