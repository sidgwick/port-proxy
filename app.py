import sys
import time

import yaml
import socket
import struct
import select
import threading


if __name__ == '__main__':
    t = sys.argv[1]
    cfg_path = "/etc/pproxy/{}.yaml".format(t)

    if t == "server":
        server = Server(cfg_path)
        server.start()
    elif t == "client":
        server = Client(cfg_path)
        server.start()
