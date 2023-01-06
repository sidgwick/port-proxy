class Proxy():

    def __init__(self, _id, server, config):
        self.id = _id
        self.server = server

        self.type = config.get("type")
        self.remote = int(config.get("remote"))
        self.local = int(config.get("local"))

    def __str__(self):
        return "Proxy<{}, local({}) -> remote({})>".format(self.type, self.local, self.remote)

    def start(self):
        pass

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
