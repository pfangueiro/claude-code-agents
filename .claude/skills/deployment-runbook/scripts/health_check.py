#!/usr/bin/env python3
"""
Deployment Health Check Script

Performs comprehensive health checks after deployment to verify system stability.
Checks API endpoints, database connectivity, cache layer, and key metrics.

TEMPLATE — READ BEFORE USING AS A DEPLOY GATE
    Only check_api_health() performs a real check out of the box. Every other
    check is an unimplemented template that you must wire to your own
    infrastructure. Those checks FAIL CLOSED: until implemented they return
    failure, so this script can never green-light a deployment it did not
    actually verify. Each one carries the snippet showing how to implement it.

Usage:
    python3 health_check.py --env production
    python3 health_check.py --env production --check api
    python3 health_check.py --env production --verbose

Exit codes (a CI gate must distinguish these):
    0   full run, every check passed — the only result that green-lights a deploy
    1   at least one check that ran FAILED
    2   PARTIAL run (--check): everything that ran passed, but not every check ran,
        so nothing was gated. Never treat 2 as a pass.
    130 interrupted
"""

import argparse
import requests
import sys
import time
from typing import Callable, Dict, List, Tuple

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

# Exit codes. A partial run gets its OWN code: `--check api` verifies one probe out
# of the full set, so reporting it as 0 would let a CI gate mistake one green probe
# for a verified deployment.
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_PARTIAL = 2


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

    def _not_implemented(self, what: str, how: str) -> Tuple[bool, str]:
        """Fail-closed result for a check that has not been wired up yet.

        A check that cannot actually verify anything MUST report failure.
        Returning success would make this script silently approve every
        deployment it is supposed to gate.
        """
        self.log(f"{what} check is an unimplemented template - reporting failure")
        return False, (
            f"NOT IMPLEMENTED - no verification of {what} was performed. "
            f"Implement this check before using it as a deploy gate ({how})."
        )

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
        """Check database connectivity — UNIMPLEMENTED TEMPLATE, fails closed"""
        self.log("Checking database connectivity...")

        # To implement, replace the fail-closed return below with a real probe:
        #     try:
        #         import psycopg2
        #         conn = psycopg2.connect(host=self.config['db_host'], ...)
        #         cursor = conn.cursor()
        #         cursor.execute("SELECT 1")
        #         conn.close()
        #         return True, "Database connectivity OK"
        #     except Exception as e:
        #         return False, f"Database error: {str(e)}"

        return self._not_implemented(
            "Database connectivity",
            f"connect to {self.config['db_host']} and run SELECT 1 - see the psycopg2 snippet in this method",
        )

    def check_cache(self) -> Tuple[bool, str]:
        """Check cache layer accessibility — UNIMPLEMENTED TEMPLATE, fails closed"""
        self.log("Checking cache layer...")

        # To implement, replace the fail-closed return below with a real probe:
        #     try:
        #         import redis
        #         r = redis.Redis(host=self.config['cache_host'], ...)
        #         r.ping()
        #         return True, "Cache layer accessible"
        #     except Exception as e:
        #         return False, f"Cache error: {str(e)}"

        return self._not_implemented(
            "Cache layer",
            f"PING {self.config['cache_host']} - see the redis snippet in this method",
        )

    def check_metrics(self) -> Tuple[bool, str]:
        """Check key metrics against thresholds — UNIMPLEMENTED TEMPLATE, fails closed"""
        self.log("Checking application metrics...")

        # To implement, fetch real values from your monitoring service and
        # compare them against the thresholds at the top of this file:
        #     try:
        #         error_rate, success_rate = fetch_from_datadog_prometheus_cloudwatch()
        #         if error_rate <= MAX_ERROR_RATE and success_rate >= MIN_SUCCESS_RATE:
        #             return True, "Metrics within thresholds"
        #         return False, f"Metrics out of range (error: {error_rate*100:.2f}%)"
        #     except Exception as e:
        #         return False, f"Metrics check failed: {str(e)}"
        # Never hard-code sample values here: a constant that always satisfies
        # the thresholds turns this gate into an unconditional pass.

        return self._not_implemented(
            "Application metrics",
            f"query your monitoring service for error rate (<= {MAX_ERROR_RATE*100:.2f}%) "
            f"and success rate (>= {MIN_SUCCESS_RATE*100:.2f}%)",
        )

    def check_external_services(self) -> Tuple[bool, str]:
        """Check connectivity to external services — UNIMPLEMENTED TEMPLATE, fails closed"""
        self.log("Checking external service connectivity...")

        # To implement, probe each dependency your deployment relies on and
        # return False if any of them is unreachable:
        # - Payment gateway
        # - Email service
        # - Third-party APIs
        # - CDN

        return self._not_implemented(
            "External services",
            "probe each dependency (payment gateway, email service, third-party APIs, CDN)",
        )

    def _all_checks(self) -> Dict[str, Callable[[], Tuple[bool, str]]]:
        """Canonical registry of every check a FULL run performs.

        Single source of truth so the partial-run accounting cannot drift from
        the set of checks that actually exists.
        """
        return {
            'API Health': self.check_api_health,
            'Database': self.check_database,
            'Cache': self.check_cache,
            'Metrics': self.check_metrics,
            'External Services': self.check_external_services,
        }

    @property
    def total_checks(self) -> int:
        """Number of checks a full run performs (the denominator of the gate)"""
        return len(self._all_checks())

    def run_all_checks(self) -> Dict[str, Tuple[bool, str]]:
        """Run all health checks"""
        results = {}
        for name, check_func in self._all_checks().items():
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


