#!/bin/bash

source ~/.bashrc

cd ~/backup
mongodump
rm -f dump.tar.gz
tar cvzf dump.tar.gz dump

DAY=$(date +%Y%m%d --utc -d '1 hour')
mkdir -p archive/$DAY
mv dump.tar.gz archive/$DAY
s3put -b variantfishtest -p /home/fishtest/ archive/$DAY/dump.tar.gz
# Don't keep the archives locally, we've filled the HD up multiple times
rm archive/$DAY/dump.tar.gz
