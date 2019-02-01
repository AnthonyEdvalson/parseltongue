import select
import socket
import struct
import threading
from enum import Enum

PACKET_SIZE = 2**12  # 2^12 = 4096
HEADER_FORMAT = "QQ"
HEADER_SIZE = 16


class ConnectionState(Enum):
    Disconnected = 0
    Connecting = 1
    Open = 2
    Busy = 3
    Closing = 4


def unwrap_header(header):
    return struct.unpack(HEADER_FORMAT, header)


def wrap(data, uid):
    return struct.pack(HEADER_FORMAT, len(data), uid) + data


def recv(s, length):
    data = b""
    received_length = 0

    while received_length < length:
        new_data = s.recv(length - received_length)

        if new_data is None or len(new_data) == 0:
            return None

        data += new_data
        received_length += len(new_data)

    return data


class ClientConnection:
    def __init__(self, client, foreign_addr):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.foreign_addr = foreign_addr
        self.client = client

        self.send_lock = threading.Lock()
        self.id_counter = 0
        self.state = ConnectionState.Disconnected
        self.active_transactions = {}
        self.delegate_thread = None

        self.closing_lock = threading.Semaphore()

    def send(self, request: bytes):
        assert self.state == ConnectionState.Open

        uid = self.get_new_id()
        ticket = ResponseTicket(uid)

        message = wrap(request, uid)

        print("client sending message #" + str(uid))

        with self.send_lock:
            self.socket.sendall(message)

        self.active_transactions[uid] = ticket
        response = ticket.wait_and_get_response()
        self.active_transactions.pop(uid)

        return response

    def _delegate_async(self):
        self.delegate_thread = threading.Thread(target=self._delegate, name="ClientDelegator")
        self.delegate_thread.start()

    def _delegate(self):
        while True:
            raw_response = recv(self.socket, HEADER_SIZE)

            if raw_response is None:
                self.close()
                break
            else:
                data_length, uid = unwrap_header(raw_response)
                print("getting reply for #" + str(uid))
                data = recv(self.socket, data_length)

                self.active_transactions[uid].add_response(data)
                print("reply gotten for #" + str(uid))

    def get_new_id(self):
        v = self.id_counter
        self.id_counter += 1
        return v

    def open(self):
        print("connecting to " + str(self.foreign_addr))
        self.socket.connect(self.foreign_addr)
        self.state = ConnectionState.Open
        self._delegate_async()

    def close(self):
        has_lock = self.closing_lock.acquire(False)
        if has_lock:

            print("closing connection to " + str(self.foreign_addr))

            self.state = ConnectionState.Closing
            self.client.remove_connection(self)
            self.socket.shutdown(socket.SHUT_WR)

            self.delegate_thread.join()


class ResponseTicket:
    def __init__(self, uid: int):
        self.uid = uid
        self._response = None
        self._has_response = threading.Event()

    def add_response(self, response: bytes):
        self._response = response
        self._has_response.set()

    def wait_and_get_response(self) -> bytes:
        if self._has_response.wait(60):
            return self._response
        else:
            raise TimeoutError("No response")


class ServerConnection:

    def __init__(self, server, s, handler):
        self.server = server
        self.socket = s
        self.handler = handler

        self.reading_uid = None
        self.read_remaining = 0
        self.awaiting_header = True
        self.read_data = []

        self.reply_lock = threading.Lock()

    def max_read_size(self):
        return HEADER_SIZE if self.awaiting_header else self.read_remaining

    def read_fragment(self, read_fragment):
        if self.awaiting_header:
            assert len(read_fragment) == HEADER_SIZE
            length, uid = unwrap_header(read_fragment)

            print("server getting request for #" + str(uid))

            self.reading_uid = uid
            self.read_remaining = length
            self.awaiting_header = False
        else:
            self.read_data.append(read_fragment)
            self.read_remaining -= len(read_fragment)

        if self.read_remaining == 0:
            print("server got request for #" + str(self.reading_uid))
            request = b''.join(self.read_data)
            self.execute_async(self.reading_uid, request)
            self.read_data.clear()
            self.awaiting_header = True

    def execute_async(self, uid, request):
        t = threading.Thread(target=self.execute, args=(uid, request))
        t.start()

    def execute(self, uid, request):
        data = self.handler(request)
        response = memoryview(wrap(data, uid))
        print("response generated for #" + str(uid))

        with self.reply_lock:
            length = len(response)
            sent = 0

            while sent < length:
                try:
                    sent += self.socket.send(response[sent:])
                except OSError as e:
                    if e.errno == 11:
                        # socket became unavailable, wait until it is open again
                        select.select([], [self.socket], [])
                        continue
