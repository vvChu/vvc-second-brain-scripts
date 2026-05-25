"""Run tests and print results."""
import subprocess
import sys
import xml.etree.ElementTree as ET

subprocess.run([sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short", "--junitxml=test_result.xml"])

tree = ET.parse("test_result.xml")
root = tree.getroot()
ts = root.find("testsuite")
total = ts.get("tests")
errors = ts.get("errors")
failures = ts.get("failures")
print(f"\nTests: {total}, Errors: {errors}, Failures: {failures}")
for tc in ts.findall("testcase"):
    name = tc.get("name")
    cls = tc.get("classname", "")
    fail = tc.find("failure")
    err = tc.find("error")
    if fail is not None:
        print(f"  [FAIL] {cls}::{name}")
        print(f"    {fail.text[:200] if fail.text else ''}")
    elif err is not None:
        print(f"  [ERR ] {cls}::{name}")
        print(f"    {err.text[:200] if err.text else ''}")
    else:
        print(f"  [PASS] {cls}::{name}")
