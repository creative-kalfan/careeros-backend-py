import os
p = "verify_final_state.py"
lines = open(p).readlines()
artifact = "<" + "/arg" + "value>"
if lines and lines[-1].strip() == artifact:
    open(p, "w").writelines(lines[:-1])
    print("Removed artifact. Lines now:", len(open(p).readlines()))
else:
    print("No artifact found. Last line:", repr(lines[-1] if lines else "empty"))