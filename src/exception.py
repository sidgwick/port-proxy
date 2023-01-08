import socket


class UnableReadSocketException(Exception):

    def __init__(self, message, sock: socket.socket):
        self.message = message
        self.sock = sock

    def __str__(self):
        return f"{self.message}, socket={self.sock.getpeername()}"


class WebsocketReadError(Exception):

    def __init__(self, message):
        self.message = message

    def __str__(self):
        return f"WebsocketReadError({self.message})"
