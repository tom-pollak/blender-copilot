from dataclasses import dataclass
import os
import json
import logging
import requests
from datetime import datetime

logger = logging.getLogger("BlenderCopilot")


@dataclass
class PlanInfo:
    plan: str
    calls_left: int
    daily_limit: int

    def __post_init__(self):
        self.plan = self.plan.capitalize()

    def plan_name_args(self):
        return

class LicenseManager:
    plan_info: PlanInfo | None

    def __init__(self, root_dir):
        self.root_dir = root_dir
        self.license_file = os.path.join(root_dir, ".license")
        self.license_key = None
        self.plan_info = None
        self.load_license()

    def load_license(self):
        """Load license key from file if it exists"""
        if os.path.exists(self.license_file):
            try:
                with open(self.license_file, "r") as f:
                    data = json.load(f)
                    self.license_key = data.get("key")
                    logger.info("License loaded successfully")
            except Exception as e:
                logger.error(f"Failed to load license: {e}")

    def save_license(self, key):
        """Save license key to file"""
        try:
            with open(self.license_file, "w") as f:
                json.dump({"key": key}, f)
            self.license_key = key
            logger.info("License saved successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to save license: {e}")
            return False

    def validate_license(self, server_url):
        """Validate license key with server and get plan info"""
        auth_headers = self.get_auth_headers()
        if not auth_headers:
            return False

        try:
            response = requests.get(
                f"{server_url}/infer/validate-license",
                headers=auth_headers,
                timeout=10,
            )

            if response.status_code == 200:
                self.update_plan_info_from_headers(response.headers)
                return True
            else:
                self.plan_info = None
                return False
        except Exception as e:
            logger.error(f"License validation failed: {e}")
            return False

    def clear_license(self):
        """Remove license key and file"""
        if os.path.exists(self.license_file):
            try:
                os.remove(self.license_file)
                self.license_key = None
                self.plan_info = None
                logger.info("License cleared successfully")
                return True
            except Exception as e:
                logger.error(f"Failed to clear license: {e}")
                return False

    def get_auth_headers(self):
        return {"Authorization": f"Bearer {self.license_key}"} if self.license_key else None

    def update_plan_info_from_headers(self, headers):
        """Update plan info from response headers"""
        try:
            plan_info_str = headers.get("X-Plan-Info")
            if plan_info_str:
                plan_info_dict = json.loads(plan_info_str)
                self.plan_info = PlanInfo(**plan_info_dict)
                logger.debug("Updated plan info from response headers")
        except Exception as e:
            logger.error(f"Failed to update plan info from headers: {e}")

