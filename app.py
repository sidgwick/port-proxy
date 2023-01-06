import sys
import logging

from src.local import LocalServer
from src.remote import RemoteServer

logging.basicConfig(level=logging.DEBUG)

if __name__ == '__main__':
    cfg_path = sys.argv[1]

    if cfg_path == 'local-server.yaml':
        server = LocalServer(cfg_path)
        server.serve()

    if cfg_path == 'remote-server.yaml':
        server = RemoteServer(cfg_path)
        server.serve()
