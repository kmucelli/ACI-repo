#!/usr/bin/env python3
"""
ACI Tenant Migration Script
Collects tenant configurations from source ACI fabric and pushes to destination ACI fabric
Author: Klaus
Date: 2026-02-18
"""

import requests
import json
import logging
import argparse
import getpass
from datetime import datetime
from urllib3.exceptions import InsecureRequestWarning

# Disable SSL warnings
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'tenant_migration_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class ACIFabric:
    """Class to interact with ACI fabric via REST API"""

    def __init__(self, apic_url, username, password):
        self.apic_url = apic_url.rstrip('/')
        self.username = username
        self.password = password
        self.token = None
        self.session = requests.Session()
        self.session.verify = False

    def login(self):
        """Login to APIC and obtain authentication token"""
        login_url = f"{self.apic_url}/api/aaaLogin.json"
        payload = {
            "aaaUser": {
                "attributes": {
                    "name": self.username,
                    "pwd": self.password
                }
            }
        }

        try:
            response = self.session.post(login_url, json=payload, timeout=30)
            response.raise_for_status()
            self.token = response.cookies.get('APIC-cookie')
            logger.info(f"Successfully logged into APIC: {self.apic_url}")
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to login to APIC {self.apic_url}: {str(e)}")
            return False

    def logout(self):
        """Logout from APIC"""
        logout_url = f"{self.apic_url}/api/aaaLogout.json"
        try:
            self.session.post(logout_url, timeout=10)
            logger.info(f"Successfully logged out from APIC: {self.apic_url}")
        except Exception as e:
            logger.warning(f"Logout warning: {str(e)}")

    def get_tenants(self, exclude_common=True, exclude_infra=True, exclude_mgmt=True):
        """Retrieve all tenant configurations from ACI fabric using two-phase approach"""

        # Phase 1: Get list of tenant names only (fast query)
        query_url = f"{self.apic_url}/api/node/class/fvTenant.json"

        try:
            logger.info("Retrieving tenant list from source APIC...")
            response = self.session.get(query_url, timeout=30)
            response.raise_for_status()
            data = response.json()

            # Default tenants to exclude
            default_exclude = []
            if exclude_common:
                default_exclude.append('common')
            if exclude_infra:
                default_exclude.append('infra')
            if exclude_mgmt:
                default_exclude.append('mgmt')

            tenant_names = []
            excluded_tenants = []

            for item in data.get('imdata', []):
                tenant_name = item['fvTenant']['attributes']['name']

                if tenant_name in default_exclude:
                    excluded_tenants.append(tenant_name)
                    continue

                tenant_names.append(tenant_name)

            logger.info(f"Found {len(tenant_names)} tenants to collect")
            if excluded_tenants:
                logger.info(f"Excluded tenants: {', '.join(excluded_tenants)}")

            # Phase 2: Get full configuration for each tenant individually
            tenants = []
            failed_tenants = []
            for idx, tenant_name in enumerate(tenant_names, 1):
                logger.info(f"[{idx}/{len(tenant_names)}] Collecting tenant: {tenant_name}")

                # Retry logic
                max_retries = 2
                for attempt in range(max_retries):
                    tenant_config = self.get_tenant_by_name(tenant_name)
                    if tenant_config:
                        tenants.append(tenant_config)
                        break
                    elif attempt < max_retries - 1:
                        logger.warning(f"Retry {attempt + 1}/{max_retries - 1} for tenant: {tenant_name}")
                    else:
                        logger.error(f"Failed to retrieve tenant after {max_retries} attempts: {tenant_name}")
                        failed_tenants.append(tenant_name)

            logger.info(f"Total tenants successfully collected: {len(tenants)}")
            if failed_tenants:
                logger.warning(f"Failed to collect {len(failed_tenants)} tenants: {', '.join(failed_tenants)}")
            return tenants

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to retrieve tenant list: {str(e)}")
            return []

    def get_tenant_by_name(self, tenant_name):
        """Retrieve specific tenant configuration by name"""
        query_url = f"{self.apic_url}/api/node/mo/uni/tn-{tenant_name}.json?rsp-subtree=full&rsp-prop-include=config-only"

        try:
            response = self.session.get(query_url, timeout=180)
            response.raise_for_status()
            data = response.json()

            if data.get('imdata'):
                logger.debug(f"Successfully retrieved tenant: {tenant_name}")
                return data['imdata'][0]
            else:
                logger.warning(f"Tenant not found: {tenant_name}")
                return None

        except requests.exceptions.Timeout:
            logger.error(f"Timeout retrieving tenant {tenant_name} (exceeded 180s)")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to retrieve tenant {tenant_name}: {str(e)}")
            return None

    def push_tenant(self, tenant_config):
        """Push tenant configuration to ACI fabric"""
        push_url = f"{self.apic_url}/api/node/mo/uni.json"

        tenant_name = tenant_config['fvTenant']['attributes']['name']

        # Remove certain attributes that shouldn't be pushed
        attributes_to_remove = ['dn', 'modTs', 'uid', 'rn', 'monPolDn', 'childAction', 'lcOwn']
        if 'attributes' in tenant_config['fvTenant']:
            for attr in attributes_to_remove:
                tenant_config['fvTenant']['attributes'].pop(attr, None)

        # Recursively clean child objects
        self._clean_config(tenant_config)

        payload = {
            "fvTenant": tenant_config['fvTenant']
        }

        try:
            response = self.session.post(push_url, json=payload, timeout=180)
            response.raise_for_status()
            logger.info(f"Successfully pushed tenant: {tenant_name}")
            return True

        except requests.exceptions.Timeout:
            logger.error(f"Timeout pushing tenant {tenant_name} (exceeded 180s)")
            return False
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to push tenant {tenant_name}: {str(e)}")
            if hasattr(e, 'response') and hasattr(e.response, 'text'):
                logger.error(f"Response: {e.response.text}")
            return False

    def _clean_config(self, config):
        """Recursively clean configuration by removing unwanted attributes"""
        attributes_to_remove = ['dn', 'modTs', 'uid', 'rn', 'monPolDn', 'childAction', 'lcOwn', 'status']

        if isinstance(config, dict):
            # Clean attributes
            if 'attributes' in config:
                for attr in attributes_to_remove:
                    config['attributes'].pop(attr, None)

            # Recursively clean children
            if 'children' in config:
                for child in config['children']:
                    self._clean_config(child)

            # Clean nested dictionaries
            for key, value in config.items():
                if isinstance(value, dict):
                    self._clean_config(value)
                elif isinstance(value, list):
                    for item in value:
                        self._clean_config(item)

        elif isinstance(config, list):
            for item in config:
                self._clean_config(item)

    def tenant_exists(self, tenant_name):
        """Check if tenant exists in the fabric"""
        query_url = f"{self.apic_url}/api/node/mo/uni/tn-{tenant_name}.json"

        try:
            response = self.session.get(query_url, timeout=10)
            response.raise_for_status()
            data = response.json()
            return len(data.get('imdata', [])) > 0
        except:
            return False


