import re
import sys
import os
import shutil
import socket

CMD_USER = re.compile(r'^\s*USER\s+([^\r\n ]+)\r\n$', re.IGNORECASE)
CMD_PASS = re.compile(r'^\s*PASS\s+([^\r\n ]+)\r\n$', re.IGNORECASE)
CMD_TYPE = re.compile(r'^TYPE\s+([AI])\r\n$', re.IGNORECASE)
CMD_RETR = re.compile(r'^RETR\s+(.+)\r\n$', re.IGNORECASE)
CMD_PORT = re.compile(r'^PORT\s+(\d+),(\d+),(\d+),(\d+),(\d+),(\d+)\r\n$', re.IGNORECASE)
CMD_SYST = re.compile(r'^SYST\r\n$', re.IGNORECASE)
CMD_NOOP = re.compile(r'^NOOP\r\n$', re.IGNORECASE)


class FTPServer:
    def __init__(self):
        self.session = {
            'authenticated': False,
            'expect_password': False,
            'data_ready': False,
            'transfer_count': 0,
            'client_address': None
        }
        self.storage_dir = "downloaded_files"
        os.makedirs(self.storage_dir, exist_ok=True)

    def process_client_command(self, command_input, connection):
        print(command_input, end="")

        if command_input.startswith((' ', '\t')):
            return "500 Syntax error, command unrecognized.\r\n"

        if command_input.strip().upper() == 'QUIT\r\n':
            return "221 Goodbye.\r\n"

        command_parts = command_input.strip().split(maxsplit=1)
        cmd_key = command_parts[0].upper() if command_parts else ""

        handlers = {
            'USER': self.handle_user_auth,
            'PASS': self.handle_password,
            'TYPE': self.handle_type_set,
            'RETR': self.handle_file_transfer,
            'PORT': self.handle_data_port,
            'SYST': self.handle_system_info,
            'NOOP': self.handle_noop
        }

        return handlers.get(cmd_key, lambda *_: "500 Syntax error, command unrecognized.\r\n")(command_input,
                                                                                               connection)

    def handle_user_auth(self, command, _):
        auth_match = CMD_USER.match(command)
        if not auth_match:
            return "501 Syntax error in parameter.\r\n"

        self.session.update({
            'expect_password': True,
            'authenticated': False,
            'data_ready': False
        })
        return "331 Guest access OK, send password.\r\n"

    def handle_password(self, command, _):
        if not self.session['expect_password']:
            return "503 Bad sequence of commands.\r\n"

        pass_match = CMD_PASS.match(command)
        if not pass_match:
            return "501 Syntax error in parameter.\r\n"

        self.session.update({
            'authenticated': True,
            'expect_password': False
        })
        return "230 Guest login OK.\r\n"

    def handle_data_port(self, command, _):
        port_match = CMD_PORT.match(command)
        if not port_match:
            return "501 Syntax error in parameter.\r\n"

        ip_components = list(map(int, port_match.groups()[:4]))
        port_number = (int(port_match.group(5)) * 256) + int(port_match.group(6))

        self.session['client_address'] = ('.'.join(map(str, ip_components)), port_number)
        self.session['data_ready'] = True

        return f"200 Port command successful ({self.session['client_address'][0]},{self.session['client_address'][1]}).\r\n"

    def handle_file_transfer(self, command, conn):
        if not self.session['data_ready']:
            return "503 Bad sequence of commands.\r\n"

        file_match = CMD_RETR.match(command)
        if not file_match or not os.path.isfile(file_match.group(1)):
            return "550 File not found or access denied.\r\n"

        file_path = file_match.group(1)
        conn.sendall("150 File status okay.\r\n".encode())
        print("150 File status okay.\r\n", end="")

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as data_sock:
                data_sock.settimeout(10)
                data_sock.connect(self.session['client_address'])
                with open(file_path, 'rb') as file_stream:
                    shutil.copyfileobj(file_stream, data_sock.makefile('wb'))

            self.session['transfer_count'] += 1
            dest_file = os.path.join(self.storage_dir, f"file{self.session['transfer_count']}")
            shutil.copy(file_path, dest_file)
            return "250 Requested file action completed.\r\n"
        except Exception:
            return "425 Can not open data connection.\r\n"
        finally:
            self.session['data_ready'] = False

    def handle_type_set(self, command, _):
        type_match = CMD_TYPE.match(command)
        if type_match:
            return f"200 Type set to {type_match.group(1).upper()}.\r\n"
        return "501 Syntax error in parameter.\r\n"

    def handle_system_info(self, command, _):
        if CMD_SYST.match(command):
            return "215 UNIX Type: L8.\r\n"
        return "501 Syntax error in parameter.\r\n"

    def handle_noop(self, command, _):
        if CMD_NOOP.match(command):
            return "200 Command OK.\r\n"
        return "501 Syntax error in parameter.\r\n"

    def start_service(self, service_port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(('', service_port))
            listener.listen(1)
            print("220 COMP 431 FTP server ready.\r\n", end="")

            while True:
                client_conn, client_addr = listener.accept()
                with client_conn:
                    client_conn.sendall(b"220 COMP 431 FTP server ready.\r\n")
                    self.session = {
                        'authenticated': False,
                        'expect_password': False,
                        'data_ready': False,
                        'transfer_count': 0,
                        'client_address': None
                    }

                    while True:
                        try:
                            incoming_data = client_conn.recv(1024).decode()
                            if not incoming_data:
                                break

                            response = self.process_client_command(incoming_data, client_conn)
                            print(response, end="")
                            client_conn.sendall(response.encode())

                            if incoming_data.strip().upper().startswith("QUIT"):
                                break
                        except Exception as e:
                            break


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 FTP_Server.py <port>")
        sys.exit(1)

    ftp_server = FTPServer()
    ftp_server.start_service(int(sys.argv[1]))