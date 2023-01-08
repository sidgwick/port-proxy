from __future__ import annotations
import socket
from abc import ABC, abstractmethod


class BasicThunnel(ABC):

    @abstractmethod
    def fileno(self):
        '''通讯中使用的最底层的文件描述符
        这个参数最终被 selectors 用来执行 register/unregister 等操作
        '''
        return NotImplementedError

    @abstractmethod
    def send(self):
        '''send data to remote server'''
        return NotImplementedError

    @abstractmethod
    def recv(self, len=None):
        '''recv data from remote server'''
        return NotImplementedError


class ThunnelClient(BasicThunnel):

    @abstractmethod
    def connect(self):
        '''connect to remote server'''
        return NotImplementedError

    @abstractmethod
    def disconnect(self):
        '''disconnect from remote server'''
        return NotImplementedError


class ThunnelServer(BasicThunnel):

    @abstractmethod
    def serve(self):
        '''listen connections from local server'''
        return NotImplementedError

    @abstractmethod
    def accept(self) -> tuple[socket.socket, socket._RetAddress]:
        '''accept connections from local server'''
        return NotImplementedError