import os
import random
import time
from threading import Thread, Event
from parseltongue import Client, Server


class TestEnv:
    def __init__(self, client_count=1):
        self.client_count = client_count

    def __enter__(self):
        self.server = Server(self.echo)
        self.server.open()

        self.clients = []

        for client in range(0, self.client_count):
            client = Client()
            client.connect(self.server.address)
            self.clients.append(client)

        return self

    def echo(self, data: bytes):
        time.sleep(random.random() * 0.2)
        return data

    def __exit__(self, exc_type, exc_val, exc_tb):
        for client in self.clients:
            client.close()

        self.server.close()


def test_sending_empty_message():
    """ Make sure it can send an empty message """
    simple_echo_assert(0)


def test_sending_small_message():
    """ Make sure it can send a message that fits in a single packet """
    simple_echo_assert(20)


def test_sending_long_message():
    """ Make sure it can send a message that is too large for a single packet """
    simple_echo_assert(10000)


def test_sending_massive_message():
    """ Make sure it can send a message that stresses memory usage """
    simple_echo_assert(2**25)  # send 32 MiB of data


def test_sending_multiple_long_messages():
    """ Make sure multiple clients can communicate over one socket without interference """
    simple_echo_assert(10000, 20)


def simple_echo_assert(msg_len, clients=1):
    msg = os.urandom(msg_len)

    trigger = Event()
    successes = 0

    def send_on_trigger(client):
        nonlocal successes
        trigger.wait()

        for connection in client.connections:
            if type(msg) == list:
                m = random.choice(msg)
            else:
                m = msg

            res = connection.send(m)

            if res == m:
                successes += 1

    threads = []

    with TestEnv(clients) as env:
        i = 0
        for client in env.clients:
            i += 1
            t = Thread(target=send_on_trigger, args=(client,), name="client " + str(i))
            threads.append(t)
            t.start()

        trigger.set()  # make sure all threads run at the same time

        for thread in threads:
            thread.join()

    assert successes == clients
