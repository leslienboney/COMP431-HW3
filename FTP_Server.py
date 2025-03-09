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
        self.shutdown = False
        self.data_ready = False
        self.current_user = None
        self.transfer_count = 0
        self.download_dir = "retr_files"
        os.makedirs(self.download_dir, exist_ok=True)

    def process_command(self, input_cmd, connection):
        print(input_cmd, end="")

        if self._invalid_command_start(input_cmd):
            return self._handle_invalid_start()

        cmd, arguments = self._parse_command(input_cmd)

        if self._is_quit_command(cmd):
            return self._process_quit()

        return self._handle_command_types(cmd, input_cmd, arguments, connection)

    def _invalid_command_start(self, cmd):
        return cmd[0].isspace()

    def _handle_invalid_start(self):
        self.user_provided = False
        return "500 Syntax error, command unrecognized.\r\n"

    def _parse_command(self, cmd):
        parts = cmd.strip().split(maxsplit=1)
        return (
            parts[0].upper() if parts else "",
            parts[1] if len(parts) > 1 else ""
        )

    def _is_quit_command(self, cmd):
        return cmd.strip() == "QUIT"

    def _process_quit(self):
        self.shutdown = True
        return "221 Goodbye.\r\n"

    def _handle_command_types(self, cmd, input_cmd, arguments, connection):
        command_handlers = {
            "USER": self._handle_user,
            "PASS": self._handle_pass,
            "TYPE": self._handle_type,
            "SYST": self._handle_syst,
            "NOOP": self._handle_noop,
            "PORT": self._handle_port,
            "RETR": self._handle_retr
        }

        if cmd not in command_handlers:
            self.user_provided = False
            return "500 Syntax error, command unrecognized.\r\n"

        return command_handlers[cmd](input_cmd, arguments, connection)

    def _handle_user(self, input_cmd, *args):
        m = USER_REGEX.match(input_cmd)
        if not m:
            self.user_provided = False
            self.is_authenticated = False
            return "501 Syntax error in parameter.\r\n"

        self.user_provided = True
        self.is_authenticated = False
        self.data_ready = False
        self.current_user = m.group(2)
        return "331 Guest access OK, send password.\r\n"

    def _handle_pass(self, input_cmd, *args):
        if not self.user_provided:
            self.is_authenticated = False
            return "503 Bad sequence of commands.\r\n"

        if not PASS_REGEX.match(input_cmd):
            return "501 Syntax error in parameter.\r\n"

        self.user_provided = False
        self.is_authenticated = True
        return "230 Guest login OK.\r\n"

    def _handle_type(self, input_cmd, *args):
        if not self.is_authenticated:
            return self._auth_error()

        m = TYPE_REGEX.match(input_cmd)
        return f"200 Type set to {m.group(1).upper()}.\r\n" if m else "501 Syntax error in parameter.\r\n"

    def _handle_syst(self, input_cmd, *args):
        if not self.is_authenticated:
            return self._auth_error()

        return "215 UNIX Type: L8.\r\n" if SYST_REGEX.match(input_cmd) else "501 Syntax error in parameter.\r\n"

    def _handle_noop(self, input_cmd, *args):
        if not self.is_authenticated:
            return self._auth_error()

        return "200 Command OK.\r\n" if NOOP_REGEX.match(input_cmd) else "501 Syntax error in parameter.\r\n"

    def _handle_port(self, input_cmd, *args):
        if not self.is_authenticated:
            return self._auth_error()

        m = PORT_REGEX.match(input_cmd)
        if not m:
            return "501 Syntax error in parameter.\r\n"

        self.client_address = '.'.join(m.group(1, 2, 3, 4))
        self.client_port = (int(m.group(5)) * 256) + int(m.group(6))
        self.data_ready = True
        return f"200 Port command successful ({self.client_address},{self.client_port}).\r\n"

    def _handle_retr(self, input_cmd, arguments, connection):
        if not self.is_authenticated:
            return self._auth_error()

        m = RETR_REGEX.match(input_cmd)
        if not m or not arguments or not os.path.isfile(arguments):
            return "550 File not found or access denied.\r\n"

        if not self.data_ready:
            return "503 Bad sequence of commands.\r\n"

        self.transfer_count += 1
        connection.sendall("150 File status okay.\r\n".encode())
        print("150 File status okay.\r\n", end="")

        try:
            data_channel = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            data_channel.settimeout(10)
            data_channel.connect((self.client_address, self.client_port))
            with open(arguments, "rb") as f:
                while chunk := f.read(1024):
                    data_channel.sendall(chunk)
            data_channel.close()
            self.data_ready = False
            return "250 Requested file action completed.\r\n"
        except Exception:
            self.data_ready = False
            return "425 Can not open data connection.\r\n"

    def _auth_error(self):
        self.user_provided = False
        return "530 Not logged in.\r\n"

    def start(self, port_num):
        self._initialize_server(port_num)
        self._handle_incoming_connections()

    def _initialize_server(self, port):
        self.main_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.main_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADD