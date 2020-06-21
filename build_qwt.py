#!/usr/bin/env python3
import os
import shutil
import multiprocessing
from pathlib import Path
from ccdc.thirdparty.package import Package, GnuMakeMixin, MakeInstallMixin


class QwtPackage(GnuMakeMixin, MakeInstallMixin, Package):
    '''qwt library'''
    name = 'qwt'
    version = os.environ['QWT_VERSION']
    qt_build = os.environ['QT_BUILD']
    qt_archive_suffix = os.environ['QT_ARCHIVE_SUFFIX']

    @property
    def qt_version(self):
        return self.qt_build.split('-')[0]
    
    @property
    def qt_buildtype(self):
        if self.windows:
            return 'msvc2017_64'
        if self.linux:
            return 'gcc_64'
        if self.macos:
            return 'clang_64'

    @property
    def qt_install_dir(self):
        return self.toolbase / 'qt' / f'qt-{self.qt_build}' / self.qt_version / self.qt_buildtype

    def extract_source_archives(self):
        self.extract_archive(self.source_downloads_base /
                                f'qwt-{self.version}.zip', self.source_extracted)
        with open(self.main_source_directory_path / 'qwtconfig.pri') as f:
            t = f.read()
        t = t.replace('/usr/local/qwt-$$QWT_VERSION', str(self.install_directory))
        t += """
QMAKE_CXXFLAGS += $$(CXXFLAGS)
QMAKE_CFLAGS += $$(CFLAGS)
QMAKE_LFLAGS += $$(LDFLAGS)
"""
        with open(self.main_source_directory_path / 'qwtconfig.pri', 'w') as f:
            f.write(t)

        self.qt_install_dir.mkdir(parents=True, exist_ok=True)
        self.extract_archive(self.source_downloads_base /
                                f'qt-{self.qt_build}-{self.qt_archive_suffix}', self.toolbase / 'qt')

    @property
    def configuration_script(self):
        return self.qt_install_dir / 'bin' / ('qmake' + ('.exe' if self.windows else ''))

    @property
    def arguments_to_configuration_script(self):
        return ['-makefile', str(self.main_source_directory_path / 'qwt.pro')]

    @property
    def cxxflags(self):
        flags = super().cxxflags
        if self.linux:
            flags.extend(['-Wno-deprecated-copy'])
        return flags

    @property
    def environment_for_build_command(self):
        e = self.environment_for_configuration_script
        e['VERBOSE']='1'
        return e

def main():
    try:
        shutil.rmtree(QwtPackage().install_directory)
        shutil.rmtree(QwtPackage().toolbase / 'qt')
        shutil.rmtree(QwtPackage().source_extracted_base)
    except OSError:
        pass
    QwtPackage().build()


if __name__ == "__main__":
    main()
