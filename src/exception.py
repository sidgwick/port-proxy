
class UnableReadSocketException(Exception):

    def __init__(self, message, sock):
        self.message = message
        self.sock = sock


class TargetSocketNotExist(Exception):
    pass
