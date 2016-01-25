# -*- coding: utf-8 -*-


import io
import os.path
import pytest
import tarfile
import tempfile
import zipfile

from smartmob_agent import unpack_archive


def test_unpack_archive_unknown_format(mktemp, temp_folder):
    # Generate archive.
    archive_path = mktemp()
    with zipfile.ZipFile(archive_path, 'w') as archive:
        archive.writestr('Procfile', 'python-help: python --help')
        archive.writestr('requirements.txt', 'somelib==1.0')

    # Cannot unpack unknown format.
    with pytest.raises(ValueError) as error:
        unpack_archive('tgz', archive_path, temp_folder)
    assert str(error.value) == 'Unknown archive format "tgz".'

def test_unpack_archive_zip(mktemp, temp_folder):
    # Generate archive.
    archive_path = mktemp()
    with zipfile.ZipFile(archive_path, 'w') as archive:
        archive.writestr('Procfile', 'python-help: python --help')
        archive.writestr('requirements.txt', 'somelib==1.0')

    # Unpack it.
    unpack_archive('zip', archive_path, temp_folder)
    
    # Check contents.
    with open(os.path.join(temp_folder, 'Procfile'), 'r') as stream:
        assert stream.read() == 'python-help: python --help'
    with open(os.path.join(temp_folder, 'requirements.txt'), 'r') as stream:
        assert stream.read() == 'somelib==1.0'


def test_unpack_archive_tar(mktemp, temp_folder):
    # Generate archive.
    archive_path = mktemp()
    with tarfile.open(archive_path, 'w') as archive:
        file_path = mktemp()
        with open(file_path, 'w') as stream:
            stream.write('python-help: python --help')
        archive.add(file_path, 'Procfile')
        file_path = mktemp()
        with open(file_path, 'w') as stream:
            stream.write('somelib==1.0')
        archive.add(file_path, 'requirements.txt')

    # Unpack it.
    unpack_archive('tar', archive_path, temp_folder)

    # Check contents.
    with open(os.path.join(temp_folder, 'Procfile'), 'r') as stream:
        assert stream.read() == 'python-help: python --help'
    with open(os.path.join(temp_folder, 'requirements.txt'), 'r') as stream:
        assert stream.read() == 'somelib==1.0'
