#!/usr/bin/env python3
"""
Watson Orchestrate Token Refresh Service for OTel Collector.

Periodically fetches IAM OAuth token using API_KEY and writes it atomically
to the token file (otel-collector/token/token) for OpenTelemetry Collector bearertokenauth extension.
"""

import argparse
import json
import logging
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("refresh_token")


def load_environment(env_file_path: Optional[Path] = None) -> Tuple[str, str]:
    """
    Load API_KEY and TOKEN_URL from environment or .env file.
    Never logs or leaks secret values.
    """
    # Try loading from .env if python-dotenv is available
    try:
        from dotenv import dotenv_values

        candidate_paths = []
        if env_file_path:
            candidate_paths.append(env_file_path)
        else:
            # Check current working directory and project root relative to this script
            candidate_paths.append(Path.cwd() / ".env")
            candidate_paths.append(Path(__file__).resolve().parent.parent / ".env")

        for p in candidate_paths:
            if p.is_file():
                logger.info("Loading configuration from %s", p)
                env_vals = dotenv_values(p)
                for k, v in env_vals.items():
                    if k and v and k not in os.environ:
                        os.environ[k] = v
                break
    except Exception as e:
        logger.warning("Failed to parse .env file with python-dotenv: %s", type(e).__name__)

    api_key = os.environ.get("API_KEY")
    token_url = os.environ.get("TOKEN_URL")

    if not token_url:
        logger.error("Missing required configuration: TOKEN_URL is not set.")
        sys.exit(1)

    if not api_key:
        logger.error("Missing required configuration: API_KEY is not set.")
        sys.exit(1)

    # Sanitize & check URL
    parsed_url = urllib.parse.urlparse(token_url)
    logger.info("Token URL configured with host: %s, path: %s", parsed_url.netloc, parsed_url.path)
    logger.info("API Key configured (length: %d chars)", len(api_key))

    return api_key, token_url


def fetch_iam_token(api_key: str, token_url: str, timeout: int = 30) -> Tuple[str, int]:
    """
    Exchange API_KEY for IAM Bearer token via HTTP POST.
    Returns (access_token, expires_in).
    Raises Exception on error.
    """
    post_data = urllib.parse.urlencode({
        "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
        "apikey": api_key,
    }).encode("utf-8")

    req = urllib.request.Request(
        token_url,
        data=post_data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": "wxo-otel-token-refresher/1.0",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Unexpected HTTP status {resp.status} from token endpoint")

        body_bytes = resp.read()
        data = json.loads(body_bytes.decode("utf-8"))

        access_token = data.get("access_token")
        if not access_token or not isinstance(access_token, str):
            raise ValueError("Token response did not contain a valid 'access_token' string")

        expires_in = data.get("expires_in", 3600)
        try:
            expires_in = int(expires_in)
        except (ValueError, TypeError):
            expires_in = 3600

        token_type = data.get("token_type", "Bearer")
        logger.info(
            "Successfully fetched token (type=%s, length=%d chars, expires_in=%ds)",
            token_type,
            len(access_token),
            expires_in,
        )

        # Return stripped token to ensure no trailing newline/whitespace
        return access_token.strip(), expires_in


def write_token_atomic(token: str, target_path: Path) -> None:
    """
    Atomically writes token string to target_path using temp file + os.replace.
    Sets permissions to 0600 (owner read/write only).
    Does NOT include trailing newline.
    """
    target_path = target_path.resolve()
    target_dir = target_path.parent
    target_dir.mkdir(parents=True, exist_ok=True)

    # Create temporary file in the same directory to ensure same filesystem for atomic rename
    temp_fd, temp_file_path = tempfile.mkstemp(
        prefix=".token_tmp_",
        dir=str(target_dir),
        text=True,
    )

    try:
        # Write exact token without trailing newline
        with open(temp_fd, "w", encoding="utf-8") as f:
            f.write(token)

        # Set permission to 0600
        os.chmod(temp_file_path, 0o600)

        # Atomic replace
        os.replace(temp_file_path, target_path)

        # Ensure target file permission is 0600
        os.chmod(target_path, 0o600)

        file_stat = target_path.stat()
        logger.info(
            "Atomically wrote token to %s (size: %d bytes, mode: %o)",
            target_path,
            file_stat.st_size,
            file_stat.st_mode & 0o777,
        )
    except Exception:
        if os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except OSError:
                pass
        raise


def refresh_cycle(
    token_path: Path,
    env_file_path: Optional[Path] = None,
    once: bool = False,
    refresh_ratio: float = 0.8,
    retry_interval: int = 30,
) -> None:
    """
    Main loop for token refresh.
    """
    api_key, token_url = load_environment(env_file_path)

    while True:
        try:
            token, expires_in = fetch_iam_token(api_key, token_url)
            write_token_atomic(token, token_path)

            if once:
                logger.info("Run-once mode completed successfully. Exiting.")
                return

            # Calculate sleep duration: refresh after (expires_in * refresh_ratio) seconds
            # Ensure at least 60s sleep if expires_in is reasonable
            sleep_seconds = max(int(expires_in * refresh_ratio), 60)
            logger.info(
                "Next token refresh scheduled in %d seconds (~%.1f minutes).",
                sleep_seconds,
                sleep_seconds / 60.0,
            )
            time.sleep(sleep_seconds)

        except urllib.error.HTTPError as e:
            logger.error("HTTP error fetching token: HTTP %s (%s)", e.code, e.reason)
            if once:
                sys.exit(1)
            logger.info("Will retry in %d seconds. Retaining existing token file.", retry_interval)
            time.sleep(retry_interval)
        except urllib.error.URLError as e:
            logger.error("Network/URL error fetching token: %s", e.reason)
            if once:
                sys.exit(1)
            logger.info("Will retry in %d seconds. Retaining existing token file.", retry_interval)
            time.sleep(retry_interval)
        except Exception as e:
            logger.error("Unexpected error during token refresh: %s: %s", type(e).__name__, e)
            if once:
                sys.exit(1)
            logger.info("Will retry in %d seconds. Retaining existing token file.", retry_interval)
            time.sleep(retry_interval)


def main():
    parser = argparse.ArgumentParser(
        description="Fetch and refresh IAM token for OTel Collector bearertokenauth extension."
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Fetch token once, write to file, and exit.",
    )
    parser.add_argument(
        "--token-path",
        type=str,
        default="otel-collector/token/token",
        help="Target path for the token file (default: otel-collector/token/token).",
    )
    parser.add_argument(
        "--env-file",
        type=str,
        default=None,
        help="Path to .env file (default: searches working directory and parent).",
    )
    parser.add_argument(
        "--refresh-ratio",
        type=float,
        default=0.8,
        help="Fraction of token lifetime after which to refresh (default: 0.8 = 80%%).",
    )
    parser.add_argument(
        "--retry-interval",
        type=int,
        default=30,
        help="Seconds to wait before retrying after a failed token fetch (default: 30).",
    )

    args = parser.parse_args()

    token_path = Path(args.token_path)
    env_file_path = Path(args.env_file) if args.env_file else None

    refresh_cycle(
        token_path=token_path,
        env_file_path=env_file_path,
        once=args.once,
        refresh_ratio=args.refresh_ratio,
        retry_interval=args.retry_interval,
    )


if __name__ == "__main__":
    main()
