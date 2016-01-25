# -*- coding: utf-8 -*-

from setuptools import find_packages, setup

with open('README.rst', 'rb') as stream:
    readme = stream.read()
    if hasattr(readme, 'decode'):
        readme = readme.decode('utf-8')

with open('smartmob_agent/version.txt', 'r') as stream:
    version = stream.read()
    if hasattr(version, 'decode'):
        version = version.decode('utf-8')
    version = version.strip()

setup(
    name='smartmob-agent',
    url='https://github.com/smartmob-project/smartmob-agent',
    description='Remote Procfile runner',
    long_description=readme,
    keywords='procfile asyncio',
    license='MIT',
    maintainer='Andre Caron',
    maintainer_email='ac@smartmob.org',
    version=version,
    classifiers=[
        'Development Status :: 1 - Planning',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Operating System :: MacOS :: MacOS X',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3.5',
        'Topic :: Software Development :: Libraries',
    ],
    packages=find_packages(),
    package_data={
        'smartmob_agent': [
            'version.txt',
        ],
    },
    entry_points={
        'console_scripts': [
            'smartmob-agent = smartmob_agent:main',
         ],
    },
    install_requires=[
        'aiohttp>=0.20,<0.21',
        'strawboss>=0.2,<0.3',
        'virtualenv>=13.1,<14',
        'voluptuous>=0.8,<0.9',
    ],
)
