from __future__ import annotations
import socket
from abc import ABC, abstractmethod


class ThunnelConnection(ABC):

    def __init__(self):
        self.handlers = []

    @property
    @abstractmethod
    def name(self):
        '''获取套接字名字'''
        return NotImplementedError

    @abstractmethod
    def alive_check(self):
        '''检查链接状态'''
        return NotImplementedError

    @abstractmethod
    def fileno(self):
        '''通讯中使用的最底层的文件描述符
        这个参数最终被 selectors 用来执行 register/unregister 等操作
        '''
        return NotImplementedError

    @abstractmethod
    def getpeername(self):
        '''获取通讯中对端的名字'''
        return NotImplementedError

    @abstractmethod
    def send(self, msg: bytes):
        '''send data to remote server'''
        return NotImplementedError

    @abstractmethod
    def recv(self, len=None):
        '''recv data from remote server'''
        return NotImplementedError

    @abstractmethod
    def disconnect(self):
        '''disconnect from remote server'''
        return NotImplementedError

    @abstractmethod
    def recvall(self):
        '''read all socket content to local buffer'''
        return NotImplementedError

    def register_message_handler(self, handler):
        '''注册指令到来之后的处理函数'''
        self.handlers.append(handler)
        return len(self.handlers) - 1

    def unregister_message_handler(self, key):
        '''删除指令到来之后的处理函数'''
        self.handlers = self.handlers[0:key]
        self.handlers.extend(self.handlers[key+1:])


class ThunnelClient():

    @abstractmethod
    def connect(self):
        '''connect to remote server'''
        return NotImplementedError


class ThunnelServer():

    @abstractmethod
    def serve(self):
        '''listen connections from local server'''
        return NotImplementedError

    @abstractmethod
    def accept(self) -> ThunnelConnection:
        '''accept connections from local server'''
        return NotImplementedError