import sys
import os
import socket
import re


class FTPClient:
    def __init__(self):
        self.control_sock = None
        self.data_port = int(sys.argv[1])  # Initial welcoming port
        self.transfer_count = 0
        self.expected_cmds = ["CONNECT"]
        self.connected = False

    # ------------------------- Main Command Loop -------------------------
    def run(self):
        for line in sys.stdin:
            line = line if '\r\n' in line else line.rstrip() + '\r\n'
            sys.stdout.write(line)
            cmd = line.strip().upper()
            if not cmd:
                continue

            if cmd.startswith("CONNECT"):
                self.handle_connect(line)
            elif cmd.startswith("GET"):
                self.handle_get(line) if self.connected else self.print_error("No control connection")
            elif cmd.startswith("QUIT"):
                self.handle_quit()
            else:
                print("ERROR -- Command Unexpected/Unknown")

    # ------------------------- Command Handlers --------------------------
    def handle_connect(self, cmd):
        host, port, err = self.parse_connect(cmd)
        if err:
            print(err)
            return

        if self.control_sock:  # Close existing connection
            self.send_quit()

        try:
            self.control_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.control_sock.connect((host, port))
            print(f"CONNECT accepted for FTP server at host {host} and port {port}\r\n", end='')
            self.read_greeting()
            self.send_login()
            self.connected = True
            self.expected_cmds = ["CONNECT", "GET", "QUIT"]
        except Exception:
            print("CONNECT failed")
            self.connected = False

    def handle_get(self, cmd):
        path, err = self.parse_get(cmd)
        if err:
            print(err)
            return

        try:
            data_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            data_sock.bind(('', self.data_port))
            data_sock.listen(1)
            self.send_port_cmd()
            self.send_retr_cmd(path)
            self.accept_data_connection(data_sock)
            self.data_port += 1  # Increment for next GET
        except Exception as e:
            print(f"GET failed, {str(e)}\r")

    def handle_quit(self):
        self.send_quit()
        self.control_sock.close()
        sys.exit(0)

    # ------------------------- Protocol Logic --------------------------
    def read_greeting(self):
        reply = self.control_sock.recv(1024).decode()
        self.parse_and_print_reply(reply)

    def send_login(self):
        for cmd in ['USER anonymous\r\n', 'PASS guest@\r\n', 'SYST\r\n', 'TYPE I\r\n']:
            self.control_sock.sendall(cmd.encode())
            sys.stdout.write(cmd)
            reply = self.control_sock.recv(1024).decode()
            self.parse_and_print_reply(reply)

    def send_port_cmd(self):
        ip = socket.gethostbyname(socket.gethostname()).replace('.', ',')
        p1, p2 = self.data_port // 256, self.data_port % 256
        port_cmd = f"PORT {ip},{p1},{p2}\r\n"
        self.control_sock.sendall(port_cmd.encode())
        sys.stdout.write(port_cmd)
        self.parse_and_print_reply(self.control_sock.recv(1024).decode())

    def send_retr_cmd(self, path):
        retr_cmd = f"RETR {path}\r\n"
        self.control_sock.sendall(retr_cmd.encode())
        sys.stdout.write(retr_cmd)
        reply = self.control_sock.recv(1024).decode()
        self.parse_and_print_reply(reply)
        if reply.startswith('150'):
            self.parse_and_print_reply(self.control_sock.recv(1024).decode())

    def accept_data_connection(self, sock):
        conn, _ = sock.accept()
        os.makedirs("retr_files", exist_ok=True)
        self.transfer_count += 1
        with open(f"retr_files/file{self.transfer_count}", 'wb') as f:
            while True:
                data = conn.recv(1024)
                if not data:
                    break
                f.write(data)
        conn.close()

    # ------------------------- Parsers --------------------------
    def parse_connect(self, cmd):
        cmd_parts = cmd[len("CONNECT"):].strip().split()
        if len(cmd_parts) < 2 or not self.validate_host(cmd_parts[0]) or not self.validate_port(cmd_parts[1]):
            return None, None, "ERROR -- Invalid CONNECT parameters\r\n"
        return cmd_parts[0], int(cmd_parts[1]), None

    def parse_get(self, cmd):
        if len(cmd.split()) < 2 or any(ord(c) > 127 for c in cmd.split()[1]):
            return None, "ERROR -- Invalid pathname\r\n"
        return cmd.split()[1], None

    def validate_host(self, host):
        return re.match(r'^([a-zA-Z0-9-]+\.)*[a-zA-Z0-9-]+$', host)

    def validate_port(self, port):
        return port.isdigit() and 0 <= int(port) <= 65535 and (len(port) == 1 or port[0] != '0')

    def parse_and_print_reply(self, reply):
        code = reply[:3]
        text = reply[4:].strip()
        print(f"FTP reply {code} accepted. Text is: {text}\r\n", end='')

    def print_error(self, msg):
        print(f"ERROR -- {msg}\r")

    def send_quit(self):
        self.control_sock.sendall(b'QUIT\r\n')
        sys.stdout.write("QUIT\r\n")
        self.parse_and_print_reply(self.control_sock.recv(1024).decode())


if __name__ == "__main__":
    client = FTPClient()
    client.run()