def save_tenant_to_file(tenant_config, output_dir='tenant_backups'):
    """Save tenant configuration to JSON file"""
    import os

    os.makedirs(output_dir, exist_ok=True)
    tenant_name = tenant_config['fvTenant']['attributes']['name']
    filename = f"{output_dir}/tenant_{tenant_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    try:
        with open(filename, 'w') as f:
            json.dump(tenant_config, f, indent=2)
        logger.info(f"Saved tenant configuration to: {filename}")
        return filename
    except Exception as e:
        logger.error(f"Failed to save tenant to file: {str(e)}")
        return None


def migrate_tenants(source_apic, dest_apic, tenant_list=None, backup=True, skip_existing=True):
    """
    Migrate tenants from source to destination APIC

    Args:
        source_apic: Source ACI fabric object
        dest_apic: Destination ACI fabric object
        tenant_list: List of specific tenant names to migrate (None = all)
        backup: Save tenant configs to files before pushing
        skip_existing: Skip tenants that already exist in destination
    """
    logger.info("=" * 80)
    logger.info("Starting Tenant Migration")
    logger.info("=" * 80)

    # Login to source APIC
    if not source_apic.login():
        logger.error("Failed to login to source APIC. Exiting.")
        return False

    # Login to destination APIC
    if not dest_apic.login():
        logger.error("Failed to login to destination APIC. Exiting.")
        source_apic.logout()
        return False

    # Collect tenants from source
    if tenant_list:
        logger.info(f"Migrating specific tenants: {', '.join(tenant_list)}")
        tenants = []
        for tenant_name in tenant_list:
            tenant_config = source_apic.get_tenant_by_name(tenant_name)
            if tenant_config:
                tenants.append(tenant_config)
    else:
        logger.info("Collecting all tenants from source APIC")
        tenants = source_apic.get_tenants()

    if not tenants:
        logger.warning("No tenants to migrate")
        source_apic.logout()
        dest_apic.logout()
        return False

    # Migrate each tenant
    success_count = 0
    failed_count = 0
    skipped_count = 0

    logger.info(f"\nStarting migration of {len(tenants)} tenants...")
    logger.info("-" * 80)

    for idx, tenant_config in enumerate(tenants, 1):
        tenant_name = tenant_config['fvTenant']['attributes']['name']
        logger.info(f"\n[{idx}/{len(tenants)}] Processing tenant: {tenant_name}")

        # Check if tenant exists in destination
        if skip_existing and dest_apic.tenant_exists(tenant_name):
            logger.warning(f"Tenant '{tenant_name}' already exists in destination. Skipping.")
            skipped_count += 1
            continue

        # Backup tenant configuration
        if backup:
            logger.info(f"Backing up tenant: {tenant_name}")
            save_tenant_to_file(tenant_config)

        # Push to destination
        logger.info(f"Pushing tenant to destination: {tenant_name}")
        if dest_apic.push_tenant(tenant_config):
            success_count += 1
            logger.info(f"✓ Tenant '{tenant_name}' migrated successfully")
        else:
            failed_count += 1
            logger.error(f"✗ Failed to migrate tenant: {tenant_name}")

    # Summary
    logger.info("=" * 80)
    logger.info("Migration Summary")
    logger.info("=" * 80)
    logger.info(f"Total tenants processed: {len(tenants)}")
    logger.info(f"Successfully migrated: {success_count}")
    logger.info(f"Failed: {failed_count}")
    logger.info(f"Skipped (already exist): {skipped_count}")
    logger.info("=" * 80)

    # Logout
    source_apic.logout()
    dest_apic.logout()

    return failed_count == 0


