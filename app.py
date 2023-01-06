import sys
import logging

from src.local import LocalServer

logging.basicConfig(level=logging.DEBUG)

if __name__ == '__main__':
    cfg_path = sys.argv[1]

    server = LocalServer(cfg_path)
    server.serve()
