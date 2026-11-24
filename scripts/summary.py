"""Writes a Markdown summary of a JUnit XML report, for the GitHub Actions job summary."""

import sys
import xml.etree.ElementTree as ET

suite = ET.parse(sys.argv[1]).getroot()
suite = suite.find("testsuite") if suite.tag == "testsuites" else suite
total = int(suite.get("tests", 0))
failed = int(suite.get("failures", 0)) + int(suite.get("errors", 0))
skipped = int(suite.get("skipped", 0))

print("## API tests\n")
print("| Passed | Failed | Skipped | Time |")
print("|---|---|---|---|")
print(f"| {total - failed - skipped} | {failed} | {skipped} | {float(suite.get('time', 0)):.1f} s |")
shown = 0
for case in suite.iter("testcase"):
    if shown == 20:
        print("\n- … more failures in the HTML report")
        break
    problem = case.find("failure") if case.find("failure") is not None else case.find("error")
    if problem is not None:
        shown += 1
        print(f"\n- ❌ `{case.get('classname')}.{case.get('name')}`: {problem.get('message', '')[:200]}")
