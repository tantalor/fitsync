#!/usr/bin/env bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
pushd $DIR > /dev/null
virtualenv env > /dev/null
source env/bin/activate
./fitsync.py
popd > /dev/null
