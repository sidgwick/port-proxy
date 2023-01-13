import socket
from urllib import parse
import time


def http2(sock: socket.socket, u: parse.ParseResult):
    _req = [
        f"GET {u.path} HTTP/1.1",
        f"Host: {u.netloc}",
        "Connection: Upgrade, HTTP2-Settings",
        "Upgrade: h2c",
        "HTTP2-Settings: <base64url encoding of HTTP/2 SETTINGS payload>",
        "x-tt-env: boe_szg_dev",
        "x-use-boe: 1",
        "",
        "",
    ]

    req = "\r\n".join(_req).encode()
    sock.sendall(req)

    while True:
        resp = sock.recv(10240)
        if len(resp) == 0:
            break

        print(resp)
        time.sleep(1)



def http1(sock: socket.socket, u: parse.ParseResult):
    _req = [
        f"GET {u.path} HTTP/1.1",
        f"Host: {u.netloc}",
        "x-tt-env: boe_szg_dev",
        "x-use-boe: 1",
        "",
        "",
    ]

    req = "\r\n".join(_req).encode()
    sock.sendall(req)

    while True:
        resp = sock.recv(10240)
        if len(resp) == 0:
            break

        print(resp)
        time.sleep(1)


# url = 'http://127.0.0.1:4608/brand/pp-ws/'
url = "http://ade-boe.bytedance.net/brand/pp-ws/"
u = parse.urlparse(url)

ip = socket.gethostbyname(u.hostname)
port = u.port if u.port is not None else 80

# ip = '127.0.0.1'
# port = 7556

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

print(ip, port)
sock.connect((ip, port))

http2(sock, u)
