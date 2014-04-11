# encoding: utf-8
# -----------------------------------------------------------------------------
#  Copyright (C) 2008-2014, IPython Development Team and Enthought, Inc.
#  Distributed under the terms of the BSD License.  See COPYING.rst.
# -----------------------------------------------------------------------------

from setuptools import setup, find_packages

install_requires = [
    'ipython',
    'numpy',
    'mpi4py'
]

metadata = {
    'name': 'distarray',
    'version': '0.2.0',
    'description': 'Distributed Memory Arrays for Python',
    'keywords': 'parallel mpi distributed array',
    'license': 'New BSD',
    'author': 'IPython Development Team and Enthought, Inc.',
    'author_email': 'ksmith@enthought.com',
    'url': 'https://github.com/enthought/distarray',
    'packages': find_packages(),
    'install_requires': install_requires
}

setup(**metadata)
