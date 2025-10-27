# A simple script that accepts a JSON snapshot of an ACI fabric as a main source file to find interfaces in use by L3Outs in an ACI fabric.
"""
Written by Klaus Mucelli | klausmucelli15@gmail.com
This script will query all interfaces in use by
L3Outs within an ACI fabric.
"""
import json
import os

# Prompt user to input the JSON file path and validate it
while True:
    filenamecsv = input("Enter the json file path: ")
    if os.path.isfile(filenamecsv) and os.access(filenamecsv, os.R_OK):
        break
    print(filenamecsv, "is not a valid path or the file is not readable")

# Load the JSON file with error handling and debug prints
try:
    with open(filenamecsv, 'r', encoding='utf-8') as f:
        data = json.load(f)
        print("JSON file loaded successfully")
except json.JSONDecodeError as e:
    print(f"Error decoding JSON: {e}")
    exit(1)
except Exception as e:
    print(f"An error occurred: {e}")
    exit(1)
    
# Function to recursively search for all 'l3extRsPathL3OutAtt' attributes
def find_all_l3extRsPathL3OutAtt(obj):
    results = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == 'l3extRsPathL3OutAtt':
                results.append(value['attributes'])
            else:
                results.extend(find_all_l3extRsPathL3OutAtt(value))
    elif isinstance(obj, list):
        for item in obj:
            results.extend(find_all_l3extRsPathL3OutAtt(item))
    return results

# Search for all 'l3extRsPathL3OutAtt' attributes
attributes_list = find_all_l3extRsPathL3OutAtt(data)

# Create a list of formatted strings
output_list = []
for attributes in attributes_list:
    descr = attributes.get('descr', '')
    tDn = attributes.get('tDn', '')
    output_list.append(f"{descr} - {tDn}")

output_list.sort()

for output in output_list:
    print(output)


