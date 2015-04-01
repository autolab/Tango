#!/usr/bin/python

# reset.py - sends a TCP RST across a connection

import socket
import struct


def client(host, port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
    s.connect((host, port))
    l_onoff = 1
    l_linger = 0
    s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                 struct.pack('ii', l_onoff, l_linger))
    s.send("this is a random string that we're sending to the server")
    s.close()


def main():
    client("localhost", 9090)

if __name__ == "__main__":
    main()
