import secrets, string
pwd = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))
print(pwd)
