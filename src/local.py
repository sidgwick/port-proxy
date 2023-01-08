import threading
import socket
import time
import logging
import selectors

from . import util, message
from .thunnel import ThunnelConnection, tcp, ws
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

        self.lock = threading.Lock()

        self.remote: dict[str, tuple[ThunnelConnection, dict]] = {}

        self.sel = selectors.DefaultSelector()
        self.app_client: dict[int, tuple[ThunnelConnection, LocalProxy]] = {}

    def init_remote_server(self, remote):
        name = remote.get("name")
        addr = remote.get("addr")

        protocol, ip, port = util.parse_xaddr(addr)

        t = None
        if protocol == 'tcp':
            t = tcp.Client(name=name, ip=ip, port=port)
        elif protocol == 'ws':
            t = ws.Client(name=name, ip=ip, port=port)

        while True:
            try:
                logging.info(f"建立 LocalServer -> RemoteServer({t}) 的连接")
                t.connect()
                break
            except Exception as e:
                logging.error(f"建立 LocalServer -> RemoteServer({t}) 的连接失败: {e}, 稍后即将重试...")
                time.sleep(2)

        logging.info(f"建立 LocalServer -> RemoteServer({t}) 的连接成功")
        self.sel.register(t, selectors.EVENT_READ, data=None)
        self.remote[name] = (t, remote)
        return t

    def close_thunnel(self, sock: ThunnelConnection):
        _, cfg = self.remote[sock.name]
        del self.remote[sock.name]

        self.sel.unregister(sock)
        sock.disconnect()
        return cfg

    def init_proxy_server(self, _id, cfg):
        proxy = LocalProxy(_id, self, cfg)
        proxy.start()
        return proxy

    def register_app_client_conn(self, remote: int, proxy: LocalProxy, sock: socket.socket):
        _id = util.sock_id(sock)
        _remote = self.remote[remote]
        self.app_client[_id] = (_remote, proxy)

    def unregister_app_client_conn(self, sock: socket.socket):
        _id = util.sock_id(sock)
        del self.app_client[_id]

    def send(self, remote: str, msg: message.Message):
        self.lock.acquire()

        try:
            logging.debug(f"data send to RemoteServer({remote}) {msg}")
            _msg = msg.encode()
            conn, _ = self.remote[remote]
            conn.send(_msg)
        except Exception as e:
            logging.error(f"data send to RemoteServer({remote}) send error: {e}")
            return False

        self.lock.release()
        return True

    def heartbeat(self):
        '''发送心跳包给 remote server, 一秒钟发送一个'''
        while True:
            remote_list = list(self.remote)
            for remote in remote_list:
                msg = message.heartbeat_message()
                self.send(remote, msg)
                time.sleep(15)

    def read_remote_server(self, sock: ThunnelConnection):
        msg = None

        try:
            msg = message.fetch_message(sock)
        except Exception as e:
            logging.error(f"fetch message from remote server error {e}")
            logging.info("restarting connection to remote server")
            cfg = self.close_thunnel(sock)
            self.init_remote_server(cfg)

        if msg is None:
            return

        logging.debug(f"received message from remote server {msg}")

        _, proxy = self.app_client[msg.id]
        proxy.read_from_local_server_write_to_app_client(msg)

    def serve(self):
        '''启动 local server'''
        remote_server_list = self.config.get("remote-server")
        for remote in remote_server_list:
            self.init_remote_server(remote)

        # 启动所有的本地 proxy
        proxy_list = self.config.get('proxy_list')
        for _id, cfg in enumerate(proxy_list):
            logging.info(f"启动本地 proxy server, proxy_id={_id}, proxy_config={cfg}")

            self.init_proxy_server(_id, cfg)

        # 维持与 remote server 的心跳
        heartbeat = threading.Thread(target=self.heartbeat)
        heartbeat.daemon = True
        heartbeat.start()

        while True:
            events = self.sel.select(timeout=None)
            for key, mask in events:
                self.read_remote_server(key.fileobj)
