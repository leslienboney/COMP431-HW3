import re
import sys
import os
import shutil
import socket
from typing import Optional, Tuple


class FTPServer:
    def __init__(self):
        self.session_state = {
            'authenticated': False,
            'user_received': False,
            'data_port': None,
            'client_addr': None,  # type: Optional[Tuple[str, int]]
            'transfer_count': 0
        }
        self.command_handlers = {
            'USER': self.handle_user,
            'PASS': self.handle_pass,
            'TYPE': self.handle_type,
            'SYST': self.handle_syst,
            'NOOP': self.handle_noop,
            'PORT': self.handle_port,
            'RETR': self.handle_retr,
            'QUIT': self.handle_quit
        }
        self.response_codes = {
            'ready': '220 COMP 431 FTP server ready.\r\n',
            'user_ok': '331 Guest access OK, send password.\r\n',
            'login_ok': '230 Guest login OK.\r\n',
            'syst_ok': '215 UNIX Type: L8.\r\n',
            'type_ok': '200 Type set to {mode}.\r\n',
            'port_ok': '200 Port command successful ({ip},{port}).\r\n',
            'retr_ready': '150 File status okay.\r\n',
            'retr_ok': '250 Requested file action completed.\r\n',
            'quit_ok': '221 Goodbye.\r\n',
            'bad_param': '501 Syntax error in parameter.\r\n',
            'bad_seq': '503 Bad sequence of commands.\r\n',
            'unauth': '530 Not logged in.\r\n',
            'file_error': '550 File not found or access denied.\r\n',
            'conn_error': '425 Can not open data connection.\r\n',
            'unrecognized': '500 Syntax error, command unrecognized.\r\n'
        }
        os.makedirs('retr_files', exist_ok=True)

    def handle_user(self, cmd: str) -> str:
        user_match = re.match(r'^\s*USER\s+(\S+)\r\n$', cmd, re.I)
        if not user_match:
            return self.response_codes['bad_param']
        self.session_state.update({
            'authenticated': False,
            'user_received': True,
            'data_port': None,
            'client_addr': None
        })
        return self.response_codes['user_ok']

    def handle_port(self, cmd: str) -> str:
        port_match = re.match(r'^PORT\s+(\d+,\d+,\d+,\d+,\d+,\d+)\r\n$', cmd, re.I)
        if not port_match:
            return self.response_codes['bad_param']

        parts = list(map(int, port_match.group(1).split(',')))
        if len(parts) != 6 or any(p < 0 or p > 255 for p in parts):
            return self.response_codes['bad_param']

        ip = '.'.join(map(str, parts[:4]))
        port = parts[4] * 256 + parts[5]
        self.session_state['client_addr'] = (ip, port)

        return self.response_codes['port_ok'].format(
            ip=ip,
            port=port
        )

    def handle_retr(self, cmd: str, conn: socket.socket) -> str:
        if not self.session_state['authenticated']:
            return self.response_codes['unauth']
        if not self.session_state['client_addr']:
            return self.response_codes['bad_seq']

        retr_match = re.match(r'^RETR\s+(\S+)\r\n$', cmd, re.I)
        if not retr_match:
            return self.response_codes['bad_param']

        file_path = retr_match.group(1)
        if not os.path.isfile(file_path):
            return self.response_codes['file_error']

        conn.sendall(self.response_codes['retr_ready'].encode())
        data_sock: Optional[socket.socket] = None

        try:
            data_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            data_sock.settimeout(10)
            data_sock.connect(self.session_state['client_addr'])

            with open(file_path, 'rb') as f:
                shutil.copyfileobj(f, data_sock.makefile('wb'))

            self.session_state['transfer_count'] += 1
            dest = os.path.join('retr_files', f'file{self.session_state["transfer_count"]}')
            shutil.copy(file_path, dest)
            return self.response_codes['retr_ok']

        except (socket.error, OSError, TimeoutError):
            return self.response_codes['conn_error']
        finally:
            if data_sock:
                data_sock.close()
            self.session_state['client_addr'] = None

    def process_command(self, cmd: str, conn: socket.socket) -> str:
        cmd_upper = cmd.strip().upper()
        for prefix in self.command_handlers:
            if cmd_upper.startswith(prefix):
                handler = self.command_handlers[prefix]
                if prefix == 'RETR':
                    return handler(cmd, conn)
                return handler(cmd)
        return self.response_codes['unrecognized']

    def run_server(self, port: int):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(('', port))
            s.listen(1)
            print(self.response_codes['ready'], end='')

            while True:
                conn, addr = s.accept()
                try:
                    conn.sendall(self.response_codes['ready'].encode())
                    self.session_state = {
                        'authenticated': False,
                        'user_received': False,
                        'data_port': None,
                        'client_addr': None,
                        'transfer_count': 0
                    }

                    while True:
                        data = conn.recv(1024).decode()
                        if not data:
                            break
                        print(data, end='')
                        response = self.process_command(data, conn)
                        print(response, end='')
                        conn.sendall(response.encode())
                        if data.strip().upper() == 'QUIT':
                            break
                finally:
                    conn.close()


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python ftpserver.py <port>")
        sys.exit(1)
    server = FTPServer()
    server.run_server(int(sys.argv[1]))