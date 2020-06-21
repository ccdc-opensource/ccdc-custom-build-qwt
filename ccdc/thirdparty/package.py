#!/usr/bin/env python3

import sys
import subprocess
import os
import stat
import shutil
import tempfile
import multiprocessing
import getpass
from pathlib import Path
from distutils.version import StrictVersion


class Package(object):
    '''Base for anything installable'''
    name = None
    version = None
    _cached_sdkroot = None

    def __init__(self):
        self.use_vs_version_in_base_name = True
        self.use_distribution_in_base_name = False

    @property
    def macos(self):
        return sys.platform == 'darwin'

    @property
    def windows(self):
        return sys.platform == 'win32'

    @property
    def linux(self):
        return sys.platform.startswith('linux')

    @property
    def centos(self):
        return self.linux and Path('/etc/centos-release').exists()

    @property
    def centos_major_version(self):
        return subprocess.check_output('rpm -E %{rhel}', shell=True).decode('utf-8').strip()

    @property
    def debian(self):
        return self.linux and Path('/etc/debian_version').exists()

    @property
    def ubuntu(self):
        return self.debian and subprocess.check_output('lsb_release -i -s', shell=True).decode('utf-8').strip() == 'Ubuntu'

    @property
    def ubuntu_version(self):
        return subprocess.check_output('lsb_release -r -s', shell=True).decode('utf-8').strip()

    @property
    def platform(self):
        if not self.use_distribution_in_base_name:
            return sys.platform
        if not self.linux:
            return sys.platform
        if self.centos:
            return f'centos{self.centos_major_version}'
        if self.ubuntu:
            return f'ubuntu{self.ubuntu_version}'

    @property
    def macos_sdkroot(self):
        if not self.macos:
            return None
        if not self._cached_sdkroot:
            self._cached_sdkroot = subprocess.check_output(
                ['xcrun', '--show-sdk-path'])[:-1].decode('utf8')
        return self._cached_sdkroot

    @property
    def macos_deployment_target(self):
        '''The minimum macos version the pagkage will work on'''
        return '10.12'

    def prepare_directories(self):
        if not self.toolbase.exists() and not self.windows:
            subprocess.check_output(['sudo', 'mkdir', '-p', '/opt/ccdc'])
            subprocess.check_output(
                ['sudo', 'chown', f'{getpass.getuser()}', '/opt/ccdc'])
        self.toolbase.mkdir(parents=True, exist_ok=True)
        self.source_downloads_base.mkdir(parents=True, exist_ok=True)
        self.source_extracted_base.mkdir(parents=True, exist_ok=True)
        self.source_builds_base.mkdir(parents=True, exist_ok=True)
        self.build_logs.mkdir(parents=True, exist_ok=True)

    @property
    def toolbase(self):
        '''Return the base directory where tools are installed'''
        if self.windows:
            return Path('D:\\x_mirror\\buildman\\tools')
        else:
            return Path('/opt/ccdc/third-party')

    @property
    def source_downloads_base(self):
        '''Return the directory where sources are downloaded'''
        if self.windows:
            if 'SYSTEM_ARTIFACTSDIRECTORY' in os.environ:
                return Path(os.environ['SYSTEM_ARTIFACTSDIRECTORY'])
            return Path('D:\\tp\\downloads')
        else:
            return Path('/opt/ccdc/third-party-sources/downloads')

    @property
    def source_extracted_base(self):
        '''Return the base directory where sources are extracted'''
        if self.windows:
            return Path('D:\\tp\\extracted')
        else:
            return Path('/opt/ccdc/third-party-sources/extracted')

    @property
    def source_builds_base(self):
        '''Return the base directory where sources are built'''
        if self.windows:
            return Path('D:\\tp\\builds')
        else:
            return Path('/opt/ccdc/third-party-sources/builds')

    @property
    def build_logs(self):
        '''Return the directory where build logs are stored'''
        if self.windows:
            return Path('D:\\tp\\logs')
        else:
            return Path('/opt/ccdc/third-party-sources/logs')

    @property
    def output_base_name(self):
        components = [
            self.name,
            self.version,
        ]
        if 'BUILD_BUILDNUMBER' in os.environ:
            components.append(os.environ['BUILD_BUILDNUMBER'])
        else:
            components.append('do-not-use-me-developer-version')
        components.append(self.platform)
        if self.use_vs_version_in_base_name and 'BUILD_VS_VERSION' in os.environ:
            components.append(f'vs{os.environ["BUILD_VS_VERSION"]}')
        return '-'.join(components)
        
    @property
    def install_directory(self):
        '''Return the canonical installation directory'''
        return self.toolbase / self.name / self.output_base_name

    @property
    def output_archive_filename(self):
        return f'{self.output_base_name}.tar.gz'

    def create_archive(self):
        if 'BUILD_ARTIFACTSTAGINGDIRECTORY' in os.environ:
            archive_output_directory = Path(
                os.environ['BUILD_ARTIFACTSTAGINGDIRECTORY'])
        else:
            archive_output_directory = self.source_builds_base
        print(f'Creating {self.output_archive_filename} in {archive_output_directory}')
        command = [
            'tar',
            '-zcf',
            f'{ archive_output_directory / self.output_archive_filename }',  # the tar filename
            f'{ self.install_directory.relative_to(self.toolbase / self.name) }',
        ]
        try:
            # keep the name + version directory in the archive, but not the package name directory
            self.system(command, cwd=self.toolbase / self.name)
        except subprocess.CalledProcessError as e:
            if not self.windows:
                raise e
            command.insert(1, '--force-local')
            # keep the name + version directory in the archive, but not the package name directory
            self.system(command, cwd=self.toolbase / self.name)

    @property
    def include_directories(self):
        '''Return the directories clients must add to their include path'''
        return [self.install_directory / 'include']

    @property
    def library_link_directories(self):
        '''Return the directories clients must add to their library link path'''
        return [self.install_directory / 'lib']

    @property
    def source_archives(self):
        '''Map of archive file/url to fetch'''
        return {}

    def fetch_source_archives(self):
        import urllib.request
        for filename, url in self.source_archives.items():
            if (self.source_downloads_base / filename).exists():
                print(
                    f'Skipping download of existing {self.source_downloads_base / filename}')
                continue
            print(f'Fetching {url} to {self.source_downloads_base / filename}')
            with urllib.request.urlopen(url) as response:
                with open(self.source_downloads_base / filename, 'wb') as final_file:
                    shutil.copyfileobj(response, final_file)

    def extract_source_archives(self):
        for source_archive_filename in self.source_archives.keys():
            self.extract_archive(self.source_downloads_base /
                                 source_archive_filename, self.source_extracted)

    def extract_archive(self, path, where):
        '''untar a file with any reasonable suffix'''
        print(f'Extracting {path} to {where}')
        if '.zip' in path.suffixes:
            self.system(['unzip', '-q', '-o', str(path)], cwd=where)
            return
        if '.7z' in path.suffixes:
            self.system(['7z', 'x', '-aoa', f'-o{where}', f'{path}'])
        if '.bz2' in path.suffixes:
            flags = ['jxf']
        elif '.gz' in path.suffixes:
            flags = ['zxf']
        elif '.tgz' in path.suffixes:
            flags = ['zxf']
        elif '.xz' in path.suffixes:
            flags = ['xf']
        elif '.zst' in path.suffixes:
            flags = ['--use-compress-program=zstd', '-xf', ]
        else:
            raise AttributeError(f"Can't extract {path}")

        if self.windows:
            flags = f'-{flags}'
            try:
                self.system(['tar', '--force-local'] +
                             flags + [str(path)], cwd=where)
            except subprocess.CalledProcessError:
                self.system(['tar'] + flags + [str(path)], cwd=where)
        else:
            self.system(['tar'] + flags + [str(path)], cwd=where)

    def patch_sources(self):
        '''Override to patch source code after extraction'''
        pass

    @property
    def source_downloads(self):
        p = self.source_downloads_base / self.name
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def source_extracted(self):
        p = self.source_extracted_base / self.name
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def main_source_directory_path(self):
        return self.source_extracted / f'{self.name}-{self.version}'

    @property
    def build_directory_path(self):
        p = self.source_builds_base / self.name
        p.mkdir(parents=True, exist_ok=True)
        return p

    def cleanup(self):
        try:
            shutil.rmtree(self.source_extracted, ignore_errors=True)
            print(f'Cleaned up {self.source_extracted}')
        except OSError:
            pass
        try:
            shutil.rmtree(self.build_directory_path, ignore_errors=True)
            print(f'Cleaned up {self.build_directory_path}')
        except OSError:
            pass

    @property
    def configuration_script(self):
        return None

    @property
    def arguments_to_configuration_script(self):
        return [f'--prefix={self.install_directory}']

    @property
    def cxxflags(self):
        flags = [
            '-O2'
        ]
        if self.macos:
            flags.extend([
                '-arch', 'x86_64',
                '-isysroot', self.macos_sdkroot,
                f'-mmacosx-version-min={self.macos_deployment_target}',
            ])
        return flags

    @property
    def ldflags(self):
        flags = []
        if self.macos:
            flags.extend([
                '-arch', 'x86_64',
                '-isysroot', self.macos_sdkroot,
                f'-mmacosx-version-min={self.macos_deployment_target}',
            ])
        return flags

    @property
    def cflags(self):
        flags = [
            '-O2'
        ]
        if self.macos:
            flags.extend([
                '-arch', 'x86_64',
                '-isysroot', self.macos_sdkroot,
                f'-mmacosx-version-min={self.macos_deployment_target}',
            ])
        return flags

    @property
    def environment_for_configuration_script(self):
        env = dict(os.environ)
        if self.cflags:
            env['CFLAGS'] = ' '.join(self.cflags)
        if self.cxxflags:
            env['CXXFLAGS'] = ' '.join(self.cxxflags)
        if self.ldflags:
            env['LDFLAGS'] = ' '.join(self.ldflags)
        return env

    def run_configuration_script(self):
        '''run the required commands to configure a package'''
        if not self.configuration_script:
            print(f'Skipping configuration script for {self.name}')
            return
        st = os.stat(self.configuration_script)
        os.chmod(self.configuration_script, st.st_mode | stat.S_IEXEC)
        self.system(
            [str(self.configuration_script)] +
            self.arguments_to_configuration_script,
            env=self.environment_for_configuration_script, cwd=self.build_directory_path)

    @property
    def environment_for_build_command(self):
        return self.environment_for_configuration_script

    def run_build_command(self):
        '''run the required commands to build a package after configuration'''
        pass

    def run_install_command(self):
        '''run the required commands to install a package'''
        pass

    def logfile_path(self, task):
        '''Canonical log file for a particular task'''
        return self.build_logs / f'{self.name}-{self.version}-{task}.log'

    def system(self, command, cwd=None, env=None, append_log=False):
        '''execute command, logging in the appropriate logfile'''
        task = sys._getframe(1).f_code.co_name
        print(f'{self.name} {task}')
        if isinstance(command, str):
            command = [command]
        print(f'Running {command}')
        openmode = 'a' if append_log else 'w'
        with open(self.logfile_path(task), openmode) as f:
            output = ''
            p = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=cwd, env=env)
            while True:
                retcode = p.poll()
                l = p.stdout.readline().decode('utf-8')
                print(l.rstrip())
                output += l
                f.write(l)
                if retcode is not None:
                    break
            assert p.returncode is not None
            if p.returncode != 0:
                print(f'Failed process environment was {env}')
                raise subprocess.CalledProcessError(
                    returncode=p.returncode, cmd=command, output=output)

    def verify(self):
        '''Override this function to verify that the install has
        produced something functional.'''
        pass

    def build(self):
        self.cleanup()
        self.fetch_source_archives()
        self.extract_source_archives()
        self.patch_sources()
        self.run_configuration_script()
        self.run_build_command()
        self.run_install_command()
        self.verify()
        self.create_archive()

    def update_dylib_id(self, library_path, new_id):
        '''MacOS helper to change a library's identifier'''
        self.system(['install_name_tool', '-id', new_id, str(library_path)])

    def change_dylib_lookup(self, library_path, from_path, to_path):
        '''MacOS helper to change the path where libraries and executables look for other libraries'''
        self.system(['install_name_tool', '-change',
                     from_path, to_path, str(library_path)])

    def patch(self, fname, *subs):
        with open(fname) as read_file:
            txt = read_file.read()
        for (old, new) in subs:
            txt = txt.replace(old, new)
        with open(fname, 'w') as out:
            out.write(txt)


