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
