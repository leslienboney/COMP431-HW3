import sys
import os
import socket

ASCII = {
    "A": ord("A"), "Z": ord("Z"),
    "a": ord("a"), "z": ord("z"),
    "0": ord("0"), "9": ord("9"),
    "min_ascii_val": 0, "max_ascii_val": 127}


def read_commands():
    expected_commands = ["CONNECT"]

    welcoming_port = int(sys.argv[1])
    ftp_control_connection = None
    num_copied_files = 0




    for command in sys.stdin:
        sys.stdout.write(command)
        tokens = command.split()
        if len(tokens) == 0:
            continue

        cmd_type = tokens[0].upper()
        if cmd_type in expected_commands:
            if cmd_type == "CONNECT":

                output_msg, server_port, server_host = parse_connect(command)

                if "ERROR" in output_msg:
                    print(output_msg)
                    continue

                print(output_msg, end='')

                if ftp_control_connection is not None:
                    process_quit(ftp_control_connection)
                    ftp_control_connection.close()
                    ftp_control_connection = None

                try:
                    ftp_control_connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    ftp_control_connection.connect((server_host, server_port))
                except Exception as e:
                    print("CONNECT failed")
                    ftp_control_connection = None
                    continue

                welcoming_port = int(sys.argv[1])

                reply = ftp_control_connection.recv(1024).decode()
                parsed_reply, _ = parse_reply(reply)
                print(parsed_reply, end='')

                for cmd in generate_connect_output():
                    sys.stdout.write(cmd)
                    ftp_control_connection.sendall(cmd.encode())
                    reply = ftp_control_connection.recv(1024).decode()
                    parsed_reply, _ = parse_reply(reply)
                    print(parsed_reply, end='')

                expected_commands = ["CONNECT", "GET", "QUIT"]





            elif cmd_type == "GET":
                if ftp_control_connection is None:
                    print("ERROR -- No FTP control connection established")
                    continue
                result = parse_get(command)
                if isinstance(result, tuple):
                    response, pathname = result
                    print(response, end='')
                else:
                    print(result)
                    continue
                ftp_control_connection, welcoming_port, num_copied_files = process_get(
                    ftp_control_connection, welcoming_port, tokens[1], num_copied_files)



            elif cmd_type == "QUIT":
                result = parse_quit(command)
                print(result, end='')
                process_quit(ftp_control_connection)
                ftp_control_connection.close()
                ftp_control_connection = None
                sys.exit(0)
        else:
            print("ERROR -- Command Unexpected/Unknown")

def process_connect(ftp_control_connection):
    pass


def process_get(ftp_control_connection, welcoming_port, file_path, num_copied_files):
    try:
        data_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        data_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        data_socket.bind(('', welcoming_port))
        data_socket.listen(1)
    except Exception as e:
        print("GET failed, FTP-data port not allocated.")
        return ftp_control_connection, welcoming_port, num_copied_files


    get_commands = generate_get_output(welcoming_port, file_path)
    retr_reply = ""
    retr_reply = ""
    for cmd in get_commands:
        sys.stdout.write(cmd)
        ftp_control_connection.sendall(cmd.encode())
        reply = ftp_control_connection.recv(1024).decode()
        parsed_reply, _ = parse_reply(reply)
        print(parsed_reply, end='')
        if cmd.startswith("RETR"):
            retr_reply = reply
            if retr_reply.startswith("150"):
                final_reply = ftp_control_connection.recv(1024).decode()
                parsed_final, _ = parse_reply(final_reply)
                print(parsed_final, end='')



    if retr_reply.startswith("550"):
        data_socket.close()
        welcoming_port += 1
        return ftp_control_connection, welcoming_port, num_copied_files


    try:
        conn, addr = data_socket.accept()
    except Exception as e:
        print("ERROR -- Unable to accept FTP-data connection:", e)
        data_socket.close()
        welcoming_port += 1
        return ftp_control_connection, welcoming_port, num_copied_files


    if not os.path.exists("retr_files"):
        os.mkdir("retr_files")
    num_copied_files += 1
    filename = os.path.join("retr_files", f"file{num_copied_files}")

    with open(filename, "wb") as f:
        while True:
            data = conn.recv(1024)
            if not data:
                break
            f.write(data)
    conn.close()
    data_socket.close()
    welcoming_port += 1
    return ftp_control_connection, welcoming_port, num_copied_files


def process_quit(ftp_control_connection):
    quit_cmd = "QUIT\r\n"
    sys.stdout.write(quit_cmd)
    ftp_control_connection.sendall(quit_cmd.encode())
    reply = ftp_control_connection.recv(1024).decode()
    parsed_reply, _ = parse_reply(reply)
    print(parsed_reply, end='')


def generate_connect_output():
    connect_commands = ["USER anonymous\r\n",
                        "PASS guest@\r\n",
                        "SYST\r\n",
                        "TYPE I\r\n"]
    return connect_commands


def generate_get_output(port_num, file_path):
    client_ip = socket.gethostbyname(socket.gethostname())
    ip_parts = client_ip.split('.')
    high = port_num // 256
    low = port_num % 256
    host_port = ",".join(ip_parts + [str(high), str(low)])
    port_cmd = f"PORT {host_port}\r\n"
    retr_cmd = f"RETR {file_path}\r\n"
    return [port_cmd, retr_cmd]