def main():
    parser = argparse.ArgumentParser(
        description='Migrate tenants from source ACI fabric to destination ACI fabric',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Migrate all tenants (interactive)
  python tenant_migration.py

  # Migrate specific tenants
  python tenant_migration.py --tenants tenant1 tenant2 tenant3

  # Skip backup and overwrite existing tenants
  python tenant_migration.py --no-backup --no-skip-existing

  # Specify APICs via command line
  python tenant_migration.py --source-apic https://10.1.1.1 --dest-apic https://10.2.2.1
        """
    )

    parser.add_argument('--source-apic', help='Source APIC URL (e.g., https://10.1.1.1)')
    parser.add_argument('--source-user', help='Source APIC username')
    parser.add_argument('--dest-apic', help='Destination APIC URL (e.g., https://10.2.2.1)')
    parser.add_argument('--dest-user', help='Destination APIC username')
    parser.add_argument('--tenants', nargs='+', help='Specific tenant names to migrate')
    parser.add_argument('--no-backup', action='store_true', help='Do not backup tenant configs to files')
    parser.add_argument('--no-skip-existing', action='store_true', help='Overwrite existing tenants in destination')

    args = parser.parse_args()

    # Get source APIC details
    source_apic_url = args.source_apic or input("Source APIC URL (e.g., https://10.1.1.1): ")
    source_username = args.source_user or input("Source APIC Username: ")
    source_password = getpass.getpass("Source APIC Password: ")

    # Get destination APIC details
    dest_apic_url = args.dest_apic or input("\nDestination APIC URL (e.g., https://10.2.2.1): ")
    dest_username = args.dest_user or input("Destination APIC Username: ")
    dest_password = getpass.getpass("Destination APIC Password: ")

    # Create ACI fabric objects
    source_apic = ACIFabric(source_apic_url, source_username, source_password)
    dest_apic = ACIFabric(dest_apic_url, dest_username, dest_password)

    # Perform migration
    success = migrate_tenants(
        source_apic=source_apic,
        dest_apic=dest_apic,
        tenant_list=args.tenants,
        backup=not args.no_backup,
        skip_existing=not args.no_skip_existing
    )

    if success:
        logger.info("Migration completed successfully!")
        return 0
    else:
        logger.error("Migration completed with errors. Check log for details.")
        return 1


if __name__ == "__main__":
    exit(main())
