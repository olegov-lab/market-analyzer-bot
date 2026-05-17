import sys, json
for f in sys.argv[1:]:
    try:
        json.load(open(f))
        print(f"{f}: valid")
    except Exception as e:
        print(f"{f}: {e}")
