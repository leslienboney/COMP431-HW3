import re
import sys
import os
import shutil
import socket

COMMAND_REGEX = {
    'USER': re.compile(r'^\s*USER\s+(\S+)\r\n$', re.IGNORECASE),
    'PASS': re.compile(r'^\s*PASS\s+(\S+)\r\n$', re.IGNORECASE),
    'TYPE': re.compile(r'^TYPE\s+([AI])\r\n$', re.IGNORECASE),
    'RETR': re.compile(r'^RETR\s+(\S+)\r\n$', re.IGNORECASE),
    'PORT': re.compile(r'^PORT\s+(\d+,\d+,\d+,\d+,\d+,\d+)\r\n$', re.IGNORECASE),
    'SYST': re.compile(r'^SYST\r\n$', re.IGNORECASE),
    'NOOP': re.compile(r'^NOOP\r\n$', re.IGNORECASE)
}


class FTPServer:
    def __init__(self):
        self.session_state = {
            'authenticated': False,
            'expecting_password': False,
            'data_ready': False,
            'transfer_count': 0,
            'client_address': None
        }
        self.storage_dir = "downloaded_files"
        os.makedirs(self.storage_dir, exist_ok=True)

    def _process_command(self, command_input, connection):
        print(command_input, end="")
        if command_input[0].isspace():
            return "500 Syntax error, command unrecognized.\r\n"

        cmd_parts = command_input.strip().split(maxsplit=1)
        cmd_type = cmd_parts[0].upper() if cmd_parts else ""

        if cmd_type == "QUIT":
            return "221 Goodbye.\r\n"

        handler = getattr(self, f'_handle_{cmd_type}', None)
        return handler(command_input, connection) if handler else "500 Syntax error, command unrecognized.\r\n"

    def _handle_USER(self, command, _):
        match = COMMAND_REGEX['USER'].match(command)
        if match:
            self.session_state.update({
                'expecting_password': True,
                'authenticated': False,
                'data_ready': False
            })
            return "331 Guest access OK, send password.\r\n"
        return "501 Syntax error in parameter.\r\n"

    def _handle_PASS(self, command, _):
        if not self.session_state['expecting_password']:
            return "503 Bad sequence of commands.\r\n"
        if COMMAND_REGEX['PASS'].match(command):
            self.session_state.update({
                'authenticated': True,
                'expecting_password': False
            })
            return "230 Guest login OK.\r\n"
        return "501 Syntax error in parameter.\r\n"

    def _handle_PORT(self, command, _):
        match = COMMAND_REGEX['PORT'].match(command)
        if not match:
            return "501 Syntax error in parameter.\r\n"

        parts = list(map(int, match.group(1).split(',')))
        ip_address = '.'.join(map(str, parts[:4]))
        port_number = (parts[4] << 8) + parts[5]
        self.session_state['client_address'] = (ip_address, port_number)
        self.session_state['data_ready'] = True
        return f"200 Port command successful ({ip_address},{port_number}).\r\n"

    def _handle_RETR(self, command, conn):
        if not self.session_state['data_ready']:
            return "503 Bad sequence of commands.\r\n"

        match = COMMAND_REGEX['RETR'].match(command)
        if not match or not os.path.isfile(match.group(1)):
            return "550 File not found or access denied.\r\n"

        conn.sendall(b"150 File status okay.\r\n")
        print("150 File status okay.\r\n", end="")
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as data_sock:
                data_sock.settimeout(10)
                data_sock.connect(self.session_state['client_address'])
                with open(match.group(1), 'rb') as src_file:
                    shutil.copyfileobj(src_file, data_sock.makefile('wb'))

                self.session_state['transfer_count'] += 1
                dest_file = os.path.join(self.storage_dir, f"file{self.session_state['transfer_count']}")
                shutil.copy(match.group(1), dest_file)
            return "250 Requested file action completed.\r\n"
        except Exception:
            return "425 Can not open data connection.\r\n"
        finally:
            self.session_state['data_ready'] = False

    def _handle_TYPE(self, command, _):
        match = COMMAND_REGEX['TYPE'].match(command)
        if match:
            return f"200 Type set to {match.group(1).upper()}.\r\n"
        return "501 Syntax error in parameter.\r\n"

    def _handle_SYST(self, command, _):
        if COMMAND_REGEX['SYST'].match(command):
            return "215 UNIX Type: L8.\r\n"
        return "501 Syntax error in parameter.\r\n"

    def _handle_NOOP(self, command, _):
        if COMMAND_REGEX['NOOP'].match(command):
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
                    self.session_state = {
                        'authenticated': False,
                        'expecting_password': False,
                        'data_ready': False,
                        'transfer_count': 0,
                        'client_address': None
                    }
                    while True:
                        try:
                            data = client_conn.recv(1024).decode()
                            if not data:
                                break
                            response = self._process_command(data, client_conn)
                            print(response, end="")
                            client_conn.sendall(response.encode())
                            if data.strip().upper() == "QUIT":
                                break
                        except Exception:
                            break


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 FTP_Server.py <port>")
        sys.exit(1)
    FTPServer().start_service(int(sys.argv[1]))