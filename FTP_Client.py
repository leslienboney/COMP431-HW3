import sys
import os
import socket
import re

char_map = {
    "A": ord("A"), "Z": ord("Z"),
    "a": ord("a"), "z": ord("z"),
    "0": ord("0"), "9": ord("9"),
    "min_val": 0, "max_val": 127}


def execute_commands():
    valid_actions = ["CONNECT"]
    data_port = int(sys.argv[1])
    control_channel = None
    file_count = 0

    for user_input in sys.stdin:
        sys.stdout.write(user_input)
        parts = user_input.strip().split()
        if not parts:
            continue

        action = parts[0].upper()
        if action not in valid_actions:
            print("ERROR -- Command Unexpected/Unknown")
            continue

        if action == "CONNECT":
            result_msg, port_num, hostname = check_connection(user_input)
            if "ERROR" in result_msg:
                print(result_msg)
                continue
            print(result_msg, end='')

            if control_channel:
                end_session(control_channel)
                control_channel.close()
                control_channel = None

            try:
                control_channel = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                control_channel.connect((hostname, port_num))
            except Exception:
                print("CONNECT failed")
                control_channel = None
                continue

            data_port = int(sys.argv[1])
            response = control_channel.recv(1024).decode()
            formatted_resp, _ = process_response(response)
            print(formatted_resp, end='')

            for ftp_cmd in auth_sequence():
                sys.stdout.write(ftp_cmd)
                control_channel.sendall(ftp_cmd.encode())
                response = control_channel.recv(1024).decode()
                formatted_resp, _ = process_response(response)
                print(formatted_resp, end='')

            valid_actions = ["CONNECT", "FETCH", "EXIT"]

        elif action == "FETCH":
            if not control_channel:
                print("ERROR -- No FTP control connection established")
                continue
            result = validate_fetch(user_input)
            if isinstance(result, tuple):
                response_msg, path = result
                print(response_msg, end='')
            else:
                print(result)
                continue
            control_channel, data_port, file_count = handle_transfer(
                control_channel, data_port, parts[1], file_count)

        elif action == "EXIT":
            result = validate_exit(user_input)
            print(result, end='')
            end_session(control_channel)
            control_channel.close()
            sys.exit(0)


def handle_transfer(conn, port_val, path, count):
    try:
        data_link = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        data_link.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        data_link.bind(('', port_val))
        data_link.listen(1)
    except Exception:
        print("FETCH failed, FTP-data port not allocated.")
        return conn, port_val, count

    cmd_list = build_transfer_cmds(port_val, path)
    final_resp = ""
    for ftp_cmd in cmd_list:
        sys.stdout.write(ftp_cmd)
        conn.sendall(ftp_cmd.encode())
        response = conn.recv(1024).decode()
        formatted_resp, _ = process_response(response)
        print(formatted_resp, end='')
        if ftp_cmd.startswith("RETR"):
            final_resp = response
            if final_resp.startswith("150"):
                end_resp = conn.recv(1024).decode()
                formatted_end, _ = process_response(end_resp)
                print(formatted_end, end='')

    if final_resp.startswith("550"):
        data_link.close()
        port_val += 1
        return conn, port_val, count

    try:
        transfer_link, addr = data_link.accept()
    except Exception:
        print("ERROR -- Unable to accept FTP-data connection")
        data_link.close()
        port_val += 1
        return conn, port_val, count

    if not os.path.exists("retr_files"):
        os.mkdir("retr_files")
    count += 1
    new_file = os.path.join("retr_files", f"file{count}")

    with open(new_file, "wb") as f:
        while True:
            chunk = transfer_link.recv(1024)
            if not chunk:
                break
            f.write(chunk)
    transfer_link.close()
    data_link.close()
    port_val += 1
    return conn, port_val, count


def end_session(conn):
    if not conn:
        return
    exit_cmd = "EXIT\r\n"
    sys.stdout.write(exit_cmd)
    conn.sendall(exit_cmd.encode())
    response = conn.recv(1024).decode()
    formatted_resp, _ = process_response(response)
    print(formatted_resp, end='')


def auth_sequence():
    return ["USER anonymous\r\n", "PASS guest@\r\n", "SYST\r\n", "TYPE I\r\n"]


def build_transfer_cmds(port_val, path):
    local_ip = socket.gethostbyname(socket.gethostname())
    ip_parts = local_ip.split('.')
    upper = port_val // 256
    lower = port_val % 256
    port_spec = ",".join(ip_parts + [str(upper), str(lower)])
    return [f"PORT {port_spec}\r\n", f"RETR {path}\r\n"]


