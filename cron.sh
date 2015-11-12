#!/bin/sh

cd $(dirname $0)
virtualenv env > /dev/null
. env/bin/activate
./fitsync.py patch