_pkg = Package()
_pkg.prepare_directories()
if _pkg.macos:
    assert os.path.exists(_pkg.macos_sdkroot)
_pkg = None


class GnuMakeMixin(object):
    '''Make based build'''

    def run_build_command(self):
        self.system(['make', f'-j{multiprocessing.cpu_count()}'],
                    env=self.environment_for_build_command, cwd=self.build_directory_path)


class MakeInstallMixin(object):
    '''Make install (rather than the default do nothing install)'''

    def run_install_command(self):
        self.system(['make', 'install'],
                    env=self.environment_for_build_command, cwd=self.build_directory_path)


class AutoconfMixin(GnuMakeMixin, MakeInstallMixin, object):
    '''Autoconf based configure script'''
    @property
    def configuration_script(self):
        return self.main_source_directory_path / 'configure'


class CMakeMixin(Package):
    @property
    def configuration_script(self):
        return shutil.which('cmake')

    def run_build_command(self):
        self.system([self.configuration_script, '--build', '.', '--config', 'Release'],
                    env=self.environment_for_build_command, cwd=self.build_directory_path)

    def run_install_command(self):
        self.system([self.configuration_script, '--install', '.'],
                    env=self.environment_for_build_command, cwd=self.build_directory_path)

    @property
    def visual_studio_generator_for_build(self):
        if not "BUILD_VS_VERSION" in os.environ:
            print('BUILD_VS_VERSION not set, defaulting to VS 2019')
            return 'Visual Studio 16 2019'
        if os.environ["BUILD_VS_VERSION"] == '2019':
            return 'Visual Studio 16 2019'
        if os.environ["BUILD_VS_VERSION"] == '2017':
            return 'Visual Studio 15 2017'
        raise Exception(f'Invalid value for BUILD_VS_VERSION: {os.environ["BUILD_VS_VERSION"]}')


class NoArchiveMixin(Package):
    def create_archive(self):
        pass
