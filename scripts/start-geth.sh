#!/bin/sh
set -e

CONFIG=$1
if [ -z $CONFIG ]; then
    echo "No config file supplied"
    exit 1
fi
shift

DATA=$1
if [ -z $DATA ]; then
    echo "No data directory supplied"
    exit 1
fi
shift

geth --datadir $DATA init $CONFIG
pwdfile=$(mktemp /tmp/password.XXXXXX)
tmpfile=$(mktemp /tmp/validator-key.XXXXXX)
echo 123456 > $pwdfile

# import validator and community keys
for mnemonic in "$VALIDATOR1_MNEMONIC" "$COMMUNITY_MNEMONIC"; do
    MNEMONIC="$mnemonic" python -c "
import os
from eth_account import Account
Account.enable_unaudited_hdwallet_features()
print(Account.from_mnemonic(os.environ['MNEMONIC']).key.hex().replace('0x', ''))
" > $tmpfile
    geth --datadir $DATA --password $pwdfile account import $tmpfile
done
rm $tmpfile

# start up
geth --dev --dev.period 1 --datadir $DATA --http --http.addr localhost --http.api 'personal,eth,net,web3,txpool,miner,debug' \
-unlock '0x378c50D9264C63F3F92B806d4ee56E9D86FfB3Ec' --password $pwdfile \
--allow-insecure-unlock --ipcdisable \
"$@"

rm $pwdfile
