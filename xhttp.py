import socket
import datetime
import time


def http2_test(sock: socket.socket):
    data = [
        "HTTP/1.1 200 OK",
        "Content-Type: text/plain",
        "Transfer-Encoding: chunked",
        "",
        "",
    ]

    data = "\r\n".join(data)

    resp = data.encode()
    print("resp: ", data)
    sock.sendall(resp)
    sock.close()
    return



def chunked_test(sock: socket.socket):
    data = [
        "HTTP/1.1 200 OK",
        "Content-Type: text/plain",
        "Transfer-Encoding: chunked",
        "",
        "",
    ]

    xdata = [
        r"7",
        r"Mozilla",
        r"11",
        r"Developer Network",
        r"0",
        r"",
        r"",

        # r"7\r\n",
        # r"Mozilla\r\n",
        # r"11\r\n",
        # r"Developer Network\r\n",
        # r"0\r\n",
        # r"\r\n",
    ]

    data = "\r\n".join(data)
    data += "\r\n".join(xdata)

    resp = data.encode()
    print("resp: ", data)
    sock.sendall(resp)
    sock.close()
    return


def chunk_http_server(sock: socket.socket):
    _resp = [
        "HTTP/1.1 200 OK",
        "Content-Type: text/plain",
        "X-Accel-Buffering: no",
        "Transfer-Encoding: chunked",
        "",
        "",
    ]

    resp = "\r\n".join(_resp).encode()

    print(f"response header sent: {resp}")
    sock.sendall(resp)

    cnt = 0
    while True:
        cnt += 1

        tm = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _data = f"line {cnt} + {tm}"
        xlen = len(_data)
        data = f'{xlen:x}\r\n{_data}\r\n'.encode()

        print(f"chunk send: {data}")
        sock.sendall(data)

        if cnt >= 5:
            break

        time.sleep(1)

    data = '0\r\n\r\n\r\n'.encode()
    print(f"chunk send: {data}")

    sock.sendall(data)
    sock.close()

    print("http serve done")


def serve_http(sock: socket.socket):
    recv = sock.recv(102400)
    print("====== request data received ======")
    print(recv.decode())
    print("====== request data received print end ======")

    # return chunked_test(sock)
    http2_test(sock)


def serve():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    sock.bind(('127.0.0.1', 7556))
    sock.listen()

    while True:
        conn, _addr = sock.accept()
        serve_http(conn)


if __name__ == '__main__':
    serve()
