import select
import socket
import threading
from typing import Callable, Tuple

from parseltongue.connection import ClientConnection, ServerConnection, recv


class Client:
    def __init__(self):
        self.connections = []

    def connect(self, addr: Tuple[str, int]) -> ClientConnection:
        con = ClientConnection(self, addr)
        con.open()
        self.connections.append(con)
        return con

    def close(self):
        for con in self.connections:
            con.close()

    def _remove_connection(self, con):
        self.connections.remove(con)


class Server(object):
    def __init__(self, handler: Callable, host='', port=0):
        self.address = (host, port)
        self.handler = handler

        self.engine = ServerEngine(handler, self.address)

    def open(self):
        self.address = self.engine.bind()
        self.engine.serve_async()

    def close(self):
        self.engine.close()


class ServerEngine:

    def __init__(self, handler: Callable, address):
        self.address = address
        self.handler = handler

        self.socket = None
        self.connections = {}
        self.closing = False

        self.inputs = []

        self.connection_handler_thread = None

    def bind(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.setblocking(False)

        self.socket.bind(self.address)

        self.socket.listen(10)
        self.inputs.append(self.socket)

        self.address = self.socket.getsockname()
        return self.address

    def serve_async(self):
        self.connection_handler_thread = threading.Thread(target=self.serve, name="ServerConnectionHandler")
        self.connection_handler_thread.start()

    def serve(self):
        while not self.closing:
            read, _, exc = select.select(self.inputs, [], self.inputs)

            try:
                for s in read:
                    self.socket_read(s)

            except OSError as e:
                if e.errno == 22:
                    return  # Socket closed, stop main server loop
                raise

            #for s in write:
            #    self.socket_write(s)

            for s in exc:
                self.socket_close(s)

    def socket_connect(self, s):
        con, client_address = s.accept()
        con.setblocking(False)
        self.inputs.append(con)
        self.connections[con] = ServerConnection(self, con, self.handler)

    def socket_read(self, s):
        connecting = s is self.socket

        if connecting:
            self.socket_connect(s)
            return

        con = self.connections[s]

        max_read = con.max_read_size()
        request_fragment = recv(s, max_read)
        closing = request_fragment is None or ""

        if closing:
            self.socket_close(s)
            return

        con.read_fragment(request_fragment)

    def socket_write(self, s):
        con = self.connections[s]

        for uid, response in con.get_responses():
            sent_size = s.send(response[:PACKET_SIZE])
            con.move_response_cursor(uid, sent_size)

    def socket_close(self, s):

        self.inputs.remove(s)
        self.connections.pop(s)

        s.close()

    def close(self):
        self.socket.shutdown(socket.SHUT_RDWR)
        self.closing = True
        self.connection_handler_thread.join()
