import struct
import socket


def parse_xaddr(addr):
    parts = addr.split('//')
    protocol = parts[0][0:-1]
    ip, port = parse_ip_port(parts[1])
    return protocol, ip, port


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


def parse_http(data: bytes) -> tuple[str, dict[str, str], bytes]:
    # 解析 HTTP 请求头
    lines = data.split(b"\r\n")
    line_number = len(lines)

    http = lines[0].decode()  # first line
    headers = {}
    body = []

    for idx in range(1, line_number):
        line = lines[idx]
        idx += 1

        if line == b"":
            body = lines[idx]
            break

        k, v = [x.strip() for x in line.split(b":", maxsplit=1)]
        kk = k.decode()
        vv = v.decode()
        headers[kk] = vv

    body = b"\r\n".join(body)
    return http, headers, body
