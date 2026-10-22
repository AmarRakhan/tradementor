#!/usr/bin/env python3
"""Ontsleutel een diag-results/<id>.enc met de privésleutel uit Claude's sessie.
Gebruik: decrypt.py PRIVATE_KEY.pem FILE.enc > result.json"""
import base64
import os
import subprocess
import sys
import tempfile

key_path, enc_path = sys.argv[1], sys.argv[2]
fields = dict(line.split("=", 1) for line in open(enc_path).read().splitlines() if "=" in line)
with tempfile.TemporaryDirectory() as d:
    open(os.path.join(d, "key.enc"), "wb").write(base64.b64decode(fields["key"]))
    open(os.path.join(d, "data.enc"), "wb").write(base64.b64decode(fields["data"]))
    subprocess.run(["openssl", "pkeyutl", "-decrypt", "-inkey", key_path, "-pkeyopt", "rsa_padding_mode:oaep",
                    "-pkeyopt", "rsa_oaep_md:sha256", "-in", f"{d}/key.enc", "-out", f"{d}/k.bin"], check=True)
    out = subprocess.run(["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-iter", "200000", "-in", f"{d}/data.enc",
                          "-pass", f"file:{d}/k.bin"], check=True, capture_output=True).stdout
sys.stdout.buffer.write(out)
print(f"\n# task={fields.get('task')} run={fields.get('run')} {fields.get('exit','')}", file=sys.stderr)