def parse_connect(command):
    server_host = ""
    server_port = -1


    if command[0:7].upper() != "CONNECT" or len(command) == 7:
        return "ERROR -- request", server_port, server_host
    command = command[7:]

    command = parse_space(command)
    if len(command) > 1:
        command, server_host = parse_server_host(command)
    else:
        command = "ERROR -- server-host"


    if "ERROR" in command:
        return command, server_port, server_host


    command = parse_space(command)
    if len(command) > 1:
        command, server_port = parse_server_port(command)
    else:
        command = "ERROR -- server-port"


    server_port = int(server_port)

    if "ERROR" in command:
        return command, server_port, server_host
    elif command != '\r\n' and command != '\n':
        return "ERROR -- <CRLF>", server_port, server_host
    return f"CONNECT accepted for FTP server at host {server_host} and port {server_port}\r\n", server_port, server_host


def parse_get(command):
    if command[0:3].upper() != "GET":
        return "ERROR -- request"
    command = command[3:]

    command = parse_space(command)
    command, pathname = parse_pathname(command)


    if "ERROR" in command:
        return command
    elif command != '\r\n' and command != '\n':
        return "ERROR -- <CRLF>"
    return f"GET accepted for {pathname}\r\n", pathname


def parse_quit(command):
    if command.upper() != "QUIT\r\n" and command.upper() != "QUIT\n":
        return "ERROR -- <CRLF>"
    else:
        return "QUIT accepted, terminating FTP client\r\n"


def parse_server_host(command):
    command, server_host = parse_domain(command)
    if command == "ERROR":
        return "ERROR -- server-host", server_host
    else:
        return command, server_host


def parse_server_port(command):
    port_nums = []
    port_string = ""
    for char in command:
        if ord(char) >= ASCII["0"] and ord(char) <= ASCII["9"]:
            port_nums.append(char)
            port_string += char
        else:
            break
    if len(port_nums) < 5:
        if ord(port_nums[0]) == ASCII["0"] and len(port_nums) > 1:
            return "ERROR -- server-port"
        return command[len(port_nums):], port_string
    elif len(port_nums) == 5:
        if ord(port_nums[0]) == ASCII["0"] or  int(command[0:5]) > 65535:
            return "ERROR -- server-port"
    return command[len(port_nums):], port_string


def parse_pathname(command):
    pathname = ""
    if command[0] == '\n' or command[0:2] == '\r\n':
        return "ERROR -- pathname", pathname
    else:
        while len(command) > 1:
            if len(command) == 2 and command[0:2] == '\r\n':
                return command, pathname
            elif ord(command[0]) >= ASCII["min_ascii_val"] and ord(command[0]) <= ASCII["max_ascii_val"]:
                pathname += command[0]
                command = command[1:]
            else:
                return "ERROR -- pathname", pathname
        return command, pathname


# <domain> ::= <element> | <element>"."<domain>
def parse_domain(command):
    command, server_host = parse_element(command)
    return command, server_host


# <element> ::= <a><let-dig-hyp-str>
def parse_element(command, element_string=""):

    if (ord(command[0]) >= ASCII["A"] and ord(command[0]) <= ASCII["Z"]) \
            or (ord(command[0]) >= ASCII["a"] and ord(command[0]) <= ASCII["z"]):
        element_string += command[0]
        command, let_dig_string = parse_let_dig_str(command[1:])
        element_string += let_dig_string
        if command[0] == ".":
            element_string += "."
            return parse_element(command[1:], element_string)
        elif command[0] == ' ':
            return command, element_string
        else:
            return "ERROR", element_string
    elif command[0] == ' ':
        return command, element_string
    return "ERROR", element_string

def parse_let_dig_str(command):
    let_dig_string = ""
    while (ord(command[0]) >= ASCII["A"] and ord(command[0]) <= ASCII["Z"]) \
            or (ord(command[0]) >= ASCII["a"] and ord(command[0]) <= ASCII["z"]) \
            or (ord(command[0]) >= ASCII["0"] and ord(command[0]) <= ASCII["9"]) \
            or (ord(command[0]) == ord('-')):
        let_dig_string += command[0]
        if len(command) > 1:
            command = command[1:]
        else:
            return command, let_dig_string
    return command, let_dig_string

def parse_space(line):
    if line[0] != ' ':
        return "ERROR"
    while line[0] == ' ':
        line = line[1:]
    return line

def parse_reply(reply):
    reply, reply_code = parse_reply_code(reply)
    if "ERROR" in reply:
        return reply, reply_code

    reply = parse_space(reply)
    if "ERROR" in reply:
        return "ERROR -- reply-code", reply_code

    reply, reply_text = parse_reply_text(reply)
    if "ERROR" in reply:
        return reply, reply_code

    if reply != '\r\n' and reply != '\n':
        return "ERROR -- <CRLF>", reply_code
    return f"FTP reply {reply_code} accepted. Text is: {reply_text}\r\n", reply_code


def parse_reply_code(reply):
    reply, reply_code = parse_reply_number(reply)
    if "ERROR" in reply:
        return "ERROR -- reply-code", reply_code
    return reply, reply_code


def parse_reply_number(reply):
    reply_number = 0
    if len(reply) < 3:
        return "ERROR", reply_number
    try:
        reply_number = int(reply[0:3])
    except ValueError:
        return "ERROR", reply_number
    reply_number = reply[0:3]
    if int(reply_number) < 100 or int(reply_number) > 599:
        return "ERROR", reply_number
    return reply[3:], reply_number


def parse_reply_text(reply):
    reply_text = ""
    if reply[0] == '\n' or reply[0:2] == '\r\n':
        return "ERROR -- reply_text", reply_text
    else:
        while len(reply) > 1:
            if len(reply) == 2 and reply[0:2] == '\r\n':
                return reply, reply_text
            elif ord(reply[0]) >= ASCII["min_ascii_val"] and ord(reply[0]) <= ASCII["max_ascii_val"]:
                reply_text += reply[0]
                reply = reply[1:]
            else:
                return "ERROR -- reply_text", reply_text
        return reply, reply_text


if __name__ == "__main__":
    read_commands()



