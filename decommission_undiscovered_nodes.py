#!/usr/bin/env python3
"""
Written by Klaus Mucelli | klausmucelli15@gmail.com
Simple script to find and decommission all undiscovered nodes in ACI
"""

import requests
import json
import urllib3
import time

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configuration
APIC_URL = "https://X.X.X.X"
USERNAME = "xxxxx"
PASSWORD = "xxxxx"

def login_to_apic():
    """Login to APIC and return session with token"""
    login_url = f"{APIC_URL}/api/aaaLogin.json"
    auth_payload = {
        "aaaUser": {
            "attributes": {
                "name": USERNAME,
                "pwd": PASSWORD
            }
        }
    }

    session = requests.Session()
    session.verify = False

    try:
        response = session.post(login_url, json=auth_payload)
        if response.status_code == 200:
            print("✓ Successfully logged in to APIC")
            return session
        else:
            print(f"✗ Login failed: {response.text}")
            return None
    except Exception as e:
        print(f"✗ Connection error: {e}")
        return None

def get_undiscovered_nodes(session):
    """Get all undiscovered nodes from APIC"""
    query_url = f"{APIC_URL}/api/node/class/fabricNode.json?query-target-filter=eq(fabricNode.fabricSt,\"undiscovered\")"

    try:
        response = session.get(query_url)
        if response.status_code == 200:
            data = response.json()
            nodes = data.get('imdata', [])
            print(f"✓ Found {data.get('totalCount', 0)} undiscovered nodes")
            return nodes
        else:
            print(f"✗ Failed to get nodes: {response.text}")
            return []
    except Exception as e:
        print(f"✗ Error getting nodes: {e}")
        return []

def generate_decommission_payload(nodes):
    """Generate decommission payload in array format"""
    payload = []

    print("\nNodes to decommission:")
    for node in nodes:
        node_attrs = node.get('fabricNode', {}).get('attributes', {})
        node_dn = node_attrs.get('dn')
        node_name = node_attrs.get('name', 'unknown')
        node_id = node_attrs.get('id')

        if node_dn:
            decom_entry = {
                "fabricRsDecommissionNode": {
                    "attributes": {
                        "tDn": node_dn,
                        "status": "created,modified",
                        "removeFromController": "true"
                    },
                    "children": []
                }
            }
            payload.append(decom_entry)
            print(f"  - {node_dn} | {node_name} (ID: {node_id})")

    return payload

def save_payload_to_file(payload, filename="decommission_payload.json"):
    """Save payload to JSON file"""
    with open(filename, 'w') as f:
        json.dump(payload, f, indent=2)
    print(f"\n✓ Payload saved to {filename}")
    return filename

def decommission_nodes(session, payload):
    """Send decommission POST request for each node individually"""
    # Correct endpoint for decommissioning nodes
    decom_url = f"{APIC_URL}/api/node/mo/uni/fabric/outofsvc.json"

    print(f"\n{'='*60}")
    print(f"Starting decommission process...")
    print(f"URL: {decom_url}")
    print(f"Total nodes to process: {len(payload)}")
    print(f"{'='*60}\n")

    success_count = 0
    failed_count = 0
    failed_nodes = []

    # Loop through each node and send individual POST request
    for i, node_entry in enumerate(payload, 1):
        node_dn = node_entry['fabricRsDecommissionNode']['attributes']['tDn']

        print(f"[{i}/{len(payload)}] Processing: {node_dn}")

        try:
            # Send the fabricRsDecommissionNode object directly to outofsvc endpoint
            response = session.post(decom_url, json=node_entry)

            if response.status_code in [200, 201]:
                print(f"  ✓ Success")
                success_count += 1
            else:
                print(f"  ✗ Failed - Status: {response.status_code}")
                print(f"  Response: {response.text}")
                failed_count += 1
                failed_nodes.append({
                    'dn': node_dn,
                    'status': response.status_code,
                    'error': response.text
                })
        except Exception as e:
            print(f"  ✗ Error: {e}")
            failed_count += 1
            failed_nodes.append({
                'dn': node_dn,
                'error': str(e)
            })

        # Small delay between requests to avoid overwhelming APIC
        if i < len(payload):
            time.sleep(0.2)

    # Summary
    print(f"\n{'='*60}")
    print(f"DECOMMISSION SUMMARY")
    print(f"{'='*60}")
    print(f"Total nodes: {len(payload)}")
    print(f"✓ Successful: {success_count}")
    print(f"✗ Failed: {failed_count}")
    print(f"{'='*60}")

    if failed_nodes:
        print("\n" + "="*60)
        print("FAILED NODES - Copy/paste these for retry:")
        print("="*60)
        for node in failed_nodes:
            # Extract just the node DN in a format that's easy to copy
            node_dn = node['dn']
            print(f"{node_dn}")

        print("\n" + "="*60)
        print("FAILED NODES DETAILS:")
        print("="*60)
        for node in failed_nodes:
            print(f"\nNode: {node['dn']}")
            if 'status' in node:
                print(f"  HTTP Status: {node['status']}")
            error_msg = node.get('error', 'Unknown')
            # Pretty print error if it's JSON
            try:
                error_json = json.loads(error_msg) if isinstance(error_msg, str) and error_msg.startswith('{') else error_msg
                if isinstance(error_json, dict):
                    print(f"  Error: {json.dumps(error_json, indent=4)}")
                else:
                    print(f"  Error: {error_msg}")
            except:
                print(f"  Error: {error_msg}")

    return success_count > 0

def main():
    print("="*60)
    print("ACI Undiscovered Nodes Decommission Tool")
    print("="*60)
    print(f"\nAPIC: {APIC_URL}\n")

    # Step 1: Login
    session = login_to_apic()
    if not session:
        return

    # Step 2: Get undiscovered nodes
    nodes = get_undiscovered_nodes(session)

    if not nodes:
        print("\n✓ No undiscovered nodes found!")
        return

    # Step 3: Generate decommission payload
    payload = generate_decommission_payload(nodes)

    if not payload:
        print("\n✗ No valid nodes to decommission")
        return

    # Step 4: Save payload to file
    filename = save_payload_to_file(payload)

    # Step 5: Ask for confirmation
    print("\n" + "="*60)
    print("WARNING: This will decommission all undiscovered nodes!")
    print(f"The script will send {len(payload)} individual POST requests")
    print("Each node will be removed one by one automatically")
    print("="*60)

    confirm = input("\nType 'YES' to proceed with automatic decommission: ")

    if confirm.upper() == 'YES':
        # Step 6: Execute decommission loop
        success = decommission_nodes(session, payload)

        if success:
            print("\n✓ Decommission process completed!")
            print("Check the summary above for details")
        else:
            print("\n✗ Decommission process failed. Check the error messages above.")
    else:
        print("\n✗ Decommission cancelled")
        print(f"Payload saved to '{filename}' for manual execution")

if __name__ == "__main__":
    main()
