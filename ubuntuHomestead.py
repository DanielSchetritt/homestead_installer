#!/usr/bin/python3
#
# homestead_installer
# Copyright (C) 2017, Gabriel Sturtevant <gabriel@gabrielsturtevant.com>
#
# This file is part of homestead_installer.
#
# homestead_installer is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# homestead_installer is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with homestead_installer.  If not, see <http://www.gnu.org/licenses/>.
#
# Contributor(s):
# Gabriel Sturtevant <gabriel@gabrielsturtevant.com>
# Daniel Schetritt <daniel.schetritt@gmail.com>

import argparse
import getpass
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

import requests
from requests.auth import HTTPBasicAuth

# Environment Variables
ENV_VARS = [
    'SCRIPTS_URL',
    'SCRIPTS_URL_NAME',
    'SCRIPTS_DIR_NAME',
    'SCRIPTS_DIR_PATH',
    'SCRIPTS_CORES'
]

# Program constants
FILE_HASH = "30394f4b4e96e5b9c333ce458387f291"
STATIC_IP = "192.168.10.10"
INITIAL_PATH = os.getcwd()
HOST_PERMISSIONS = "644"
HOMESTEAD_URL = 'https://github.com/laravel/homestead.git'
VAGRANT_URL = 'https://raw.githubusercontent.com/GabrielSturtevant/homestead_installer/master/GetVagrantLink.py'
SSH_SUCCESS_CODE = 256
# Gets the number of CPUS on the system, but if for some reason it doesn't work, default to 32.
MAX_NUMEBR_OF_CPUS = int(subprocess.check_output('nproc --all', shell=True)) or 32

# Mapping of supported package managers, to their sub commands, and whether or not they use sudo.
SUPPORTED_PACKAGE_MANAGERS = {
    'brew': {'name':'brew', 'install': 'install','update': 'update', 'sudo': False},
    'apt':  {'name':'brew', 'install': 'install -y', 'update': 'update', 'sudo': True}
}
# User defined variables. Will be set by the argument parser.
USER_VARS = {}

# System modifications
sys.stdin = open('/dev/tty')


