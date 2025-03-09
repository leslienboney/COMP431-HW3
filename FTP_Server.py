import re
import sys
import os
import socket

USER_REGEX = re.compile(r'^\s*(USER)\s+([^\r\n ][\x00-\x7F]*)\r\n$', re.I)
PASS_REGEX = re.compile(r'^\s*(PASS)\s+([^\r\n ][\x00-\x7F]*)\r\n$', re.I)
TYPE_REGEX = re.compile(r'^TYPE\s+(A|I)\r\n$', re.I)
RETR_REGEX = re.compile(r'^RETR\s+(.+)\r\n$', re.I)
PORT_REGEX = re.compile(r'^PORT\s+(\d+),(\d+),(\d+),(\d+),(\d+),(\d+)\r\n$', re.I)
SYST_REGEX = re.compile(r'^SYST\r\n$', re.I)
NOOP_REGEX = re.compile(r'^NOOP\r\n$', re.I)


class FTPServer:
    def __init__(self):
        self.authenticated = False
        self.user_pending = False
        self.terminated = False
        self.data_configured = False
        self.current_user = None
        self.transfer_count = 0
        self.storage_dir = "retr_files"
        os.makedirs(self.storage_dir, exist_ok=True)

    def process_command(self, input_data, conn):
        print(input_data, end="")
        if input_data[0].isspace():
            self.user_pending = False
            return "500 Syntax error, command unrecognized.\r\n"

        parts = input_data.strip().split(maxsplit=1)
        cmd = parts[0].upper() if parts else ""
        params = parts[1] if len(parts) > 1 else ""

        if cmd == "QUIT":
            self.terminated = True
            return "221 Goodbye.\r\n"

        if cmd in ["USER", "PASS", "TYPE", "RETR", "PORT", "SYST", "NOOP"]:
            if cmd == "USER":
                match = USER_REGEX.match(input_data)
                if match:
                    self.user_pending = True
                    self.authenticated = False
                    self.data_configured = False
                    self.current_user = match.group(2)
                    return "331 Guest access OK, send password.\r\n"
                self.user_pending = False
                return "501 Syntax error in parameter.\r\n"

            if cmd == "PASS":
                if not self.user_pending:
                    return "503 Bad sequence of commands.\r\n"
                match = PASS_REGEX.match(input_data)
                if match:
                    self.user_pending = False
                    self.authenticated = True
                    return "230 Guest login OK.\r\n"
                return "501 Syntax error in parameter.\r\n"

            if not self.authenticated:
                return "530 Not logged in.\r\n"

            if cmd == "TYPE":
                if (match := TYPE_REGEX.match(input_data)):
                    return f"200 Type set to {match.group(1).upper()}.\r\n"
                return "501 Syntax error in parameter.\r\n"

            if cmd == "SYST":
                if SYST_REGEX.match(input_data):
                    return "215 UNIX Type: L8.\r\n"
                return "501 Syntax error in parameter.\r\n"

            if cmd == "NOOP":
                if NOOP_REGEX.match(input_data):
                    return "200 Command OK.\r\n"
                return "501 Syntax error in parameter.\r\n"

            if cmd == "PORT":
                if (match := PORT_REGEX.match(input_data)):
                    self.client_ip = '.'.join(match.group(1, 2, 3, 4))
                    self.client_port = (int(match.group(5)) << 8) + int(match.group(6))
                    self.data_configured = True
                    return f"200 Port command successful ({self.client_ip},{self.client_port}).\r\n"
                return "501 Syntax error in parameter.\r\n"

            if cmd == "RETR":
                if (match := RETR_REGEX.match(input_data)):
                    if not self.data_configured:
                        return "503 Bad sequence of commands.\r\n"
                    if not params or not os.path.isfile(params):
                        return "550 File not found or access denied.\r\n"

                    self.transfer_count += 1
                    new_name = f"file{self.transfer_count}"
                    dest_path = os.path.join(self.storage_dir, new_name)

                    conn.sendall("150 File status okay.\r\n".encode())
                    print("150 File status okay.\r\n", end="")
                    try:
                        data_conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        data_conn.settimeout(10)
                        data_conn.connect((self.client_ip, self.client_port))
                        with open(params, "rb") as f:
                            while chunk := f.read(1024):
                                data_conn.sendall(chunk)
                        data_conn.close()
                        self.data_configured = False
                        return "250 Requested file action completed.\r\n"
                    except Exception:
                        self.data_configured = False
                        return "425 Can not open data connection.\r\n"
                return "501 Syntax error in parameter.\r\n"

        return "500 Syntax error, command unrecognized.\r\n"

    def start_server(self, port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('', port))
        sock.listen(1)

        while True:
            conn, addr = sock.accept()
            greeting = "220 COMP 431 FTP server ready.\r\n"
            print(greeting, end="")
            conn.sendall(greeting.encode())

            self.authenticated = False
            self.user_pending = False
            self.terminated = False
            self.data_configured = False
            self.current_user = None
            self.transfer_count = 0

            while True:
                try:
                    data = conn.recv(1024).decode()
                    if not data:
                        break
                    response = self.process_command(data, conn)
                    print(response, end="")
                    conn.sendall(response.encode())
                    if data.upper().startswith("QUIT"):
                        break
                except Exception as e:
                    print("Error:", e)
                    break
            conn.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 FTPServer.py <port>")
        sys.exit(1)
    port = int(sys.argv[1])
    server = FTPServer()
    server.start_server(port)