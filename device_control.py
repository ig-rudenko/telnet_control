#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from concurrent.futures import ThreadPoolExecutor
from typing import Union
import argparse
import subprocess
import yaml
import sys
import os

from core.tc import TelnetConnect
from core.tabulate import tabulate
from core.datagather import DataGather
from core.database import DataBase

root_dir = sys.path[0]  # Полный путь к корневой папки


def show_last_saved_data(command, device_ip, device_name):
    print(f'Оборудование недоступно! ({device_ip})\n')
    if 'show-interfaces' in command and os.path.exists(f'{root_dir}/data/{device_name}/interfaces.yaml'):
        with open(f'{root_dir}/data/{device_name}/interfaces.yaml', 'r') as file:
            interfaces_last_data = yaml.safe_load(file)
            print(f'Последние сохраненные данные: ({interfaces_last_data["saved time"]})\n')
            print(tabulate(interfaces_last_data['data'], headers='keys', tablefmt="fancy_grid"))

    if 'vlan' in command and os.path.exists(f'{root_dir}/data/{device_name}/vlans.yaml') and \
            os.path.exists(f'{root_dir}/data/{device_name}/vlans_info.yaml'):
        print('Последние сохраненные данные:\n')
        with open(f'{root_dir}/data/{device_name}/vlans.yaml', 'r') as file:
            print(tabulate(yaml.safe_load(file), headers='keys', tablefmt="fancy_grid"))
        with open(f'{root_dir}/data/{device_name}/vlans_info.yaml', 'r') as file:
            print(tabulate(yaml.safe_load(file), headers=['VLAN', 'Name', 'Status']))

    if 'mac' in command and os.path.exists(f'{root_dir}/data/{device_name}/mac_result.yaml'):
        print('Последние сохраненные данные:\n')
        with open(f'{root_dir}/data/{device_name}/mac_result.yaml', 'r') as file:
            print(yaml.safe_load(file))

    if 'cable-diagnostic' in command and os.path.exists(f'{root_dir}/data/{device_name}/cable-diag.yaml'):
        print('Последние сохраненные данные:\n')
        with open(f'{root_dir}/data/{device_name}/cable-diag.yaml', 'r') as file:
            print(yaml.safe_load(file))

    if 'sys-info' in command and os.path.exists(f'{root_dir}/data/{device_name}/sys-info.yaml'):
        print('Последние сохраненные данные:\n')
        with open(f'{root_dir}/data/{device_name}/sys-info.yaml', 'r') as file:
            print(yaml.safe_load(file))


def show_info(device_name: str,
              device_ip: str,
              command: str = '',
              interface_filter: str = 'NOMON',
              authentication_file_path: str = f'{root_dir}/auth.yaml',
              authentication_mode: str = 'mixed',
              authentication_group: str = None,
              login: Union[str, list, None] = None,
              password: Union[str, list, None] = None,
              privilege_mode_password: str = None):

    ip_check = subprocess.run(['ping', '-c', '3', '-n', device_ip], stdout=subprocess.DEVNULL)
    # Проверка на доступность: 0 - доступен, 1 и 2 - недоступен
    if ip_check.returncode == 2:
        print(f'Неправильный ip адрес: {device_ip}')
        sys.exit()

    # Если оборудование недоступно
    elif ip_check.returncode == 1:
        show_last_saved_data(command, device_ip, device_name)

    # Если оборудование доступно
    elif ip_check.returncode == 0:
        session = TelnetConnect(device_ip, device_name=device_name)                       # Создаем экземпляр класса
        if login and password:
            session.set_authentication(login=login, password=password, privilege_mode_password=privilege_mode_password)
        if authentication_group:
            session.set_authentication(mode='group', auth_group=authentication_group, auth_file=authentication_file_path)
        if not authentication_mode or authentication_mode == 'auto':
            session.set_authentication(mode='auto', auth_file=authentication_file_path)
        if authentication_mode == 'mixed':
            session.set_authentication(mode='mixed', auth_file=authentication_file_path)

        if not session.connect():  # Подключаемся
            show_last_saved_data(command, device_ip, device_name)
            sys.exit()

        print(f"\n    Подключаемся к {device_name} ({device_ip})\n"
              f"\n    Тип оборудования: {session.vendor}\n")

        if 'show-interfaces' in command:
            print(tabulate(session.get_interfaces(), headers='keys', tablefmt="fancy_grid"))

        if 'vlan' in command:
            print(tabulate(session.get_vlans(), headers='keys', tablefmt="fancy_grid"))
            print(tabulate(session.vlan_info, headers=['VLAN', 'Name', 'Status']))

        if 'mac' in command:
            print(session.get_mac(description_filter=interface_filter))

        if 'cable-diagnostic' in command:
            print(session.cable_diagnostic())

        if 'sys-info' in command:
            print(session.get_device_info())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="telnet control")

    parser.add_argument("-N", dest="device_name", help="device name")
    parser.add_argument("-i", dest='ip', help="device IP")
    parser.add_argument("-m", dest="mode", help="show-interfaces, vlan, mac, sys-info, cable-diagnostic")
    parser.add_argument("--desc-filter", dest="description_filter")
    parser.add_argument("--auth-file", dest="auth_file")
    parser.add_argument("--auth-mode", dest="auth_mode", help="default, group, auto, mixed")
    parser.add_argument("--auth-group", dest="auth_group", help="groups from auth file")
    parser.add_argument("--data-gather", dest="data_gather", help="Collect data from devices in database "
                                                                  "(interfaces, sys-info)")
    parser.add_argument("--data-gather-mode", dest="auth_group", help="groups from auth file")
    parser.add_argument("-l", dest="login")
    parser.add_argument("-p", dest="password")

    args = parser.parse_args()
    dev_name = args.device_name if args.device_name else ''
    auth_file = args.auth_file if args.auth_file else f'{root_dir}/auth.yaml'
    auth_mode = args.auth_mode if args.auth_mode else 'mixed'
    auth_group = args.auth_group if args.auth_group else None
    mode = args.mode if args.mode else ''
    description_filter = args.description_filter if args.description_filter else r'\S+'

    if args.data_gather:
        db = DataBase()
        with ThreadPoolExecutor(max_workers=30) as executor:
            for line in db.get_table():
                data_gather = DataGather(ip=line[0], name=line[1])
                executor.submit(data_gather.collect, args.data_gather)
        sys.exit()

    show_info(
        device_name=dev_name,
        device_ip=args.ip,
        command=mode,
        interface_filter=description_filter,
        authentication_file_path=auth_file,
        authentication_mode=auth_mode,
        authentication_group=auth_group,
        login=args.login,
        password=args.password
    )
