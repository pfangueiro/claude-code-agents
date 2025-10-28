#!/usr/bin/env python3
"""
Deployment Health Check Script

Performs comprehensive health checks after deployment to verify system stability.
Checks API endpoints, database connectivity, cache layer, and key metrics.

Usage:
    python3 health_check.py --env production
    python3 health_check.py --env production --check api
    python3 health_check.py --env production --verbose
"""

import argparse
import requests
import sys
import time
from typing import Dict, List, Tuple

# Configuration
ENVIRONMENTS = {
    'production': {
        'api_url': 'https://api.example.com/health',
        'db_host': 'db.example.com',
        'cache_host': 'redis.example.com',
    },
    'staging': {
        'api_url': 'https://api-staging.example.com/health',
        'db_host': 'db-staging.example.com',
        'cache_host': 'redis-staging.example.com',
    },
}

# Thresholds
MAX_RESPONSE_TIME_MS = 200
MAX_ERROR_RATE = 0.01  # 1%
MIN_SUCCESS_RATE = 0.999  # 99.9%


class HealthChecker:
    """Performs various health checks for deployed applications"""

    def __init__(self, environment: str, verbose: bool = False):
        self.environment = environment
        self.verbose = verbose
        self.config = ENVIRONMENTS.get(environment)

        if not self.config:
            raise ValueError(f"Unknown environment: {environment}")

    def log(self, message: str):
        """Print message if verbose mode enabled"""
        if self.verbose:
            print(f"  {message}")

    def check_api_health(self) -> Tuple[bool, str]:
        """Check if API health endpoint is responding"""
        self.log("Checking API health endpoint...")

        try:
            start_time = time.time()
            response = requests.get(
                self.config['api_url'],
                timeout=5
            )
            response_time = (time.time() - start_time) * 1000

            if response.status_code == 200:
                if response_time <= MAX_RESPONSE_TIME_MS:
                    self.log(f"Response time: {response_time:.2f}ms")
                    return True, f"API responding ({response_time:.0f}ms)"
                else:
                    return False, f"API slow ({response_time:.0f}ms > {MAX_RESPONSE_TIME_MS}ms)"
            else:
                return False, f"API returned {response.status_code}"

        except requests.exceptions.Timeout:
            return False, "API request timed out"
        except requests.exceptions.RequestException as e:
            return False, f"API unreachable: {str(e)}"

    def check_database(self) -> Tuple[bool, str]:
        """Check database connectivity"""
        self.log("Checking database connectivity...")

        try:
            # In a real implementation, you would:
            # import psycopg2
            # conn = psycopg2.connect(host=self.config['db_host'], ...)
            # cursor = conn.cursor()
            # cursor.execute("SELECT 1")
            # conn.close()

            # For demonstration:
            self.log(f"Connecting to {self.config['db_host']}...")
            return True, "Database connectivity OK"

        except Exception as e:
            return False, f"Database error: {str(e)}"

    def check_cache(self) -> Tuple[bool, str]:
        """Check cache layer accessibility"""
        self.log("Checking cache layer...")

        try:
            # In a real implementation, you would:
            # import redis
            # r = redis.Redis(host=self.config['cache_host'], ...)
            # r.ping()

            # For demonstration:
            self.log(f"Connecting to {self.config['cache_host']}...")
            return True, "Cache layer accessible"

        except Exception as e:
            return False, f"Cache error: {str(e)}"

    def check_metrics(self) -> Tuple[bool, str]:
        """Check if key metrics are within acceptable ranges"""
        self.log("Checking application metrics...")

        try:
            # In a real implementation, you would fetch from monitoring service
            # metrics = fetch_from_datadog/prometheus/cloudwatch()

            # For demonstration:
            error_rate = 0.0005  # 0.05%
            success_rate = 0.9995  # 99.95%

            if error_rate <= MAX_ERROR_RATE and success_rate >= MIN_SUCCESS_RATE:
                self.log(f"Error rate: {error_rate*100:.2f}%")
                self.log(f"Success rate: {success_rate*100:.2f}%")
                return True, f"Metrics within thresholds"
            else:
                return False, f"Metrics out of range (error: {error_rate*100:.2f}%)"

        except Exception as e:
            return False, f"Metrics check failed: {str(e)}"

    def check_external_services(self) -> Tuple[bool, str]:
        """Check connectivity to external services"""
        self.log("Checking external service connectivity...")

        try:
            # In a real implementation, you would check:
            # - Payment gateway
            # - Email service
            # - Third-party APIs
            # - CDN

            return True, "External services reachable"

        except Exception as e:
            return False, f"External services error: {str(e)}"

    def run_all_checks(self) -> Dict[str, Tuple[bool, str]]:
        """Run all health checks"""
        checks = {
            'API Health': self.check_api_health,
            'Database': self.check_database,
            'Cache': self.check_cache,
            'Metrics': self.check_metrics,
            'External Services': self.check_external_services,
        }

        results = {}
        for name, check_func in checks.items():
            results[name] = check_func()

        return results

    def run_single_check(self, check_name: str) -> Tuple[bool, str]:
        """Run a single named check"""
        checks = {
            'api': self.check_api_health,
            'database': self.check_database,
            'db': self.check_database,
            'cache': self.check_cache,
            'redis': self.check_cache,
            'metrics': self.check_metrics,
            'external': self.check_external_services,
        }

        check_func = checks.get(check_name.lower())
        if not check_func:
            raise ValueError(f"Unknown check: {check_name}")

        return check_func()


def print_results(results: Dict[str, Tuple[bool, str]]):
    """Print health check results"""
    print("\n" + "="*50)
    print("DEPLOYMENT HEALTH CHECK RESULTS")
    print("="*50 + "\n")

    all_passed = True
    for name, (passed, message) in results.items():
        status = "✓" if passed else "✗"
        color = "\033[92m" if passed else "\033[91m"
        reset = "\033[0m"

        print(f"{color}{status}{reset} {name}: {message}")

        if not passed:
            all_passed = False

    print("\n" + "="*50)
    if all_passed:
        print("\033[92m✓ ALL CHECKS PASSED\033[0m")
        print("="*50 + "\n")
        return 0
    else:
        print("\033[91m✗ SOME CHECKS FAILED\033[0m")
        print("="*50 + "\n")
        return 1


def main():
    parser = argparse.ArgumentParser(
        description="Run deployment health checks"
    )
    parser.add_argument(
        '--env', '--environment',
        required=True,
        choices=['production', 'staging'],
        help="Environment to check"
    )
    parser.add_argument(
        '--check',
        help="Run specific check only (api, database, cache, metrics, external)"
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help="Enable verbose output"
    )

    args = parser.parse_args()

    print(f"\n🏥 Running health checks for {args.env} environment...\n")

    checker = HealthChecker(args.env, args.verbose)

    try:
        if args.check:
            # Run single check
            passed, message = checker.run_single_check(args.check)
            results = {args.check.title(): (passed, message)}
        else:
            # Run all checks
            results = checker.run_all_checks()

        return print_results(results)

    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n\nHealth check interrupted by user")
        return 130


if __name__ == "__main__":
    sys.exit(main())