def print_results(results: Dict[str, Tuple[bool, str]], total_checks: int):
    """Print health check results and return the process exit code.

    `total_checks` is how many checks a FULL run performs. When fewer than that
    actually ran (`--check <name>`), the run verified only a slice of the system
    and MUST NOT be reported as a pass — it gets the PARTIAL banner and its own
    exit code so a CI gate cannot mistake it for a full green.
    """
    print("\n" + "="*50)
    print("DEPLOYMENT HEALTH CHECK RESULTS")
    print("="*50 + "\n")

    all_passed = True
    passed_count = 0
    for name, (passed, message) in results.items():
        status = "✓" if passed else "✗"
        color = "\033[92m" if passed else "\033[91m"
        reset = "\033[0m"

        print(f"{color}{status}{reset} {name}: {message}")

        if passed:
            passed_count += 1
        else:
            all_passed = False

    ran_count = len(results)
    is_partial = ran_count < total_checks

    print("\n" + "="*50)
    if not all_passed:
        print(f"\033[91m✗ SOME CHECKS FAILED ({passed_count}/{ran_count} of the checks that ran passed)\033[0m")
        if is_partial:
            print(f"\033[93m⚠ PARTIAL RUN — only {ran_count}/{total_checks} checks ran, NOT A DEPLOY GATE\033[0m")
        print("="*50 + "\n")
        return EXIT_FAILED

    if is_partial:
        print(f"\033[93m⚠ {passed_count}/{total_checks} CHECKS PASSED — PARTIAL RUN, NOT A DEPLOY GATE\033[0m")
        print(f"  {total_checks - ran_count} check(s) never ran. Re-run without --check for the full gate.")
        print("="*50 + "\n")
        return EXIT_PARTIAL

    print(f"\033[92m✓ ALL CHECKS PASSED ({passed_count}/{total_checks})\033[0m")
    print("="*50 + "\n")
    return EXIT_OK


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

        return print_results(results, checker.total_checks)

    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return EXIT_FAILED
    except KeyboardInterrupt:
        print("\n\nHealth check interrupted by user")
        return 130


if __name__ == "__main__":
    sys.exit(main())
