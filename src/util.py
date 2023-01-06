import struct
import socket


def parse_ip_port(addr):
    parts = addr.split(':')

    ip = '0.0.0.0'
    _port = parts[0]

    if len(parts) == 2:
        ip, _port = parts

    port = int(_port)
    return ip, port


def sock_id(sock: socket.socket):
    ip, port = sock.getpeername()
    ip = struct.unpack("!I", socket.inet_aton(ip))[0]

    return (ip << 16) + int(port)


def six_bytes_id_to_int(data):
    _id_a = struct.unpack("!L", data[:4])[0]
    _id_b = struct.unpack("!H", data[4:6])[0]
    return (_id_a << 16) + _id_b


def send_data(sock, data):
    bytes_sent = 0
    while True:
        r = sock.send(data[bytes_sent:])
        if r < 0:
            return r
        bytes_sent += r
        if bytes_sent == len(data):
            return bytes_sent


def _forward_data(sock, remote, max_len=None, middleware=[]):
    # 一次最多读取 4096 字节, 再多的分多次读取
    if max_len is None or max_len > 4096:
        max_len = 4096

    data = sock.recv(max_len)

    l = len(data)
    if l <= 0:
        return 0

    middleware = middleware if middleware is not None else []
    for m in middleware:
        data = m(data)

    result = send_data(remote, data)
    if result < l:
        raise Exception('failed to send all data: {} < {}'.format(result, l))

    return l


def forward_data(sock, remote, length=None, middleware=None):
    if length is None:
        return _forward_data(sock, remote, middleware=middleware)

    cnt = 0
    while cnt < length:
        l = _forward_data(sock, remote, max_len=length - cnt, middleware=middleware)
        cnt += l

        if l == 0:
            raise Exception("数据长度不足")

    return cnt
