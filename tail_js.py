import sys
f = open(sys.argv[1]).read()
lines = f.splitlines()
print("Total lines:", len(lines))
for i, l in enumerate(lines[-20:]):
    print(f"{len(lines)-20+i+1}: {l}")
