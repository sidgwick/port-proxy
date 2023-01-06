import sys
import time

import yaml
import socket
import struct
import select
import threading


class BaseServer(object):

    def __init__(self):
        self.conn_list = {}

    def load_config(self, path):
        with open(path) as fh:
            config = yaml.load(fh.read(), Loader=yaml.Loader)
            return config
