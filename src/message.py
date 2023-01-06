import struct
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
InsInitialRemoteServer = 0x0000
InsInitialConnection = 0x0001
InsHeartbeat = 0x0002
InsData = 0x0003
InsCloseConnection = 0x0004


def heartbeat_message():
    return Message(InsHeartbeat)


def initial_connection_message(_id, port):
    return Message(InsInitialConnection, _id=_id, port=port)


def close_connection_message(_id, port):
    return Message(InsCloseConnection, _id=_id, port=port)


def data_message(_id, data):
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
        elif self.ins == InsInitialRemoteServer:
            _type = "InsInitialRemoteServer"
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

        if self.ins == InsInitialRemoteServer:
            name = ""
            ins = struct.pack("!H", InsInitialRemoteServer)
            length = struct.pack("!L", len(name))
            return ins + length + name.encode("utf-8")

        if self.ins == InsCloseConnection:
            ins_and_id = (InsCloseConnection << 48) + self.id
            ins_and_id = struct.pack("!Q", ins_and_id)
            return ins_and_id

    def decode():
        pass