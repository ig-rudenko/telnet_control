#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from typing import Union
from re import findall
from datetime import datetime
import pexpect
import sys
import os
import yaml
import ipaddress
from core.database import DataBase
from vendors import *

root_dir = sys.path[0]


def ip_range(ip_input_range_list: list):
    result = []
    for ip_input_range in ip_input_range_list:
        if '/' in ip_input_range:
            try:
                ip = ipaddress.ip_network(ip_input_range)
            except ValueError:
                ip = ipaddress.ip_interface(ip_input_range).network
            return [str(i) for i in list(ip.hosts())]
        range_ = {}
        ip = ip_input_range.split('.')
        for num, oct in enumerate(ip, start=1):
            if '-' in oct:
                ip_range = oct.split('-')
                ip_range[0] = ip_range[0] if 0 <= int(ip_range[0]) < 256 else 0
                ip_range[1] = ip_range[0] if 0 <= int(ip_range[1]) < 256 else 0
                range_[num] = oct.split('-')
            elif 0 <= int(oct) < 256:
                range_[num] = [oct, oct]
            else:
                range_[num] = [0, 0]

        for oct1 in range(int(range_[1][0]), int(range_[1][1])+1):
            for oct2 in range(int(range_[2][0]), int(range_[2][1])+1):
                for oct3 in range(int(range_[3][0]), int(range_[3][1])+1):
                    for oct4 in range(int(range_[4][0]), int(range_[4][1])+1):
                        result.append(f'{oct1}.{oct2}.{oct3}.{oct4}')
    return result


