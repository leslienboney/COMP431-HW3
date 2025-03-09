import sys
import os
import socket
import re

ASCII_CODES = {
    "A": ord("A"), "Z": ord("Z"), "a": ord("a"), "z": ord("z"),
    "0": ord("0"), "9": ord("9"), "min_val": 0, "max_val": 127
}


def handle_commands():
    valid_commands = ["CONNECT"]
    data_port = int(sys.argv[1])
    control_sock = None
    file_counter = 0

    for cmd in sys.stdin:
        sys.stdout.write(cmd)
        parts = cmd.strip().split()
        if not parts:
            continue

        action = parts[0].upper()
        if action not in valid_commands:
            print("ERROR -- Command Unexpected/Unknown")
            continue

        if action == "CONNECT":
            msg, s_port, host = parse_connection(cmd)
            if "ERROR" in msg:
                print(msg)
                continue
            print(msg, end='')

            if control_sock:
                send_quit(control_sock)
                control_sock.close()
                control_sock = None

            try:
                control_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                control_sock.connect((host, s_port))
            except:
                print("CONNECT failed")
                control_sock = None
                continue

            data_port = int(sys.argv[1])
            reply = control_sock.recv(1024).decode()
            pr, _ = parse_response(reply)
            print(pr, end='')

            for ftp_cmd in login_sequence():
                sys.stdout.write(ftp_cmd)
                control_sock.sendall(ftp_cmd.encode())
                resp = control_sock.recv(1024).decode()
                pr, _ = parse_response(resp)
                print(pr, end='')

            valid_commands = ["CONNECT", "GET", "QUIT"]

        elif action == "GET":
            if not control_sock:
                print("ERROR -- No FTP control connection established")
                continue
            res = validate_get(cmd)
            if isinstance(res, tuple):
                response, fpath = res
                print(response, end='')
            else:
                print(res)
                continue
            control_sock, data_port, file_counter = process_transfer(
                control_sock, data_port, parts[1], file_counter)

        elif action == "QUIT":
            res = validate_quit(cmd)
            print(res, end='')
            send_quit(control_sock)
            control_sock.close()
            sys.exit(0)


def login_sequence():
    return ["USER anonymous\r\n", "PASS guest@\r\n",
            "SYST\r\n", "TYPE I\r\n"]


def process_transfer(conn, port, path, count):
    try:
        data_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        data_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        data_sock.bind(('', port))
        data_sock.listen(1)
    except:
        print("GET failed, FTP-data port not allocated.")
        return conn, port, count

    cmds = generate_port_retr(port, path)
    final_response = ""
    for c in cmds:
        sys.stdout.write(c)
        conn.sendall(c.encode())
        reply = conn.recv(1024).decode()
        pr, _ = parse_response(reply)
        print(pr, end='')
        if c.startswith("RETR"):
            final_response = reply
            if final_response.startswith("150"):
                fr = conn.recv(1024).decode()
                pfr, _ = parse_response(fr)
                print(pfr, end='')

    if final_response.startswith("550"):
        data_sock.close()
        port += 1
        return conn, port, count

    try:
        d_conn, addr = data_sock.accept()
    except:
        print("ERROR -- Unable to accept FTP-data connection")
        data_sock.close()
        port += 1
        return conn, port, count

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
    port += 1
    return conn, port, count


def send_quit(sock):
    if not sock:
        return
    cmd = "QUIT\r\n"
    sys.stdout.write(cmd)
    sock.sendall(cmd.encode())
    resp = sock.recv(1024).decode()
    pr, _ = parse_response(resp)
    print(pr, end='')


def generate_port_retr(port, path):
    ip = socket.gethostbyname(socket.gethostname())
    ip_parts = ip.split('.')
    hi = port // 256
    lo = port % 256
    port_cmd = f"PORT {','.join(ip_parts + [str(hi), str(lo)])}\r\n"
    return [port_cmd, f"RETR {path}\r\n"]


def parse_connection(cmd):
    host, port = "", -1
    if cmd[:7].upper() != "CONNECT" or len(cmd) == 7:
        return "ERROR -- request", port, host
    cmd = cmd[7:].lstrip()

    cmd, host = parse_host(cmd)
    if "ERROR" in cmd:
        return cmd, port, host

    cmd = cmd.lstrip()
    cmd, port = parse_port(cmd)
    port = int(port)

    if "ERROR" in cmd:
        return cmd, port, host
    if cmd.strip():
        return "ERROR -- <CRLF>", port, host
    return f"CONNECT accepted for FTP server at host {host} and port {port}\r\n", port, host


def parse_host(s):
    s, host = parse_domain(s)
    return s, host


def parse_port(s):
    nums = []
    for c in s:
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
    return s[len(nums):], port


def parse_domain(s):
    parts = []
    while s:
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


def validate_get(cmd):
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


def validate_quit(cmd):
    if cmd.upper() not in ["QUIT\r\n", "QUIT\n"]:
        return "ERROR -- <CRLF>"
    return "QUIT accepted, terminating FTP client\r\n"


def parse_response(resp):
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
    handle_commands()