def check_connection(cmd):
    hostname = ""
    port_num = -1
    if cmd[:7].upper() != "CONNECT" or len(cmd) == 7:
        return "ERROR -- request", port_num, hostname
    cmd = cmd[7:].lstrip()

    cmd = check_whitespace(cmd)
    if len(cmd) > 1:
        cmd, hostname = get_host(cmd)
    else:
        cmd = "ERROR -- server-host"

    if "ERROR" in cmd:
        return cmd, port_num, hostname

    cmd = check_whitespace(cmd)
    if len(cmd) > 1:
        cmd, port_num = get_port(cmd)
    else:
        cmd = "ERROR -- server-port"

    port_num = int(port_num)
    if "ERROR" in cmd:
        return cmd, port_num, hostname
    if cmd.strip():
        return "ERROR -- <CRLF>", port_num, hostname
    return f"CONNECT accepted for FTP server at host {hostname} and port {port_num}\r\n", port_num, hostname


def validate_fetch(cmd):
    if cmd[:3].upper() != "FETCH":
        return "ERROR -- request"
    cmd = cmd[3:].lstrip()

    cmd = check_whitespace(cmd)
    cmd, path = check_path(cmd)

    if "ERROR" in cmd:
        return cmd
    if cmd.strip():
        return "ERROR -- <CRLF>"
    return f"FETCH accepted for {path}\r\n", path


def validate_exit(cmd):
    if cmd.upper() not in ["EXIT\r\n", "EXIT\n"]:
        return "ERROR -- <CRLF>"
    return "EXIT accepted, terminating FTP client\r\n"


def get_host(s):
    s, host = parse_domain(s)
    return s, host


def get_port(s):
    digits = []
    port_str = ""
    for c in s:
        if ord(c) >= char_map["0"] and ord(c) <= char_map["9"]:
            digits.append(c)
            port_str += c
        else:
            break
    if len(digits) < 5:
        if digits and digits[0] == '0' and len(digits) > 1:
            return "ERROR -- server-port"
        return s[len(digits):], port_str
    elif len(digits) == 5:
        if digits[0] == '0' or int(s[:5]) > 65535:
            return "ERROR -- server-port"
    return s[len(digits):], port_str


def check_path(s):
    path = ""
    if s[:2] in ['\r\n', '\n']:
        return "ERROR -- pathname", path

    while len(s) > 1:
        if s[:2] == '\r\n':
            return s, path
        if ord(s[0]) < char_map["min_val"] or ord(s[0]) > char_map["max_val"]:
            return "ERROR -- pathname", path
        path += s[0]
        s = s[1:]
    return s, path


def parse_domain(s):
    s, domain = parse_domain_part(s)
    return s, domain


def parse_domain_part(s, current=""):
    if s and s[0].isalpha():
        current += s[0]
        s, sub = parse_alnum(s[1:])
        current += sub
        if s and s[0] == '.':
            return parse_domain_part(s[1:], current + '.')
        elif s and s[0] == ' ':
            return s, current
        else:
            return "ERROR", current
    elif s.startswith(' '):
        return s, current
    return "ERROR", current


def parse_alnum(s):
    valid_chars = ""
    while s and (s[0].isalnum() or s[0] == '-'):
        valid_chars += s[0]
        s = s[1:]
    return s, valid_chars


def check_whitespace(s):
    if not s.startswith(' '):
        return "ERROR"
    return s.lstrip(' ')


def process_response(resp):
    resp, code = get_code(resp)
    if "ERROR" in resp:
        return resp, code

    resp = check_whitespace(resp)
    if "ERROR" in resp:
        return "ERROR -- reply-code", code

    resp, text = get_text(resp)
    if "ERROR" in resp:
        return resp, code

    if resp not in ['\r\n', '\n']:
        return "ERROR -- <CRLF>", code
    return f"FTP reply {code} accepted. Text is: {text}\r\n", code


def get_code(resp):
    if len(resp) < 3:
        return "ERROR", ""
    try:
        code = int(resp[:3])
    except ValueError:
        return "ERROR", ""
    if not 100 <= code <= 599:
        return "ERROR", ""
    return resp[3:], str(code)


def get_text(resp):
    text = ""
    if resp[:2] in ['\r\n', '\n']:
        return "ERROR -- reply_text", text

    while resp and resp not in ['\r\n', '\n']:
        if ord(resp[0]) < 0 or ord(resp[0]) > 127:
            return "ERROR -- reply_text", text
        text += resp[0]
        resp = resp[1:]
    return resp, text


if __name__ == "__main__":
    execute_commands()