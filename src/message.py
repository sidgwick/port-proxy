from __future__ import annotations
import struct
import socket

from .exception import UnableReadSocketException
from . import util, thunnel
'''
一条消息由 <指令(16bit) + 目标端口(16bit) + 连接id(48bit) + 数据长度(32bit) + 数据> 共同组成.

消息中的指令是必须存在的, 剩余的部分可以没有

指令长度 16 位, 目标端口 16 位, _id 48 位, length 32 位
initial_remote_server + length + name
initial_connection + _id + target port
heartbeat
data + _id + length
close_connection + _id
'''

# 数据交换指令
InsInitialConnection = 0x0001
InsHeartbeat = 0x0002
InsData = 0x0003
InsCloseConnection = 0x0004


def fetch_message(sock: thunnel.ThunnelConnection) -> Message:
    '''从 sock 里面获取完整的 message 数据包'''
    sock.alive_check()

    data = sock.recv(2)
    if len(data) < 2:
        msg = f"期望能读取到最好 16 bits 的指令数据, 实际读到内容 {data}"
        raise UnableReadSocketException(msg, sock)

    msg = None
    ins = struct.unpack("!H", data)[0]

    if ins == InsInitialConnection:
        data = sock.recv(8)
        data = struct.unpack("!Q", data)[0]
        _id = (data & 0xFFFFFFFFFFFF0000) >> 16
        port = data & 0x000000000000FFFF
        msg = Message(ins=InsInitialConnection, _id=_id, port=port)
    elif ins == InsData:
        data = sock.recv(10)
        _id = util.six_bytes_id_to_int(data[:6])

        length = struct.unpack("!L", data[6:])[0]
        data = sock.recv(length)
        if len(data) != length:
            msg = f"未能从数据交换指令中读取到一个完整的数据包 data_length={length}"
            raise UnableReadSocketException(msg, sock)

        msg = Message(InsData, _id=_id, data=data)
    elif ins == InsCloseConnection:
        data = sock.recv(6)
        _id = util.six_bytes_id_to_int(data)
        msg = Message(InsCloseConnection, _id=_id)
    elif ins == InsHeartbeat:
        msg = Message(InsHeartbeat)
    else:
        raise Exception("Unknown data swap instruction: 0x{:X}".format(ins))

    return msg


def heartbeat_message():
    return Message(InsHeartbeat)


def initial_connection_message(port, sock: socket.socket = None, _id=None):
    if _id is None:
        _id = util.sock_id(sock)

    return Message(InsInitialConnection, _id=_id, port=port)


def close_connection_message(sock: socket.socket = None, _id=None):
    if _id is None:
        _id = util.sock_id(sock)

    return Message(InsCloseConnection, _id=_id)


def data_message(data, sock: socket.socket = None, _id=None):
    if _id is None:
        _id = util.sock_id(sock)
    return Message(InsData, _id=_id, data=data)


class Message():

    def __init__(self, ins=None, port=None, _id=None, data=None):
        self.ins = ins
        self.port = port
        self.id = _id
        self.data = data

    def __str__(self):
        length = None
        if self.data is not None:
            length = f"data<{len(self.data)}bytes>"

        _type = None
        if self.ins == InsHeartbeat:
            _type = "InsHeartbeat"
        elif self.ins == InsInitialConnection:
            _type = "InsInitialConnection"
        elif self.ins == InsData:
            _type = "InsData"
        elif self.ins == InsCloseConnection:
            _type = "InsCloseConnection"

        return f"Message({_type}, {self.port}, {self.id}, {length})"

    def encode(self):
        if self.ins == InsHeartbeat:
            return struct.pack("!H", InsHeartbeat)

        if self.ins == InsInitialConnection:
            ins_and_id = (InsInitialConnection << 48) + self.id
            ins_and_id = struct.pack("!Q", ins_and_id)
            _port = struct.pack("!H", self.port)
            return ins_and_id + _port

        if self.ins == InsData:
            ins_and_id = (InsData << 48) + self.id
            ins_and_id = struct.pack("!Q", ins_and_id)
            length = struct.pack("!L", len(self.data))
            return ins_and_id + length + self.data

        if self.ins == InsCloseConnection:
            ins_and_id = (InsCloseConnection << 48) + self.id
            ins_and_id = struct.pack("!Q", ins_and_id)
            return ins_and_id