class TelnetConnect:
    def __init__(self, ip: str, device_name: str = ''):
        self.device_name = device_name
        self.ip = ip
        self.auth_mode = 'default'
        self.auth_file = f'{root_dir}/auth.yaml'
        self.auth_group = None
        self.login = ['admin']
        self.password = ['admin']
        self.privilege_mode_password = 'enable'
        self.telnet_session = None
        self.vendor = None
        self.interfaces = []
        self.raw_interfaces = []
        self.device_info = None
        self.mac_last_result = None
        self.vlans = None
        self.vlan_info = None
        self.cable_diag = None

    def set_authentication(self, mode: str = 'default', auth_file: str = f'{root_dir}/auth.yaml',
                           auth_group: str = None, login: Union[str, list, None] = None,
                           password: Union[str, list, None] = None,
                           privilege_mode_password: str = None) -> None:
        self.auth_mode = mode
        self.auth_file = auth_file
        self.auth_group = auth_group

        if self.auth_mode.lower() == 'default' or self.auth_mode.lower() == 'group':
            try:
                with open(self.auth_file, 'r') as file:
                    auth_dict = yaml.safe_load(file)
                iter_dict = auth_dict['GROUPS'][self.auth_group.upper()]
                self.login = (iter_dict['login'] if isinstance(iter_dict['login'], list)
                              else [iter_dict['login']]) if iter_dict.get('login') else ['admin']
                # Логин равен списку паролей найденных в элементе 'password' или 'admin'
                self.password = (iter_dict['password'] if isinstance(iter_dict['password'], list)
                                 else [iter_dict['password']]) if iter_dict.get('password') else ['admin']
                self.privilege_mode_password = iter_dict['privilege_mode_password'] if iter_dict.get(
                    'privilege_mode_password') else 'enable'
                print(self.login, self.password, self.privilege_mode_password)

            except Exception:
                pass

        if self.auth_mode.lower() == 'auto':
            try:
                with open(self.auth_file, 'r') as file:
                    auth_dict = yaml.safe_load(file)
                for group in auth_dict["GROUPS"]:
                    iter_dict = auth_dict["GROUPS"][group]  # Записываем группу в отдельзую переменную
                    # Если есть ключ 'devices_by_name' и в нем имеется имя устройства ИЛИ
                    # есть ключ 'devices_by_ip' и в нем имеется IP устройства
                    if (iter_dict.get('devices_by_name') and self.device_name in iter_dict.get('devices_by_name')) \
                            or (iter_dict.get('devices_by_ip') and self.ip in ip_range(iter_dict.get('devices_by_ip'))):
                        # Логин равен списку логинов найденных в элементе 'login' или 'admin'
                        self.login = (iter_dict['login'] if isinstance(iter_dict['login'], list)
                                      else [iter_dict['login']]) if iter_dict.get('login') else ['admin']
                        # Логин равен списку паролей найденных в элементе 'password' или 'admin'
                        self.password = (iter_dict['password'] if isinstance(iter_dict['password'], list)
                                         else [iter_dict['password']]) if iter_dict.get('password') else ['admin']
                        self.privilege_mode_password = iter_dict['privilege_mode_password'] if iter_dict.get(
                            'privilege_mode_password') else 'enable'

                        break

            except Exception:
                pass

        if login and password:
            self.login = login if isinstance(login, list) else [login]
            self.password = password if isinstance(password, list) else [password]
            self.privilege_mode_password = privilege_mode_password if privilege_mode_password else 'enable'

        if self.auth_mode == 'mixed':
            try:
                with open(self.auth_file, 'r') as file:
                    auth_dict = yaml.safe_load(file)
                self.login = auth_dict['MIXED']['login']
                self.password = auth_dict['MIXED']['password']
                self.privilege_mode_password = privilege_mode_password if privilege_mode_password else 'enable'

            except Exception:
                pass

    def connect(self) -> bool:
        if not self.login or not self.password:
            self.set_authentication()
        connected = False
        self.telnet_session = pexpect.spawn(f"telnet {self.ip}")
        try:
            for login, password in zip(self.login+['admin'], self.password+['admin']):
                while not connected:  # Если не авторизировались
                    login_stat = self.telnet_session.expect(
                        [
                            r"[Ll]ogin(?![-\siT]).*:\s*$",  # 0
                            r"[Uu]ser\s(?![lfp]).*:\s*$",   # 1
                            r"[Nn]ame.*:\s*$",              # 2
                            r'[Pp]ass.*:\s*$',              # 3
                            r'Connection closed',           # 4
                            r'Unable to connect',           # 5
                            r'[#>\]]\s*$'                   # 6
                        ],
                        timeout=20
                    )
                    if login_stat < 3:
                        self.telnet_session.sendline(login)  # Вводим логин
                        continue
                    if 4 <= login_stat <= 5:
                        print(f"    Telnet недоступен! {self.device_name} ({self.ip})")
                        return False
                    if login_stat == 3:
                        self.telnet_session.sendline(password)  # Вводим пароль
                    if login_stat >= 6:  # Если был поймал символ начала ввода команды
                        connected = True  # Подключились
                    break  # Выход из цикла

                if connected:
                    break

            else:  # Если не удалось зайти под логинами и паролями из списка аутентификации
                print(f'    Неверный логин или пароль! {self.device_name} ({self.ip})')
                return False

            # Подключаемся к базе данных и смотрим, есть ли запись о вендоре для текущего оборудования
            db = DataBase()
            item = db.get_item(ip=self.ip)
            if not item:  # Если в базе нет данных, то создаем их
                db.add_data(data=[(self.ip, self.device_name, self.vendor, self.auth_group)])
            else:
                self.vendor = item[0][2]

            # Если нет записи о вендоре устройства, то определим его
            if not self.vendor:
                self.telnet_session.sendline('show version')
                version = ''
                while True:
                    m = self.telnet_session.expect([r']$', '-More-', r'>\s*$', r'#\s*', pexpect.TIMEOUT])
                    version += str(self.telnet_session.before.decode('utf-8'))
                    if m == 1:
                        self.telnet_session.sendline(' ')
                    if m == 4:
                        self.telnet_session.sendcontrol('C')
                    else:
                        break
                if ' ZTE Corporation:' in version:
                    self.vendor = 'zte'
                if 'Unrecognized command' in version:
                    self.vendor = 'huawei'
                if 'cisco' in version.lower():
                    self.vendor = 'cisco'
                if 'Next possible completions:' in version:
                    self.vendor = 'd-link'
                if findall(r'SW version\s+', version):
                    self.vendor = 'alcatel_or_lynksys'
                if 'Hardware version' in version:
                    self.vendor = 'edge-core'
                if 'Active-image:' in version:
                    self.vendor = 'eltex-mes'
                if 'Boot version:' in version:
                    self.vendor = 'eltex-esr'
                if 'ExtremeXOS' in version:
                    self.vendor = 'extreme'
                if 'QTECH' in version:
                    self.vendor = 'q-tech'

                if '% Unknown command' in version:
                    self.telnet_session.sendline('display version')
                    while True:
                        m = self.telnet_session.expect([r']$', '---- More', r'>$', r'#', pexpect.TIMEOUT, '{'])
                        if m == 5:
                            self.telnet_session.expect('}:')
                            self.telnet_session.sendline('\n')
                            continue
                        version += str(self.telnet_session.before.decode('utf-8'))
                        if m == 1:
                            self.telnet_session.sendline(' ')
                        if m == 4:
                            self.telnet_session.sendcontrol('C')
                        else:
                            break
                    if findall(r'VERSION : MA\d+', version):
                        self.vendor = 'huawei-msan'

                if 'show: invalid command, valid commands are' in version:
                    self.telnet_session.sendline('sys info show')
                    while True:
                        m = self.telnet_session.expect([r']$', '---- More', r'>\s*$', r'#\s*$', pexpect.TIMEOUT])
                        version += str(self.telnet_session.before.decode('utf-8'))
                        if m == 1:
                            self.telnet_session.sendline(' ')
                        if m == 4:
                            self.telnet_session.sendcontrol('C')
                        else:
                            break
                    if 'ZyNOS version' in version:
                        self.vendor = 'zyxel'

                # После того, как определили тип устройства, обновляем таблицу базы данных
                db.update(
                    ip=self.ip,
                    update_data=[
                        (self.ip, self.device_name, self.vendor, self.auth_group)
                    ]
                )
            return True

        except pexpect.exceptions.TIMEOUT:
            print(f"    Время ожидания превышено! (timeout) {self.device_name} ({self.ip})")
            return False

    def collect_data(self, mode, data):
        if not os.path.exists(f'{sys.path[0]}/data/{self.device_name}'):
            os.makedirs(f'{sys.path[0]}/data/{self.device_name}')
        with open(f'{sys.path[0]}/data/{self.device_name}/{mode}.yaml', 'w') as file:
            yaml.dump(data, file, default_flow_style=False)

    def get_interfaces(self):
        if 'cisco' in self.vendor:
            self.raw_interfaces = cisco.show_interfaces(telnet_session=self.telnet_session)
            self.interfaces = [
                {'Interface': line[0], 'Admin Status': line[1], 'Link': line[2], 'Description': line[3]}
                for line in self.raw_interfaces
            ]
        if 'd-link' in self.vendor:
            self.raw_interfaces = d_link.show_interfaces(telnet_session=self.telnet_session)
            self.interfaces = [
                {'Interface': line[0], 'Admin Status': line[1], 'Link': line[2], 'Description': line[3]}
                for line in self.raw_interfaces
            ]
        if 'huawei' in self.vendor:
            self.raw_interfaces, self.vendor = huawei.show_interfaces(telnet_session=self.telnet_session)
            self.interfaces = [
                {'Interface': line[0], 'Port Status': line[1], 'Description': line[2]}
                for line in self.raw_interfaces
            ]
        if 'zte' in self.vendor:
            self.raw_interfaces = zte.show_interfaces(telnet_session=self.telnet_session)
            self.interfaces = [
                {'Interface': line[0], 'Admin Status': line[1], 'Link': line[2], 'Description': line[3]}
                for line in self.raw_interfaces
            ]
        if 'alcatel' in self.vendor or 'lynksys' in self.vendor:
            interfaces_list = alcatel_linksys.show_interfaces(telnet_session=self.telnet_session)
            self.interfaces = [
                {'Interface': line[0], 'Admin Status': line[1], 'Link': line[2], 'Description': line[3]}
                for line in interfaces_list
            ]
        if 'edge-core' in self.vendor:
            self.raw_interfaces = edge_core.show_interfaces(telnet_session=self.telnet_session)
            self.interfaces = [
                {'Interface': line[0], 'Admin Status': line[1], 'Link': line[2], 'Description': line[3]}
                for line in self.raw_interfaces
            ]
        if 'eltex' in self.vendor:
            self.raw_interfaces = eltex.show_interfaces(telnet_session=self.telnet_session, eltex_type=self.vendor)
            self.interfaces = [
                {'Interface': line[0], 'Admin Status': line[1], 'Link': line[2], 'Description': line[3]}
                for line in self.raw_interfaces
            ]
        if 'extreme' in self.vendor:
            self.raw_interfaces = extreme.show_interfaces(telnet_session=self.telnet_session)
            self.interfaces = [
                {'Interface': line[0], 'Admin Status': line[1], 'Link': line[2], 'Description': line[3]}
                for line in self.raw_interfaces
            ]
        if 'q-tech' in self.vendor:
            self.raw_interfaces = qtech.show_interfaces(telnet_session=self.telnet_session)
            self.interfaces = [
                {'Interface': line[0], 'Link Status': line[1], 'Description': line[2]}
                for line in self.raw_interfaces
            ]
        self.collect_data(
            mode='interfaces',
            data={
                'saved time': datetime.now().strftime("%d %b %Y, %H:%M:%S"),
                'data': self.interfaces
            }
        )
        return self.interfaces

    def get_device_info(self):
        if 'cisco' in self.vendor:
            self.device_info = cisco.show_device_info(telnet_session=self.telnet_session)
        if 'd-link' in self.vendor:
            self.device_info = d_link.show_device_info(telnet_session=self.telnet_session)
        if 'huawei' in self.vendor:
            self.device_info = huawei.show_device_info(telnet_session=self.telnet_session)
        if 'zte' in self.vendor:
            self.device_info = zte.show_device_info(telnet_session=self.telnet_session)
        if 'alcatel' in self.vendor or 'lynksys' in self.vendor:
            self.device_info = alcatel_linksys.show_device_info(telnet_session=self.telnet_session)
        if 'edge-core' in self.vendor:
            self.device_info = edge_core.show_device_info(telnet_session=self.telnet_session)
        if 'eltex' in self.vendor:
            self.device_info = eltex.show_device_info(telnet_session=self.telnet_session)
        if 'extreme' in self.vendor:
            self.device_info = extreme.show_device_info(telnet_session=self.telnet_session)
        if 'q-tech' in self.vendor:
            self.device_info = qtech.show_device_info(telnet_session=self.telnet_session)
        self.collect_data(
            mode='sys-info',
            data={
                'saved time': datetime.now().strftime("%d %b %Y, %H:%M:%S"),
                'data': self.device_info
            }
        )
        return self.device_info

    def get_mac(self, description_filter: str = r'\S+'):
        if not self.raw_interfaces:
            self.get_interfaces()
        if 'cisco' in self.vendor:
            self.mac_last_result = cisco.show_mac(self.telnet_session, self.raw_interfaces, description_filter)
        if 'd-link' in self.vendor:
            self.mac_last_result = d_link.show_mac(self.telnet_session, self.raw_interfaces, description_filter)
        if 'huawei-1' in self.vendor:
            self.mac_last_result = huawei.show_mac_huawei_1(self.telnet_session, self.raw_interfaces,
                                                            description_filter)
        if 'huawei-2' in self.vendor:
            self.mac_last_result = huawei.show_mac_huawei_2(self.telnet_session, self.raw_interfaces,
                                                            description_filter)
        if 'zte' in self.vendor:
            self.mac_last_result = zte.show_mac(self.telnet_session, self.raw_interfaces, description_filter)
        if 'alcatel' in self.vendor or 'lynksys' in self.vendor:
            self.mac_last_result = "Для данного типа оборудования просмотр MAC'ов в данный момент недоступен 🦉"
            # self.mac_last_result = alcatel_linksys.show_mac(self.telnet_session, self.raw_interfaces, description_filter)
        if 'edge-core' in self.vendor:
            self.mac_last_result = "Для данного типа оборудования просмотр MAC'ов в данный момент недоступен 🦉"
            # self.mac_last_result = edge_core.show_mac(self.telnet_session, self.raw_interfaces, description_filter)
        if 'eltex-mes' in self.vendor:
            self.mac_last_result = eltex.show_mac_mes(self.telnet_session, self.raw_interfaces, description_filter)
        if 'eltex-esr' in self.vendor:
            self.mac_last_result = eltex.show_mac_esr_12vf(self.telnet_session)
        if 'extreme' in self.vendor:
            self.mac_last_result = extreme.show_mac(self.telnet_session, self.raw_interfaces, description_filter)
        if 'q-tech' in self.vendor:
            self.mac_last_result = qtech.show_mac(self.telnet_session, self.raw_interfaces, description_filter)
        self.collect_data(
            mode='mac_result',
            data={
                'saved time': datetime.now().strftime("%d %b %Y, %H:%M:%S"),
                'data': self.mac_last_result
            }
        )
        return self.mac_last_result

    def get_vlans(self):
        if not self.raw_interfaces:
            self.get_interfaces()
        if 'cisco' in self.vendor:
            self.vlan_info, vlans_last_result = cisco.show_vlans(self.telnet_session, self.raw_interfaces)
            self.vlans = [
                {'Interface': line[0], 'Admin Status': line[1], 'Link': line[2], 'Description': line[3],
                 "VLAN's": line[4]}
                for line in vlans_last_result
            ]
        if 'd-link' in self.vendor:
            self.vlan_info, vlans_last_result = d_link.show_vlans(self.telnet_session, self.raw_interfaces)
            self.vlans = [
                {'Interface': line[0], 'Admin Status': line[1], 'Link': line[2], 'Description': line[3],
                 "VLAN's": line[4]}
                for line in vlans_last_result
            ]
        if 'huawei' in self.vendor:
            self.vlan_info, vlans_last_result = huawei.show_vlans(self.telnet_session, self.raw_interfaces)
            self.vlans = [
                {'Interface': line[0], 'Port Link': line[1], 'Description': line[2], "VLAN's": line[3]}
                for line in vlans_last_result
            ]
        if 'zte' in self.vendor:
            self.vlans_last_result = "Для данного типа оборудования просмотр VLAN'ов в данный момент недоступен 🦉"
            # self.vlans_last_result = zte.show_vlans(self.telnet_session, self.raw_interfaces)
        if 'alcatel' in self.vendor or 'lynksys' in self.vendor:
            self.vlans_last_result = "Для данного типа оборудования просмотр VLAN'ов в данный момент недоступен 🦉"
            # self.vlans_last_result = alcatel_linksys.show_vlans(self.telnet_session, self.raw_interfaces)
        if 'edge-core' in self.vendor:
            self.vlans_last_result = "Для данного типа оборудования просмотр VLAN'ов в данный момент недоступен 🦉"
            # self.vlans_last_result = edge_core.show_vlans(self.telnet_session, self.raw_interfaces)
        if 'eltex' in self.vendor:
            self.vlan_info, vlans_last_result = eltex.show_vlans(self.telnet_session, self.raw_interfaces)
            self.vlans = [
                {'Interface': line[0], 'Admin Status': line[1], 'Link': line[2], 'Description': line[3],
                 "VLAN's": line[4]}
                for line in vlans_last_result
            ]
        if 'extreme' in self.vendor:
            self.vlan_info, vlans_last_result = extreme.show_vlans(self.telnet_session, self.raw_interfaces)
            self.vlans = [
                {'Interface': line[0], 'Admin Status': line[1], 'Link': line[2], 'Description': line[3],
                 "VLAN's": line[4]}
                for line in vlans_last_result
            ]
        if 'q-tech' in self.vendor:
            self.vlans_last_result = "Для данного типа оборудования просмотр VLAN'ов в данный момент недоступен 🦉"
            # self.vlans_last_result = qtech.show_vlans(self.telnet_session, self.raw_interfaces)
        self.collect_data(
            mode='vlans',
            data={
                'saved time': datetime.now().strftime("%d %b %Y, %H:%M:%S"),
                'data': self.vlans
            }
        )
        self.collect_data(
            mode='vlans_info',
            data={
                'saved time': datetime.now().strftime("%d %b %Y, %H:%M:%S"),
                'data': self.vlan_info
            }
        )
        return self.vlans

    def cable_diagnostic(self):
        if 'd-link' in self.vendor:
            self.cable_diag = d_link.show_cable_diagnostic(telnet_session=self.telnet_session)
        if 'huawei' in self.vendor:
            self.cable_diag = huawei.show_cable_diagnostic(telnet_session=self.telnet_session)
        self.collect_data(
            mode='cable-diag',
            data={
                'saved time': datetime.now().strftime("%d %b %Y, %H:%M:%S"),
                'data': self.cable_diag
            }
        )
        return self.cable_diag
