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
    python3 health_check.py --env green            # blue-green: check the inactive slot
    python3 health_check.py --env production --check api
    python3 health_check.py --env production --verbose

    --env accepts every key of ENVIRONMENTS below (production, staging, blue, green).

Exit codes (a CI gate must distinguish these):
    0   FULL run, every check passed — the only result that green-lights a deploy
    1   at least one check that RAN failed
    2   USAGE error: the invocation was rejected (unknown --env, bad flag), so NO
        check ran and nothing was verified. Reserved for argparse; deliberately
        NOT shared with any code that means "what ran passed".
    3   PARTIAL run (--check): everything that ran passed, but not every check ran,
        so nothing was gated. Never treat 3 as a pass.
    130 interrupted

    Only 0 is a pass. 2 and 3 both mean "the deployment was not gated" and differ
    only in why; 2 additionally means the command itself was wrong.
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
    # Blue-green slots. The Blue-Green procedure health-checks the INACTIVE slot
    # before switching traffic onto it, so both colours must be addressable by
    # name — running that step against 'production' would probe the live side and
    # verify nothing about the release being promoted.
    'blue': {
        'api_url': 'https://api-blue.example.com/health',
        'db_host': 'db-blue.example.com',
        'cache_host': 'redis-blue.example.com',
    },
    'green': {
        'api_url': 'https://api-green.example.com/health',
        'db_host': 'db-green.example.com',
        'cache_host': 'redis-green.example.com',
    },
}

# Thresholds
MAX_RESPONSE_TIME_MS = 200
# Healthy is error rate < 0.1% — the runbook's Phase 4 definition, and the exact
# complement of MIN_SUCCESS_RATE below. The runbook's ">1%" figure is the EMERGENCY
# ROLLBACK trigger, a different threshold; using it here would make this gate 10x
# looser than the level it exists to protect.
MAX_ERROR_RATE = 0.001  # 0.1%
MIN_SUCCESS_RATE = 0.999  # 99.9%

# Exit codes. Two collisions are deliberately avoided here:
#   - A partial run gets its OWN code: `--check api` verifies one probe out of the
#     full set, so reporting it as 0 would let a CI gate mistake one green probe for
#     a verified deployment.
#   - A usage error gets its own code too, and it must NEVER be the partial code.
#     argparse exits 2 when it rejects an invocation, so 2 is reserved for "nothing
#     ran, the command was wrong" and EXIT_PARTIAL lives at 3. Sharing 2 would let a
#     CI gate read a rejected command as "everything that ran passed".
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2      # argparse's rejected-invocation code; pinned by _StrictParser
EXIT_PARTIAL = 3


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
            'external_services': self.check_external_services,
        }

        check_func = checks.get(check_name.lower())
        if not check_func:
            # A typo must not be indistinguishable from a failed probe: both used to exit 1,
            # so a misspelled --check read as "the check ran and failed".
            raise UnknownCheckError(
                f"Unknown check {check_name!r}. Valid checks: "
                + ", ".join(sorted(checks))
            )

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


class UnknownCheckError(ValueError):
    """A --check name that does not exist. A typo is a USAGE error (exit 2), not a
    health result — exiting 1 would make it indistinguishable from a probe that ran
    and failed."""

class _StrictParser(argparse.ArgumentParser):
    """ArgumentParser that pins the usage-error exit code and labels it.

    argparse's default rejected-invocation code is 2, which this script documents
    as EXIT_USAGE. Pinning it here means the exit-code table in the header is
    enforced by code rather than inherited from an argparse implementation detail,
    and the extra stderr line states outright that nothing was verified — so a CI
    gate cannot read a rejected command as any kind of health result.
    """

    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, (
            f"{self.prog}: error: {message}\n"
            f"{self.prog}: NO health checks ran — this is a usage error "
            f"(exit {EXIT_USAGE}), not a health result. Nothing was verified.\n"
        ))


def main():
    parser = _StrictParser(
        description="Run deployment health checks"
    )
    parser.add_argument(
        '--env', '--environment',
        required=True,
        # Derived from ENVIRONMENTS so the accepted set can never drift from the
        # configured set. A hand-maintained list is what made the runbook's own
        # `--env green` a usage error while the config was the thing to fix.
        choices=sorted(ENVIRONMENTS),
        help="Environment to check"
    )
    parser.add_argument(
        '--check',
        help=("Run specific check only (api, database, cache, metrics, "
              "external_services; aliases: db, redis, external)")
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

    except UnknownCheckError as e:
        print(f"\n\033[91m✗ {e}\033[0m")
        print(f"Usage error (exit {EXIT_USAGE}) — nothing was verified.\n")
        return EXIT_USAGE
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return EXIT_FAILED
    except KeyboardInterrupt:
        print("\n\nHealth check interrupted by user")
        return 130


if __name__ == "__main__":
    sys.exit(main())
