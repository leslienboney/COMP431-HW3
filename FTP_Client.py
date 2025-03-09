import sys
import os
import socket
import re

CHARACTER_CODES = {
    "A": ord("A"), "Z": ord("Z"),
    "a": ord("a"), "z": ord("z"),
    "0": ord("0"), "9": ord("9"),
    "min_value": 0, "max_value": 127}


def execute_commands():
    allowed_actions, data_port, command_channel, file_counter = _initialize_client()

    for user_input in sys.stdin:
        _process_user_input(
            user_input,
            allowed_actions,
            data_port,
            command_channel,
            file_counter
        )


def _initialize_client():
    return ["CONNECT"], int(sys.argv[1]), None, 0


def _process_user_input(input_line, allowed_actions, data_port, command_channel, file_counter):
    sys.stdout.write(input_line)
    components = input_line.strip().split()

    if not components:
        return allowed_actions, data_port, command_channel, file_counter

    action = components[0].upper()

    if action not in allowed_actions:
        print("ERROR -- Command Unexpected/Unknown")
        return allowed_actions, data_port, command_channel, file_counter

    if action == "CONNECT":
        return _handle_connect(
            input_line,
            allowed_actions,
            data_port,
            command_channel,
            file_counter
        )

    if action == "GET":
        return _handle_get(
            input_line,
            components,
            allowed_actions,
            data_port,
            command_channel,
            file_counter
        )

    if action == "QUIT":
        _handle_quit(input_line, command_channel)

    return allowed_actions, data_port, command_channel, file_counter


def _handle_connect(input_line, allowed_actions, data_port, command_channel, file_counter):
    result_msg, server_port, hostname = validate_connection(input_line)

    if "ERROR" in result_msg:
        print(result_msg)
        return allowed_actions, data_port, command_channel, file_counter

    print(result_msg, end='')

    command_channel = _manage_existing_connection(command_channel)
    command_channel = _establish_new_connection(hostname, server_port)

    if command_channel:
        data_port = int(sys.argv[1])
        _perform_authentication_sequence(command_channel)
        allowed_actions = ["CONNECT", "GET", "QUIT"]

    return allowed_actions, data_port, command_channel, file_counter


def _manage_existing_connection(connection):
    if connection:
        terminate_session(connection)
        connection.close()
    return None


def _establish_new_connection(host, port):
    try:
        new_conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        new_conn.connect((host, port))
        return new_conn
    except Exception:
        print("CONNECT failed")
        return None


def _perform_authentication_sequence(connection):
    server_response = connection.recv(1024).decode()
    formatted_response, _ = process_server_reply(server_response)
    print(formatted_response, end='')

    for auth_cmd in authentication_sequence():
        sys.stdout.write(auth_cmd)
        connection.sendall(auth_cmd.encode())
        response = connection.recv(1024).decode()
        formatted_response, _ = process_server_reply(response)
        print(formatted_response, end='')


def _handle_get(input_line, components, allowed_actions, data_port, command_channel, file_counter):
    if not command_channel:
        print("ERROR -- No FTP control connection established")
        return allowed_actions, data_port, command_channel, file_counter

    validation_result = check_get_command(input_line)

    if isinstance(validation_result, tuple):
        response_msg, path = validation_result
        print(response_msg, end='')
    else:
        print(validation_result)
        return allowed_actions, data_port, command_channel, file_counter

    return _process_file_transfer(
        command_channel,
        data_port,
        components[1],
        file_counter,
        allowed_actions
    )


def _process_file_transfer(conn, port, path, count, actions):
    new_conn, new_port, new_count = handle_file_transfer(conn, port, path, count)
    return actions, new_port, new_conn, new_count


def _handle_quit(input_line, connection):
    quit_result = validate_quit_command(input_line)
    print(quit_result, end='')
    terminate_session(connection)
    if connection:
        connection.close()
    sys.exit(0)


def handle_file_transfer(connection, port_number, file_path, transfer_count):
    data_channel = _create_data_channel(port_number)
    if not data_channel:
        return connection, port_number, transfer_count

    final_response = _send_transfer_commands(connection, port_number, file_path)

    if _should_abort_transfer(final_response):
        data_channel.close()
        return connection, port_number + 1, transfer_count

    transfer_conn = _accept_data_connection(data_channel, port_number)
    if not transfer_conn:
        return connection, port_number + 1, transfer_count

    transfer_count = _save_transferred_data(transfer_conn, transfer_count)

    data_channel.close()
    return connection, port_number + 1, transfer_count


def _create_data_channel(port):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('', port))
        sock.listen(1)
        return sock
    except Exception:
        print("GET failed, FTP-data port not al