from setuptools import setup

setup(
    name='apps + shared_lib',
    version='1.0.0',
    packages=['shared_lib', 'shared_lib.tests'],
    url='',
    license='',
    author='Rong Fan, HongWei Yuan',
    author_email='',
    description='standard shared library',
    install_requires=[
        'yfinance>=0.2.40'
    ]
)
