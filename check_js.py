import sys
f = open(sys.argv[1]).read()
print("lines:", len(f.splitlines()))
print("open_brace:", f.count("{"))
print("close_brace:", f.count("}"))
print("open_paren:", f.count("("))
print("close_paren:", f.count(")"))
print("open_bracket:", f.count("["))
print("close_bracket:", f.count("]"))
