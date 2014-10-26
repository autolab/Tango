# -*- coding: utf-8 -*-
# This setup.py was generated automatically by Pyron.
# For details, see http://pypi.python.org/pypi/pyron/

from setuptools import setup, find_packages

setup(
    name = 'backports.ssl_match_hostname',
    version = '3.4.0.2',
    description = 'The ssl.match_hostname() function from Python 3.4',
    long_description = '\nThe Secure Sockets layer is only actually *secure*\nif you check the hostname in the certificate returned\nby the server to which you are connecting,\nand verify that it matches to hostname\nthat you are trying to reach.\n\nBut the matching logic, defined in `RFC2818`_,\ncan be a bit tricky to implement on your own.\nSo the ``ssl`` package in the Standard Library of Python 3.2\nand greater now includes a ``match_hostname()`` function\nfor performing this check instead of requiring every application\nto implement the check separately.\n\nThis backport brings ``match_hostname()`` to users\nof earlier versions of Python.\nSimply make this distribution a dependency of your package,\nand then use it like this::\n\n    from backports.ssl_match_hostname import match_hostname, CertificateError\n    ...\n    sslsock = ssl.wrap_socket(sock, ssl_version=ssl.PROTOCOL_SSLv3,\n                              cert_reqs=ssl.CERT_REQUIRED, ca_certs=...)\n    try:\n        match_hostname(sslsock.getpeercert(), hostname)\n    except CertificateError, ce:\n        ...\n\nNote that the ``ssl`` module is only included in the Standard Library\nfor Python 2.6 and later;\nusers of Python 2.5 or earlier versions\nwill also need to install the ``ssl`` distribution\nfrom the Python Package Index to use code like that shown above.\n\nBrandon Craig Rhodes is merely the packager of this distribution;\nthe actual code inside comes verbatim from Python 3.4.\n\nHistory\n-------\n* This function was introduced in python-3.2\n* It was updated for python-3.4a1 for a CVE \n  (backports-ssl_match_hostname-3.4.0.1)\n* It was updated from RFC2818 to RFC 6125 compliance in order to fix another\n  security flaw for python-3.3.3 and python-3.4a5\n  (backports-ssl_match_hostname-3.4.0.2)\n\n\n.. _RFC2818: http://tools.ietf.org/html/rfc2818.html\n\n',
    author = 'Brandon Craig Rhodes',
    author_email = 'brandon@rhodesmill.org',
    url = 'http://bitbucket.org/brandon/backports.ssl_match_hostname',
    classifiers = ['Development Status :: 5 - Production/Stable', 'License :: OSI Approved :: Python Software Foundation License', 'Programming Language :: Python :: 2.4', 'Programming Language :: Python :: 2.5', 'Programming Language :: Python :: 2.6', 'Programming Language :: Python :: 2.7', 'Programming Language :: Python :: 3', 'Programming Language :: Python :: 3.0', 'Programming Language :: Python :: 3.1', 'Topic :: Security :: Cryptography'],

    package_dir = {'': 'src'},
    packages = find_packages('src'),
    include_package_data = True,
    install_requires = [],
    entry_points = '',
    )
