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
        self.logged_in = False
        self.user_received = False
        self.quit_received = False
        self.port_set = False
        self.last_username = None
        self.retr_count = 0
        self.retr_directory = "retr_files"
        os.makedirs(self.retr_directory, exist_ok=True)

    def parse_ftp_command(self, ftp_input_data, conn):
        print(ftp_input_data, end="")

        if ftp_input_data[0].isspace():
            self.user_received = False
            return "500 Syntax error, command unrecognized.\r\n"

        parts = ftp_input_data.strip().split(maxsplit=1)
        command = parts[0].upper() if parts else ""
        params = parts[1] if len(parts) > 1 else ""

        if command.strip() == "QUIT":
            self.quit_received = True
            return "221 Goodbye.\r\n"

        if command in ["USER", "PASS", "TYPE", "RETR", "PORT", "SYST", "NOOP"]:
            if command == "USER":
                match = USER_REGEX.match(ftp_input_data)
                if match:
                    self.user_received = True
                    self.logged_in = False
                    self.port_set = False
                    self.last_username = match.group(2)
                    return "331 Guest access OK, send password.\r\n"
                self.user_received = False
                self.logged_in = False
                return "501 Syntax error in parameter.\r\n"

            if command == "PASS":
                if not self.user_received:
                    self.logged_in = False
                    return "503 Bad sequence of commands.\r\n"
                match = PASS_REGEX.match(ftp_input_data)
                if match:
                    self.user_received = False
                    self.logged_in = True
                    return "230 Guest login OK.\r\n"
                return "501 Syntax error in parameter.\r\n"

            if self.logged_in:
                if command == "TYPE":
                    if (match := TYPE_REGEX.match(ftp_input_data)):
                        return f"200 Type set to {match.group(1).upper()}.\r\n"
                    return "501 Syntax error in parameter.\r\n"

                if command == "SYST":
                    if (match := SYST_REGEX.match(ftp_input_data)):
                        return "215 UNIX Type: L8.\r\n"
                    return "501 Syntax error in parameter.\r\n"

                if command == "NOOP":
                    if (match := NOOP_REGEX.match(ftp_input_data)):
                        return "200 Command OK.\r\n"
                    return "501 Syntax error in parameter.\r\n"

                if command == "PORT":
                    if (match := PORT_REGEX.match(ftp_input_data)):
                        self.client_ip = '.'.join(match.group(1, 2, 3, 4))
                        self.client_port = (int(match.group(5)) * 256) + int(match.group(6))
                        self.port_set = True
                        return f"200 Port command successful ({self.client_ip},{self.client_port}).\r\n"
                    return "501 Syntax error in parameter.\r\n"

                if command == "RETR":
                    if (match := RETR_REGEX.match(ftp_input_data)):
                        if not self.port_set:
                            return "503 Bad sequence of commands.\r\n"
                        if not params or not os.path.isfile(params):
                            return "550 File not found or access denied.\r\n"

                        self.retr_count += 1
                        new_filename = f"file{self.retr_count}"
                        destination_path = os.path.join(self.retr_directory, new_filename)

                        conn.sendall("150 File status okay.\r\n".encode())
                        print("150 File status okay.\r\n", end="")  # This goes to the server log.
                        try:
                            data_conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                            data_conn.settimeout(10)
                            data_conn.connect((self.client_ip, self.client_port))
                            with open(params, "rb") as f:
                                while True:
                                    chunk = f.read(1024)
                                    if not chunk:
                                        break
                                    data_conn.sendall(chunk)
                            data_conn.close()  # Only close after sending all data.
                            self.port_set = False
                            return "250 Requested file action completed.\r\n"
                        except Exception as e:
                            self.port_set = False
                            return "425 Can not open data connection.\r\n"

                    return "501 Syntax error in parameter.\r\n"

            self.user_received = False
            return "530 Not logged in.\r\n"

        self.user_received = False
        return "500 Syntax error, command unrecognized.\r\n"

    def run(self, listen_port):
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind(('', listen_port))
        server_socket.listen(1)

        while True:
            conn, addr = server_socket.accept()
            greeting = "220 COMP 431 FTP server ready.\r\n"
            print(greeting, end="")
            conn.sendall(greeting.encode())

            self.logged_in = False
            self.user_received = False
            self.quit_received = False
            self.port_set = False
            self.last_username = None
            self.retr_count = 0

            while True:
                try:
                    ftp_input_data = conn.recv(1024).decode()
                    if not ftp_input_data:
                        break

                    response = self.parse_ftp_command(ftp_input_data, conn)
                    print(response, end="")
                    conn.sendall(response.encode())

                    if ftp_input_data.upper().startswith("QUIT"):
                        break

                except Exception as e:
                    print("Error:", e)
                    break

            conn.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 FTP_Server.py <port>")
        sys.exit(1)

    listen_port = int(sys.argv[1])
    server = FTPServer()
    server.run(listen_port)
