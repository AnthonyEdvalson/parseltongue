# parseltongue

A simple socket communication package for Python.

This package was created because for many projects that I work on, I need to communicate using sockets, and the socket API that python comes with tends to be very wordy and difficult to use.

parseltongue is a wrapper around the standard python socket API that provides an OO interface that is much easier to work with.

# How to Use

```python
# Server
import parseltongue

def echo(data: bytes):
    return data

server = parseltongue.Server(echo, port=5000)
server.open()

input("Press enter to close server")

server.close()
```

```python
# Client
import parseltongue

address = ("localhost", 5000)
client = parseltongue.Client()
connection = client.connect(address)

reponse = connection.send(b"Hello, World!")

print(response)  # Prints b'Hello, World!'
```
