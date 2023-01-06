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
    ip = struct.unpack("!L", data[:4])[0]
    port = struct.unpack("!H", data[4:6])[0]
    return (ip << 16) + port
