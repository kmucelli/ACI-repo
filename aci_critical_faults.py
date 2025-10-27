#! /usr/bin/env python
"""
Written by Klaus Mucelli | klausmucelli15@gmail.com
This script will query the APIC for Faults and output
them to the Terminal, sorted by fault code. It requires
a separate credentials.py file to access the APIC.
"""

from acitoolkit.acitoolkit import *
from acitoolkit import Faults
from credentials import *

fault_count = {"total": 0, "critical": 0}

session = Session(URL, LOGIN, PASSWORD)
resp = session.login()
if not resp.ok:
    print('%% Could not login to APIC')
    SystemExit.exit(1)

faults_obj = Faults()
faults_obj.subscribe_faults(session)

critical_faults = []

while faults_obj.has_faults(session):
    faults = faults_obj.get_faults(session)
    if faults is not None:
        for fault in faults:
            fault_count["total"] += 1
            if fault is not None and fault.severity == "critical":
                fault_count["critical"] += 1
                fault_code = fault.dn.split('fault-')[-1]
                # Collect (code, description) tuples
                critical_faults.append((fault_code, fault.descr))

critical_faults.sort()

for code, descr in critical_faults:
    print(f"{code:<10}:{descr}")

print("*********************************")
print(f"{fault_count['total']} Faults were found.")
print(f"{fault_count['critical']} listed above are critical")

