#!/usr/bin/env python
from setuptools import setup, find_packages


with open('README.rst') as readme_file:
    README = readme_file.read()


setup(
    name='jmeslog',
    version='0.1.1',
    description="Tool for managing changelogs.",
    long_description=README,
    author="James Saryerwinnie",
    author_email='js@jamesls.com',
    url='https://github.com/jamesls/jmeslog',
    packages=find_packages(exclude=['tests']),
    py_modules=['jmeslog'],
    license="Apache License 2.0",
    zip_safe=True,
    keywords='changelog jmeslog changes',
    entry_points={
        'console_scripts': [
            'jmeslog = jmeslog:main',
        ]
    },
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: Apache Software License',
        'Natural Language :: English',
        'Programming Language :: Python :: 3.7',
    ],
)
