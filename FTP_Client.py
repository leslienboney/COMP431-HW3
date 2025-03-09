import sys
import os
import socket
import re

ASCII_VALS = {
    "A": ord("A"), "Z": ord("Z"), "a": ord("a"), "z": ord("z"),
    "0": ord("0"), "9": ord("9"), "min": 0, "max": 127
}

USER_REGEX = re.compile(r'^\s*(USER)\s+([^\r\n ][\x00-\x7F]*)\r\n$', re.I)
PASS_REGEX = re.compile(r'^\s*(PASS)\s+([^\r\n ][\x00-\x7F]*)\r\n$', re.I)
TYPE_REGEX = re.compile(r'^TYPE\s+(A|I)\r\n$', re.I)
RETR_REGEX = re.compile(r'^RETR\s+(.+)\r\n$', re.I)
PORT_REGEX = re.compile(r'^PORT\s+(\d+),(\d+),(\d+),(\d+),(\d+),(\d+)\r\n$', re.I)
SYST_REGEX = re.compile(r'^SYST\r\n$', re.I)
NOOP_REGEX = re.compile(r'^NOOP\r\n$', re.I)


class FTPClient:
    def __init__(self):
        self.control = None
        self.allowed = ["CONNECT"]
        self.port = int(sys.argv[1])
        self.file_count = 0

    def start(self):
        for cmd in sys.stdin:
            sys.stdout.write(cmd)
            parts = cmd.strip().split()
            if not parts:
                continue

            action = parts[0].upper()
            if action not in self.allowed:
                print("ERROR -- Command Unexpected/Unknown")
                continue

            if action == "CONNECT":
                msg, s_port, host = self.handle_connect(cmd)
                if "ERROR" in msg:
                    print(msg)
                    continue
                print(msg, end='')

                if self.control:
                    self.do_quit()
                    self.control.close()
                    self.control = None

                try:
                    self.control = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    self.control.connect((host, s_port))
                except:
                    print("CONNECT failed")
                    self.control = None
                    continue

                reply = self.control.recv(1024).decode()
                p_reply, _ = self.parse_response(reply)
                print(p_reply, end='')

                for ftp_cmd in self.auth_sequence():
                    sys.stdout.write(ftp_cmd)
                    self.control.sendall(ftp_cmd.encode())
                    resp = self.control.recv(1024).decode()
                    pr, _ = self.parse_response(resp)
                    print(pr, end='')

                self.allowed = ["CONNECT", "GET", "QUIT"]

            elif action == "GET":
                if not self.control:
                    print("ERROR -- No FTP control connection established")
                    continue
                res = self.parse_get_cmd(cmd)
                if isinstance(res, tuple):
                    response, fpath = res
                    print(response, end='')
                else:
                    print(res)
                    continue
                self.control, self.port, self.file_count = self.transfer_file(
                    self.control, self.port, parts[1], self.file_count)

            elif action == "QUIT":
                res = self.parse_quit_cmd(cmd)
                print(res, end='')
                self.do_quit()
                self.control.close()
                sys.exit(0)

    def auth_sequence(self):
        return ["USER anonymous\r\n", "PASS guest@\r\n",
                "SYST\r\n", "TYPE I\r\n"]

    def transfer_file(self, conn, port_num, fpath, count):
        try:
            data_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            data_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            data_sock.bind(('', port_num))
            data_sock.listen(1)
        except:
            print("GET failed, FTP-data port not allocated.")
            return conn, port_num, count

        cmds = self.port_retr_commands(port_num, fpath)
        final = ""
        for c in cmds:
            sys.stdout.write(c)
            conn.sendall(c.encode())
            reply = conn.recv(1024).decode()
            pr, _ = self.parse_response(reply)
            print(pr, end='')
            if c.startswith("RETR"):
                final = reply
                if final.startswith("150"):
                    fr = conn.recv(1024).decode()
                    pfr, _ = self.parse_response(fr)
                    print(pfr, end='')

        if final.startswith("550"):
            data_sock.close()
            port_num += 1
            return conn, port_num, count

        try:
            d_conn, addr = data_sock.accept()
        except:
            print("ERROR -- Unable to accept FTP-data connection")
            data_sock.close()
            port_num += 1
            return conn, port_num, count

        if not os.path.exists("retr_files"):
            os.mkdir("retr_files")
        count += 1
        new_file = os.path.join("retr_files", f"file{count}")

        with open(new_file, "wb") as f:
            while True:
                chunk = d_conn.recv(1024)
                if not chunk:
                    break
                f.write(chunk)
        d_conn.close()
        data_sock.close()
        port_num += 1
        return conn, port_num, count

    def do_quit(self):
        if not self.control:
            return
        cmd = "QUIT\r\n"
        sys.stdout.write(cmd)
        self.control.sendall(cmd.encode())
        resp = self.control.recv(1024).decode()
        pr, _ = self.parse_response(resp)
        print(pr, end='')

    def port_retr_commands(self, port, path):
        ip = socket.gethostbyname(socket.gethostname())
        ip_parts = ip.split('.')
        hi = port // 256
        lo = port % 256
        port_cmd = f"PORT {','.join(ip_parts + [str(hi), str(lo)])}\r\n"
        return [port_cmd, f"RETR {path}\r\n"]

    def handle_connect(self, cmd):
        host, port = "", -1
        if cmd[:7].upper() != "CONNECT" or len(cmd) == 7:
            return "ERROR -- request", port, host
        cmd = cmd[7:].lstrip()

        cmd, host = self.get_host(cmd)
        if "ERROR" in cmd:
            return cmd, port, host

        cmd = cmd.lstrip()
        cmd, port = self.get_port(cmd)
        port = int(port)

        if "ERROR" in cmd:
            return cmd, port, host
        if cmd.strip():
            return "ERROR -- <CRLF>", port, host
        return f"CONNECT accepted for FTP server at host {host} and port {port}\r\n", port, host

    def get_host(self, cmd):
        cmd, host = self.parse_domain(cmd)
        return cmd, host

    def get_port(self, cmd):
        nums = []
        for c in cmd:
            if c.isdigit():
                nums.append(c)
            else:
                break
        if not nums:
            return "ERROR -- server-port", ""
        if len(nums) > 1 and nums[0] == '0':
            return "ERROR -- server-port", ""
        port = int(''.join(nums))
        if port > 65535:
            return "ERROR -- server-port", ""
        return cmd[len(nums):], port

    def parse_domain(self, s):
        parts = []
        while True:
            if not s:
                break
            if s[0] == '.':
                parts.append('.')
                s = s[1:]
            elif s[0].isalpha():
                part = [s[0]]
                s = s[1:]
                while s and (s[0].isalnum() or s[0] == '-'):
                    part.append(s[0])
                    s = s[1:]
                parts.append(''.join(part))
            else:
                break
        if not parts:
            return "ERROR", ""
        return s, '.'.join(parts).rstrip('.')

    def parse_get_cmd(self, cmd):
        if cmd[:3].upper() != "GET":
            return "ERROR -- request"
        cmd = cmd[3:].lstrip()
        path = cmd.split()[0]
        if not path:
            return "ERROR -- pathname"
        remaining = cmd[len(path):].strip()
        if remaining:
            return "ERROR -- <CRLF>"
        return f"GET accepted for {path}\r\n", path

    def parse_quit_cmd(self, cmd):
        if cmd.upper() not in ["QUIT\r\n", "QUIT\n"]:
            return "ERROR -- <CRLF>"
        return "QUIT accepted, terminating FTP client\r\n"

    def parse_response(self, resp):
        if len(resp) < 3:
            return "ERROR -- reply-code", ""
        code = resp[:3]
        if not code.isdigit() or not (100 <= int(code) <= 599):
            return "ERROR -- reply-code", ""
        rest = resp[3:].lstrip()
        text = []
        while rest and rest not in ['\r\n', '\n']:
            if ord(rest[0]) < 0 or ord(rest[0]) > 127:
                return "ERROR -- reply-text", code
            text.append(rest[0])
            rest = rest[1:]
        if rest not in ['\r\n', '\n']:
            return "ERROR -- <CRLF>", code
        return f"FTP reply {code} accepted. Text is: {''.join(text)}\r\n", code


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 FTP_Client.py <port>")
        sys.exit(1)
    client = FTPClient()
    client.start()