import sys
import logging

from src.local import LocalServer
from src.remote import RemoteServer

logging.basicConfig(level=logging.DEBUG)

if __name__ == '__main__':
    mode = sys.argv[1]
    cfg_path = sys.argv[2]

    if mode == "local":
        server = LocalServer(cfg_path)
        server.serve()

    if mode == "remote":
        server = RemoteServer(cfg_path)
        server.serve()
