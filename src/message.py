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
    ins = struct.pack("!H", InsHeartbeat)
    return ins
