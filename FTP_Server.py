import re
import sys
import os
import socket

USER_REGEX = re.compile(r'^\s*(USER)\s+([^\r\n ][\x00-\x7F]*)\r\n$', re.IGNORECASE)
PASS_REGEX = re.compile(r'^\s*(PASS)\s+([^\r\n ][\x00-\x7F]*)\r\n$', re.IGNORECASE)
TYPE_REGEX = re.compile(r'^TYPE\s+(A|I)\r\n$', re.IGNORECASE)
RETR_REGEX = re.compile(r'^RETR\s+(.+)\r\n$', re.IGNORECASE)
PORT_REGEX = re.compile(r'^PORT\s+(\d+),(\d+),(\d+),(\d+),(\d+),(\d+)\r\n$', re.IGNORECASE)
SYST_REGEX = re.compile(r'^SYST\r\n$', re.IGNORECASE)
NOOP_REGEX = re.compile(r'^NOOP\r\n$', re.IGNORECASE)


class FTPServer:
    def __init__(self):
        self.is_authenticated = False
        self.user_provided = False
        self.quit_called = False
        self.port_configured = False
        self.current_user = None
        self.file_transfer_count = 0
        self.transfer_dir = "retr_files"
        os.makedirs(self.transfer_dir, exist_ok=True)

    def process_command(self, cmd_input, connection):
        print(cmd_input, end="")

        if cmd_input[0].isspace():
            self.user_provided = False
            return "500 Syntax error, command unrecognized.\r\n"

        tokens = cmd_input.strip().split(maxsplit=1)
        cmd = tokens[0].upper() if tokens else ""
        args = tokens[1] if len(tokens) > 1 else ""

        if cmd.strip() == "QUIT":
            self.quit_called = True
            return "221 Goodbye.\r\n"

        if cmd in ["USER", "PASS", "TYPE", "RETR", "PORT", "SYST", "NOOP"]:
            if cmd == "USER":
                m = USER_REGEX.match(cmd_input)
                if m:
                    self.user_provided = True
                    self.is_authenticated = False
                    self.port_configured = False
                    self.current_user = m.group(2)
                    return "331 Guest access OK, send password.\r\n"
                self.user_provided = False
                self.is_authenticated = False
                return "501 Syntax error in parameter.\r\n"

            if cmd == "PASS":
                if not self.user_provided:
                    self.is_authenticated = False
                    return "503 Bad sequence of commands.\r\n"
                m = PASS_REGEX.match(cmd_input)
                if m:
                    self.user_provided = False
                    self.is_authenticated = True
                    return "230 Guest login OK.\r\n"
                return "501 Syntax error in parameter.\r\n"

            if self.is_authenticated:
                if cmd == "TYPE":
                    if (m := TYPE_REGEX.match(cmd_input)):
                        return f"200 Type set to {m.group(1).upper()}.\r\n"
                    return "501 Syntax error in parameter.\r\n"

                if cmd == "SYST":
                    if (m := SYST_REGEX.match(cmd_input)):
                        return "215 UNIX Type: L8.\r\n"
                    return "501 Syntax error in parameter.\r\n"

                if cmd == "NOOP":
                    if (m := NOOP_REGEX.match(cmd_input)):
                        return "200 Command OK.\r\n"
                    return "501 Syntax error in parameter.\r\n"

                if cmd == "PORT":
                    if (m := PORT_REGEX.match(cmd_input)):
                        self.data_ip = '.'.join(m.group(1, 2, 3, 4))
                        self.data_port = (int(m.group(5)) * 256) + int(m.group(6))
                        self.port_configured = True
                        return f"200 Port command successful ({self.data_ip},{self.data_port}).\r\n"
                    return "501 Syntax error in parameter.\r\n"

                if cmd == "RETR":
                    if (m := RETR_REGEX.match(cmd_input)):
                        if not self.port_configured:
                            return "503 Bad sequence of commands.\r\n"
                        if not args or not os.path.isfile(args):
                            return "550 File not found or access denied.\r\n"

                        self.file_transfer_count += 1
                        filename = f"file{self.file_transfer_count}"
                        target_path = os.path.join(self.transfer_dir, filename)

                        connection.sendall("150 File status okay.\r\n".encode())
                        print("150 File status okay.\r\n", end="")
                        try:
                            data_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                            data_socket.settimeout(10)
                            data_socket.connect((self.data_ip, self.data_port))
                            with open(args, "rb") as f:
                                while True:
                                    chunk = f.read(1024)
                                    if not chunk:
                                        break
                                    data_socket.sendall(chunk)
                            data_socket.close()
                            self.port_configured = False
                            return "250 Requested file action completed.\r\n"
                        except Exception as e:
                            self.port_configured = False
                            return "425 Can not open data connection.\r\n"

                    return "501 Syntax error in parameter.\r\n"

            self.user_provided = False
            return "530 Not logged in.\r\n"

        self.user_provided = False
        return "500 Syntax error, command unrecognized.\r\n"

    def start(self, port):
        main_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        main_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        main_socket.bind(('', port))
        main_socket.listen(1)

        while True:
            client_conn, client_address = main_socket.accept()
            welcome_msg = "220 COMP 431 FTP server ready.\r\n"
            print(welcome_msg, end="")
            client_conn.sendall(welcome_msg.encode())

            self.is_authenticated = False
            self.user_provided = False
            self.quit_called = False
            self.port_configured = False
            self.current_user = None
            self.file_transfer_count = 0

            while True:
                try:
                    incoming_data = client_conn.recv(1024).decode()
                    if not incoming_data:
                        break

                    response = self.process_command(incoming_data, client_conn)
                    print(response, end="")
                    client_conn.sendall(response.encode())

                    if incoming_data.upper().startswith("QUIT"):
                        break

                except Exception as e:
                    print("Error:", e)
                    break

            client_conn.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 FTP_Server.py <port>")
        sys.exit(1)

    server_port = int(sys.argv[1])
    ftp_server = FTPServer()
    ftp_server.start(server_port)