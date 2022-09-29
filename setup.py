

import setuptools
from codecs import open  # To use a consistent encoding
from os import path

here = path.abspath(path.dirname(__file__))

# Get the long description from the relevant file
with open(path.join(here, 'DESCRIPTION.md'), encoding='utf-8') as f:
    long_description = f.read()

setuptools.setup(
    name='artemis_uploader',

    # Versions should comply with PEP440.  For a discussion on single-sourcing
    # the version across setup.py and the project code, see
    # http://packaging.python.org/en/latest/tutorial.html#version
    version='3.0.0',

    description='Application to upload firmware to SparkFun Artemis based products',
    long_description=long_description,

    # The project's main homepage.
    url='https://www.sparkfun.com/artemis',

    # Author details
    author='SparkFun Electronics',
    author_email='sales@sparkfun.com',

    project_urls = {
        "Bug Tracker" : "https://github.com/sparkfun/Artemis-Firmware-Upload-GUI/issues",
        "Repositor"   : "https://github.com/sparkfun/Artemis-Firmware-Upload-GUI"
    },
    # Choose your license
    license='MIT',

    # See https://pypi.python.org/pypi?%3Aaction=list_classifiers
    classifiers=[
        # How mature is this project? Common values are
        #   3 - Alpha
        #   4 - Beta
        #   5 - Production/Stable
        'Production Stable :: 5',

        # Indicate who your project is intended for
        'Intended Audience :: Developers',
        'Topic :: Hardware Development :: Build Tools',

        # Pick your license as you wish (should match "license" above)
        'License :: OSI Approved :: MIT License',

        # Specify the Python versions you support here. In particular, ensure
        # that you indicate whether you support Python 2, Python 3 or both.
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',

    ],

    download_url="https://github.com/sparkfun/Artemis-Firmware-Upload-GUI/releases",

    # What does your project relate to?
    keywords='Firmware SparkFun Artemis Arduino',

    # You can just specify the packages manually here if your project is
    # simple. Or you can use find_packages().
    packages=["artemis_uploader", "artemis_uploader/asb", "artemis_uploader/resource"],

    # List run-time dependencies here.  These will be installed by pip when your
    # project is installed. For an analysis of "install_requires" vs pip's
    # requirements files see:
    # https://packaging.python.org/en/latest/technical.html#install-requires-vs-requirements-files
    install_requires=['pyserial', 'pycryptodome', 'pyqt5', 'darkdetect'],

    # If there are data files included in your packages that need to be
    # installed, specify them here.  If using Python 2.6 or less, then these
    # have to be included in MANIFEST.in as well.
    package_data={
        'artemis_uploader/resource': ['*.png', '*.ico', '*.bin', '*.icns'],
    },



    # To provide executable scripts, use entry points in preference to the
    # "scripts" keyword. Entry points provide cross-platform support and allow
    # pip to create the appropriate form of executable for the target platform.
    entry_points={
        'console_scripts': ['artemis_upload=artemis_uploader:startArtemisUploader',
        ],
    },
)