def md5(fname):
    hash_md5 = hashlib.md5()
    with open(fname, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def ask_for_package_manager() -> dict:
    """ Lets the user interactively specify a package manager for this script to use.

    :return: a dictionary containing the name, install sub-command, update-subcommand, and privelege of the newly
             specified package manager.
    """
    package_manager_name = input("Please enter the command for your package manager," +
                                 "(or leave this blank and press the return key to quit):")
    if package_manager_name is '':
        print("Exiting now.")
        exit(1)

    package_install_command = input("Please enter the sub-command for installing packages with" +
                                    "your package manager:")
    package_update_command = input("Please enter the sub-command for updating the list of packages with" +
                                   "your package manager:")
    choice = None
    print('Does your package manager require sudo?')
    while choice is not 'yes' and choice is not 'no':
        choice = input("Please choose `yes' or `no':")
    use_sudo = bool(choice is 'yes')

    return {'name': package_manager_name,
            'install': package_install_command,
            'update': package_update_command,
            'sudo': use_sudo}


def choose_package_manager() -> dict:
    """
    Ensures that a valid package manager is installed, and sets this script to use it.
    The default package manager is set in the argparser.
    :return: The chosen package manager in the same format as a value in SUPPORTED_PACKAGE_MANAGERS
    """
    known_managers = SUPPORTED_PACKAGE_MANAGERS
    package_manager_name = USER_VARS['package_manager_name']
    chosen_package_manager = dict
    use_sudo = False
    is_set_up = False

    while not is_set_up:
        if package_manager_name in list(known_managers):
            # Try the currently set Package Manager
            if shutil.which(package_manager_name) is not None:
                print("Using package manager: {0}.".format(package_manager_name))
                # set our environment variable to the known package manager.
                chosen_package_manager = known_managers[package_manager_name]
                is_set_up = True
            else:
                print("`Warning: {0}' is not installed.".format(package_manager_name))
        if len(list(known_managers)) > 0:
            # Try another known package manager.
            next_known_package_manager = known_managers.pop()
            package_manager_name = next_known_package_manager['name']
            print('Trying another package manager: {0}.', package_manager_name)
        else:
            # Try asking them for one
            print('Warning: Your system does not have a supported package manager installed.')
            specified_package_manager = ask_for_package_manager()
            package_manager_name = specified_package_manager['name']
            # Now we know about it. Let's repeat the loop and try again.
            known_managers[package_manager_name] = specified_package_manager

    return chosen_package_manager


def set_up_package_manager():
    """ The result of this function is the addition of a value for USER_VARS['package_manager'] such that:
    1. Passing "USER_VARS['package_manager']['update']" into os.system would update the selected package manager.
    2. Passing "USER_VARS['package_manager']['install'] + program_name" into os.system would install program_name.

    :return: None
    """

    package_manager = choose_package_manager()
    install_command = package_manager['install']
    update_command = package_manager['update']

    if package_manager['sudo']:
        install_command = 'sudo ' + install_command
        update_command = 'sudo ' + update_command

    USER_VARS['package_manager'] = dict
    USER_VARS['package_manager']['install'] = install_command
    USER_VARS['package_manager']['update'] = update_command


def install(program_name, common_name, optional=False):
    install_command = USER_VARS['package_manager']['install']
    success_code = 0
    print('Checking whether {} is installed'.format(common_name))
    if shutil.which(program_name) is None:
        print('{} is not installed, installing now'.format(common_name))
        cmd_code = os.system('{0} {1}'.format(install_command, program_name))
        if cmd_code is not success_code:
            if optional:
                print('Warning: Optional dependency not installed: {}'.format(common_name))
            else:
                print("ERROR: Failed to install dependency: {}.".format(common_name))
                print("Exiting now.")
                exit(1)
    else:
        print('{} is already installed'.format(common_name))

    time.sleep(1)
    os.system('clear')


def add_ssh_key_to_github(ssh_key):
    # Check if your key already works.
    ssh_accepted = os.system('ssh -Ta git@github.com')
    computer_name = ""
    while ssh_accepted is not SSH_SUCCESS_CODE and computer_name is "":
        computer_name = input("What would you like to call your computer on GitHub?\nComputer Name: ")

    while ssh_accepted is not SSH_SUCCESS_CODE:
        user_name = input('What\'s your github username? ')
        password = getpass.getpass('What\'s your github password? ')
        auth = HTTPBasicAuth(user_name, password)

        key = ssh_key
        url = 'https://api.github.com/user/keys'

        data = {
            'title': computer_name,
            'key': key,
        }

        github_response = requests.post(url, data=json.dumps(data), auth=auth)
        print("Status code:")

        github_response_data = json.loads(github_response.text)
        os.system('clear')
        if github_response.status_code == 201:
            print('Congratulations! Your ssh key has been successfully added to GitHub.')
        else:
            os.system('clear')
            try:
                print('GitHub returned an error: ' + github_response_data['errors'][0]['message'])
            except Exception:
                print('An unknown error occurred')
                print('Your username and/or password were probably incorrect\n')

        print("Verifying SSH connection...")
        ssh_accepted = os.system('ssh -Ta git@github.com')


# Parse command-line arguments and create the help text.
parser = argparse.ArgumentParser(description='Laravel/Homestead+Ubuntu installation script')

parser.add_argument('-u', '--framework-url',
                    metavar='FRAMEWORK_URL',
                    type=str,
                    nargs=1,
                    default="https://github.com/laravel/laravel.git",
                    help='a custom url telling this script where to find the Laravel git repository')

parser.add_argument('-n', '--app-name',
                    metavar='APP_NAME',
                    type=str,
                    nargs=1,
                    default="homestead",
                    help='the name of the default application to be created within Homestead')

parser.add_argument('-d', '--framework-dir-path',
                    metavar='FRAMEWORK_DIR_PATH',
                    type=str,
                    nargs=1,
                    default='Code',
                    help='a directory path in which to install Laravel')

parser.add_argument('-D', '--framework-dir-name',
                    metavar='FRAMEWORK_DIR_NAME',
                    type=str,
                    nargs=1,
                    default='Laravel',
                    help='a custom name for your Laravel directory')

parser.add_argument('-c', '--number-of-cpus',
                    metavar='NUMBER_OF_CPUS',
                    type=int,
                    nargs=1,
                    choices=range(1, MAX_NUMEBR_OF_CPUS + 1),
                    default=1,
                    help='the number of cpu cores to give the VM')
parser.add_argument('-p', '--package-manager-name',
                    metavar='PACKAGE_MANAGER_NAME',
                    type=str,
                    nargs=1,
                    default='brew',
                    help='the package manager you use for installing programs.')

# Parse the arguments into an object with attribute variables named the
# same as the --long-option for the parameters, but in snake_case.
args = parser.parse_args()

# Handle any special cases in the arguments
USER_VARS.update(args.__dict__)

if 'git@github.com' in USER_VARS['framework_url']:
    USER_VARS['ssh_link'] = True
if '.app' not in USER_VARS['app_name']:
    USER_VARS['app_name'] += '.app'

set_up_package_manager()

os.system('clear')

print('Running Homestead installation script')

# Update system
print('Updating system')
os.system(USER_VARS['package_manager']['update'])

time.sleep(1)
os.system('clear')

# Ensures dependencies are met
install('wget', 'Wget')
install('curl', 'Curl')
install('git', 'Git')
install('virtualbox', 'VirtualBox')
install('vim', 'Vim')
install('python-pip', 'Pip')
install('vagrant', 'Vagrant', optional=True)

# Install python dependencies
os.system('sudo -H pip install beautifulsoup4')
os.system('sudo -H pip install requests')
os.system('sudo -H pip install lxml')

# Checks whether the user has configured an ssh key
if not os.path.isfile(os.environ['HOME'] + '/.ssh/id_rsa.pub'):
    os.system('clear')
    print('ssh key has not been configured.')
    email = input('Please enter your email address (aids in generating ssh key):\n')
    os.system('ssh-keygen -f ~/.ssh/id_rsa -t rsa -b 4096 -C "{}" -N ""'.format(email))
    print("You will need to add this ssh key to github")

ssh_key = open(os.environ['HOME'] + '/.ssh/id_rsa.pub', 'r').read()

add_ssh_key_to_github(ssh_key)

# TODO: Add prompt to exchange ssh key with github

time.sleep(1)
os.system('clear')

os.system('rm -rf vagrant*.deb')

time.sleep(1)

# If vagrant could not be installed, get it manually.
if shutil.which('vagrant') is None:
    if USER_VARS['package_manager_name'] not in list(SUPPORTED_PACKAGE_MANAGERS):
        # This is a known bug, only for systems which don't have a supported package manager.
        exit(1)

    # We are probably using apt.
    file_name = 'temp.py'
    python_program = open(file_name, 'w+')
    r = requests.get(VAGRANT_URL)
    python_program.write(r.content.decode('utf-8'))
    python_program.close()

    if md5(file_name) == FILE_HASH:
        os.system('wget $(python {})'.format(file_name))
    else:
        print('Python script integrity compromised. Exiting now')
        exit(1)

    os.system('rm -f {}'.format(file_name))

    os.system('sudo dpkg -i vagrant*.deb')

    os.system('rm -rf vagrant*.deb')

print('Attempting to edit /etc/hosts, a backup will be created at /etc/hosts.BAK')
new_hosts = open('hosts', 'w+')
old_hosts = open('/etc/hosts', 'r')
new_hosts.write(old_hosts.read())

old_hosts.close()
os.system('sudo cp /etc/hosts /etc/hosts.BAK')

to_write = "\n# Homestead ip address and url\n"
to_write += "{}\t{}".format(STATIC_IP, USER_VARS['app_name'])
new_hosts.write(to_write)
new_hosts.close()

os.system('sudo mv hosts /etc/hosts')
os.system('sudo chmod {} /etc/hosts'.format(HOST_PERMISSIONS))
print('Finished editing hosts file')

# Go to home directory
os.chdir(os.environ['HOME'])

os.system('git clone ' + HOMESTEAD_URL + ' Homestead')

path = USER_VARS['framework_dir_path']

while True:
    path = path.split('/')
    if path[0] == '':
        path.pop()

    try:
        os.makedirs(os.path.join(os.environ['HOME'], *path))
        USER_VARS['framework_dir_path'] = '/'.join(path)
        break
    except FileExistsError:
        print('Oops, looks like that directory already exists\n')
        path = input('Please enter a new path to place the framework'
                     ' in \n(type N to place it in existing directory):\n')
        if path.lower() == 'n':
            break

os.chdir('{}/{}'.format(os.environ['HOME'], USER_VARS['framework_dir_path']))
os.system('git clone {} {}'.format(USER_VARS['framework_url'], USER_VARS['framework_dir_name']))

os.chdir(os.environ['HOME'] + '/Homestead')
os.system('chmod +x init.sh; ./init.sh')

homestead_yaml = open('Homestead.yaml', 'r+')
new_yaml = open('Homestead.yaml.new', 'w+')
info = homestead_yaml.readlines()

for line in info:
    if 'Code' in line:
        line = line.replace('Code', '{}'.format(USER_VARS['framework_dir_path']))

    if 'Laravel' in line:
        line = line.replace('Laravel', '{}'.format(USER_VARS['framework_dir_name']))

    if 'cpus: 1' in line:
        line = line.replace('1', str(USER_VARS['number_of_cpus']))

    if 'homestead.app' in line:
        line = line.replace('homestead.app', USER_VARS['app_name'])
    new_yaml.write(line)
os.system('rm Homestead.yaml; mv Homestead.yaml.new Homestead.yaml')

os.chdir(INITIAL_PATH)
