#!/usr/bin/env python3
"""Issue a short-lived LAN JWT locally; never exposes a remote minting endpoint."""
import argparse
import os
import time

import jwt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user', required=True)
    parser.add_argument('--role', choices=('viewer', 'control', 'admin'), default='viewer')
    parser.add_argument('--ttl', type=int, default=900, help='Lifetime in seconds (1–900)')
    args = parser.parse_args()
    secret = os.environ.get('DORI_API_JWT_SECRET', '').strip()
    if len(secret) < 32:
        parser.error('DORI_API_JWT_SECRET must contain at least 32 random characters')
    if not 1 <= args.ttl <= 900:
        parser.error('--ttl must be between 1 and 900 seconds')
    now = int(time.time())
    claims = {'sub': args.user, 'roles': [args.role], 'iat': now, 'exp': now + args.ttl}
    for claim, variable in (('iss', 'DORI_API_JWT_ISSUER'), ('aud', 'DORI_API_JWT_AUDIENCE')):
        value = os.environ.get(variable, '').strip()
        if value:
            claims[claim] = value
    print(jwt.encode(claims, secret, algorithm='HS256'))


if __name__ == '__main__':
    main()
