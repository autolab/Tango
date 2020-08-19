from __future__ import print_function
#
# Recursively validates all python files with pyflakes that were modified
# since the last validation, and provides basic stats. Ignores hidden
# directories.
#

try:
    import pyflakes
    pyflakes  # avoid unused warning when validating self!
except ImportError:
    print('Validate requires pyflakes. Please install '\
          'with: pip install pyflakes')
    exit()

import argparse
import os
from subprocess import call
import re

abspath = os.path.abspath(__file__)
dname = os.path.dirname(abspath)
os.chdir(dname + "/..")

path_in_hidden_folders = re.compile(r'^(.*/)?\.[^/]+/.+$')

# Options
parser = argparse.ArgumentParser(
    description='Recursively validates all '
    'python files with pyflakes that were modified since the last '
    'validation,and provides basic stats. Ignores hidden directories.')
parser.add_argument('--all', dest='all', action='store_true', default=False,
                    help='check all files, regardless of last modification '
                         'and validation dates')
parser.add_argument('--stats', dest='stats', action='store_true',
                    default=False, help='return statistics on Python '
                                        'files (line count, etc)')
args = parser.parse_args()

# Setup
skip_paths = []

# Stats
file_count = 0
validated_count = 0
validated_issue_count = 0
line_count = 0


print('\n---- Validating all files ----')

for dirname, dirnames, filenames in os.walk('.'):
    for filename in filenames:
        if filename.endswith('.py'):

            # File details
            path = os.path.join(dirname, filename)
            #print("PATH: " + path)
            # Skip
            if "/venv/" in path:
                continue
            if path in skip_paths:
                continue
            if path_in_hidden_folders.match(path):
                continue

            # Validate
            file_count += 1
            mtime = int(os.stat(path).st_mtime)

            if call(['pyflakes', path]):
                validated_issue_count += 1
            if call(['pep8', path]):
                validated_issue_count += 1
            validated_count += 1

            # Stats
            if args.stats:
                line_count += sum(1 for line in open(path))
if validated_issue_count == 0:
    print('ALL OKAY')
print('\n---- Validation summary ----')
print('Files with validation issues: %i' % validated_issue_count)
print('Validated files: %i' % validated_count)
print('Total python files: %i' % file_count)

# Print stats
if args.stats:
    print('\n---- Stats ----')
    print('Total python line count: %i' % line_count)

# Finish
print('')
