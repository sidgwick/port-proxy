
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
